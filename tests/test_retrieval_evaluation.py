import unittest
from pathlib import Path
from typing import Any

from src.catalog import load_tool_catalog
from src.catalog.retrieval_eval import (
    RetrievalQuery,
    evaluate_retrieval_queries,
    load_retrieval_queries,
)
from src.recipes import load_recipe_catalog


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "retrieval_queries.json"


def fake_retriever(
    query: str,
    _tool_catalog,
    _recipe_catalog,
    _top_k_recipes: int,
    _top_k_tools: int,
) -> dict[str, Any]:
    fixtures = {
        "supported hit": {
            "recipes": [{"id": "rnaseq_differential_expression"}],
            "tools": [{"id": "fastp"}, {"id": "salmon"}],
            "fallback_used": False,
            "fallback_reason": None,
        },
        "supported miss": {
            "recipes": [{"id": "other_recipe"}],
            "tools": [{"id": "multiqc"}],
            "fallback_used": True,
            "fallback_reason": "synthetic fallback",
        },
        "unsupported direct match": {
            "recipes": [{"id": "rnaseq_differential_expression"}],
            "tools": [{"id": "fastp"}],
            "fallback_used": False,
            "fallback_reason": None,
        },
    }
    retrieval = fixtures[query]
    return {
        "query": query,
        "strategy": "fake_v1",
        **retrieval,
    }


def multi_version_fake_retriever(
    query: str,
    _tool_catalog,
    _recipe_catalog,
    _top_k_recipes: int,
    _top_k_tools: int,
) -> dict[str, Any]:
    return {
        "query": query,
        "strategy": "fake_multi_version_v1",
        "recipes": [{"id": "rnaseq_differential_expression"}],
        "tools": [
            {"id": "salmon", "version": "1.9.0"},
            {"id": "salmon", "version": "1.10.0"},
            {"id": "fastp", "version": "1.3.3"},
        ],
        "fallback_used": False,
        "fallback_reason": None,
    }


class RetrievalEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tool_catalog = load_tool_catalog()
        self.recipe_catalog = load_recipe_catalog(tool_catalog=self.tool_catalog)

    def test_loads_current_catalog_query_fixture(self):
        queries = load_retrieval_queries(FIXTURE_PATH)

        self.assertEqual(len(queries), 31)
        self.assertEqual(sum(1 for query in queries if query.supported), 27)
        self.assertEqual(sum(1 for query in queries if not query.supported), 4)
        self.assertEqual(queries[0].id, "rnaseq_deg_basic_en")
        self.assertEqual(queries[0].workflow_family, "bulk_rnaseq")
        self.assertIn("fastp", queries[0].expected_tools)
        self.assertIn(
            "rnaseq_reference_prep_basic_en",
            {query.id for query in queries},
        )
        self.assertIn(
            "rnaseq_deg_alternative_backends_en",
            {query.id for query in queries},
        )
        queries_by_id = {query.id: query for query in queries}
        explicit_deseq2 = queries_by_id["rnaseq_deg_explicit_tools_en"]
        self.assertIn("deseq2", explicit_deseq2.expected_tools)
        self.assertEqual(
            explicit_deseq2.expected_roles["differential_expression"],
            ["deseq2"],
        )
        chinese_explicit_deseq2 = queries_by_id["rnaseq_deg_cn_mixed_tools"]
        self.assertIn("deseq2", chinese_explicit_deseq2.expected_tools)
        self.assertEqual(
            chinese_explicit_deseq2.expected_roles["differential_expression"],
            ["deseq2"],
        )
        generic_deg = queries_by_id["rnaseq_deg_abbrev_en"]
        self.assertNotIn("deseq2", generic_deg.expected_tools)
        self.assertEqual(
            generic_deg.expected_roles["differential_expression"],
            ["deseq2", "edger", "limma_voom"],
        )
        chipseq = queries_by_id["chipseq_peak_calling_basic_en"]
        self.assertEqual(chipseq.workflow_family, "chipseq")
        self.assertEqual(chipseq.expected_recipe, "chipseq_peak_calling")
        self.assertIn("macs2", chipseq.expected_tools)
        chipseq_annotation = queries_by_id["unsupported_chipseq_peak_annotation_en"]
        self.assertFalse(chipseq_annotation.supported)
        self.assertEqual(chipseq_annotation.workflow_family, "chipseq")

    def test_evaluates_current_catalog_baseline(self):
        queries = load_retrieval_queries(FIXTURE_PATH)

        result = evaluate_retrieval_queries(
            queries,
            self.tool_catalog,
            self.recipe_catalog,
        )

        self.assertEqual(result["strategy"], "lexical_v1")
        self.assertEqual(result["top_k_recipes"], 3)
        self.assertEqual(result["top_k_tools"], 8)
        self.assertEqual(result["query_count"], 31)
        self.assertEqual(result["supported_query_count"], 27)
        self.assertEqual(result["unsupported_query_count"], 4)
        self.assertEqual(len(result["queries"]), 31)
        for metric in result["metrics"].values():
            self.assertGreaterEqual(metric, 0.0)
            self.assertLessEqual(metric, 1.0)
        self.assertEqual(result["metrics"]["planner_context_tool_recall"], 1.0)
        self.assertEqual(result["metrics"]["planner_context_role_coverage"], 1.0)
        self.assertEqual(
            set(result["family_metrics"]),
            {"bulk_rnaseq", "chipseq", "metagenomics", "scrnaseq", "variant_calling"},
        )
        self.assertEqual(result["family_metrics"]["bulk_rnaseq"]["query_count"], 21)
        self.assertEqual(result["family_metrics"]["chipseq"]["query_count"], 7)
        self.assertEqual(result["family_metrics"]["chipseq"]["supported_query_count"], 6)
        for metric in result["macro_family_metrics"].values():
            self.assertGreaterEqual(metric, 0.0)
            self.assertLessEqual(metric, 1.0)

    def test_computes_supported_metrics_and_tracks_unsupported_matches(self):
        queries = [
            RetrievalQuery(
                id="q1",
                query="supported hit",
                supported=True,
                workflow_family="bulk_rnaseq",
                expected_recipe="rnaseq_differential_expression",
                expected_tools=["fastp", "deseq2"],
                expected_roles={
                    "read_quality_control": ["fastp"],
                    "differential_expression": ["deseq2"],
                },
            ),
            RetrievalQuery(
                id="q2",
                query="supported miss",
                supported=True,
                workflow_family="bulk_rnaseq",
                expected_recipe="rnaseq_differential_expression",
                expected_tools=["deseq2"],
                expected_roles={"differential_expression": ["deseq2"]},
            ),
            RetrievalQuery(
                id="q3",
                query="unsupported direct match",
                supported=False,
                workflow_family="chipseq",
                expected_recipe=None,
                expected_tools=[],
                expected_roles={},
            ),
        ]

        result = evaluate_retrieval_queries(
            queries,
            self.tool_catalog,
            self.recipe_catalog,
            retriever=fake_retriever,
        )

        self.assertEqual(result["strategy"], "fake_v1")
        self.assertEqual(result["metrics"]["recipe_recall_at_1"], 0.5)
        self.assertEqual(result["metrics"]["recipe_recall_at_k"], 0.5)
        self.assertEqual(result["metrics"]["recipe_mrr"], 0.5)
        self.assertEqual(result["metrics"]["tool_recall_at_3"], 0.25)
        self.assertEqual(result["metrics"]["tool_recall_at_5"], 0.25)
        self.assertEqual(result["metrics"]["tool_recall_at_k"], 0.25)
        self.assertEqual(result["metrics"]["tool_mrr"], 0.5)
        self.assertEqual(result["metrics"]["role_coverage"], 0.25)
        self.assertEqual(result["metrics"]["planner_context_tool_recall"], 0.5)
        self.assertEqual(result["metrics"]["planner_context_role_coverage"], 0.5)
        self.assertEqual(result["metrics"]["fallback_rate"], 0.3333)
        self.assertEqual(result["metrics"]["supported_fallback_rate"], 0.5)
        self.assertEqual(result["metrics"]["unsupported_fallback_rate"], 0.0)
        self.assertEqual(result["metrics"]["unsupported_direct_match_rate"], 1.0)
        self.assertEqual(result["fallback_query_ids"], ["q2"])
        self.assertEqual(result["unsupported_direct_match_query_ids"], ["q3"])
        self.assertEqual(result["family_metrics"]["bulk_rnaseq"]["query_count"], 2)
        self.assertEqual(result["family_metrics"]["chipseq"]["query_count"], 1)
        self.assertEqual(result["macro_family_metrics"]["recipe_recall_at_1"], 0.5)
        self.assertIn("deseq2", result["queries"][0]["planner_context_tools"])
        self.assertEqual(result["queries"][1]["missed_expected_tools"], ["deseq2"])
        self.assertEqual(result["queries"][1]["missed_roles"], ["differential_expression"])
        self.assertEqual(
            result["queries"][1]["planner_context_missed_expected_tools"],
            ["deseq2"],
        )

    def test_deduplicates_planner_context_tool_ids_from_multiple_versions(self):
        queries = [
            RetrievalQuery(
                id="multi-version",
                query="multi-version tool results",
                supported=True,
                workflow_family="bulk_rnaseq",
                expected_recipe="rnaseq_differential_expression",
                expected_tools=["salmon", "deseq2"],
                expected_roles={
                    "expression_quantification": ["salmon"],
                    "differential_expression": ["deseq2"],
                },
            )
        ]

        result = evaluate_retrieval_queries(
            queries,
            self.tool_catalog,
            self.recipe_catalog,
            retriever=multi_version_fake_retriever,
        )

        planner_context_tools = result["queries"][0]["planner_context_tools"]
        self.assertEqual(planner_context_tools[:2], ["salmon", "fastp"])
        self.assertEqual(planner_context_tools.count("salmon"), 1)
        self.assertEqual(result["metrics"]["planner_context_tool_recall"], 1.0)
        self.assertEqual(result["metrics"]["planner_context_role_coverage"], 1.0)

    def test_rejects_unsupported_queries_with_expected_hits(self):
        with self.assertRaisesRegex(ValueError, "unsupported queries must not define expected hits"):
            RetrievalQuery.from_dict(
                {
                    "id": "bad",
                    "query": "unsupported",
                    "supported": False,
                    "workflow_family": "bulk_rnaseq",
                    "expected_recipe": "rnaseq_differential_expression",
                    "expected_tools": [],
                    "expected_roles": {},
                }
            )

    def test_requires_workflow_family_in_query_schema(self):
        with self.assertRaisesRegex(ValueError, "workflow_family must be a non-empty string"):
            RetrievalQuery.from_dict(
                {
                    "id": "missing-family",
                    "query": "quantify expression",
                    "supported": True,
                    "expected_recipe": "rnaseq_differential_expression",
                    "expected_tools": ["salmon"],
                    "expected_roles": {"expression_quantification": ["salmon"]},
                }
            )

    def test_requires_enough_tool_results_for_fixed_recall_cutoffs(self):
        query = RetrievalQuery(
            id="q1",
            query="supported hit",
            supported=True,
            workflow_family="bulk_rnaseq",
            expected_recipe="rnaseq_differential_expression",
            expected_tools=["fastp"],
            expected_roles={"read_quality_control": ["fastp"]},
        )

        with self.assertRaisesRegex(ValueError, "top_k_tools must be >= 5"):
            evaluate_retrieval_queries(
                [query],
                self.tool_catalog,
                self.recipe_catalog,
                top_k_tools=4,
                retriever=fake_retriever,
            )

    def test_rejects_non_object_fixture_entries(self):
        with self.assertRaisesRegex(ValueError, "entry at index 0 must be an object"):
            load_retrieval_queries(FIXTURE_PATH.with_name("invalid_non_object_queries.json"))


if __name__ == "__main__":
    unittest.main()
