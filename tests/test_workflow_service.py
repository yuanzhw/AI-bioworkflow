import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.graph import build_compiler_graph
from src.nodes.reviewer_repair import make_reviewer_repair_node
from src.reviewer_provider import ReviewerProviderError
from src.services.workflow_service import (
    _raise_orchestration_error,
    compile_structured_workflow,
    plan_and_compile_workflow,
)
from src.nl_planner import PlannerJsonError
from src.orchestration.state import build_initial_orchestration_state


EXAMPLES_DIR = Path(__file__).parents[1] / "examples"


class FakePlannerLlm:
    def __init__(self, response: str):
        self.response = response
        self.prompts = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.response)


class RecordingReviewerProvider:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def repair(self, request):
        self.requests.append(request)
        return self.result


class RaisingReviewerProvider:
    def __init__(self):
        self.requests = []

    def repair(self, request):
        self.requests.append(request)
        raise ReviewerProviderError("TOP_SECRET provider failure")


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
            "steps": [
                {
                    "kind": "call",
                    "id": "align",
                    "task": "bwa_mem",
                    "inputs": {
                        "r1": "qc.clean_r1",
                        "r2": "qc.clean_r2",
                        "ref": "reference",
                    },
                },
                {
                    "kind": "call",
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


def reviewer_repairable_ir() -> dict:
    workflow_ir = load_example("rnaseq_workflow_ir.json")
    workflow_ir["workflow"]["steps"][0]["inputs"]["r1"] = "missing_input"
    return workflow_ir


def reviewer_patch_result() -> dict:
    return {
        "status": "patch_proposed",
        "patch": {
            "summary": "Reconnect the QC input to a declared workflow input.",
            "actions": [
                {
                    "operation": "replace",
                    "path": "/workflow/steps/0/inputs/r1",
                    "value": "raw_r1",
                    "reason": "Use the existing workflow input.",
                }
            ],
            "diagnostic_references": [
                "references unknown value 'missing_input'"
            ],
            "confidence": 0.9,
        },
        "diagnostics": ["The replacement uses an existing workflow input."],
    }


def reviewer_policy_rejected_result() -> dict:
    return {
        "status": "patch_proposed",
        "patch": {
            "summary": "Attempt a forbidden runtime edit.",
            "actions": [
                {
                    "operation": "replace",
                    "path": "/tasks/fastp/runtime/docker",
                    "value": "ubuntu:22.04",
                    "reason": "Reviewer must not change runtime images.",
                }
            ],
        },
    }


class WorkflowServiceTests(unittest.TestCase):
    def test_compile_structured_workflow_compiles_recipe_plan_without_check(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")

        result = compile_structured_workflow(plan, check=False)

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertIs(result.plan, plan)
        self.assertIsNone(result.catalog_retrieval)
        self.assertEqual(result.workflow_ir["workflow"]["name"], "RNASeqDEG")
        self.assertIn("workflow RNASeqDEG", result.wdl)
        self.assertEqual(result.validation_message, "WDL syntax validation skipped (--no-check).")
        self.assertFalse(result.check_performed)

    def test_compile_structured_workflow_compiles_workflow_ir_without_plan(self):
        workflow_ir = load_example("rnaseq_workflow_ir.json")

        result = compile_structured_workflow(workflow_ir, check=False)

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertIsNone(result.plan)
        self.assertIsNone(result.catalog_retrieval)
        self.assertEqual(result.workflow_ir["workflow"]["name"], "RNASeqPipeline")
        self.assertIn("workflow RNASeqPipeline", result.wdl)

    def test_compile_structured_workflow_without_check_uses_unchecked_graph(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")

        with patch(
            "src.services.workflow_service.build_compiler_graph",
            wraps=build_compiler_graph,
        ) as graph_builder:
            result = compile_structured_workflow(plan, check=False)

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertFalse(result.check_performed)
        graph_builder.assert_called_once_with(reviewer_node=None, check=False)

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
            [step["id"] for step in events[artifact_index]["workflow_ir"]["workflow"]["steps"]],
            ["qc", "align"],
        )

    def test_analyzer_repair_failure_emits_failed_event(self):
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

        with patch(
            "src.nodes.repairer.repair_workflow_ir",
            side_effect=RuntimeError("Synthetic repairer failure."),
        ):
            result = compile_structured_workflow(
                repairable_forward_reference_ir(),
                check=False,
                event_callback=event_callback,
            )

        self.assertFalse(result.succeeded)
        self.assertTrue(result.state["repairer_failed"])
        self.assertEqual(result.state["repair_count"], 1)
        self.assertEqual(result.repair_actions, [])
        repairer_events = [event for event in events if event["node"] == "repairer"]
        self.assertEqual(
            [event["type"] for event in repairer_events],
            ["node.started", "node.failed"],
        )
        self.assertEqual(
            repairer_events[-1]["payload"],
            {"repairer_failed": True},
        )

    def test_evented_reviewer_patch_emits_artifacts_before_repair_events(self):
        events = []
        provider = RecordingReviewerProvider(reviewer_patch_result())
        reviewer_node = make_reviewer_repair_node(enabled=True, provider=provider)

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
            reviewer_repairable_ir(),
            check=False,
            event_callback=event_callback,
            reviewer_node=reviewer_node,
        )

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(result.reviewer_attempt_count, 1)
        self.assertEqual(result.reviewer_repair_status, "patch_proposed")
        self.assertTrue(result.reviewer_patch_applied)
        reviewer_events = [
            event for event in events if event["node"] == "reviewer_repair"
        ]
        self.assertEqual(
            [event["type"] for event in reviewer_events],
            [
                "node.started",
                "artifact.updated",
                "artifact.updated",
                "repair.proposed",
                "artifact.updated",
                "repair.applied",
                "node.completed",
            ],
        )
        self.assertEqual(
            [
                event["payload"].get("artifact")
                for event in reviewer_events
                if event["type"] == "artifact.updated"
            ],
            ["reviewer_repair_request", "reviewer_ir_patch", "workflow_ir"],
        )
        workflow_ir_index = next(
            index
            for index, event in enumerate(reviewer_events)
            if event["payload"].get("artifact") == "workflow_ir"
        )
        repair_index = next(
            index
            for index, event in enumerate(reviewer_events)
            if event["type"] == "repair.applied"
        )
        self.assertLess(workflow_ir_index, repair_index)
        self.assertEqual(
            reviewer_events[workflow_ir_index]["workflow_ir"]["workflow"]["steps"][0]["inputs"]["r1"],
            "raw_r1",
        )

    def test_evented_and_non_evented_reviewer_results_match(self):
        direct_provider = RecordingReviewerProvider(reviewer_patch_result())
        evented_provider = RecordingReviewerProvider(reviewer_patch_result())

        direct_result = compile_structured_workflow(
            reviewer_repairable_ir(),
            check=False,
            reviewer_node=make_reviewer_repair_node(
                enabled=True,
                provider=direct_provider,
            ),
        )
        evented_result = compile_structured_workflow(
            reviewer_repairable_ir(),
            check=False,
            event_callback=lambda *args: None,
            reviewer_node=make_reviewer_repair_node(
                enabled=True,
                provider=evented_provider,
            ),
        )

        self.assertEqual(evented_result.to_dict(), direct_result.to_dict())
        self.assertEqual(len(direct_provider.requests), 1)
        self.assertEqual(len(evented_provider.requests), 1)

    def test_evented_reviewer_policy_rejection_emits_proposed_and_rejected(self):
        events = []
        provider = RecordingReviewerProvider(reviewer_policy_rejected_result())

        def event_callback(event_type, node, summary, state, payload):
            events.append(
                {
                    "type": event_type,
                    "node": node,
                    "payload": payload or {},
                }
            )

        result = compile_structured_workflow(
            reviewer_repairable_ir(),
            check=False,
            event_callback=event_callback,
            reviewer_node=make_reviewer_repair_node(
                enabled=True,
                provider=provider,
            ),
        )

        self.assertFalse(result.succeeded)
        self.assertEqual(result.reviewer_repair_status, "policy_rejected")
        self.assertFalse(result.reviewer_patch_applied)
        self.assertIn("forbidden", result.reviewer_rejection_reason or "")
        reviewer_events = [
            event for event in events if event["node"] == "reviewer_repair"
        ]
        self.assertEqual(
            [event["type"] for event in reviewer_events],
            [
                "node.started",
                "artifact.updated",
                "artifact.updated",
                "repair.proposed",
                "repair.rejected",
                "node.completed",
            ],
        )
        self.assertNotIn("repair.applied", [event["type"] for event in reviewer_events])

    def test_evented_reviewer_model_error_emits_request_then_failure(self):
        events = []
        provider = RaisingReviewerProvider()

        def event_callback(event_type, node, summary, state, payload):
            events.append(
                {
                    "type": event_type,
                    "node": node,
                    "payload": payload or {},
                }
            )

        result = compile_structured_workflow(
            reviewer_repairable_ir(),
            check=False,
            event_callback=event_callback,
            reviewer_node=make_reviewer_repair_node(
                enabled=True,
                provider=provider,
            ),
        )

        self.assertFalse(result.succeeded)
        self.assertEqual(result.reviewer_repair_status, "model_error")
        self.assertEqual(result.reviewer_attempt_count, 1)
        self.assertNotIn("TOP_SECRET", json.dumps(result.to_dict()))
        reviewer_events = [
            event for event in events if event["node"] == "reviewer_repair"
        ]
        self.assertEqual(
            [event["type"] for event in reviewer_events],
            ["node.started", "artifact.updated", "node.failed"],
        )
        self.assertEqual(
            reviewer_events[1]["payload"]["artifact"],
            "reviewer_repair_request",
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
                "src.graph.checker_node",
                side_effect=[
                    {
                        "is_valid": False,
                        "validation_message": "invalid WDL",
                        "error_count": 1,
                        "repair_failure_stage": "checker",
                        "messages": [],
                    },
                    {
                        "is_valid": True,
                        "validation_message": "valid WDL",
                        "error_count": 1,
                        "repair_failure_stage": None,
                        "messages": [],
                    },
                ],
            ) as checker,
            patch(
                "src.graph.repairer_node",
                side_effect=repairer_update,
            ) as repairer,
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
        self.assertEqual(result.catalog_retrieval["strategy"], "lexical_v1")
        self.assertEqual(result.catalog_retrieval["recipes"][0]["id"], "rnaseq_differential_expression")
        self.assertIn("Catalog:", result.planner_prompt or "")
        self.assertIn("RNASeqDEG", result.planner_raw_response or "")
        self.assertIn("workflow RNASeqDEG", result.wdl)
        self.assertEqual(len(fake_llm.prompts), 1)

    def test_plan_and_compile_workflow_event_callback_covers_planner_and_compiler(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")
        fake_llm = FakePlannerLlm(json.dumps(plan))
        events = []

        def event_callback(event_type, node, summary, state, payload):
            events.append(
                {
                    "type": event_type,
                    "node": node,
                    "summary": summary,
                    "state": state,
                    "payload": payload or {},
                }
            )

        result = plan_and_compile_workflow(
            "Run bulk RNA-seq differential expression.",
            llm=fake_llm,
            check=False,
            event_callback=event_callback,
        )

        self.assertTrue(result.succeeded, result.analysis_errors)
        event_keys = [(event["type"], event["node"]) for event in events]
        self.assertEqual(
            event_keys[:7],
            [
                ("node.started", "catalog_retriever"),
                ("node.completed", "catalog_retriever"),
                ("artifact.updated", "catalog_retriever"),
                ("node.started", "planner"),
                ("node.completed", "planner"),
                ("artifact.updated", "planner"),
                ("node.started", "compiler_graph"),
            ],
        )
        self.assertIn(("node.started", "ir_normalizer"), event_keys)
        artifact_events = [
            event for event in events if event["type"] == "artifact.updated"
        ]
        self.assertIn({"artifact": "catalog_retrieval"}, [event["payload"] for event in artifact_events])
        self.assertIn({"artifact": "workflow_ir"}, [event["payload"] for event in artifact_events])
        self.assertIn({"artifact": "wdl"}, [event["payload"] for event in artifact_events])
        self.assertEqual(event_keys[-1], ("node.completed", "compiler_graph"))

        catalog_event = next(
            event for event in artifact_events if event["payload"] == {"artifact": "catalog_retrieval"}
        )
        self.assertEqual(catalog_event["state"]["catalog_retrieval"]["strategy"], "lexical_v1")
        plan_event = next(event for event in artifact_events if event["payload"] == {"artifact": "plan"})
        self.assertEqual(plan_event["state"]["plan"], plan)

    def test_plan_and_compile_workflow_preserves_planner_error_classification(self):
        fake_llm = FakePlannerLlm("not json")

        with self.assertRaisesRegex(PlannerJsonError, "does not contain a JSON object"):
            plan_and_compile_workflow(
                "Run bulk RNA-seq differential expression.",
                llm=fake_llm,
                check=False,
            )

    def test_orchestration_error_unknown_type_is_runtime_error(self):
        state = build_initial_orchestration_state(
            "Run bulk RNA-seq differential expression.",
            planner_model="planner-model",
        )
        state["errors"].append("planner transport unavailable")
        state["events"].append(
            {
                "type": "node.failed",
                "node": "planner",
                "summary": "Planner failed.",
                "payload": {"error_type": "RuntimeError"},
            }
        )

        with self.assertRaisesRegex(RuntimeError, "RuntimeError: planner transport unavailable"):
            _raise_orchestration_error(state)

    def test_result_to_dict_exposes_json_ready_service_fields(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")

        result = compile_structured_workflow(plan, check=False).to_dict()

        self.assertEqual(result["plan"], plan)
        self.assertIsNone(result["catalog_retrieval"])
        self.assertIn("workflow", result["workflow_ir"])
        self.assertIn("workflow RNASeqDEG", result["wdl"])
        self.assertEqual(result["analysis_errors"], [])
        self.assertTrue(result["succeeded"])
        self.assertEqual(result["reviewer_attempt_count"], 0)
        self.assertIsNone(result["reviewer_repair_status"])
        self.assertIsNone(result["reviewer_rejection_reason"])
        self.assertEqual(result["reviewer_diagnostics"], [])
        self.assertFalse(result["reviewer_patch_applied"])


if __name__ == "__main__":
    unittest.main()
