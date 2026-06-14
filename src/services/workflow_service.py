"""Workflow planning and compilation service entry points."""

from dataclasses import dataclass
from typing import Any, Callable, Mapping, cast

from src.catalog.loader import ToolCatalog
from src.graph import MAX_REPAIR_ATTEMPTS, compiler_graph
from src.nodes.checker import checker_node
from src.nl_planner import DEFAULT_PLANNER_MODEL, PlannerLlm, create_natural_language_plan
from src.nodes.analyzer import analyzer_node
from src.nodes.ir_normalizer import ir_normalizer_node
from src.nodes.renderer import renderer_node
from src.nodes.repairer import repairer_node
from src.recipes.loader import RecipeCatalog
from src.state import WorkflowState
from src.tools.validator import VALIDATOR_MISSING_MARKER


CompilerEventCallback = Callable[
    [str, str | None, str, WorkflowState, dict[str, Any] | None],
    None,
]


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
    planner_prompt: str | None = None
    planner_raw_response: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
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
            "planner_prompt": self.planner_prompt,
            "planner_raw_response": self.planner_raw_response,
        }


def compile_structured_workflow(
    parsed_json: dict[str, Any],
    check: bool = True,
    event_callback: CompilerEventCallback | None = None,
) -> WorkflowCompilationResult:
    """Compile a Recipe Tool Plan or Workflow IR without natural-language planning."""
    state = _run_compiler(parsed_json, check=check, event_callback=event_callback)
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
) -> WorkflowCompilationResult:
    """Plan from natural language, then compile the resulting Recipe Tool Plan."""
    plan_result = create_natural_language_plan(
        request,
        model=model,
        llm=llm,
        tool_catalog=tool_catalog,
        recipe_catalog=recipe_catalog,
    )
    state = _run_compiler(plan_result.plan, check=check)
    return _result_from_state(
        state,
        plan=plan_result.plan,
        check=check,
        planner_prompt=plan_result.planner_prompt,
        planner_raw_response=plan_result.raw_response,
    )


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
) -> WorkflowState:
    state = build_initial_state(parsed_json)
    if check and event_callback is None:
        return cast(WorkflowState, compiler_graph.invoke(state))

    _emit_compiler_event(event_callback, "node.started", "ir_normalizer", "IR normalizer started.", state)
    _merge_state(state, ir_normalizer_node(state))
    if state["analysis_errors"]:
        _emit_compiler_event(
            event_callback,
            "node.failed",
            "ir_normalizer",
            "IR normalizer failed.",
            state,
            {"analysis_errors": state["analysis_errors"]},
        )
        return state
    _emit_compiler_event(event_callback, "node.completed", "ir_normalizer", "IR normalizer completed.", state)
    _emit_compiler_event(
        event_callback,
        "artifact.updated",
        "ir_normalizer",
        "Workflow IR artifact updated.",
        state,
        {"artifact": "workflow_ir"},
    )

    _analyze_with_repair(state, event_callback=event_callback)
    if state["analysis_errors"]:
        return state

    _emit_compiler_event(event_callback, "node.started", "renderer", "Renderer started.", state)
    _merge_state(state, renderer_node(state))
    _emit_compiler_event(event_callback, "node.completed", "renderer", "Renderer completed.", state)
    _emit_compiler_event(
        event_callback,
        "artifact.updated",
        "renderer",
        "WDL artifact updated.",
        state,
        {"artifact": "wdl"},
    )

    if check:
        _validate_with_repair(state, event_callback=event_callback)
        return state

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
        state=state,
        planner_prompt=planner_prompt,
        planner_raw_response=planner_raw_response,
    )


def _is_recipe_tool_plan(parsed_json: dict[str, Any]) -> bool:
    workflow = parsed_json.get("workflow")
    if not isinstance(workflow, dict):
        return False
    return "recipe" in workflow and "tool_calls" in workflow


def _analyze_with_repair(
    state: WorkflowState,
    event_callback: CompilerEventCallback | None = None,
) -> None:
    while True:
        _emit_compiler_event(event_callback, "node.started", "analyzer", "Analyzer started.", state)
        _merge_state(state, analyzer_node(state))
        if not state["analysis_errors"]:
            _emit_compiler_event(event_callback, "node.completed", "analyzer", "Analyzer completed.", state)
            return

        _emit_compiler_event(
            event_callback,
            "node.failed",
            "analyzer",
            "Analyzer found Workflow IR errors.",
            state,
            {"analysis_errors": state["analysis_errors"]},
        )
        if not _can_attempt_repair(state):
            return

        _emit_compiler_event(event_callback, "node.started", "repairer", "Repairer started.", state)
        _merge_state(state, repairer_node(state))
        if not state["repair_actions"]:
            _emit_compiler_event(
                event_callback,
                "node.completed",
                "repairer",
                "Repairer found no safe deterministic fix.",
                state,
            )
            return
        _emit_workflow_ir_artifact_updated(event_callback, state)
        _emit_compiler_event(
            event_callback,
            "repair.applied",
            "repairer",
            "Workflow IR repair applied.",
            state,
            {"repair_actions": state["repair_actions"]},
        )
        _emit_compiler_event(event_callback, "node.completed", "repairer", "Repairer completed.", state)


def _validate_with_repair(
    state: WorkflowState,
    event_callback: CompilerEventCallback | None = None,
) -> None:
    while True:
        _emit_compiler_event(event_callback, "node.started", "checker", "Checker started.", state)
        _merge_state(state, checker_node(state))
        _emit_compiler_event(
            event_callback,
            "validation.completed",
            "checker",
            "WDL validation completed.",
            state,
            {
                "is_valid": state["is_valid"],
                "validation_message": state["validation_message"],
                "check_performed": True,
            },
        )
        if state["is_valid"] or _missing_local_validator(state) or not _can_attempt_repair(state):
            return

        _emit_compiler_event(event_callback, "node.started", "repairer", "Repairer started.", state)
        _merge_state(state, repairer_node(state))
        if not state["repair_actions"]:
            _emit_compiler_event(
                event_callback,
                "node.completed",
                "repairer",
                "Repairer found no safe deterministic fix.",
                state,
            )
            return
        _emit_workflow_ir_artifact_updated(event_callback, state)
        _emit_compiler_event(
            event_callback,
            "repair.applied",
            "repairer",
            "Workflow IR repair applied.",
            state,
            {"repair_actions": state["repair_actions"]},
        )
        _emit_compiler_event(event_callback, "node.completed", "repairer", "Repairer completed.", state)
        _analyze_with_repair(state, event_callback=event_callback)
        if state["analysis_errors"]:
            return
        _emit_compiler_event(event_callback, "node.started", "renderer", "Renderer started.", state)
        _merge_state(state, renderer_node(state))
        _emit_compiler_event(event_callback, "node.completed", "renderer", "Renderer completed.", state)
        _emit_compiler_event(
            event_callback,
            "artifact.updated",
            "renderer",
            "WDL artifact updated.",
            state,
            {"artifact": "wdl"},
        )


def _can_attempt_repair(state: WorkflowState) -> bool:
    return bool(state.get("workflow_ir")) and state.get("repair_count", 0) < MAX_REPAIR_ATTEMPTS


def _missing_local_validator(state: WorkflowState) -> bool:
    return VALIDATOR_MISSING_MARKER in state.get("validation_message", "")


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
) -> None:
    _emit_compiler_event(
        event_callback,
        "artifact.updated",
        "repairer",
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
        elif key == "is_valid":
            state["is_valid"] = value
