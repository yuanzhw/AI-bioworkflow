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


VALID_QUERY = "Run RNA-seq differential expression."


class StaticRetrievalBackend:
    name = "static_v1"

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def retrieve(
        self,
        _query,
        _tool_catalog,
        _recipe_catalog,
        _top_k_recipes=3,
        _top_k_tools=8,
    ):
        self.calls += 1
        return self.result


def valid_static_result(tool_catalog, recipe_catalog):
    result = retrieve_catalog_context(VALID_QUERY, tool_catalog, recipe_catalog)
    return {
        **result,
        "strategy": "static_v1",
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
        query = VALID_QUERY
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
        result = valid_static_result(self.tool_catalog, self.recipe_catalog)
        result["strategy"] = "other_v1"

        with self.assertRaisesRegex(ValueError, "returned strategy 'other_v1'"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_rejects_inconsistent_fallback_provenance(self):
        result = valid_static_result(self.tool_catalog, self.recipe_catalog)
        result["recipe_fallback_used"] = True

        with self.assertRaisesRegex(ValueError, "fallback_used must equal"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_requires_versioned_backend_evidence(self):
        result = valid_static_result(self.tool_catalog, self.recipe_catalog)
        result["backend_evidence"] = {"backend": "static_v1"}

        with self.assertRaisesRegex(ValueError, "schema version 1.0"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_requires_complete_candidate_shape(self):
        result = valid_static_result(self.tool_catalog, self.recipe_catalog)
        result["recipes"][0].pop("score")

        with self.assertRaisesRegex(ValueError, "finite numeric score"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_rejects_recipe_outside_approved_catalog(self):
        result = valid_static_result(self.tool_catalog, self.recipe_catalog)
        result["recipes"][0]["id"] = "unknown_recipe"

        with self.assertRaisesRegex(ValueError, "unknown approved recipe"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_requires_tool_version(self):
        result = valid_static_result(self.tool_catalog, self.recipe_catalog)
        result["tools"][0].pop("version")

        with self.assertRaisesRegex(ValueError, "non-empty version"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_rejects_tool_version_outside_approved_catalog(self):
        result = valid_static_result(self.tool_catalog, self.recipe_catalog)
        result["tools"][0]["version"] = "999.0"

        with self.assertRaisesRegex(ValueError, "unknown approved tool version"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_preserves_catalog_tool_metadata(self):
        result = valid_static_result(self.tool_catalog, self.recipe_catalog)
        result["tools"][0]["execution_verification"] = {
            "status": "invalid",
            "evidence": [],
        }

        with self.assertRaisesRegex(ValueError, "preserve Catalog execution_verification"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_requires_catalog_approved_trust_status(self):
        result = valid_static_result(self.tool_catalog, self.recipe_catalog)
        result["tools"][0]["trust_status"] = "candidate"

        with self.assertRaisesRegex(ValueError, "catalog-approved"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_rejects_non_json_backend_evidence(self):
        result = valid_static_result(self.tool_catalog, self.recipe_catalog)
        result["backend_evidence"]["model"] = object()

        with self.assertRaisesRegex(ValueError, "non-JSON-compatible value"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_rejects_non_finite_values(self):
        result = valid_static_result(self.tool_catalog, self.recipe_catalog)
        result["recipes"][0]["score"] = float("nan")

        with self.assertRaisesRegex(ValueError, "non-finite number"):
            retrieve_catalog_context_with_backend(
                StaticRetrievalBackend(result),
                VALID_QUERY,
                self.tool_catalog,
                self.recipe_catalog,
            )

    def test_contract_requires_positive_top_k_before_backend_dispatch(self):
        cases = (
            ("top_k_recipes", {"top_k_recipes": 0}),
            ("top_k_tools", {"top_k_tools": -1}),
            ("top_k_tools", {"top_k_tools": True}),
        )

        for field_name, limits in cases:
            with self.subTest(field_name=field_name, value=limits[field_name]):
                backend = StaticRetrievalBackend(
                    valid_static_result(self.tool_catalog, self.recipe_catalog)
                )
                with self.assertRaisesRegex(
                    ValueError,
                    f"{field_name} must be a positive integer",
                ):
                    retrieve_catalog_context_with_backend(
                        backend,
                        VALID_QUERY,
                        self.tool_catalog,
                        self.recipe_catalog,
                        **limits,
                    )
                self.assertEqual(backend.calls, 0)

    def test_contract_rejects_candidate_counts_above_top_k(self):
        cases = (
            ("recipes", {"top_k_recipes": 1}, "top_k_recipes=1"),
            ("tools", {"top_k_tools": 1}, "top_k_tools=1"),
        )

        for field_name, limits, expected_message in cases:
            with self.subTest(field_name=field_name):
                result = valid_static_result(self.tool_catalog, self.recipe_catalog)
                candidate = result[field_name][0]
                result[field_name] = [candidate, dict(candidate)]
                backend = StaticRetrievalBackend(result)

                with self.assertRaisesRegex(ValueError, expected_message):
                    retrieve_catalog_context_with_backend(
                        backend,
                        VALID_QUERY,
                        self.tool_catalog,
                        self.recipe_catalog,
                        **limits,
                    )
                self.assertEqual(backend.calls, 1)


if __name__ == "__main__":
    unittest.main()
