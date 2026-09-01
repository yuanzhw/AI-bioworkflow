import unittest

from src.services.catalog_service import get_recipe, get_tool, list_recipes, list_tools


class CatalogServiceTests(unittest.TestCase):
    def test_list_recipes_returns_json_ready_recipe_records(self):
        recipes = list_recipes()

        self.assertGreaterEqual(len(recipes), 1)
        recipe = next(
            recipe for recipe in recipes if recipe["id"] == "rnaseq_differential_expression"
        )
        self.assertEqual(recipe["id"], "rnaseq_differential_expression")
        self.assertIn("required_inputs", recipe)
        self.assertIn("steps", recipe)
        self.assertEqual(recipe["steps"][0]["id"], "qc")
        self.assertIn("fastp", recipe["steps"][0]["allowed_tools"])

    def test_get_recipe_returns_named_recipe(self):
        recipe = get_recipe("rnaseq_differential_expression")

        self.assertEqual(recipe["name"], "RNA-seq differential expression")
        self.assertEqual(recipe["required_inputs"]["sample_ids"]["type"], "Array[String]")
        self.assertEqual(recipe["steps"][0]["scatter"]["id"], "per_sample")

    def test_get_chipseq_recipe_returns_compile_ready_steps(self):
        recipe = get_recipe("chipseq_peak_calling")

        self.assertEqual(recipe["name"], "ChIP-seq peak calling")
        self.assertEqual(recipe["required_inputs"]["genome_index"]["type"], "File")
        self.assertEqual(
            [step["id"] for step in recipe["steps"]],
            ["qc", "align_reads", "sort_and_index", "call_peaks", "qc_report"],
        )
        self.assertEqual(recipe["steps"][3]["allowed_tools"], ["macs2"])
        self.assertTrue(recipe["steps"][4]["optional"])

    def test_list_tools_returns_json_ready_tool_records(self):
        tools = list_tools()

        self.assertGreaterEqual(len(tools), 5)
        fastp = next(tool for tool in tools if tool["id"] == "fastp")
        self.assertEqual(fastp["version"], "1.3.3")
        self.assertEqual(fastp["runtime"]["docker"], "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0")
        self.assertEqual(fastp["trust_status"], "catalog-approved")
        self.assertEqual(fastp["execution_verification"]["status"], "e2e-validated")
        self.assertIn("docs/test-cases.md", fastp["execution_verification"]["evidence"])
        self.assertIn("clean_r1", fastp["outputs"])

    def test_get_tool_returns_explicit_version(self):
        tool = get_tool("salmon", "1.9.0")

        self.assertEqual(tool["id"], "salmon")
        self.assertEqual(tool["version"], "1.9.0")
        self.assertEqual(tool["inputs"]["r1"]["type"], "File")
        self.assertEqual(tool["execution_verification"]["status"], "e2e-validated")
        self.assertIn("1.9.0", tool["versions"])

    def test_get_tool_defaults_to_highest_catalog_version(self):
        tool = get_tool("multiqc")

        self.assertEqual(tool["id"], "multiqc")
        self.assertEqual(tool["version"], "1.21")

    def test_get_chipseq_tool_exposes_unverified_compile_ready_metadata(self):
        tool = get_tool("macs2")

        self.assertEqual(tool["version"], "2.2.9.1")
        self.assertEqual(tool["trust_status"], "catalog-approved")
        self.assertEqual(
            tool["runtime"]["docker"],
            "quay.io/biocontainers/macs2:2.2.9.1--py310h1fe012e_5",
        )
        self.assertFalse(tool["inputs"]["control_bam"]["required"])
        self.assertIn(
            "enriched genomic regions",
            tool["outputs"]["narrow_peaks"]["description"],
        )
        self.assertEqual(
            tool["execution_verification"],
            {"status": "unverified", "evidence": []},
        )

    def test_unknown_recipe_and_tool_raise_key_error(self):
        with self.assertRaisesRegex(KeyError, "unknown recipe"):
            get_recipe("missing_recipe")

        with self.assertRaisesRegex(KeyError, "unknown tool"):
            get_tool("missing_tool")


if __name__ == "__main__":
    unittest.main()
