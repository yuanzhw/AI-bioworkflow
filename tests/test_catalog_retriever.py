import unittest

from src.catalog import load_tool_catalog, retrieve_catalog_context, tokenize_for_retrieval
from src.recipes import load_recipe_catalog


class CatalogRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.tool_catalog = load_tool_catalog()
        self.recipe_catalog = load_recipe_catalog(tool_catalog=self.tool_catalog)

    def test_retrieves_rnaseq_recipe_and_key_tools(self):
        result = retrieve_catalog_context(
            (
                "Build a bulk RNA-seq differential expression workflow with FASTQ QC, "
                "adapter trimming, transcript quantification, Salmon aggregation, "
                "transcript to gene counts, DESeq2 DEG, and workflow summary report."
            ),
            self.tool_catalog,
            self.recipe_catalog,
            top_k_recipes=3,
            top_k_tools=8,
        )

        self.assertEqual(result["strategy"], "lexical_v1")
        self.assertFalse(result["fallback_used"])
        self.assertIsNone(result["fallback_reason"])
        self.assertEqual(result["recipes"][0]["id"], "rnaseq_differential_expression")

        tool_ids = {tool["id"] for tool in result["tools"]}
        self.assertTrue(
            {"fastp", "salmon", "tximport", "deseq2", "multiqc"}.issubset(tool_ids),
            result["tools"],
        )

        recipe = result["recipes"][0]
        self.assertGreater(recipe["score"], 0)
        self.assertTrue(recipe["matched_terms"])
        self.assertTrue(recipe["matched_fields"])
        self.assertIn("Matched approved catalog recipe", recipe["reason"])

        deseq2 = next(tool for tool in result["tools"] if tool["id"] == "deseq2")
        self.assertGreater(deseq2["score"], 0)
        self.assertIn("differential", deseq2["matched_terms"])
        self.assertTrue(deseq2["matched_fields"])
        self.assertEqual(deseq2["trust_status"], "catalog-approved")
        self.assertIn("Matched approved catalog tool", deseq2["reason"])

    def test_tokenizer_supports_rnaseq_variants_and_cjk_ngrams(self):
        tokens = tokenize_for_retrieval("做差异表达 RNAseq")

        self.assertIn("rna", tokens)
        self.assertIn("seq", tokens)
        self.assertIn("rnaseq", tokens)
        self.assertIn("差", tokens)
        self.assertIn("差异", tokens)
        self.assertIn("表达", tokens)

    def test_no_match_fallback_records_reason_and_approved_tools(self):
        result = retrieve_catalog_context(
            "zzzz qqqq",
            self.tool_catalog,
            self.recipe_catalog,
            top_k_recipes=2,
            top_k_tools=3,
        )

        self.assertTrue(result["fallback_used"])
        self.assertIn("recipe recall returned no matches", result["fallback_reason"])
        self.assertIn("tool recall returned no matches", result["fallback_reason"])
        self.assertGreaterEqual(len(result["recipes"]), 1)
        self.assertEqual(result["recipes"][0]["score"], 0.0)
        self.assertEqual(result["recipes"][0]["matched_terms"], [])
        self.assertIn("Fallback result", result["recipes"][0]["reason"])
        self.assertEqual(len(result["tools"]), 3)
        for tool in result["tools"]:
            self.assertEqual(tool["trust_status"], "catalog-approved")
            self.assertEqual(tool["matched_terms"], [])
            self.assertIn("Fallback result", tool["reason"])

    def test_rejects_empty_query(self):
        with self.assertRaisesRegex(ValueError, "query must not be empty"):
            retrieve_catalog_context(
                "  ",
                self.tool_catalog,
                self.recipe_catalog,
            )


if __name__ == "__main__":
    unittest.main()
