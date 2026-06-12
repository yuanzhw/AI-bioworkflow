import unittest
from typing import Any

from src.analyzer import analyze_workflow_ir
from src.graph import agent
from src.renderers import render_wdl
from src.schema import coerce_workflow_ir
from src.state import WorkflowState


def sample_multi_task_ir() -> dict[str, Any]:
    return {
        "workflow": {
            "name": "RNASeqPipeline",
            "inputs": {
                "raw_r1": "File",
                "raw_r2": "File",
                "reference": "File",
            },
            "calls": [
                {
                    "id": "qc",
                    "task": "fastp",
                    "inputs": {
                        "r1": "raw_r1",
                        "r2": "raw_r2",
                    },
                },
                {
                    "id": "align",
                    "task": "bwa_mem",
                    "inputs": {
                        "r1": "qc.clean_r1",
                        "r2": "qc.clean_r2",
                        "ref": "reference",
                    },
                },
            ],
            "outputs": {
                "bam": "align.bam",
            },
        },
        "tasks": {
            "fastp": {
                "inputs": {
                    "r1": "File",
                    "r2": "File",
                },
                "command": "fastp -i ~{r1} -I ~{r2} -o clean_R1.fq.gz -O clean_R2.fq.gz",
                "outputs": {
                    "clean_r1": {
                        "type": "File",
                        "value": "\"clean_R1.fq.gz\"",
                    },
                    "clean_r2": {
                        "type": "File",
                        "value": "\"clean_R2.fq.gz\"",
                    },
                },
                "runtime": {
                    "docker": "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0",
                    "cpu": 4,
                    "memory": "8G",
                },
            },
            "bwa_mem": {
                "inputs": {
                    "r1": "File",
                    "r2": "File",
                    "ref": "File",
                },
                "command": "bwa mem ~{ref} ~{r1} ~{r2} > aligned.sam",
                "outputs": {
                    "bam": {
                        "type": "File",
                        "value": "\"aligned.sam\"",
                    },
                },
                "runtime": {
                    "docker": "quay.io/biocontainers/bwa:0.7.17--hed695b0_7",
                    "cpu": 8,
                    "memory": "32G",
                },
            },
        },
    }


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


def initial_state(parsed_json: dict[str, Any]) -> WorkflowState:
    state: WorkflowState = {
        "parsed_json": parsed_json,
        "workflow_ir": {},
        "analysis_errors": [],
        "analysis_warnings": [],
        "messages": [],
        "current_wdl": "",
        "validation_message": "",
        "error_count": 0,
        "repair_count": 0,
        "repair_actions": [],
        "is_valid": False,
    }
    return state


class WorkflowCompilationTests(unittest.TestCase):
    def test_multi_task_ir_analyzes_and_renders(self):
        workflow_ir = coerce_workflow_ir(sample_multi_task_ir())
        report = analyze_workflow_ir(workflow_ir)

        self.assertTrue(report.is_valid, report.errors)

        wdl = render_wdl(workflow_ir)
        self.assertIn("workflow RNASeqPipeline", wdl)
        self.assertIn("call fastp as qc", wdl)
        self.assertIn("call bwa_mem as align", wdl)
        self.assertIn("r1 = qc.clean_r1", wdl)
        self.assertIn("File bam = align.bam", wdl)
        self.assertIn("task fastp", wdl)
        self.assertIn("task bwa_mem", wdl)

    def test_analyzer_rejects_forward_output_reference(self):
        raw_ir = sample_multi_task_ir()
        raw_ir["workflow"]["calls"].reverse()

        workflow_ir = coerce_workflow_ir(raw_ir)
        report = analyze_workflow_ir(workflow_ir)

        self.assertFalse(report.is_valid)
        self.assertIn("references unavailable output 'qc.clean_r1'", "\n".join(report.errors))

    def test_agent_repairs_forward_output_reference_order(self):
        raw_ir = sample_multi_task_ir()
        raw_ir["workflow"]["calls"].reverse()

        final_state = agent.invoke(initial_state(raw_ir))

        self.assertTrue(final_state["is_valid"], final_state["validation_message"])
        self.assertEqual(
            [call["id"] for call in final_state["workflow_ir"]["workflow"]["calls"]],
            ["qc", "align"],
        )
        self.assertTrue(final_state["repair_actions"])

    def test_analyzer_allows_omitted_optional_call_inputs(self):
        raw_ir = sample_multi_task_ir()
        raw_ir["tasks"]["fastp"]["inputs"]["r2"] = "File?"
        raw_ir["workflow"]["calls"][0]["inputs"].pop("r2")

        workflow_ir = coerce_workflow_ir(raw_ir)
        report = analyze_workflow_ir(workflow_ir)

        self.assertTrue(report.is_valid, report.errors)

    def test_explicit_scatter_steps_analyze_and_render(self):
        raw_ir = {
            "workflow": {
                "name": "ScatterQC",
                "inputs": {
                    "raw_fastqs": "Array[File]",
                },
                "steps": [
                    {
                        "kind": "scatter",
                        "id": "per_sample",
                        "item": "i",
                        "over": "range(length(raw_fastqs))",
                        "body": [
                            {
                                "kind": "call",
                                "id": "qc",
                                "task": "fastp_single",
                                "inputs": {
                                    "fastq": "raw_fastqs[i]",
                                },
                            }
                        ],
                    }
                ],
                "outputs": {
                    "clean_fastqs": "qc.clean_fastq",
                },
            },
            "tasks": {
                "fastp_single": {
                    "inputs": {
                        "fastq": "File",
                    },
                    "command": "cp ~{fastq} clean.fq.gz",
                    "outputs": {
                        "clean_fastq": {
                            "type": "File",
                            "value": '"clean.fq.gz"',
                        }
                    },
                    "runtime": {
                        "docker": "ubuntu:22.04",
                    },
                }
            },
        }

        workflow_ir = coerce_workflow_ir(raw_ir)
        report = analyze_workflow_ir(workflow_ir)
        wdl = render_wdl(workflow_ir)

        self.assertTrue(report.is_valid, report.errors)
        self.assertIn("scatter (i in range(length(raw_fastqs)))", wdl)
        self.assertIn("fastq = raw_fastqs[i]", wdl)
        self.assertIn("Array[File] clean_fastqs = qc.clean_fastq", wdl)

    def test_array_call_inputs_can_collect_scatter_outputs(self):
        raw_ir = {
            "workflow": {
                "name": "ScatterReport",
                "inputs": {
                    "raw_fastqs": "Array[File]",
                    "extra_report": "File",
                },
                "steps": [
                    {
                        "kind": "scatter",
                        "id": "per_sample",
                        "item": "i",
                        "over": "range(length(raw_fastqs))",
                        "body": [
                            {
                                "kind": "call",
                                "id": "qc",
                                "task": "qc_task",
                                "inputs": {
                                    "fastq": "raw_fastqs[i]",
                                },
                            }
                        ],
                    },
                    {
                        "kind": "call",
                        "id": "report",
                        "task": "report_task",
                        "inputs": {
                            "files": ["qc.html_report", "qc.json_report", "extra_report"],
                        },
                    },
                ],
                "outputs": {
                    "report": "report.html",
                },
            },
            "tasks": {
                "qc_task": {
                    "inputs": {
                        "fastq": "File",
                    },
                    "command": "touch report.html report.json",
                    "outputs": {
                        "html_report": {
                            "type": "File",
                            "value": '"report.html"',
                        },
                        "json_report": {
                            "type": "File",
                            "value": '"report.json"',
                        },
                    },
                    "runtime": {
                        "docker": "ubuntu:22.04",
                    },
                },
                "report_task": {
                    "inputs": {
                        "files": "Array[File]",
                    },
                    "command": "touch combined.html",
                    "outputs": {
                        "html": {
                            "type": "File",
                            "value": '"combined.html"',
                        }
                    },
                    "runtime": {
                        "docker": "ubuntu:22.04",
                    },
                },
            },
        }

        workflow_ir = coerce_workflow_ir(raw_ir)
        report = analyze_workflow_ir(workflow_ir)
        wdl = render_wdl(workflow_ir)

        self.assertTrue(report.is_valid, report.errors)
        self.assertIn("files = flatten([qc.html_report, qc.json_report, [extra_report]])", wdl)

    def test_legacy_json_is_normalized_to_ir(self):
        legacy_json = {
            "workflow_name": "SimpleQC",
            "inputs": {
                "raw_fastq": "File",
            },
            "tasks": [
                {
                    "name": "fastp_qc",
                    "docker": "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0",
                    "command": "fastp -i ~{raw_fastq} -o out.fq",
                    "outputs": {
                        "clean_fastq": "File",
                    },
                },
            ],
        }

        workflow_ir = coerce_workflow_ir(legacy_json)

        self.assertEqual(workflow_ir.workflow.name, "SimpleQC")
        self.assertEqual(workflow_ir.workflow.calls[0].id, "fastp_qc")
        self.assertEqual(
            workflow_ir.tasks["fastp_qc"].runtime.docker,
            "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0",
        )

    def test_agent_repairs_bare_file_output_literals(self):
        raw_ir = sample_multi_task_ir()
        raw_ir["tasks"]["fastp"]["outputs"]["clean_r1"]["value"] = "clean_R1.fq.gz"
        raw_ir["tasks"]["fastp"]["outputs"]["clean_r2"]["value"] = "clean_R2.fq.gz"

        final_state = agent.invoke(initial_state(raw_ir))

        self.assertTrue(final_state["is_valid"], final_state["validation_message"])
        self.assertIn('File clean_r1 = "clean_R1.fq.gz"', final_state["current_wdl"])
        self.assertIn('File clean_r2 = "clean_R2.fq.gz"', final_state["current_wdl"])
        self.assertTrue(final_state["repair_actions"])

    def test_agent_stops_when_repairer_has_no_safe_action(self):
        raw_ir = sample_multi_task_ir()
        raw_ir["workflow"]["calls"][0]["inputs"]["r1"] = "missing_input"

        final_state = agent.invoke(initial_state(raw_ir))

        self.assertFalse(final_state["is_valid"])
        self.assertIn("references unknown value 'missing_input'", "\n".join(final_state["analysis_errors"]))
        self.assertEqual(final_state["repair_actions"], [])

    def test_agent_compiles_recipe_tool_plan(self):
        final_state = agent.invoke(initial_state(sample_rnaseq_tool_plan()))

        self.assertTrue(final_state["is_valid"], final_state["validation_message"])
        self.assertEqual(final_state["analysis_errors"], [])
        self.assertEqual(final_state["workflow_ir"]["workflow"]["steps"][0]["kind"], "scatter")
        self.assertIn("scatter (i in range(length(sample_ids)))", final_state["current_wdl"])
        self.assertIn("call fastp_qc as qc", final_state["current_wdl"])
        self.assertIn("call salmon_quantify as quantify", final_state["current_wdl"])
        self.assertIn("call tximport_summarize as summarize", final_state["current_wdl"])
        self.assertIn("call deseq2_deg as deg", final_state["current_wdl"])
        self.assertIn("call multiqc_report as report", final_state["current_wdl"])
        self.assertIn("Array[File] quant_files", final_state["current_wdl"])
        self.assertIn(
            "report_files = flatten([qc.html_report, qc.json_report, quantify.log_file])",
            final_state["current_wdl"],
        )
        self.assertIn("File deg_table = deg.deg_table", final_state["current_wdl"])
        self.assertIn("File multiqc_report = report.multiqc_report", final_state["current_wdl"])


if __name__ == "__main__":
    unittest.main()
