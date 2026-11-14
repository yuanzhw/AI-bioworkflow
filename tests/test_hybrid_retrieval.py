import copy
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.evaluate_retrieval import main as evaluate_retrieval_main
from scripts.evaluate_retrieval import parse_args as parse_evaluation_args
from src.catalog import (HybridCatalogRetrievalBackend,
                         build_catalog_retrieval_corpus,
                         get_catalog_retrieval_backend, load_tool_catalog,
                         retrieve_catalog_context_with_backend)
from src.catalog.hybrid_retrieval import DEFAULT_RRF_K
from src.catalog.retrieval_eval import (evaluate_retrieval_queries,
                                        load_retrieval_queries)
from src.catalog.vector_retrieval import (DEFAULT_DOCUMENT_PREFIX,
                                          DEFAULT_EMBEDDING_DIMENSION,
                                          DEFAULT_EMBEDDING_MODEL_ID,
                                          DEFAULT_EMBEDDING_MODEL_REVISION,
                                          DEFAULT_QUERY_PREFIX)
from src.recipes import load_recipe_catalog

VALID_QUERY = "Run RNA-seq differential expression."


def unit_vector(index):
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
            unit_vector(index) for index, _document in enumerate(corpus.documents)
        ]
        self.query_vectors = {VALID_QUERY: unit_vector(0)}

    def embed_documents(self, texts):
        if list(texts) != self.document_texts:
            raise AssertionError("unexpected canonical document batch")
        return self.document_vectors

    def embed_queries(self, texts):
        return [
            self.query_vectors.get(text, unit_vector(DEFAULT_EMBEDDING_DIMENSION - 1))
            for text in texts
        ]


class StaticComponentBackend:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = []

    def retrieve(
        self,
        query,
        _tool_catalog,
        _recipe_catalog,
        top_k_recipes=3,
        top_k_tools=8,
    ):
        self.calls.append((query, top_k_recipes, top_k_tools))
        result = copy.deepcopy(self.result)
        result["query"] = query
        return result


def component_result(
    backend_name,
    tool_catalog,
    *,
    recipe_ids,
    tool_ids,
    recipe_fallback=False,
    tool_fallback=False,
):
    def score(rank):
        return float(1000 - rank) if backend_name == "lexical_v1" else 1.0 / rank

    def explanation(rank):
        if backend_name == "lexical_v1" and not recipe_fallback:
            return [f"lexical-{rank}"], ["description"]
        return [], []

    recipes = []
    for rank, recipe_id in enumerate(recipe_ids, start=1):
        matched_terms, matched_fields = explanation(rank)
        recipes.append(
            {
                "id": recipe_id,
                "score": 0.0 if recipe_fallback else score(rank),
                "matched_terms": matched_terms,
                "matched_fields": matched_fields,
                "reason": f"{backend_name} recipe candidate",
                "backend_evidence": {"source_rank": rank},
            }
        )

    tools = []
    tools_by_id = {tool.id: tool for tool in tool_catalog.all()}
    for rank, tool_id in enumerate(tool_ids, start=1):
        tool = tools_by_id[tool_id]
        matched_terms = (
            [f"tool-lexical-{rank}"]
            if backend_name == "lexical_v1" and not tool_fallback
            else []
        )
        matched_fields = ["aliases"] if matched_terms else []
        tools.append(
            {
                "id": tool.id,
                "version": tool.version,
                "score": 0.0 if tool_fallback else score(rank),
                "matched_terms": matched_terms,
                "matched_fields": matched_fields,
                "trust_status": "catalog-approved",
                "execution_verification": tool.execution_verification.model_dump(
                    mode="json"
                ),
                "reason": f"{backend_name} tool candidate",
                "backend_evidence": {"source_rank": rank},
            }
        )

    fallback_used = recipe_fallback or tool_fallback
    return {
        "query": VALID_QUERY,
        "strategy": backend_name,
        "recipes": recipes,
        "tools": tools,
        "recipe_fallback_used": recipe_fallback,
        "tool_fallback_used": tool_fallback,
        "fallback_used": fallback_used,
        "fallback_reason": "component fallback" if fallback_used else None,
        "backend_evidence": {
            "schema_version": "1.0",
            "backend": backend_name,
        },
    }


class HybridRankFusionTests(unittest.TestCase):
    def setUp(self):
        self.tool_catalog = load_tool_catalog()
        self.recipe_catalog = load_recipe_catalog(tool_catalog=self.tool_catalog)

    def test_fuses_complete_component_ranks_and_preserves_lexical_explanation(self):
        lexical = StaticComponentBackend(
            "lexical_v1",
            component_result(
                "lexical_v1",
                self.tool_catalog,
                recipe_ids=[
                    "chipseq_peak_calling",
                    "rnaseq_differential_expression",
                ],
                tool_ids=["fastp", "multiqc"],
            ),
        )
        vector = StaticComponentBackend(
            "vector_v1",
            component_result(
                "vector_v1",
                self.tool_catalog,
                recipe_ids=[
                    "scrnaseq_qc_clustering",
                    "rnaseq_differential_expression",
                ],
                tool_ids=["samtools", "multiqc"],
            ),
        )
        backend = HybridCatalogRetrievalBackend(lexical, vector)

        result = retrieve_catalog_context_with_backend(
            backend,
            VALID_QUERY,
            self.tool_catalog,
            self.recipe_catalog,
            top_k_recipes=3,
            top_k_tools=3,
        )

        self.assertEqual(
            [candidate["id"] for candidate in result["recipes"]],
            [
                "rnaseq_differential_expression",
                "chipseq_peak_calling",
                "scrnaseq_qc_clustering",
            ],
        )
        self.assertEqual(
            [candidate["id"] for candidate in result["tools"]],
            ["multiqc", "fastp", "samtools"],
        )
        self.assertEqual(
            result["recipes"][0]["score"],
            round(2 / (DEFAULT_RRF_K + 2), 12),
        )
        self.assertEqual(result["recipes"][0]["matched_terms"], ["lexical-2"])
        self.assertEqual(result["recipes"][2]["matched_terms"], [])
        components = result["recipes"][0]["backend_evidence"]["components"]
        self.assertEqual(components["lexical_v1"]["rank"], 2)
        self.assertEqual(components["lexical_v1"]["score"], 998.0)
        self.assertEqual(components["vector_v1"]["rank"], 2)
        self.assertEqual(components["vector_v1"]["score"], 0.5)
        self.assertEqual(
            components["lexical_v1"]["rrf_contribution"],
            round(1 / (DEFAULT_RRF_K + 2), 12),
        )
        self.assertEqual(
            lexical.calls,
            [(VALID_QUERY, 5, 16)],
        )
        self.assertEqual(vector.calls, [(VALID_QUERY, 5, 16)])
        self.assertEqual(
            result["backend_evidence"]["fusion"]["candidate_pool"],
            {"recipes": 5, "tools": 16},
        )
        self.assertFalse(result["fallback_used"])
        json.dumps(result, allow_nan=False)

    def test_component_fallback_candidates_do_not_receive_rrf_credit(self):
        lexical = StaticComponentBackend(
            "lexical_v1",
            component_result(
                "lexical_v1",
                self.tool_catalog,
                recipe_ids=["chipseq_peak_calling"],
                tool_ids=["fastp"],
                recipe_fallback=True,
                tool_fallback=True,
            ),
        )
        vector = StaticComponentBackend(
            "vector_v1",
            component_result(
                "vector_v1",
                self.tool_catalog,
                recipe_ids=["scrnaseq_qc_clustering"],
                tool_ids=["samtools"],
            ),
        )
        backend = HybridCatalogRetrievalBackend(lexical, vector)

        result = retrieve_catalog_context_with_backend(
            backend,
            VALID_QUERY,
            self.tool_catalog,
            self.recipe_catalog,
        )

        self.assertEqual(
            [candidate["id"] for candidate in result["recipes"]],
            ["scrnaseq_qc_clustering"],
        )
        self.assertEqual(
            [candidate["id"] for candidate in result["tools"]],
            ["samtools"],
        )
        self.assertFalse(result["fallback_used"])
        self.assertTrue(
            result["backend_evidence"]["components"]["lexical_v1"][
                "fallback_used"
            ]
        )

    def test_falls_back_only_when_all_ranking_components_fall_back(self):
        lexical = StaticComponentBackend(
            "lexical_v1",
            component_result(
                "lexical_v1",
                self.tool_catalog,
                recipe_ids=["chipseq_peak_calling"],
                tool_ids=["fastp"],
                recipe_fallback=True,
                tool_fallback=True,
            ),
        )
        vector = StaticComponentBackend(
            "vector_v1",
            component_result(
                "vector_v1",
                self.tool_catalog,
                recipe_ids=["scrnaseq_qc_clustering"],
                tool_ids=["samtools"],
                recipe_fallback=True,
                tool_fallback=True,
            ),
        )
        backend = HybridCatalogRetrievalBackend(lexical, vector)

        result = retrieve_catalog_context_with_backend(
            backend,
            VALID_QUERY,
            self.tool_catalog,
            self.recipe_catalog,
        )

        self.assertTrue(result["recipe_fallback_used"])
        self.assertTrue(result["tool_fallback_used"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["recipes"][0]["id"], "chipseq_peak_calling")
        self.assertEqual(result["recipes"][0]["score"], 0.0)
        self.assertTrue(
            result["recipes"][0]["backend_evidence"]["fusion"]["fallback"]
        )

    def test_rejects_invalid_components_and_rrf_constant(self):
        valid = StaticComponentBackend(
            "lexical_v1",
            component_result(
                "lexical_v1",
                self.tool_catalog,
                recipe_ids=["chipseq_peak_calling"],
                tool_ids=["fastp"],
            ),
        )
        wrong = StaticComponentBackend("other_v1", valid.result)
        vector = StaticComponentBackend(
            "vector_v1",
            component_result(
                "vector_v1",
                self.tool_catalog,
                recipe_ids=["chipseq_peak_calling"],
                tool_ids=["fastp"],
            ),
        )

        with self.assertRaisesRegex(ValueError, "vector_v1 component"):
            HybridCatalogRetrievalBackend(valid, wrong)
        for invalid_rrf_k in (True, 60.0, 59):
            with self.subTest(rrf_k=invalid_rrf_k):
                with self.assertRaisesRegex(ValueError, "fixed rrf_k value 60"):
                    HybridCatalogRetrievalBackend(
                        valid,
                        vector,
                        rrf_k=invalid_rrf_k,
                    )

    def test_rejects_duplicate_candidates_from_one_component(self):
        lexical_result = component_result(
            "lexical_v1",
            self.tool_catalog,
            recipe_ids=["chipseq_peak_calling"],
            tool_ids=["fastp"],
        )
        lexical_result["recipes"].append(copy.deepcopy(lexical_result["recipes"][0]))
        lexical = StaticComponentBackend("lexical_v1", lexical_result)
        vector = StaticComponentBackend(
            "vector_v1",
            component_result(
                "vector_v1",
                self.tool_catalog,
                recipe_ids=["scrnaseq_qc_clustering"],
                tool_ids=["samtools"],
            ),
        )
        backend = HybridCatalogRetrievalBackend(lexical, vector)

        with self.assertRaisesRegex(ValueError, "duplicate hybrid candidate"):
            backend.retrieve(
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )


class HybridCatalogRetrievalBackendTests(unittest.TestCase):
    def setUp(self):
        self.tool_catalog = load_tool_catalog()
        self.recipe_catalog = load_recipe_catalog(tool_catalog=self.tool_catalog)
        self.corpus = build_catalog_retrieval_corpus(
            self.tool_catalog,
            self.recipe_catalog,
        )
        self.provider = FakeEmbeddingProvider(self.corpus)

    def test_factory_requires_explicit_hybrid_dependencies(self):
        with self.assertRaisesRegex(ValueError, "explicit Tool Catalog"):
            get_catalog_retrieval_backend("hybrid_v1")

        with self.assertRaisesRegex(ValueError, "local embedding model path"):
            get_catalog_retrieval_backend(
                "hybrid_v1",
                tool_catalog=self.tool_catalog,
                recipe_catalog=self.recipe_catalog,
            )

    def test_factory_builds_hybrid_backend_with_injected_provider(self):
        backend = get_catalog_retrieval_backend(
            " Hybrid_V1 ",
            embedding_provider=self.provider,
            tool_catalog=self.tool_catalog,
            recipe_catalog=self.recipe_catalog,
        )

        self.assertIsInstance(backend, HybridCatalogRetrievalBackend)
        result = retrieve_catalog_context_with_backend(
            backend,
            VALID_QUERY,
            self.tool_catalog,
            self.recipe_catalog,
        )
        self.assertEqual(result["strategy"], "hybrid_v1")
        self.assertEqual(
            result["backend_evidence"]["fusion"],
            {
                "algorithm": "reciprocal_rank_fusion",
                "rrf_k": 60,
                "candidate_pool": {"recipes": 5, "tools": 16},
            },
        )
        self.assertIn("lexical_v1", result["backend_evidence"]["components"])
        self.assertIn("vector_v1", result["backend_evidence"]["components"])
        json.dumps(result, allow_nan=False)

    def test_hybrid_backend_runs_shared_64_query_evaluation(self):
        backend = get_catalog_retrieval_backend(
            "hybrid_v1",
            embedding_provider=self.provider,
            tool_catalog=self.tool_catalog,
            recipe_catalog=self.recipe_catalog,
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

        self.assertEqual(evaluation["strategy"], "hybrid_v1")
        self.assertEqual(evaluation["query_count"], 64)
        self.assertTrue(
            all(
                result["backend_evidence"]["backend"] == "hybrid_v1"
                for result in evaluation["queries"]
            )
        )
        json.dumps(evaluation, allow_nan=False)


class HybridEvaluationCliTests(unittest.TestCase):
    def test_cli_accepts_explicit_hybrid_configuration(self):
        args = parse_evaluation_args(
            [
                "--backend",
                "hybrid_v1",
                "--embedding-model-path",
                "local-model",
            ]
        )

        self.assertEqual(args.backend, "hybrid_v1")
        self.assertEqual(args.embedding_model_path, Path("local-model"))

    def test_cli_rejects_hybrid_backend_without_local_model_path(self):
        stdout = StringIO()
        stderr = StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = evaluate_retrieval_main(["--backend", "hybrid_v1"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("hybrid_v1 requires --embedding-model-path", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
