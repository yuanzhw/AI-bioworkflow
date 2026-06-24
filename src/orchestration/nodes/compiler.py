"""Compiler delegation node for the orchestration graph."""

from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

from src.orchestration.state import OrchestrationState

if TYPE_CHECKING:
    from src.services.workflow_service import WorkflowCompilationResult


StructuredCompiler = Callable[[dict[str, Any], bool], "WorkflowCompilationResult"]
CompilerNode = Callable[[OrchestrationState], dict[str, Any]]


def compile_planned_workflow_node(state: OrchestrationState) -> dict[str, Any]:
    """Compile the planner-produced Recipe Tool Plan using default services."""
    return make_compile_planned_workflow_node()(state)


def make_compile_planned_workflow_node(
    compiler: StructuredCompiler | None = None,
) -> CompilerNode:
    """Create a compiler delegation node, optionally injecting the compiler."""

    def node(state: OrchestrationState) -> dict[str, Any]:
        started_event = _compiler_event(
            "node.started",
            "Compiler graph started.",
            {"check": state["check"]},
        )
        plan = state["plan"]
        if plan is None:
            error = "Planner did not produce a Recipe Tool Plan."
            return {
                "compiler_result": None,
                "errors": [error],
                "events": [
                    started_event,
                    _compiler_event(
                        "node.failed",
                        "Compiler graph was not invoked.",
                        {"error": error},
                    ),
                ],
            }

        try:
            compiler_fn = compiler or _default_structured_compiler
            compiler_result = compiler_fn(plan, state["check"])
        except Exception as exc:
            return {
                "compiler_result": None,
                "errors": [str(exc)],
                "events": [
                    started_event,
                    _compiler_event(
                        "node.failed",
                        "Compiler graph failed unexpectedly.",
                        {
                            "error_type": exc.__class__.__name__,
                            "error": str(exc),
                        },
                    ),
                ],
            }

        if compiler_result.succeeded:
            event_type = "node.completed"
            summary = "Compiler graph completed."
        else:
            event_type = "node.failed"
            summary = "Compiler graph completed with diagnostics."

        return {
            "compiler_result": compiler_result,
            "events": [
                started_event,
                _compiler_event(event_type, summary, _compiler_result_payload(compiler_result)),
            ],
        }

    return node


def _default_structured_compiler(parsed_json: dict[str, Any], check: bool) -> "WorkflowCompilationResult":
    from src.services.workflow_service import compile_structured_workflow

    return compile_structured_workflow(parsed_json, check=check)


def _compiler_result_payload(result: "WorkflowCompilationResult") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "succeeded": result.succeeded,
        "check_performed": result.check_performed,
    }
    if result.analysis_errors:
        payload["analysis_errors"] = result.analysis_errors
    if result.validation_message:
        payload["validation_message"] = result.validation_message
    return payload


def _compiler_event(
    event_type: str,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": event_type,
        "node": "compiler_graph",
        "summary": summary,
    }
    if payload is not None:
        event["payload"] = payload
    return event
