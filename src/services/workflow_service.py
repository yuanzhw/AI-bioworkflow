"""Workflow planning and compilation service entry points."""

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, cast

from src.catalog.loader import ToolCatalog
from src.graph import build_compiler_graph
from src.nl_planner import (
    DEFAULT_PLANNER_MODEL,
    NaturalLanguagePlanningError,
    PlannerCatalogError,
    PlannerJsonError,
    PlannerLlm,
    PlannerSchemaError,
)
from src.nodes.reviewer_repair import ReviewerNode
from src.orchestration.graph import build_orchestration_graph
from src.orchestration.nodes.compiler import make_compile_planned_workflow_node
from src.orchestration.nodes.planner import make_natural_language_planner_node
from src.orchestration.state import OrchestrationState, build_initial_orchestration_state
from src.recipes.loader import RecipeCatalog
from src.reviewer_repair import ReviewerRepairStatus
from src.state import WorkflowState


WorkflowEventState = Mapping[str, Any] | None
WorkflowEventCallback = Callable[
    [str, str | None, str, WorkflowEventState, dict[str, Any] | None],
    None,
]
CompilerEventCallback = WorkflowEventCallback


@dataclass(frozen=True)
class WorkflowCompilationResult:
    """Stable service result for CLI, API, and future UI callers."""

    plan: dict[str, Any] | None
    workflow_ir: dict[str, Any]
    wdl: str
    analysis_errors: list[str]
    analysis_warnings: list[str]
    repair_actions: list[str]
    validation_message: str
    is_valid: bool
    succeeded: bool
    check_performed: bool
    state: WorkflowState
    reviewer_attempt_count: int = 0
    reviewer_repair_status: str | None = None
    reviewer_rejection_reason: str | None = None
    reviewer_diagnostics: list[str] = field(default_factory=list)
    reviewer_patch_applied: bool = False
    catalog_retrieval: dict[str, Any] | None = None
    planner_prompt: str | None = None
    planner_raw_response: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_retrieval": self.catalog_retrieval,
            "plan": self.plan,
            "workflow_ir": self.workflow_ir,
            "wdl": self.wdl,
            "analysis_errors": self.analysis_errors,
            "analysis_warnings": self.analysis_warnings,
            "repair_actions": self.repair_actions,
            "validation_message": self.validation_message,
            "is_valid": self.is_valid,
            "succeeded": self.succeeded,
            "check_performed": self.check_performed,
            "reviewer_attempt_count": self.reviewer_attempt_count,
            "reviewer_repair_status": self.reviewer_repair_status,
            "reviewer_rejection_reason": self.reviewer_rejection_reason,
            "reviewer_diagnostics": self.reviewer_diagnostics,
            "reviewer_patch_applied": self.reviewer_patch_applied,
            "planner_prompt": self.planner_prompt,
            "planner_raw_response": self.planner_raw_response,
        }


def compile_structured_workflow(
    parsed_json: dict[str, Any],
    check: bool = True,
    event_callback: CompilerEventCallback | None = None,
    *,
    reviewer_node: ReviewerNode | None = None,
) -> WorkflowCompilationResult:
    """Compile a Recipe Tool Plan or Workflow IR without natural-language planning."""
    state = _run_compiler(
        parsed_json,
        check=check,
        event_callback=event_callback,
        reviewer_node=reviewer_node,
    )
    plan = parsed_json if _is_recipe_tool_plan(parsed_json) else None
    return _result_from_state(state, plan=plan, check=check)


def plan_and_compile_workflow(
    request: str,
    *,
    model: str = DEFAULT_PLANNER_MODEL,
    check: bool = True,
    llm: PlannerLlm | None = None,
    tool_catalog: ToolCatalog | None = None,
    recipe_catalog: RecipeCatalog | None = None,
    event_callback: WorkflowEventCallback | None = None,
    reviewer_node: ReviewerNode | None = None,
) -> WorkflowCompilationResult:
    """Plan from natural language through the orchestration graph, then compile."""
    planner_node = make_natural_language_planner_node(
        llm=llm,
        tool_catalog=tool_catalog,
        recipe_catalog=recipe_catalog,
        event_callback=event_callback,
    )
    compiler_node = make_compile_planned_workflow_node(
        compiler=_compiler_with_callback(event_callback, reviewer_node),
        event_callback=event_callback,
    )
    graph = build_orchestration_graph(planner_node=planner_node, compiler_node=compiler_node)
    orchestration_state = cast(
        OrchestrationState,
        graph.invoke(
            build_initial_orchestration_state(
                request,
                planner_model=model,
                check=check,
            )
        ),
    )
    if orchestration_state["errors"]:
        _raise_orchestration_error(orchestration_state)

    compiler_result = orchestration_state["compiler_result"]
    if compiler_result is None:
        raise RuntimeError("orchestration graph did not produce a compiler result")

    return replace(
        cast(WorkflowCompilationResult, compiler_result),
        catalog_retrieval=orchestration_state["catalog_retrieval"],
        planner_prompt=orchestration_state["planner_prompt"],
        planner_raw_response=orchestration_state["planner_raw_response"],
    )


def _compiler_with_callback(
    event_callback: WorkflowEventCallback | None,
    reviewer_node: ReviewerNode | None,
) -> Callable[[dict[str, Any], bool], WorkflowCompilationResult] | None:
    if event_callback is None and reviewer_node is None:
        return None

    def compile_with_events(parsed_json: dict[str, Any], check: bool) -> WorkflowCompilationResult:
        return compile_structured_workflow(
            parsed_json,
            check=check,
            event_callback=event_callback,
            reviewer_node=reviewer_node,
        )

    return compile_with_events


def build_initial_state(
    parsed_json: dict[str, Any],
) -> WorkflowState:
    return {
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
        "repairer_failed": False,
        "repair_failure_stage": None,
        "reviewer_attempt_count": 0,
        "reviewer_repair_status": None,
        "reviewer_repair_request": None,
        "reviewer_ir_patch": None,
        "reviewer_rejection_reason": None,
        "reviewer_diagnostics": [],
        "reviewer_patch_applied": False,
        "is_valid": False,
    }


def compile_workflow(
    parsed_json: dict[str, Any],
    check: bool = True,
) -> WorkflowState:
    return compile_structured_workflow(parsed_json, check=check).state


def _run_compiler(
    parsed_json: dict[str, Any],
    check: bool = True,
    event_callback: CompilerEventCallback | None = None,
    reviewer_node: ReviewerNode | None = None,
) -> WorkflowState:
    state = build_initial_state(parsed_json)
    graph = build_compiler_graph(reviewer_node=reviewer_node, check=check)
    if event_callback is None:
        state = cast(WorkflowState, graph.invoke(state))
    else:
        _run_compiler_graph_with_events(
            graph,
            state,
            check=check,
            event_callback=event_callback,
        )

    if not check and state["current_wdl"]:
        state["validation_message"] = "WDL syntax validation skipped (--no-check)."
        _emit_compiler_event(
            event_callback,
            "validation.completed",
            "checker",
            state["validation_message"],
            state,
            {"is_valid": state["is_valid"], "check_performed": False},
        )
    return state


def _run_compiler_graph_with_events(
    graph: Any,
    state: WorkflowState,
    *,
    check: bool,
    event_callback: CompilerEventCallback,
) -> None:
    active_tasks: dict[str, tuple[str, int]] = {}
    try:
        for task in graph.stream(state, stream_mode="tasks"):
            if not isinstance(task, Mapping):
                continue
            task_id = str(task.get("id") or task.get("name") or "compiler-node")
            node = task.get("name")
            if not isinstance(node, str):
                continue

            if "input" in task:
                active_tasks[task_id] = (
                    node,
                    state.get("reviewer_attempt_count", 0),
                )
                _emit_compiler_event(
                    event_callback,
                    "node.started",
                    node,
                    _node_started_summary(node),
                    state,
                )
                continue

            active_node, previous_reviewer_attempt_count = active_tasks.pop(
                task_id,
                (node, state.get("reviewer_attempt_count", 0)),
            )
            error = task.get("error")
            if error is not None:
                _emit_compiler_event(
                    event_callback,
                    "node.failed",
                    active_node,
                    f"{_node_label(active_node)} failed.",
                    state,
                    _task_error_payload(error),
                )
                if isinstance(error, BaseException):
                    raise error
                raise RuntimeError(f"{_node_label(active_node)} failed: {error}")

            update = task.get("result")
            if isinstance(update, Mapping):
                _merge_state(state, update)
            _emit_node_result_events(
                event_callback,
                active_node,
                state,
                check=check,
                previous_reviewer_attempt_count=previous_reviewer_attempt_count,
            )
    except Exception as exc:
        if active_tasks:
            active_node, _ = list(active_tasks.values())[-1]
            _emit_compiler_event(
                event_callback,
                "node.failed",
                active_node,
                f"{_node_label(active_node)} failed.",
                state,
                _task_error_payload(exc),
            )
        raise


def _emit_node_result_events(
    event_callback: CompilerEventCallback,
    node: str,
    state: WorkflowState,
    *,
    check: bool,
    previous_reviewer_attempt_count: int,
) -> None:
    if node == "ir_normalizer":
        if state["analysis_errors"]:
            _emit_compiler_event(
                event_callback,
                "node.failed",
                node,
                "IR normalizer failed.",
                state,
                {"analysis_errors": state["analysis_errors"]},
            )
            return
        _emit_compiler_event(
            event_callback,
            "node.completed",
            node,
            "IR normalizer completed.",
            state,
        )
        _emit_artifact_updated(
            event_callback,
            node,
            "Workflow IR artifact updated.",
            state,
            "workflow_ir",
        )
        return

    if node == "analyzer":
        if state["analysis_errors"]:
            _emit_compiler_event(
                event_callback,
                "node.failed",
                node,
                "Analyzer found Workflow IR errors.",
                state,
                {"analysis_errors": state["analysis_errors"]},
            )
            return
        _emit_compiler_event(
            event_callback,
            "node.completed",
            node,
            "Analyzer completed.",
            state,
        )
        return

    if node == "renderer":
        _emit_compiler_event(
            event_callback,
            "node.completed",
            node,
            "Renderer completed.",
            state,
        )
        _emit_artifact_updated(
            event_callback,
            node,
            "WDL artifact updated.",
            state,
            "wdl",
        )
        return

    if node == "checker":
        _emit_compiler_event(
            event_callback,
            "validation.completed",
            node,
            "WDL validation completed.",
            state,
            {
                "is_valid": state["is_valid"],
                "validation_message": state["validation_message"],
                "check_performed": check,
            },
        )
        return

    if node == "repairer":
        if state["repairer_failed"]:
            _emit_compiler_event(
                event_callback,
                "node.failed",
                node,
                "Repairer failed.",
                state,
                {"repairer_failed": True},
            )
            return
        if state["repair_actions"]:
            _emit_workflow_ir_artifact_updated(event_callback, state, node=node)
            _emit_compiler_event(
                event_callback,
                "repair.applied",
                node,
                "Workflow IR repair applied.",
                state,
                {"repair_actions": state["repair_actions"]},
            )
            summary = "Repairer completed."
        else:
            summary = "Repairer found no safe deterministic fix."
        _emit_compiler_event(
            event_callback,
            "node.completed",
            node,
            summary,
            state,
        )
        return

    if node == "reviewer_repair":
        _emit_reviewer_result_events(
            event_callback,
            state,
            previous_attempt_count=previous_reviewer_attempt_count,
        )


def _emit_reviewer_result_events(
    event_callback: CompilerEventCallback,
    state: WorkflowState,
    *,
    previous_attempt_count: int,
) -> None:
    status = state.get("reviewer_repair_status")
    current_attempt_count = state.get("reviewer_attempt_count", 0)
    attempted = current_attempt_count > previous_attempt_count
    payload = _reviewer_event_payload(state)

    if attempted and state.get("reviewer_repair_request") is not None:
        _emit_artifact_updated(
            event_callback,
            "reviewer_repair",
            "Reviewer repair request artifact updated.",
            state,
            "reviewer_repair_request",
        )

    current_patch = (
        attempted
        and state.get("reviewer_ir_patch") is not None
        and status
        in {
            ReviewerRepairStatus.PATCH_PROPOSED.value,
            ReviewerRepairStatus.POLICY_REJECTED.value,
            ReviewerRepairStatus.INVALID_REQUEST.value,
        }
    )
    if current_patch:
        _emit_artifact_updated(
            event_callback,
            "reviewer_repair",
            "Reviewer IR patch artifact updated.",
            state,
            "reviewer_ir_patch",
        )
        _emit_compiler_event(
            event_callback,
            "repair.proposed",
            "reviewer_repair",
            "Reviewer proposed a Workflow IR patch.",
            state,
            {
                **payload,
                "action_count": len(
                    (state.get("reviewer_ir_patch") or {}).get("actions", [])
                ),
            },
        )

    if state.get("reviewer_patch_applied"):
        _emit_workflow_ir_artifact_updated(
            event_callback,
            state,
            node="reviewer_repair",
        )
        _emit_compiler_event(
            event_callback,
            "repair.applied",
            "reviewer_repair",
            "Reviewer patch applied to Workflow IR candidate.",
            state,
            payload,
        )
        _emit_compiler_event(
            event_callback,
            "node.completed",
            "reviewer_repair",
            "Reviewer repair completed.",
            state,
            payload,
        )
        return

    if current_patch and status in {
        ReviewerRepairStatus.POLICY_REJECTED.value,
        ReviewerRepairStatus.INVALID_REQUEST.value,
    }:
        _emit_compiler_event(
            event_callback,
            "repair.rejected",
            "reviewer_repair",
            "Reviewer patch was rejected.",
            state,
            payload,
        )
        _emit_compiler_event(
            event_callback,
            "node.completed",
            "reviewer_repair",
            "Reviewer repair completed with a rejected patch.",
            state,
            payload,
        )
        return

    if status in {
        ReviewerRepairStatus.INVALID_REQUEST.value,
        ReviewerRepairStatus.MODEL_ERROR.value,
    }:
        _emit_compiler_event(
            event_callback,
            "node.failed",
            "reviewer_repair",
            "Reviewer repair failed.",
            state,
            payload,
        )
        return

    _emit_compiler_event(
        event_callback,
        "node.completed",
        "reviewer_repair",
        "Reviewer repair completed without an applicable patch.",
        state,
        payload,
    )


def _reviewer_event_payload(state: WorkflowState) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "reviewer_status": state.get("reviewer_repair_status"),
        "reviewer_attempt_count": state.get("reviewer_attempt_count", 0),
        "failure_stage": state.get("repair_failure_stage"),
        "patch_applied": bool(state.get("reviewer_patch_applied")),
    }
    rejection_reason = state.get("reviewer_rejection_reason")
    if rejection_reason:
        payload["rejection_reason"] = rejection_reason
    return payload


def _node_started_summary(node: str) -> str:
    return f"{_node_label(node)} started."


def _node_label(node: str) -> str:
    return {
        "ir_normalizer": "IR normalizer",
        "analyzer": "Analyzer",
        "renderer": "Renderer",
        "checker": "Checker",
        "repairer": "Repairer",
        "reviewer_repair": "Reviewer repair",
    }.get(node, node)


def _task_error_payload(error: object) -> dict[str, str]:
    return {
        "error_type": error.__class__.__name__,
        "error": str(error),
    }


def _emit_artifact_updated(
    event_callback: CompilerEventCallback,
    node: str,
    summary: str,
    state: WorkflowState,
    artifact: str,
) -> None:
    _emit_compiler_event(
        event_callback,
        "artifact.updated",
        node,
        summary,
        state,
        {"artifact": artifact},
    )


def workflow_succeeded(state: WorkflowState, check: bool) -> bool:
    if state["analysis_errors"]:
        return False
    if not state["current_wdl"]:
        return False
    return state["is_valid"] if check else True


def _result_from_state(
    state: WorkflowState,
    *,
    plan: dict[str, Any] | None,
    check: bool,
    catalog_retrieval: dict[str, Any] | None = None,
    planner_prompt: str | None = None,
    planner_raw_response: str | None = None,
) -> WorkflowCompilationResult:
    return WorkflowCompilationResult(
        plan=plan,
        workflow_ir=state["workflow_ir"],
        wdl=state["current_wdl"],
        analysis_errors=state["analysis_errors"],
        analysis_warnings=state["analysis_warnings"],
        repair_actions=state["repair_actions"],
        validation_message=state["validation_message"],
        is_valid=state["is_valid"],
        succeeded=workflow_succeeded(state, check=check),
        check_performed=check,
        reviewer_attempt_count=state["reviewer_attempt_count"],
        reviewer_repair_status=state["reviewer_repair_status"],
        reviewer_rejection_reason=state["reviewer_rejection_reason"],
        reviewer_diagnostics=state["reviewer_diagnostics"],
        reviewer_patch_applied=state["reviewer_patch_applied"],
        state=state,
        catalog_retrieval=catalog_retrieval,
        planner_prompt=planner_prompt,
        planner_raw_response=planner_raw_response,
    )


def _is_recipe_tool_plan(parsed_json: dict[str, Any]) -> bool:
    workflow = parsed_json.get("workflow")
    if not isinstance(workflow, dict):
        return False
    return "recipe" in workflow and "tool_calls" in workflow


def _raise_orchestration_error(state: OrchestrationState) -> None:
    message = state["errors"][-1] if state["errors"] else "orchestration graph failed"
    failed_event = _last_failed_event(state)
    if failed_event and failed_event.get("node") == "compiler_graph":
        raise RuntimeError(message)

    error_type = _event_error_type(failed_event)
    exception_type = {
        "NaturalLanguagePlanningError": NaturalLanguagePlanningError,
        "PlannerJsonError": PlannerJsonError,
        "PlannerSchemaError": PlannerSchemaError,
        "PlannerCatalogError": PlannerCatalogError,
    }.get(error_type)
    if exception_type is not None:
        raise exception_type(message)
    if error_type:
        raise RuntimeError(f"{error_type}: {message}")
    raise NaturalLanguagePlanningError(message)


def _last_failed_event(state: OrchestrationState) -> dict[str, Any] | None:
    for event in reversed(state["events"]):
        if event.get("type") == "node.failed":
            return event
    return None


def _event_error_type(event: dict[str, Any] | None) -> str | None:
    if event is None:
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    error_type = payload.get("error_type")
    return error_type if isinstance(error_type, str) else None


def _emit_compiler_event(
    event_callback: CompilerEventCallback | None,
    event_type: str,
    node: str | None,
    summary: str,
    state: WorkflowState,
    payload: dict[str, Any] | None = None,
) -> None:
    if event_callback is not None:
        event_callback(event_type, node, summary, state, payload)


def _emit_workflow_ir_artifact_updated(
    event_callback: CompilerEventCallback | None,
    state: WorkflowState,
    *,
    node: str,
) -> None:
    _emit_compiler_event(
        event_callback,
        "artifact.updated",
        node,
        "Workflow IR artifact updated.",
        state,
        {"artifact": "workflow_ir"},
    )


def _merge_state(state: WorkflowState, update: Mapping[str, Any]) -> None:
    for key, value in update.items():
        if key == "messages":
            state["messages"] = state["messages"] + value
        elif key == "parsed_json":
            state["parsed_json"] = value
        elif key == "workflow_ir":
            state["workflow_ir"] = value
        elif key == "analysis_errors":
            state["analysis_errors"] = value
        elif key == "analysis_warnings":
            state["analysis_warnings"] = value
        elif key == "current_wdl":
            state["current_wdl"] = value
        elif key == "validation_message":
            state["validation_message"] = value
        elif key == "error_count":
            state["error_count"] = value
        elif key == "repair_count":
            state["repair_count"] = value
        elif key == "repair_actions":
            state["repair_actions"] = value
        elif key == "repairer_failed":
            state["repairer_failed"] = value
        elif key == "repair_failure_stage":
            state["repair_failure_stage"] = value
        elif key == "reviewer_attempt_count":
            state["reviewer_attempt_count"] = value
        elif key == "reviewer_repair_status":
            state["reviewer_repair_status"] = value
        elif key == "reviewer_repair_request":
            state["reviewer_repair_request"] = value
        elif key == "reviewer_ir_patch":
            state["reviewer_ir_patch"] = value
        elif key == "reviewer_rejection_reason":
            state["reviewer_rejection_reason"] = value
        elif key == "reviewer_diagnostics":
            state["reviewer_diagnostics"] = value
        elif key == "reviewer_patch_applied":
            state["reviewer_patch_applied"] = value
        elif key == "is_valid":
            state["is_valid"] = value
