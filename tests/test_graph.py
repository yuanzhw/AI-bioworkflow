import unittest

from src.analyzer import analyze_workflow_ir
from src.renderers import render_wdl
from src.schema import coerce_workflow_ir


def sample_multi_task_ir():
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
                    "docker": "quay.io/biocontainers/fastp:0.23.2",
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

    def test_analyzer_allows_omitted_optional_call_inputs(self):
        raw_ir = sample_multi_task_ir()
        raw_ir["tasks"]["fastp"]["inputs"]["r2"] = "File?"
        raw_ir["workflow"]["calls"][0]["inputs"].pop("r2")

        workflow_ir = coerce_workflow_ir(raw_ir)
        report = analyze_workflow_ir(workflow_ir)

        self.assertTrue(report.is_valid, report.errors)

    def test_legacy_json_is_normalized_to_ir(self):
        legacy_json = {
            "workflow_name": "SimpleQC",
            "inputs": {
                "raw_fastq": "File",
            },
            "tasks": [
                {
                    "name": "fastp_qc",
                    "docker": "quay.io/biocontainers/fastp:0.23.2",
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
        self.assertEqual(workflow_ir.tasks["fastp_qc"].runtime.docker, "quay.io/biocontainers/fastp:0.23.2")


if __name__ == "__main__":
    unittest.main()
