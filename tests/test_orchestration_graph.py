import unittest

from src.nl_planner import DEFAULT_PLANNER_MODEL
from src.orchestration.graph import build_orchestration_graph, orchestration_graph
from src.orchestration.nodes import make_compile_planned_workflow_node
from src.orchestration.state import (
    build_initial_orchestration_state,
    orchestration_failure_stage,
    orchestration_succeeded,
)
from src.services.workflow_service import WorkflowCompilationResult, build_initial_state


def sample_plan() -> dict:
    return {
        "workflow": {
            "name": "RNASeqDEG",
            "recipe": "rnaseq_differential_expression",
            "tool_calls": [],
        }
    }


def sample_catalog_retrieval() -> dict:
    return {
        "query": "Run RNA-seq DEG.",
        "strategy": "lexical_v1",
        "recipes": [{"id": "rnaseq_differential_expression"}],
        "tools": [{"id": "fastp", "trust_status": "catalog-approved"}],
        "fallback_used": False,
        "fallback_reason": None,
    }


def compilation_result(
    plan: dict,
    *,
    check: bool,
    succeeded: bool = True,
    analysis_errors: list[str] | None = None,
) -> WorkflowCompilationResult:
    workflow_state = build_initial_state(plan)
    workflow_state["workflow_ir"] = {"workflow": {"name": "RNASeqDEG"}}
    workflow_state["current_wdl"] = "version 1.0\nworkflow RNASeqDEG {}" if succeeded else ""
    workflow_state["analysis_errors"] = analysis_errors or []
    workflow_state["validation_message"] = (
        "WDL syntax validation skipped (--no-check)." if not check else "valid WDL"
    )
    workflow_state["is_valid"] = check and succeeded
    return WorkflowCompilationResult(
        plan=plan,
        workflow_ir=workflow_state["workflow_ir"],
        wdl=workflow_state["current_wdl"],
        analysis_errors=workflow_state["analysis_errors"],
        analysis_warnings=[],
        repair_actions=[],
        validation_message=workflow_state["validation_message"],
        is_valid=workflow_state["is_valid"],
        succeeded=succeeded,
        check_performed=check,
        state=workflow_state,
    )


def planner_success_node(plan: dict):
    def node(state):
        return {
            "catalog_retrieval": sample_catalog_retrieval(),
            "plan": plan,
            "planner_prompt": "planner prompt",
            "planner_raw_response": "{}",
            "errors": [],
            "events": [
                {"type": "node.started", "node": "catalog_retriever", "summary": "Catalog retriever started."},
                {"type": "node.completed", "node": "catalog_retriever", "summary": "Catalog retriever completed."},
                {
                    "type": "artifact.updated",
                    "node": "catalog_retriever",
                    "summary": "Catalog retrieval artifact updated.",
                    "payload": {"artifact": "catalog_retrieval"},
                },
                {"type": "node.started", "node": "planner", "summary": "Planner started."},
                {"type": "node.completed", "node": "planner", "summary": "Planner completed."},
                {
                    "type": "artifact.updated",
                    "node": "planner",
                    "summary": "Plan artifact updated.",
                    "payload": {"artifact": "plan"},
                },
            ],
        }

    return node


class OrchestrationGraphTests(unittest.TestCase):
    def test_default_orchestration_graph_is_invokable(self):
        self.assertTrue(callable(orchestration_graph.invoke))

    def test_orchestration_graph_runs_planner_then_compiler(self):
        plan = sample_plan()
        compiler_calls = []

        def compiler(parsed_json, check):
            compiler_calls.append({"parsed_json": parsed_json, "check": check})
            return compilation_result(parsed_json, check=check)

        graph = build_orchestration_graph(
            planner_node=planner_success_node(plan),
            compiler_node=make_compile_planned_workflow_node(compiler=compiler),
        )
        state = build_initial_orchestration_state(
            "Run RNA-seq DEG.",
            planner_model=DEFAULT_PLANNER_MODEL,
            check=False,
        )

        final_state = graph.invoke(state)

        self.assertEqual(compiler_calls, [{"parsed_json": plan, "check": False}])
        self.assertEqual(final_state["plan"], plan)
        self.assertEqual(final_state["catalog_retrieval"]["strategy"], "lexical_v1")
        self.assertEqual(final_state["planner_prompt"], "planner prompt")
        self.assertIsNotNone(final_state["compiler_result"])
        self.assertTrue(final_state["compiler_result"].succeeded)
        self.assertTrue(orchestration_succeeded(final_state))
        self.assertIsNone(orchestration_failure_stage(final_state))
        self.assertEqual(
            [event["type"] for event in final_state["events"]],
            [
                "node.started",
                "node.completed",
                "artifact.updated",
                "node.started",
                "node.completed",
                "artifact.updated",
                "node.started",
                "node.completed",
            ],
        )

    def test_orchestration_graph_stops_after_planner_failure(self):
        def planner_failure_node(state):
            return {
                "plan": None,
                "planner_prompt": None,
                "planner_raw_response": None,
                "errors": ["LLM planner JSON parsing failed: bad json"],
                "events": [
                    {"type": "node.started", "node": "planner", "summary": "Planner started."},
                    {
                        "type": "node.failed",
                        "node": "planner",
                        "summary": "Planner failed.",
                        "payload": {"error_type": "PlannerJsonError"},
                    },
                ],
            }

        def compiler_should_not_run(state):
            raise AssertionError("compiler graph should not run after planner failure")

        graph = build_orchestration_graph(
            planner_node=planner_failure_node,
            compiler_node=compiler_should_not_run,
        )
        state = build_initial_orchestration_state(
            "Run RNA-seq DEG.",
            planner_model=DEFAULT_PLANNER_MODEL,
        )

        final_state = graph.invoke(state)

        self.assertIsNone(final_state["compiler_result"])
        self.assertIn("bad json", final_state["errors"][0])
        self.assertFalse(orchestration_succeeded(final_state))
        self.assertEqual(orchestration_failure_stage(final_state), "orchestration")
        self.assertEqual(
            [event["node"] for event in final_state["events"]],
            ["planner", "planner"],
        )

    def test_orchestration_graph_preserves_compiler_failure_diagnostics(self):
        plan = sample_plan()

        def compiler(parsed_json, check):
            return compilation_result(
                parsed_json,
                check=check,
                succeeded=False,
                analysis_errors=["missing required workflow input 'sample_groups'"],
            )

        graph = build_orchestration_graph(
            planner_node=planner_success_node(plan),
            compiler_node=make_compile_planned_workflow_node(compiler=compiler),
        )
        state = build_initial_orchestration_state(
            "Run RNA-seq DEG.",
            planner_model=DEFAULT_PLANNER_MODEL,
            check=False,
        )

        final_state = graph.invoke(state)

        self.assertEqual(final_state["errors"], [])
        self.assertFalse(orchestration_succeeded(final_state))
        self.assertEqual(orchestration_failure_stage(final_state), "compiler")
        self.assertIsNotNone(final_state["compiler_result"])
        self.assertEqual(
            final_state["compiler_result"].analysis_errors,
            ["missing required workflow input 'sample_groups'"],
        )
        self.assertEqual(final_state["events"][-1]["type"], "node.failed")
        self.assertEqual(final_state["events"][-1]["node"], "compiler_graph")
        self.assertEqual(
            final_state["events"][-1]["payload"]["analysis_errors"],
            ["missing required workflow input 'sample_groups'"],
        )

    def test_compiler_exception_errors_include_exception_type(self):
        class EmptyCompilerError(Exception):
            def __str__(self):
                return ""

        plan = sample_plan()

        def compiler(parsed_json, check):
            raise EmptyCompilerError()

        graph = build_orchestration_graph(
            planner_node=planner_success_node(plan),
            compiler_node=make_compile_planned_workflow_node(compiler=compiler),
        )
        state = build_initial_orchestration_state(
            "Run RNA-seq DEG.",
            planner_model=DEFAULT_PLANNER_MODEL,
        )

        final_state = graph.invoke(state)

        self.assertEqual(final_state["compiler_result"], None)
        self.assertEqual(final_state["errors"], ["EmptyCompilerError"])
        self.assertEqual(final_state["events"][-1]["type"], "node.failed")
        self.assertEqual(final_state["events"][-1]["payload"]["error_type"], "EmptyCompilerError")
        self.assertEqual(final_state["events"][-1]["payload"]["error"], "EmptyCompilerError")


if __name__ == "__main__":
    unittest.main()
