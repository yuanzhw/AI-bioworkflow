import unittest

from scripts.evaluate_retrieval import parse_args
from src.catalog import (
    CatalogRetrievalBackend,
    LexicalCatalogRetrievalBackend,
    get_catalog_retrieval_backend,
    load_tool_catalog,
    retrieve_catalog_context,
    retrieve_catalog_context_with_backend,
)
from src.recipes import load_recipe_catalog


class StaticRetrievalBackend:
    name = "static_v1"

    def __init__(self, result):
        self.result = result

    def retrieve(
        self,
        _query,
        _tool_catalog,
        _recipe_catalog,
        _top_k_recipes=3,
        _top_k_tools=8,
    ):
        return self.result


def valid_static_result():
    return {
        "query": "demo",
        "strategy": "static_v1",
        "recipes": [{"id": "demo_recipe"}],
        "tools": [{"id": "demo_tool"}],
        "recipe_fallback_used": False,
        "tool_fallback_used": False,
        "fallback_used": False,
        "fallback_reason": None,
        "backend_evidence": {
            "schema_version": "1.0",
            "backend": "static_v1",
        },
    }


class RetrievalBackendFactoryTests(unittest.TestCase):
    def test_factory_defaults_to_lexical_backend(self):
        backend = get_catalog_retrieval_backend()

        self.assertIsInstance(backend, LexicalCatalogRetrievalBackend)
        self.assertIsInstance(backend, CatalogRetrievalBackend)
        self.assertEqual(backend.name, "lexical_v1")

    def test_factory_normalizes_explicit_backend_name(self):
        backend = get_catalog_retrieval_backend(" Lexical_V1 ")

        self.assertIsInstance(backend, LexicalCatalogRetrievalBackend)

    def test_unknown_backend_error_lists_supported_backends(self):
        with self.assertRaisesRegex(ValueError, "vector_v1.*lexical_v1"):
            get_catalog_retrieval_backend("vector_v1")

    def test_evaluation_cli_defaults_to_lexical_backend(self):
        self.assertEqual(parse_args([]).backend, "lexical_v1")
        self.assertEqual(
            parse_args(["--backend", "lexical_v1"]).backend,
            "lexical_v1",
        )


class RetrievalBackendContractTests(unittest.TestCase):
    def setUp(self):
        self.tool_catalog = load_tool_catalog()
        self.recipe_catalog = load_recipe_catalog(tool_catalog=self.tool_catalog)

    def test_lexical_backend_preserves_legacy_results_and_adds_evidence(self):
        query = "Run RNA-seq differential expression."
        legacy = retrieve_catalog_context(query, self.tool_catalog, self.recipe_catalog)

        result = retrieve_catalog_context_with_backend(
            get_catalog_retrieval_backend("lexical_v1"),
            query,
            self.tool_catalog,
            self.recipe_catalog,
        )

        evidence = result.pop("backend_evidence")
        self.assertEqual(result, legacy)
        self.assertEqual(evidence["schema_version"], "1.0")
        self.assertEqual(evidence["backend"], "lexical_v1")
        self.assertIn("differential", evidence["query_tokens"])

    def test_contract_rejects_mismatched_strategy(self):
        result = valid_static_result()
        result["strategy"] = "other_v1"

        with self.assertRaisesRegex(ValueError, "returned strategy 'other_v1'"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                "demo",
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_rejects_inconsistent_fallback_provenance(self):
        result = valid_static_result()
        result["recipe_fallback_used"] = True

        with self.assertRaisesRegex(ValueError, "fallback_used must equal"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                "demo",
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_requires_versioned_backend_evidence(self):
        result = valid_static_result()
        result["backend_evidence"] = {"backend": "static_v1"}

        with self.assertRaisesRegex(ValueError, "schema version 1.0"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                "demo",
                self.tool_catalog,
                self.recipe_catalog,
            )


if __name__ == "__main__":
    unittest.main()
