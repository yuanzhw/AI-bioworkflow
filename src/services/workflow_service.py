"""Workflow planning and compilation service entry points."""

from dataclasses import dataclass
from typing import Any, Mapping, cast

from src.catalog.loader import ToolCatalog
from src.graph import agent
from src.nl_planner import DEFAULT_PLANNER_MODEL, PlannerLlm, create_natural_language_plan
from src.nodes.analyzer import analyzer_node
from src.nodes.ir_normalizer import ir_normalizer_node
from src.nodes.renderer import renderer_node
from src.nodes.repairer import repairer_node
from src.recipes.loader import RecipeCatalog
from src.state import WorkflowState


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
) -> WorkflowCompilationResult:
    """Compile a Recipe Tool Plan or Workflow IR without natural-language planning."""
    state = _run_compiler(parsed_json, check=check)
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
) -> WorkflowState:
    state = build_initial_state(parsed_json)
    if check:
        return cast(WorkflowState, agent.invoke(state))

    _merge_state(state, ir_normalizer_node(state))
    if state["analysis_errors"]:
        return state

    _analyze_with_repair(state)
    if state["analysis_errors"]:
        return state

    _merge_state(state, renderer_node(state))
    state["validation_message"] = "WDL syntax validation skipped (--no-check)."
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


def _analyze_with_repair(state: WorkflowState) -> None:
    while True:
        _merge_state(state, analyzer_node(state))
        if not state["analysis_errors"]:
            return

        _merge_state(state, repairer_node(state))
        if not state["repair_actions"]:
            return


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
