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


FIXTURE_PATH = Path("tests/fixtures/retrieval_queries.json")


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


class RetrievalEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.tool_catalog = load_tool_catalog()
        self.recipe_catalog = load_recipe_catalog(tool_catalog=self.tool_catalog)

    def test_loads_current_catalog_query_fixture(self):
        queries = load_retrieval_queries(FIXTURE_PATH)

        self.assertEqual(len(queries), 16)
        self.assertEqual(sum(1 for query in queries if query.supported), 12)
        self.assertEqual(sum(1 for query in queries if not query.supported), 4)
        self.assertEqual(queries[0].id, "rnaseq_deg_basic_en")
        self.assertIn("fastp", queries[0].expected_tools)

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
        self.assertEqual(result["query_count"], 16)
        self.assertEqual(result["supported_query_count"], 12)
        self.assertEqual(result["unsupported_query_count"], 4)
        self.assertEqual(len(result["queries"]), 16)
        for metric in result["metrics"].values():
            self.assertGreaterEqual(metric, 0.0)
            self.assertLessEqual(metric, 1.0)

    def test_computes_supported_metrics_and_tracks_unsupported_matches(self):
        queries = [
            RetrievalQuery(
                id="q1",
                query="supported hit",
                supported=True,
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
                expected_recipe="rnaseq_differential_expression",
                expected_tools=["deseq2"],
                expected_roles={"differential_expression": ["deseq2"]},
            ),
            RetrievalQuery(
                id="q3",
                query="unsupported direct match",
                supported=False,
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
        self.assertEqual(result["metrics"]["recipe_recall_at_k"], 0.5)
        self.assertEqual(result["metrics"]["recipe_mrr"], 0.5)
        self.assertEqual(result["metrics"]["tool_recall_at_k"], 0.25)
        self.assertEqual(result["metrics"]["tool_mrr"], 0.5)
        self.assertEqual(result["metrics"]["role_coverage"], 0.25)
        self.assertEqual(result["metrics"]["fallback_rate"], 0.3333)
        self.assertEqual(result["metrics"]["supported_fallback_rate"], 0.5)
        self.assertEqual(result["metrics"]["unsupported_fallback_rate"], 0.0)
        self.assertEqual(result["fallback_query_ids"], ["q2"])
        self.assertEqual(result["unsupported_direct_match_query_ids"], ["q3"])
        self.assertEqual(result["queries"][1]["missed_expected_tools"], ["deseq2"])
        self.assertEqual(result["queries"][1]["missed_roles"], ["differential_expression"])

    def test_rejects_unsupported_queries_with_expected_hits(self):
        with self.assertRaisesRegex(ValueError, "unsupported queries must not define expected hits"):
            RetrievalQuery.from_dict(
                {
                    "id": "bad",
                    "query": "unsupported",
                    "supported": False,
                    "expected_recipe": "rnaseq_differential_expression",
                    "expected_tools": [],
                    "expected_roles": {},
                }
            )


if __name__ == "__main__":
    unittest.main()
