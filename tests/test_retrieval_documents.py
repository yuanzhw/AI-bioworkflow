import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from scripts.build_retrieval_corpus import main as build_retrieval_corpus_main
from src.catalog import (
    CatalogRetrievalCorpus,
    CatalogRetrievalDocument,
    ToolCatalog,
    build_catalog_retrieval_corpus,
    load_tool_catalog,
)
from src.recipes import RecipeCatalog, load_recipe_catalog


class CatalogRetrievalDocumentTests(unittest.TestCase):
    def setUp(self):
        self.tool_catalog = load_tool_catalog()
        self.recipe_catalog = load_recipe_catalog(tool_catalog=self.tool_catalog)
        self.corpus = build_catalog_retrieval_corpus(
            self.tool_catalog,
            self.recipe_catalog,
        )

    def test_builds_versioned_sorted_current_catalog_corpus(self):
        document_ids = [document.document_id for document in self.corpus.documents]

        self.assertEqual(self.corpus.schema_version, "1.0")
        self.assertEqual(self.corpus.document_schema_version, "1.0")
        self.assertEqual(self.corpus.fingerprint_algorithm, "sha256")
        self.assertEqual(
            self.corpus.fingerprint,
            "sha256:a0d1e6dde133936d808bf43a4262f5f1e6fc764a89732733298933aa97b490db",
        )
        self.assertEqual(len(self.corpus.documents), 21)
        self.assertEqual(document_ids, sorted(document_ids))
        self.assertEqual(len(document_ids), len(set(document_ids)))

    def test_recipe_document_preserves_identity_and_searchable_structure(self):
        document = self._document("recipe:rnaseq_differential_expression")

        self.assertEqual(document.kind, "recipe")
        self.assertEqual(document.catalog_id, "rnaseq_differential_expression")
        self.assertIsNone(document.catalog_version)
        self.assertIsNone(document.trust_status)
        self.assertIn("name: RNA-seq differential expression", document.text)
        self.assertIn("role=differential_expression", document.text)
        self.assertIn("allowed_tools=deseq2,edger,limma_voom", document.text)

    def test_tool_document_preserves_identity_and_catalog_owned_metadata(self):
        document = self._document("tool:deseq2@1.42.1")

        self.assertEqual(document.kind, "tool")
        self.assertEqual(document.catalog_id, "deseq2")
        self.assertEqual(document.catalog_version, "1.42.1")
        self.assertEqual(document.trust_status, "catalog-approved")
        self.assertEqual(document.execution_verification_status, "e2e-validated")
        self.assertEqual(
            document.execution_verification_evidence,
            ("DEVELOPMENT.md", "docs/test-cases.md"),
        )
        self.assertIn("aliases: DEG | differential expression", document.text)
        self.assertIn("contrast; type=String", document.text)

    def test_corpus_is_independent_of_catalog_insertion_order(self):
        reordered_tools = ToolCatalog(
            {
                (tool.id, tool.version): tool
                for tool in reversed(self.tool_catalog.all())
            }
        )
        reordered_recipes = RecipeCatalog(
            {recipe.id: recipe for recipe in reversed(self.recipe_catalog.all())}
        )

        reordered = build_catalog_retrieval_corpus(
            reordered_tools,
            reordered_recipes,
        )

        self.assertEqual(reordered, self.corpus)

    def test_fingerprint_changes_when_searchable_catalog_content_changes(self):
        tools = {
            (tool.id, tool.version): tool for tool in self.tool_catalog.all()
        }
        deseq2 = tools[("deseq2", "1.42.1")]
        tools[("deseq2", "1.42.1")] = deseq2.model_copy(
            update={"description": deseq2.description + " Updated retrieval text."}
        )

        changed = build_catalog_retrieval_corpus(
            ToolCatalog(tools),
            self.recipe_catalog,
        )

        self.assertNotEqual(changed.fingerprint, self.corpus.fingerprint)

    def test_rejects_recipe_document_with_unknown_allowed_tool(self):
        recipes = {recipe.id: recipe for recipe in self.recipe_catalog.all()}
        recipe = recipes["rnaseq_differential_expression"]
        steps = list(recipe.steps)
        steps[0] = steps[0].model_copy(
            update={"allowed_tools": ["not_approved"]}
        )
        recipes[recipe.id] = recipe.model_copy(update={"steps": steps})

        with self.assertRaisesRegex(ValueError, "unknown approved tool 'not_approved'"):
            build_catalog_retrieval_corpus(
                self.tool_catalog,
                RecipeCatalog(recipes),
            )

    def test_document_rejects_text_that_does_not_match_sections(self):
        document = self._document("tool:deseq2@1.42.1")
        payload = document.model_dump(mode="json")
        payload["text"] = "tampered"

        with self.assertRaisesRegex(ValueError, "text must match its ordered sections"):
            CatalogRetrievalDocument.model_validate(payload)

    def test_corpus_rejects_mismatched_fingerprint(self):
        payload = self.corpus.model_dump(mode="json")
        payload["fingerprint"] = "sha256:" + ("0" * 64)

        with self.assertRaisesRegex(ValueError, "fingerprint must match"):
            CatalogRetrievalCorpus.model_validate(payload)

    def _document(self, document_id: str) -> CatalogRetrievalDocument:
        return next(
            document
            for document in self.corpus.documents
            if document.document_id == document_id
        )


class CatalogRetrievalCorpusCliTests(unittest.TestCase):
    def test_cli_prints_pure_json_corpus_artifact_to_stdout(self):
        stdout = StringIO()

        with redirect_stdout(stdout):
            exit_code = build_retrieval_corpus_main([])
        artifact = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(artifact["documents"]), 21)

    def test_cli_writes_json_ready_corpus_artifact(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "nested" / "retrieval_corpus.json"

            exit_code = build_retrieval_corpus_main(["--output", str(output_path)])
            artifact = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(artifact["schema_version"], "1.0")
        self.assertEqual(artifact["document_schema_version"], "1.0")
        self.assertRegex(artifact["fingerprint"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(len(artifact["documents"]), 21)


if __name__ == "__main__":
    unittest.main()
