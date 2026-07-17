import copy
import unittest
from pathlib import Path
from typing import Any

import yaml

from src.analyzer import analyze_workflow_ir
from src.catalog import load_tool_catalog, resolve_tool_plan
from src.catalog.schema import ToolSpec
from src.recipes import load_recipe_catalog
from src.renderers import render_wdl


CATALOG_TOOLS_DIR = Path(__file__).resolve().parents[1] / "src" / "catalog" / "tools"


def sample_rnaseq_tool_plan() -> dict[str, Any]:
    return {
        "workflow": {
            "name": "RNASeqDEG",
            "recipe": "rnaseq_differential_expression",
            "inputs": {
                "sample_ids": "Array[String]",
                "raw_r1s": "Array[File]",
                "raw_r2s": "Array[File]",
                "transcriptome_index": "File",
                "tx2gene": "File",
                "sample_groups": "File",
            },
            "tool_calls": [
                {
                    "id": "qc",
                    "step": "qc",
                    "tool": "fastp",
                    "version": "1.3.3",
                    "inputs": {
                        "r1": "raw_r1s",
                        "r2": "raw_r2s",
                    },
                    "params": {
                        "thread": 4,
                    },
                },
                {
                    "id": "quantify",
                    "step": "quantify",
                    "tool": "salmon",
                    "version": "1.9.0",
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
                    "id": "summarize",
                    "step": "summarize_transcripts",
                    "tool": "tximport",
                    "version": "1.30.0",
                    "inputs": {
                        "quant_files": "quantify.quant_file",
                        "sample_ids": "sample_ids",
                        "tx2gene": "tx2gene",
                    },
                    "params": {},
                },
                {
                    "id": "deg",
                    "step": "differential_expression",
                    "tool": "deseq2",
                    "version": "1.42.1",
                    "inputs": {
                        "counts": "summarize.gene_counts",
                        "sample_groups": "sample_groups",
                    },
                    "params": {
                        "contrast": "condition",
                    },
                },
                {
                    "id": "report",
                    "step": "qc_report",
                    "tool": "multiqc",
                    "version": "1.21",
                    "inputs": {
                        "report_files": [
                            "qc.html_report",
                            "qc.json_report",
                            "quantify.log_file",
                        ],
                    },
                    "params": {},
                },
            ],
            "outputs": {
                "deg_table": "deg.deg_table",
                "multiqc_report": "report.multiqc_report",
            },
        }
    }


def sample_rnaseq_reference_prep_plan() -> dict[str, Any]:
    return {
        "workflow": {
            "name": "RNASeqReferencePrep",
            "recipe": "rnaseq_reference_preparation",
            "inputs": {
                "transcriptome_fasta": "File",
                "annotation_gtf": "File",
            },
            "tool_calls": [
                {
                    "id": "index",
                    "step": "build_salmon_index",
                    "tool": "salmon_index",
                    "version": "1.9.0",
                    "inputs": {
                        "transcriptome_fasta": "transcriptome_fasta",
                    },
                    "params": {
                        "kmer_size": 31,
                    },
                },
                {
                    "id": "mapping",
                    "step": "extract_tx2gene",
                    "tool": "gtf_tx2gene",
                    "version": "1.0.0",
                    "inputs": {
                        "annotation_gtf": "annotation_gtf",
                    },
                    "params": {},
                },
            ],
            "outputs": {
                "transcriptome_index": "index.index_archive",
                "tx2gene": "mapping.tx2gene",
            },
        }
    }


class CatalogDefinitionTests(unittest.TestCase):
    def test_catalog_file_path_matches_tool_id_and_version(self):
        for yaml_path in sorted(CATALOG_TOOLS_DIR.rglob("*.yaml")):
            with yaml_path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)

            with self.subTest(path=str(yaml_path.relative_to(CATALOG_TOOLS_DIR))):
                self.assertIsInstance(data, dict)
                self.assertEqual(yaml_path.parent.name, data.get("id"))
                self.assertEqual(yaml_path.stem, str(data.get("version")))


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
        self.assertIn("tximport_summarize", workflow_ir.tasks)
        self.assertIn("deseq2_deg", workflow_ir.tasks)
        self.assertIn("multiqc_report", workflow_ir.tasks)
        self.assertEqual(workflow_ir.workflow.steps[0].kind, "scatter")

        wdl = render_wdl(workflow_ir)
        self.assertIn("scatter (i in range(length(sample_ids)))", wdl)
        self.assertIn("call fastp_qc as qc", wdl)
        self.assertIn("call salmon_quantify as quantify", wdl)
        self.assertIn("r1 = raw_r1s[i]", wdl)
        self.assertIn("r2 = raw_r2s[i]", wdl)
        self.assertIn("call tximport_summarize as summarize", wdl)
        self.assertIn("call deseq2_deg as deg", wdl)
        self.assertIn("call multiqc_report as report", wdl)
        self.assertIn("report_files = flatten([qc.html_report, qc.json_report, quantify.log_file])", wdl)
        self.assertIn("File deg_table = deg.deg_table", wdl)
        self.assertIn("File multiqc_report = report.multiqc_report", wdl)
        self.assertIn("quant_files = quantify.quant_file", wdl)
        self.assertIn("--contrast ~{contrast}", wdl)
        self.assertIn('contrast = "condition"', wdl)
        self.assertIn('lib_type = "A"', wdl)
        self.assertIn("fastp -i ~{r1} \\\n    -I ~{r2}", wdl)
        self.assertIn("-I ~{r2} \\\n    -o clean_R1.fq.gz", wdl)
        self.assertIn("-O clean_R2.fq.gz \\\n    --html fastp.html", wdl)
        self.assertIn("salmon quant \\\n    -l ~{lib_type}", wdl)
        self.assertIn("-l ~{lib_type} \\\n    -i ~{index}", wdl)
        self.assertIn("run_deseq2.R \\\n    --counts ~{counts}", wdl)

    def test_reference_prep_plan_resolves_to_valid_renderable_ir(self):
        workflow_ir = resolve_tool_plan(
            sample_rnaseq_reference_prep_plan(),
            self.recipe_catalog,
            self.tool_catalog,
        )
        report = analyze_workflow_ir(workflow_ir)

        self.assertTrue(report.is_valid, report.errors)
        self.assertEqual(workflow_ir.workflow.name, "RNASeqReferencePrep")
        self.assertIn("salmon_index_index", workflow_ir.tasks)
        self.assertIn("gtf_tx2gene_mapping", workflow_ir.tasks)

        wdl = render_wdl(workflow_ir)
        self.assertIn("call salmon_index_index as index", wdl)
        self.assertIn("call gtf_tx2gene_mapping as mapping", wdl)
        self.assertIn("salmon index \\\n    -t ~{transcriptome_fasta}", wdl)
        self.assertIn("tar -czf salmon_index.tar.gz salmon_index", wdl)
        self.assertIn("run_gtf_tx2gene.py \\\n    --annotation-gtf ~{annotation_gtf}", wdl)
        self.assertIn("File transcriptome_index = index.index_archive", wdl)
        self.assertIn("File tx2gene = mapping.tx2gene", wdl)

    def test_rnaseq_de_tool_alternatives_resolve_to_valid_wdl(self):
        alternatives = [
            ("edger", "4.0.16", "edger_deg", "run_edger.R"),
            ("limma_voom", "3.58.1", "limma_voom_deg", "run_limma_voom.R"),
        ]

        for tool_id, version, task_name, command in alternatives:
            with self.subTest(tool=tool_id):
                plan = copy.deepcopy(sample_rnaseq_tool_plan())
                deg_call = next(
                    tool_call
                    for tool_call in plan["workflow"]["tool_calls"]
                    if tool_call["step"] == "differential_expression"
                )
                deg_call["tool"] = tool_id
                deg_call["version"] = version
                deg_call["params"] = {
                    "contrast": "condition",
                    "min_count": 1,
                    "fdr": 0.1,
                }

                workflow_ir = resolve_tool_plan(plan, self.recipe_catalog, self.tool_catalog)
                report = analyze_workflow_ir(workflow_ir)
                wdl = render_wdl(workflow_ir)

                self.assertTrue(report.is_valid, report.errors)
                self.assertIn(task_name, workflow_ir.tasks)
                self.assertIn(f"call {task_name} as deg", wdl)
                self.assertIn(command, wdl)
                self.assertIn("min_count = 1", wdl)
                self.assertIn("fdr = 0.1", wdl)
                self.assertIn("File deg_table = deg.deg_table", wdl)

    def test_tool_spec_requires_runtime_docker(self):
        with self.assertRaisesRegex(ValueError, "must define runtime.docker"):
            ToolSpec.model_validate(
                {
                    "id": "fastp",
                    "version": "1.3.3",
                    "description": "FASTQ quality control.",
                    "inputs": {
                        "r1": {
                            "type": "File",
                            "required": True,
                        }
                    },
                    "outputs": {
                        "clean_r1": {
                            "type": "File",
                            "value": '"clean_R1.fq.gz"',
                        }
                    },
                    "command_template": "fastp -i ~{r1} -o clean_R1.fq.gz",
                    "runtime": {
                        "cpu": 4,
                        "memory": "8G",
                    },
                }
            )

    def test_resolver_rejects_tool_not_allowed_for_recipe_step(self):
        plan = copy.deepcopy(sample_rnaseq_tool_plan())
        plan["workflow"]["tool_calls"][0]["tool"] = "salmon"
        plan["workflow"]["tool_calls"][0]["version"] = "1.9.0"

        with self.assertRaisesRegex(ValueError, "not allowed for recipe step 'qc'"):
            resolve_tool_plan(plan, self.recipe_catalog, self.tool_catalog)

    def test_resolver_rejects_unknown_recipe_step(self):
        plan = copy.deepcopy(sample_rnaseq_tool_plan())
        plan["workflow"]["tool_calls"][0]["step"] = "magic"

        with self.assertRaisesRegex(ValueError, "references unknown recipe step 'magic'"):
            resolve_tool_plan(plan, self.recipe_catalog, self.tool_catalog)

    def test_resolver_rejects_missing_required_recipe_step(self):
        plan = copy.deepcopy(sample_rnaseq_tool_plan())
        plan["workflow"]["tool_calls"] = [
            tool_call
            for tool_call in plan["workflow"]["tool_calls"]
            if tool_call["step"] != "differential_expression"
        ]

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

    def test_multiqc_report_files_can_be_auto_collected_from_output_tags(self):
        plan = copy.deepcopy(sample_rnaseq_tool_plan())
        report_call = plan["workflow"]["tool_calls"][-1]
        report_call["inputs"] = {}

        workflow_ir = resolve_tool_plan(
            plan,
            self.recipe_catalog,
            self.tool_catalog,
        )
        report = analyze_workflow_ir(workflow_ir)
        wdl = render_wdl(workflow_ir)

        self.assertTrue(report.is_valid, report.errors)
        self.assertEqual(
            workflow_ir.workflow.calls[-1].inputs["report_files"],
            ["qc.html_report", "qc.json_report", "quantify.log_file"],
        )
        self.assertIn("report_files = flatten([qc.html_report, qc.json_report, quantify.log_file])", wdl)


if __name__ == "__main__":
    unittest.main()
