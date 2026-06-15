import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services.workflow_service import (
    _validate_with_repair,
    build_initial_state,
    compile_structured_workflow,
    plan_and_compile_workflow,
)


EXAMPLES_DIR = Path(__file__).parents[1] / "examples"


class FakePlannerLlm:
    def __init__(self, response: str):
        self.response = response
        self.prompts = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.response)


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


def repairable_forward_reference_ir() -> dict:
    return {
        "workflow": {
            "name": "RepairableWorkflow",
            "inputs": {
                "raw_r1": "File",
                "raw_r2": "File",
                "reference": "File",
            },
            "calls": [
                {
                    "id": "align",
                    "task": "bwa_mem",
                    "inputs": {
                        "r1": "qc.clean_r1",
                        "r2": "qc.clean_r2",
                        "ref": "reference",
                    },
                },
                {
                    "id": "qc",
                    "task": "fastp",
                    "inputs": {
                        "r1": "raw_r1",
                        "r2": "raw_r2",
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
                        "value": '"clean_R1.fq.gz"',
                    },
                    "clean_r2": {
                        "type": "File",
                        "value": '"clean_R2.fq.gz"',
                    },
                },
                "runtime": {
                    "docker": "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0",
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
                        "value": '"aligned.sam"',
                    },
                },
                "runtime": {
                    "docker": "quay.io/biocontainers/bwa:0.7.17--hed695b0_7",
                },
            },
        },
    }


class WorkflowServiceTests(unittest.TestCase):
    def test_compile_structured_workflow_compiles_recipe_plan_without_check(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")

        result = compile_structured_workflow(plan, check=False)

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertIs(result.plan, plan)
        self.assertEqual(result.workflow_ir["workflow"]["name"], "RNASeqDEG")
        self.assertIn("workflow RNASeqDEG", result.wdl)
        self.assertEqual(result.validation_message, "WDL syntax validation skipped (--no-check).")
        self.assertFalse(result.check_performed)

    def test_compile_structured_workflow_compiles_workflow_ir_without_plan(self):
        workflow_ir = load_example("rnaseq_workflow_ir.json")

        result = compile_structured_workflow(workflow_ir, check=False)

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertIsNone(result.plan)
        self.assertEqual(result.workflow_ir["workflow"]["name"], "RNASeqPipeline")
        self.assertIn("workflow RNASeqPipeline", result.wdl)

    def test_compile_structured_workflow_without_check_does_not_invoke_graph(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")

        with patch(
            "src.services.workflow_service.compiler_graph.invoke",
            side_effect=AssertionError("compiled graph should not run when check=False"),
        ) as graph:
            result = compile_structured_workflow(plan, check=False)

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertFalse(result.check_performed)
        graph.assert_not_called()

    def test_compile_structured_workflow_returns_diagnostics_for_invalid_plan(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")
        plan["workflow"]["inputs"].pop("sample_groups")

        result = compile_structured_workflow(plan, check=False)

        self.assertFalse(result.succeeded)
        self.assertEqual(result.wdl, "")
        self.assertIn("missing required workflow input 'sample_groups'", "\n".join(result.analysis_errors))

    def test_analyzer_repair_emits_workflow_ir_artifact_update_before_repair_event(self):
        events = []

        def event_callback(event_type, node, summary, state, payload):
            events.append(
                {
                    "type": event_type,
                    "node": node,
                    "summary": summary,
                    "workflow_ir": state["workflow_ir"],
                    "payload": payload or {},
                }
            )

        result = compile_structured_workflow(
            repairable_forward_reference_ir(),
            check=False,
            event_callback=event_callback,
        )

        self.assertTrue(result.succeeded, result.analysis_errors)
        event_types = [event["type"] for event in events]
        artifact_index = event_types.index("artifact.updated", event_types.index("repair.applied") - 1)
        repair_index = event_types.index("repair.applied")
        self.assertLess(artifact_index, repair_index)
        self.assertEqual(events[artifact_index]["node"], "repairer")
        self.assertEqual(events[artifact_index]["payload"], {"artifact": "workflow_ir"})
        self.assertEqual(
            [call["id"] for call in events[artifact_index]["workflow_ir"]["workflow"]["calls"]],
            ["qc", "align"],
        )

    def test_validation_repair_emits_workflow_ir_artifact_update_before_repair_event(self):
        events = []
        state = build_initial_state(repairable_forward_reference_ir())
        state["workflow_ir"] = repairable_forward_reference_ir()
        state["current_wdl"] = "broken wdl"

        def event_callback(event_type, node, summary, state, payload):
            events.append(
                {
                    "type": event_type,
                    "node": node,
                    "summary": summary,
                    "workflow_ir": state["workflow_ir"],
                    "payload": payload or {},
                }
            )

        repaired_ir = repairable_forward_reference_ir()
        repaired_ir["workflow"]["calls"].reverse()
        with (
            patch(
                "src.services.workflow_service.checker_node",
                side_effect=[
                    {"is_valid": False, "validation_message": "invalid WDL", "error_count": 1},
                    {"is_valid": True, "validation_message": "valid WDL", "error_count": 1},
                ],
            ),
            patch(
                "src.services.workflow_service.repairer_node",
                return_value={
                    "workflow_ir": repaired_ir,
                    "analysis_errors": [],
                    "analysis_warnings": [],
                    "current_wdl": "",
                    "is_valid": False,
                    "repair_actions": ["Reordered workflow steps."],
                    "repair_count": 1,
                    "messages": [],
                },
            ),
            patch("src.services.workflow_service._analyze_with_repair"),
            patch("src.services.workflow_service.renderer_node", return_value={"current_wdl": "fixed wdl"}),
        ):
            _validate_with_repair(state, event_callback=event_callback)

        event_types = [event["type"] for event in events]
        artifact_index = event_types.index("artifact.updated", event_types.index("repair.applied") - 1)
        repair_index = event_types.index("repair.applied")
        self.assertLess(artifact_index, repair_index)
        self.assertEqual(events[artifact_index]["node"], "repairer")
        self.assertEqual(events[artifact_index]["payload"], {"artifact": "workflow_ir"})
        self.assertEqual(
            [call["id"] for call in events[artifact_index]["workflow_ir"]["workflow"]["calls"]],
            ["qc", "align"],
        )

    def test_compile_structured_workflow_check_true_event_callback_runs_validation_repair_loop(self):
        events = []

        def event_callback(event_type, node, summary, state, payload):
            events.append(
                {
                    "type": event_type,
                    "node": node,
                    "summary": summary,
                    "payload": payload or {},
                }
            )

        def repairer_update(state):
            return {
                "workflow_ir": state["workflow_ir"],
                "analysis_errors": [],
                "analysis_warnings": [],
                "current_wdl": "",
                "is_valid": False,
                "repair_actions": ["Repaired WDL validation issue."],
                "repair_count": 1,
                "messages": [],
            }

        with (
            patch(
                "src.services.workflow_service.checker_node",
                side_effect=[
                    {"is_valid": False, "validation_message": "invalid WDL", "error_count": 1},
                    {"is_valid": True, "validation_message": "valid WDL", "error_count": 1},
                ],
            ) as checker,
            patch(
                "src.services.workflow_service.repairer_node",
                side_effect=repairer_update,
            ) as repairer,
            patch(
                "src.services.workflow_service.compiler_graph.invoke",
                side_effect=AssertionError("event callbacks should use the manual compiler path"),
            ) as graph,
        ):
            result = compile_structured_workflow(
                load_example("rnaseq_workflow_ir.json"),
                check=True,
                event_callback=event_callback,
            )

        self.assertTrue(result.succeeded, result.validation_message)
        self.assertTrue(result.check_performed)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.validation_message, "valid WDL")
        self.assertEqual(result.repair_actions, ["Repaired WDL validation issue."])
        self.assertEqual(checker.call_count, 2)
        repairer.assert_called_once()
        graph.assert_not_called()

        event_types = [event["type"] for event in events]
        self.assertEqual(event_types.count("validation.completed"), 2)
        self.assertIn("repair.applied", event_types)
        validation_indexes = [
            index for index, event_type in enumerate(event_types) if event_type == "validation.completed"
        ]
        repair_index = event_types.index("repair.applied")
        self.assertLess(validation_indexes[0], repair_index)
        self.assertGreater(validation_indexes[1], repair_index)
        validation_events = [
            event for event in events if event["type"] == "validation.completed"
        ]
        self.assertFalse(validation_events[0]["payload"]["is_valid"])
        self.assertTrue(validation_events[0]["payload"]["check_performed"])
        self.assertTrue(validation_events[1]["payload"]["is_valid"])
        self.assertTrue(validation_events[1]["payload"]["check_performed"])

    def test_plan_and_compile_workflow_plans_then_compiles(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")
        fake_llm = FakePlannerLlm(json.dumps(plan))

        result = plan_and_compile_workflow(
            "Run bulk RNA-seq differential expression.",
            llm=fake_llm,
            check=False,
        )

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertEqual(result.plan, plan)
        self.assertIn("Catalog:", result.planner_prompt or "")
        self.assertIn("RNASeqDEG", result.planner_raw_response or "")
        self.assertIn("workflow RNASeqDEG", result.wdl)
        self.assertEqual(len(fake_llm.prompts), 1)

    def test_result_to_dict_exposes_json_ready_service_fields(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")

        result = compile_structured_workflow(plan, check=False).to_dict()

        self.assertEqual(result["plan"], plan)
        self.assertIn("workflow", result["workflow_ir"])
        self.assertIn("workflow RNASeqDEG", result["wdl"])
        self.assertEqual(result["analysis_errors"], [])
        self.assertTrue(result["succeeded"])


if __name__ == "__main__":
    unittest.main()
