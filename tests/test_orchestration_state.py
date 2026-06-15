import unittest

from src.nl_planner import DEFAULT_PLANNER_MODEL
from src.orchestration import (
    build_initial_orchestration_state,
    orchestration_failure_stage,
    orchestration_succeeded,
)
from src.services.workflow_service import WorkflowCompilationResult, build_initial_state


class OrchestrationStateTests(unittest.TestCase):
    def test_initial_orchestration_state_records_request_and_planner_options(self):
        state = build_initial_orchestration_state(
            "Run bulk RNA-seq differential expression.",
            planner_model=DEFAULT_PLANNER_MODEL,
            check=False,
        )

        self.assertEqual(state["request"], "Run bulk RNA-seq differential expression.")
        self.assertEqual(state["planner_model"], DEFAULT_PLANNER_MODEL)
        self.assertFalse(state["check"])
        self.assertIsNone(state["plan"])
        self.assertIsNone(state["planner_prompt"])
        self.assertIsNone(state["planner_raw_response"])
        self.assertIsNone(state["compiler_result"])
        self.assertEqual(state["errors"], [])
        self.assertEqual(state["events"], [])

    def test_initial_orchestration_state_uses_independent_mutable_lists(self):
        first = build_initial_orchestration_state("first", planner_model=DEFAULT_PLANNER_MODEL)
        second = build_initial_orchestration_state("second", planner_model=DEFAULT_PLANNER_MODEL)

        first["errors"].append("planner failed")
        first["events"].append({"type": "node.failed", "node": "planner"})

        self.assertEqual(second["errors"], [])
        self.assertEqual(second["events"], [])

    def test_orchestration_state_does_not_pollute_compiler_workflow_state(self):
        workflow_state = build_initial_state({})

        orchestration_only_fields = {
            "request",
            "planner_model",
            "check",
            "plan",
            "planner_prompt",
            "planner_raw_response",
            "compiler_result",
            "errors",
            "events",
        }
        for field in orchestration_only_fields:
            self.assertNotIn(field, workflow_state)

    def test_orchestration_failure_stage_distinguishes_top_level_errors(self):
        state = build_initial_orchestration_state(
            "Run bulk RNA-seq differential expression.",
            planner_model=DEFAULT_PLANNER_MODEL,
        )
        state["errors"].append("LLM planner JSON parsing failed: bad json")

        self.assertFalse(orchestration_succeeded(state))
        self.assertEqual(orchestration_failure_stage(state), "orchestration")

    def test_orchestration_failure_stage_distinguishes_compiler_failure(self):
        state = build_initial_orchestration_state(
            "Run bulk RNA-seq differential expression.",
            planner_model=DEFAULT_PLANNER_MODEL,
        )
        state["compiler_result"] = WorkflowCompilationResult(
            plan=None,
            workflow_ir={},
            wdl="",
            analysis_errors=["missing required workflow input 'sample_groups'"],
            analysis_warnings=[],
            repair_actions=[],
            validation_message="",
            is_valid=False,
            succeeded=False,
            check_performed=False,
            state=build_initial_state({}),
        )

        self.assertFalse(orchestration_succeeded(state))
        self.assertEqual(orchestration_failure_stage(state), "compiler")

    def test_orchestration_succeeded_requires_successful_compiler_result(self):
        state = build_initial_orchestration_state(
            "Run bulk RNA-seq differential expression.",
            planner_model=DEFAULT_PLANNER_MODEL,
        )
        state["compiler_result"] = WorkflowCompilationResult(
            plan={"workflow": {"recipe": "rnaseq_differential_expression"}},
            workflow_ir={"workflow": {"name": "RNASeqDEG"}},
            wdl="version 1.0\nworkflow RNASeqDEG {}",
            analysis_errors=[],
            analysis_warnings=[],
            repair_actions=[],
            validation_message="WDL syntax validation skipped (--no-check).",
            is_valid=False,
            succeeded=True,
            check_performed=False,
            state=build_initial_state({}),
            planner_prompt="planner prompt",
            planner_raw_response="{}",
        )

        self.assertTrue(orchestration_succeeded(state))
        self.assertIsNone(orchestration_failure_stage(state))


if __name__ == "__main__":
    unittest.main()
