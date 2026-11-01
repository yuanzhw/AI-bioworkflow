import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from scripts.evaluate_retrieval import main as evaluate_retrieval_main
from scripts.evaluate_retrieval import parse_args as parse_evaluation_args
from scripts.prepare_embedding_model import prepare_embedding_model
from src.catalog import (CatalogVectorIndex, CatalogVectorIndexEntry,
                         LocalEmbeddingModelConfig,
                         SentenceTransformerEmbeddingProvider, ToolCatalog,
                         VectorCatalogRetrievalBackend,
                         build_catalog_retrieval_corpus,
                         build_catalog_vector_index, embedding_model_manifest,
                         get_catalog_retrieval_backend,
                         load_embedding_model_manifest, load_tool_catalog,
                         retrieve_catalog_context_with_backend,
                         search_catalog_vector_index)
from src.catalog.retrieval_eval import (evaluate_retrieval_queries,
                                        load_retrieval_queries)
from src.catalog.vector_retrieval import (DEFAULT_DOCUMENT_PREFIX,
                                          DEFAULT_EMBEDDING_DIMENSION,
                                          DEFAULT_EMBEDDING_MODEL_ID,
                                          DEFAULT_EMBEDDING_MODEL_REVISION,
                                          DEFAULT_QUERY_PREFIX,
                                          EMBEDDING_MODEL_MANIFEST_FILENAME,
                                          embed_catalog_query)
from src.recipes import load_recipe_catalog

VALID_QUERY = "Run RNA-seq differential expression."
TARGET_RECIPE_DOCUMENT = "recipe:rnaseq_differential_expression"
TARGET_TOOL_DOCUMENT = "tool:deseq2@1.42.1"


def unit_vector(index: int) -> list[float]:
    vector = [0.0] * DEFAULT_EMBEDDING_DIMENSION
    vector[index] = 1.0
    return vector


class FakeEmbeddingProvider:
    model_id = DEFAULT_EMBEDDING_MODEL_ID
    revision = DEFAULT_EMBEDDING_MODEL_REVISION
    dimension = DEFAULT_EMBEDDING_DIMENSION
    query_prefix = DEFAULT_QUERY_PREFIX
    document_prefix = DEFAULT_DOCUMENT_PREFIX

    def __init__(self, corpus):
        self.document_texts = [document.text for document in corpus.documents]
        self.document_vectors = [
            unit_vector(index + 1)
            for index, _document in enumerate(corpus.documents)
        ]
        for index, document in enumerate(corpus.documents):
            if document.document_id in {
                TARGET_RECIPE_DOCUMENT,
                TARGET_TOOL_DOCUMENT,
            }:
                self.document_vectors[index] = unit_vector(0)
        self.query_vectors = {VALID_QUERY: unit_vector(0)}
        self.document_calls = 0
        self.query_calls = 0

    def embed_documents(self, texts):
        self.document_calls += 1
        if list(texts) != self.document_texts:
            raise AssertionError("unexpected canonical document batch")
        return self.document_vectors

    def embed_queries(self, texts):
        self.query_calls += 1
        return [
            self.query_vectors.get(text, unit_vector(DEFAULT_EMBEDDING_DIMENSION - 1))
            for text in texts
        ]


class CatalogVectorIndexTests(unittest.TestCase):
    def setUp(self):
        self.tool_catalog = load_tool_catalog()
        self.recipe_catalog = load_recipe_catalog(tool_catalog=self.tool_catalog)
        self.corpus = build_catalog_retrieval_corpus(
            self.tool_catalog,
            self.recipe_catalog,
        )
        self.provider = FakeEmbeddingProvider(self.corpus)
        self.index = build_catalog_vector_index(self.corpus, self.provider)

    def test_builds_deterministic_index_bound_to_model_and_corpus(self):
        rebuilt = build_catalog_vector_index(
            self.corpus,
            FakeEmbeddingProvider(self.corpus),
        )
        document_ids = [entry.document_id for entry in self.index.entries]

        self.assertEqual(self.index, rebuilt)
        self.assertEqual(self.provider.document_calls, 1)
        self.assertEqual(len(self.index.entries), 21)
        self.assertEqual(document_ids, sorted(document_ids))
        self.assertEqual(self.index.model_id, DEFAULT_EMBEDDING_MODEL_ID)
        self.assertEqual(self.index.model_revision, DEFAULT_EMBEDDING_MODEL_REVISION)
        self.assertEqual(self.index.dimension, DEFAULT_EMBEDDING_DIMENSION)
        self.assertEqual(self.index.corpus_fingerprint, self.corpus.fingerprint)
        self.assertRegex(self.index.fingerprint, r"^sha256:[0-9a-f]{64}$")

    def test_exact_cosine_search_ranks_target_and_breaks_ties_by_document_id(self):
        results = search_catalog_vector_index(
            self.index,
            unit_vector(0),
            kind="recipe",
            top_k=3,
        )

        self.assertEqual(results[0].entry.document_id, TARGET_RECIPE_DOCUMENT)
        self.assertEqual(results[0].score, 1.0)
        tied_ids = [result.entry.document_id for result in results[1:]]
        self.assertEqual(tied_ids, sorted(tied_ids))

    def test_index_rejects_invalid_embedding_batches(self):
        cases = (
            (
                "returned 20 vectors; expected 21",
                self.provider.document_vectors[:-1],
            ),
            (
                "must have dimension 384; got 383",
                [unit_vector(0)[:-1], *self.provider.document_vectors[1:]],
            ),
            (
                "components must be finite",
                [
                    [float("nan"), *unit_vector(0)[1:]],
                    *self.provider.document_vectors[1:],
                ],
            ),
            (
                "vectors must not be zero",
                [
                    [0.0] * DEFAULT_EMBEDDING_DIMENSION,
                    *self.provider.document_vectors[1:],
                ],
            ),
        )

        for expected_message, vectors in cases:
            with self.subTest(expected_message=expected_message):
                provider = FakeEmbeddingProvider(self.corpus)
                provider.document_vectors = vectors
                with self.assertRaisesRegex(ValueError, expected_message):
                    build_catalog_vector_index(self.corpus, provider)

    def test_query_embedding_rejects_invalid_vectors(self):
        cases = (
            ("must have dimension 384; got 383", unit_vector(0)[:-1]),
            (
                "components must be finite",
                [float("inf"), *unit_vector(0)[1:]],
            ),
            ("vectors must not be zero", [0.0] * DEFAULT_EMBEDDING_DIMENSION),
        )

        for expected_message, vector in cases:
            with self.subTest(expected_message=expected_message):
                provider = FakeEmbeddingProvider(self.corpus)
                provider.query_vectors[VALID_QUERY] = vector
                with self.assertRaisesRegex(ValueError, expected_message):
                    embed_catalog_query(VALID_QUERY, provider)

    def test_index_schema_rejects_tampered_fingerprint(self):
        payload = self.index.model_dump(mode="json")
        payload["fingerprint"] = "sha256:" + ("0" * 64)

        with self.assertRaisesRegex(ValueError, "fingerprint must match"):
            CatalogVectorIndex.model_validate(payload)

    def test_index_entry_rejects_kind_document_id_mismatch(self):
        payload = self.index.entries[0].model_dump(mode="json")
        payload["kind"] = "tool" if payload["kind"] == "recipe" else "recipe"

        with self.assertRaisesRegex(ValueError, "prefix must match"):
            CatalogVectorIndexEntry.model_validate(payload)

    def test_index_fingerprint_changes_when_vector_content_changes(self):
        provider = FakeEmbeddingProvider(self.corpus)
        provider.document_vectors[0] = unit_vector(200)

        changed = build_catalog_vector_index(self.corpus, provider)

        self.assertNotEqual(changed.fingerprint, self.index.fingerprint)


class VectorCatalogRetrievalBackendTests(unittest.TestCase):
    def setUp(self):
        self.tool_catalog = load_tool_catalog()
        self.recipe_catalog = load_recipe_catalog(tool_catalog=self.tool_catalog)
        self.corpus = build_catalog_retrieval_corpus(
            self.tool_catalog,
            self.recipe_catalog,
        )
        self.provider = FakeEmbeddingProvider(self.corpus)

    def test_factory_requires_explicit_vector_dependencies(self):
        with self.assertRaisesRegex(ValueError, "explicit Tool Catalog"):
            get_catalog_retrieval_backend("vector_v1")

        with self.assertRaisesRegex(ValueError, "local embedding model path"):
            get_catalog_retrieval_backend(
                "vector_v1",
                tool_catalog=self.tool_catalog,
                recipe_catalog=self.recipe_catalog,
            )

    def test_factory_builds_vector_backend_with_injected_provider(self):
        backend = get_catalog_retrieval_backend(
            " Vector_V1 ",
            embedding_provider=self.provider,
            tool_catalog=self.tool_catalog,
            recipe_catalog=self.recipe_catalog,
        )

        self.assertIsInstance(backend, VectorCatalogRetrievalBackend)
        self.assertEqual(backend.name, "vector_v1")

    def test_vector_backend_ranks_candidates_and_preserves_catalog_metadata(self):
        backend = VectorCatalogRetrievalBackend(
            self.provider,
            self.tool_catalog,
            self.recipe_catalog,
        )

        result = retrieve_catalog_context_with_backend(
            backend,
            VALID_QUERY,
            self.tool_catalog,
            self.recipe_catalog,
        )

        self.assertEqual(result["strategy"], "vector_v1")
        self.assertEqual(result["recipes"][0]["id"], "rnaseq_differential_expression")
        self.assertEqual(result["tools"][0]["id"], "deseq2")
        self.assertEqual(result["tools"][0]["version"], "1.42.1")
        self.assertEqual(result["tools"][0]["trust_status"], "catalog-approved")
        self.assertEqual(
            result["tools"][0]["execution_verification"],
            self.tool_catalog.get("deseq2", "1.42.1")
            .execution_verification.model_dump(mode="json"),
        )
        self.assertFalse(result["fallback_used"])
        self.assertEqual(
            result["recipes"][0]["backend_evidence"],
            {
                "document_id": TARGET_RECIPE_DOCUMENT,
                "rank": 1,
                "cosine_similarity": 1.0,
            },
        )
        evidence = result["backend_evidence"]
        self.assertEqual(evidence["model_id"], DEFAULT_EMBEDDING_MODEL_ID)
        self.assertEqual(evidence["model_revision"], DEFAULT_EMBEDDING_MODEL_REVISION)
        self.assertEqual(evidence["corpus_fingerprint"], self.corpus.fingerprint)
        self.assertEqual(evidence["index_fingerprint"], backend.index.fingerprint)
        json.dumps(result, allow_nan=False)

    def test_vector_backend_rejects_catalog_drift_after_index_build(self):
        backend = VectorCatalogRetrievalBackend(
            self.provider,
            self.tool_catalog,
            self.recipe_catalog,
        )
        tools = {
            (tool.id, tool.version): tool for tool in self.tool_catalog.all()
        }
        deseq2 = tools[("deseq2", "1.42.1")]
        tools[("deseq2", "1.42.1")] = deseq2.model_copy(
            update={"description": deseq2.description + " changed"}
        )

        with self.assertRaisesRegex(ValueError, "corpus fingerprint"):
            backend.retrieve(
                VALID_QUERY,
                ToolCatalog(tools),
                self.recipe_catalog,
            )

    def test_vector_backend_runs_the_shared_64_query_evaluation(self):
        backend = VectorCatalogRetrievalBackend(
            self.provider,
            self.tool_catalog,
            self.recipe_catalog,
        )
        queries = load_retrieval_queries(
            Path(__file__).parent / "fixtures" / "retrieval_queries.json"
        )

        evaluation = evaluate_retrieval_queries(
            queries,
            self.tool_catalog,
            self.recipe_catalog,
            backend=backend,
        )

        self.assertEqual(evaluation["strategy"], "vector_v1")
        self.assertEqual(evaluation["query_count"], 64)
        self.assertEqual(len(evaluation["queries"]), 64)
        self.assertTrue(
            all(
                result["backend_evidence"]["backend"] == "vector_v1"
                for result in evaluation["queries"]
            )
        )
        json.dumps(evaluation, allow_nan=False)


class EmbeddingModelPreparationTests(unittest.TestCase):
    def test_prepare_command_uses_pinned_revision_and_writes_manifest(self):
        calls = []

        def downloader(**kwargs):
            calls.append(kwargs)
            output = Path(kwargs["local_dir"])
            (output / "model.safetensors").write_bytes(b"test")
            return str(output)

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "model"
            manifest = prepare_embedding_model(output, downloader=downloader)
            loaded = load_embedding_model_manifest(output)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["repo_id"], DEFAULT_EMBEDDING_MODEL_ID)
        self.assertEqual(calls[0]["revision"], DEFAULT_EMBEDDING_MODEL_REVISION)
        self.assertFalse(calls[0]["token"])
        self.assertEqual(manifest, embedding_model_manifest().model_dump(mode="json"))
        self.assertEqual(loaded, embedding_model_manifest())

    def test_manifest_rejects_tampered_model_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir)
            payload = embedding_model_manifest().model_dump(mode="json")
            payload["revision"] = "main"
            (model_path / EMBEDDING_MODEL_MANIFEST_FILENAME).write_text(
                json.dumps(payload),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "manifest is invalid"):
                load_embedding_model_manifest(model_path)

    def test_prepare_command_reports_download_failure_without_writing_manifest(self):
        def downloader(**_kwargs):
            raise ConnectionError("remote detail")

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "model"
            output.mkdir()
            manifest_path = output / EMBEDDING_MODEL_MANIFEST_FILENAME
            manifest_path.write_text("stale", encoding="utf-8")

            with self.assertRaisesRegex(
                RuntimeError,
                "failed to download the pinned embedding model snapshot",
            ):
                prepare_embedding_model(output, downloader=downloader)

            self.assertFalse(manifest_path.exists())

    def test_sentence_transformer_provider_requires_prepared_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = LocalEmbeddingModelConfig(model_path=Path(tmpdir))

            with self.assertRaisesRegex(ValueError, EMBEDDING_MODEL_MANIFEST_FILENAME):
                SentenceTransformerEmbeddingProvider(config)

    def test_sentence_transformer_provider_uses_current_dimension_api(self):
        calls = []

        class FakeSentenceTransformer:
            def __init__(self, model_path, **kwargs):
                calls.append((model_path, kwargs))

            def get_embedding_dimension(self):
                return DEFAULT_EMBEDDING_DIMENSION

        fake_module = ModuleType("sentence_transformers")
        fake_module.SentenceTransformer = FakeSentenceTransformer

        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = Path(tmpdir)
            (model_path / EMBEDDING_MODEL_MANIFEST_FILENAME).write_text(
                json.dumps(embedding_model_manifest().model_dump(mode="json")),
                encoding="utf-8",
            )
            config = LocalEmbeddingModelConfig(model_path=model_path)

            with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
                provider = SentenceTransformerEmbeddingProvider(config)

        self.assertEqual(provider.dimension, DEFAULT_EMBEDDING_DIMENSION)
        self.assertEqual(len(calls), 1)
        loaded_path, kwargs = calls[0]
        self.assertEqual(loaded_path, str(model_path.resolve()))
        self.assertEqual(kwargs["device"], "cpu")
        self.assertTrue(kwargs["local_files_only"])
        self.assertFalse(kwargs["trust_remote_code"])


class VectorEvaluationCliTests(unittest.TestCase):
    def test_cli_accepts_explicit_vector_configuration(self):
        args = parse_evaluation_args(
            [
                "--backend",
                "vector_v1",
                "--embedding-model-path",
                "local-model",
                "--embedding-device",
                "cpu",
            ]
        )

        self.assertEqual(args.backend, "vector_v1")
        self.assertEqual(args.embedding_model_path, Path("local-model"))
        self.assertEqual(args.embedding_device, "cpu")

    def test_cli_rejects_vector_backend_without_local_model_path(self):
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = evaluate_retrieval_main(["--backend", "vector_v1"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("requires --embedding-model-path", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
