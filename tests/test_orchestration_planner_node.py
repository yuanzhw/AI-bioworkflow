import json
import unittest
from types import SimpleNamespace

from src.nl_planner import DEFAULT_PLANNER_MODEL
from src.orchestration.nodes import make_natural_language_planner_node, natural_language_planner_node
from src.orchestration.state import build_initial_orchestration_state


def sample_rnaseq_tool_plan() -> dict:
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


class FakePlannerLlm:
    def __init__(self, response: str):
        self.response = response
        self.prompts = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.response)


class OrchestrationPlannerNodeTests(unittest.TestCase):
    def test_planner_node_returns_plan_trace_and_events(self):
        fake_llm = FakePlannerLlm(json.dumps(sample_rnaseq_tool_plan()))
        state = build_initial_orchestration_state(
            "Run RNA-seq differential expression.",
            planner_model=DEFAULT_PLANNER_MODEL,
        )

        update = make_natural_language_planner_node(llm=fake_llm)(state)

        self.assertEqual(update["plan"]["workflow"]["recipe"], "rnaseq_differential_expression")
        self.assertIn("Catalog:", update["planner_prompt"])
        self.assertIn("RNASeqDEG", update["planner_raw_response"])
        self.assertEqual(update["errors"], [])
        self.assertNotIn("compiler_result", update)
        self.assertNotIn("workflow_ir", update)
        self.assertNotIn("wdl", update)
        self.assertEqual(
            [event["type"] for event in update["events"]],
            ["node.started", "node.completed", "artifact.updated"],
        )
        self.assertEqual(update["events"][0]["payload"], {"planner_model": DEFAULT_PLANNER_MODEL})
        self.assertEqual(update["events"][-1]["payload"], {"artifact": "plan"})
        self.assertEqual(len(fake_llm.prompts), 1)

    def test_default_planner_node_uses_same_node_contract(self):
        self.assertTrue(callable(natural_language_planner_node))

    def test_planner_node_records_json_failure_without_secret_payloads(self):
        fake_llm = FakePlannerLlm("I would run fastp first.")
        state = build_initial_orchestration_state(
            "Run RNA-seq differential expression.",
            planner_model=DEFAULT_PLANNER_MODEL,
        )

        update = make_natural_language_planner_node(llm=fake_llm)(state)

        self.assertIn("LLM planner response does not contain a JSON object", update["errors"][0])
        self.assertIsNone(update["plan"])
        self.assertIsNone(update["planner_prompt"])
        self.assertIsNone(update["planner_raw_response"])
        self.assertEqual(
            [event["type"] for event in update["events"]],
            ["node.started", "node.failed"],
        )
        failure_payload = update["events"][-1]["payload"]
        self.assertEqual(failure_payload["error_type"], "PlannerJsonError")
        self.assertNotIn("api_key", json.dumps(failure_payload).lower())
        self.assertNotIn("authorization", json.dumps(failure_payload).lower())

    def test_planner_node_preserves_schema_error_classification(self):
        fake_llm = FakePlannerLlm(json.dumps({"workflow": {"name": "RNASeqDEG"}}))
        state = build_initial_orchestration_state(
            "Run RNA-seq differential expression.",
            planner_model=DEFAULT_PLANNER_MODEL,
        )

        update = make_natural_language_planner_node(llm=fake_llm)(state)

        self.assertIn("plan schema validation failed", update["errors"][0])
        self.assertEqual(update["events"][-1]["payload"]["error_type"], "PlannerSchemaError")

    def test_planner_node_preserves_catalog_error_classification(self):
        plan = sample_rnaseq_tool_plan()
        plan["workflow"]["tool_calls"] = [
            tool_call
            for tool_call in plan["workflow"]["tool_calls"]
            if tool_call["step"] != "differential_expression"
        ]
        fake_llm = FakePlannerLlm(json.dumps(plan))
        state = build_initial_orchestration_state(
            "Run RNA-seq differential expression.",
            planner_model=DEFAULT_PLANNER_MODEL,
        )

        update = make_natural_language_planner_node(llm=fake_llm)(state)

        self.assertIn("recipe/catalog validation failed", update["errors"][0])
        self.assertEqual(update["events"][-1]["payload"]["error_type"], "PlannerCatalogError")


if __name__ == "__main__":
    unittest.main()
