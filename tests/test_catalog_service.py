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

    def test_get_scrnaseq_tool_exposes_compile_ready_wrapper_contract(self):
        tool = get_tool("scanpy_qc_clustering")

        self.assertEqual(tool["version"], "1.12.3")
        self.assertEqual(tool["trust_status"], "catalog-approved")
        self.assertEqual(
            tool["runtime"]["docker"],
            "ghcr.io/yuanzhw/ai-bioworkflow/scanpy_qc_clustering:1.12.3-r1",
        )
        self.assertFalse(tool["inputs"]["cell_metadata"]["required"])
        self.assertIn("marker_genes", tool["outputs"])
        self.assertEqual(
            tool["execution_verification"],
            {"status": "unverified", "evidence": []},
        )

    def test_get_variant_calling_tools_exposes_compile_ready_contracts(self):
        bwa_mem2 = get_tool("bwa_mem2")
        bcftools_call = get_tool("bcftools_call")
        bcftools_filter = get_tool("bcftools_filter")

        self.assertEqual(bwa_mem2["version"], "2.3")
        self.assertEqual(
            bwa_mem2["runtime"]["docker"],
            "quay.io/biocontainers/bwa-mem2:2.3--he70b90d_0",
        )
        self.assertIn("aligned_sam", bwa_mem2["outputs"])
        self.assertEqual(bcftools_call["version"], "1.24")
        self.assertIn("reference_fai", bcftools_call["inputs"])
        self.assertIn("unfiltered_vcf_index", bcftools_call["outputs"])
        self.assertIn(
            "record includes INFO/DP",
            bcftools_call["outputs"]["unfiltered_vcf"]["description"],
        )
        self.assertEqual(bcftools_filter["params"]["min_qual"]["default"], 20.0)
        self.assertIn("filtered_vcf_index", bcftools_filter["outputs"])
        self.assertIn(
            "record must include INFO/DP",
            bcftools_filter["inputs"]["unfiltered_vcf"]["description"],
        )
        for tool in (bwa_mem2, bcftools_call, bcftools_filter):
            self.assertEqual(tool["trust_status"], "catalog-approved")
            self.assertEqual(
                tool["execution_verification"],
                {"status": "unverified", "evidence": []},
            )

    def test_get_scrnaseq_recipe_returns_bounded_single_step(self):
        recipe = get_recipe("scrnaseq_qc_clustering")

        self.assertEqual(recipe["name"], "scRNA-seq QC and clustering")
        self.assertEqual(recipe["required_inputs"]["matrix_h5"]["type"], "File")
        self.assertEqual(recipe["steps"][0]["id"], "analyze_cells")
        self.assertEqual(recipe["steps"][0]["role"], "single_cell_qc_clustering")
        self.assertEqual(recipe["steps"][0]["allowed_tools"], ["scanpy_qc_clustering"])

    def test_get_germline_short_variant_calling_recipe_returns_bounded_steps(self):
        recipe = get_recipe("germline_short_variant_calling")

        self.assertEqual(recipe["name"], "Germline short variant calling")
        self.assertEqual(
            set(recipe["required_inputs"]),
            {"raw_r1", "raw_r2", "bwa_index", "reference_fasta", "reference_fai"},
        )
        self.assertEqual(
            [step["id"] for step in recipe["steps"]],
            [
                "qc",
                "align_reads",
                "sort_and_index",
                "call_variants",
                "filter_variants",
                "qc_report",
            ],
        )
        self.assertEqual(recipe["steps"][1]["allowed_tools"], ["bwa_mem2"])
        self.assertEqual(recipe["steps"][3]["allowed_tools"], ["bcftools_call"])
        self.assertEqual(recipe["steps"][4]["allowed_tools"], ["bcftools_filter"])
        self.assertTrue(recipe["steps"][5]["optional"])

    def test_unknown_recipe_and_tool_raise_key_error(self):
        with self.assertRaisesRegex(KeyError, "unknown recipe"):
            get_recipe("missing_recipe")

        with self.assertRaisesRegex(KeyError, "unknown tool"):
            get_tool("missing_tool")


if __name__ == "__main__":
    unittest.main()
