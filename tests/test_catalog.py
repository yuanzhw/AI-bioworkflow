import copy
import unittest
from typing import Any

from src.analyzer import analyze_workflow_ir
from src.catalog import load_tool_catalog, resolve_tool_plan
from src.recipes import load_recipe_catalog
from src.renderers import render_wdl


def sample_rnaseq_tool_plan() -> dict[str, Any]:
    return {
        "workflow": {
            "name": "RNASeqDEG",
            "recipe": "rnaseq_differential_expression",
            "inputs": {
                "raw_r1": "File",
                "raw_r2": "File",
                "transcriptome_index": "File",
                "sample_groups": "File",
            },
            "tool_calls": [
                {
                    "id": "qc",
                    "step": "qc",
                    "tool": "fastp",
                    "version": "0.23.2",
                    "inputs": {
                        "r1": "raw_r1",
                        "r2": "raw_r2",
                    },
                    "params": {
                        "thread": 4,
                    },
                },
                {
                    "id": "quantify",
                    "step": "quantify",
                    "tool": "salmon",
                    "version": "1.10.2",
                    "inputs": {
                        "r1": "qc.clean_r1",
                        "r2": "qc.clean_r2",
                        "index": "transcriptome_index",
                    },
                    "params": {
                        "thread": 8,
                    },
                },
                {
                    "id": "deg",
                    "step": "differential_expression",
                    "tool": "deseq2",
                    "version": "1.42.0",
                    "inputs": {
                        "counts": "quantify.gene_counts",
                        "sample_groups": "sample_groups",
                    },
                    "params": {
                        "contrast": "condition",
                    },
                },
            ],
            "outputs": {
                "deg_table": "deg.deg_table",
            },
        }
    }


class CatalogResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tool_catalog = load_tool_catalog()
        self.recipe_catalog = load_recipe_catalog(tool_catalog=self.tool_catalog)

    def test_catalog_plan_resolves_to_valid_renderable_ir(self):
        workflow_ir = resolve_tool_plan(
            sample_rnaseq_tool_plan(),
            self.recipe_catalog,
            self.tool_catalog,
        )
        report = analyze_workflow_ir(workflow_ir)

        self.assertTrue(report.is_valid, report.errors)
        self.assertEqual(workflow_ir.workflow.name, "RNASeqDEG")
        self.assertIn("fastp_qc", workflow_ir.tasks)
        self.assertIn("salmon_quantify", workflow_ir.tasks)
        self.assertIn("deseq2_deg", workflow_ir.tasks)

        wdl = render_wdl(workflow_ir)
        self.assertIn("call fastp_qc as qc", wdl)
        self.assertIn("call salmon_quantify as quantify", wdl)
        self.assertIn("call deseq2_deg as deg", wdl)
        self.assertIn("File deg_table = deg.deg_table", wdl)
        self.assertIn("--contrast ~{contrast}", wdl)
        self.assertIn('contrast = "condition"', wdl)
        self.assertIn("-I ~{r2}\n    -o clean_R1.fq.gz", wdl)
        self.assertIn("-O clean_R2.fq.gz\n    --thread ~{thread}", wdl)

    def test_resolver_rejects_tool_not_allowed_for_recipe_step(self):
        plan = copy.deepcopy(sample_rnaseq_tool_plan())
        plan["workflow"]["tool_calls"][0]["tool"] = "salmon"
        plan["workflow"]["tool_calls"][0]["version"] = "1.10.2"

        with self.assertRaisesRegex(ValueError, "not allowed for recipe step 'qc'"):
            resolve_tool_plan(plan, self.recipe_catalog, self.tool_catalog)

    def test_resolver_rejects_unknown_recipe_step(self):
        plan = copy.deepcopy(sample_rnaseq_tool_plan())
        plan["workflow"]["tool_calls"][0]["step"] = "magic"

        with self.assertRaisesRegex(ValueError, "references unknown recipe step 'magic'"):
            resolve_tool_plan(plan, self.recipe_catalog, self.tool_catalog)

    def test_resolver_rejects_missing_required_recipe_step(self):
        plan = copy.deepcopy(sample_rnaseq_tool_plan())
        plan["workflow"]["tool_calls"] = plan["workflow"]["tool_calls"][:-1]

        with self.assertRaisesRegex(ValueError, "missing required recipe step\\(s\\): differential_expression"):
            resolve_tool_plan(plan, self.recipe_catalog, self.tool_catalog)

    def test_resolver_rejects_duplicate_recipe_step(self):
        plan = copy.deepcopy(sample_rnaseq_tool_plan())
        duplicate_call = copy.deepcopy(plan["workflow"]["tool_calls"][0])
        duplicate_call["id"] = "qc_again"
        plan["workflow"]["tool_calls"].append(duplicate_call)

        with self.assertRaisesRegex(ValueError, "duplicate tool calls for recipe step\\(s\\): qc"):
            resolve_tool_plan(plan, self.recipe_catalog, self.tool_catalog)

    def test_resolver_rejects_missing_required_workflow_input(self):
        plan = copy.deepcopy(sample_rnaseq_tool_plan())
        plan["workflow"]["inputs"].pop("sample_groups")

        with self.assertRaisesRegex(ValueError, "missing required workflow input 'sample_groups'"):
            resolve_tool_plan(plan, self.recipe_catalog, self.tool_catalog)

    def test_resolver_rejects_required_workflow_input_type_mismatch(self):
        plan = copy.deepcopy(sample_rnaseq_tool_plan())
        plan["workflow"]["inputs"]["sample_groups"] = "String"

        with self.assertRaisesRegex(
            ValueError,
            "workflow input 'sample_groups' expects File but received String",
        ):
            resolve_tool_plan(plan, self.recipe_catalog, self.tool_catalog)

    def test_resolver_rejects_unknown_param(self):
        plan = copy.deepcopy(sample_rnaseq_tool_plan())
        plan["workflow"]["tool_calls"][0]["params"]["magic"] = 1

        with self.assertRaisesRegex(ValueError, "unknown param 'magic'"):
            resolve_tool_plan(plan, self.recipe_catalog, self.tool_catalog)


if __name__ == "__main__":
    unittest.main()
