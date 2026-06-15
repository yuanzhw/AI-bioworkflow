"""State helpers for the natural-language orchestration graph."""

from __future__ import annotations

import operator
from typing import Any, Literal, TYPE_CHECKING

from typing_extensions import Annotated, TypedDict

if TYPE_CHECKING:
    from src.services.workflow_service import WorkflowCompilationResult


FailureStage = Literal["orchestration", "compiler"]


class OrchestrationState(TypedDict):
    """Top-level state for natural-language planning and compiler delegation."""

    request: str
    planner_model: str
    check: bool
    plan: dict[str, Any] | None
    planner_prompt: str | None
    planner_raw_response: str | None
    compiler_result: WorkflowCompilationResult | None
    errors: Annotated[list[str], operator.add]
    events: Annotated[list[dict[str, Any]], operator.add]


def build_initial_orchestration_state(
    request: str,
    *,
    planner_model: str,
    check: bool = True,
) -> OrchestrationState:
    """Build the initial state for a natural-language orchestration run."""
    return {
        "request": request,
        "planner_model": planner_model,
        "check": check,
        "plan": None,
        "planner_prompt": None,
        "planner_raw_response": None,
        "compiler_result": None,
        "errors": [],
        "events": [],
    }


def orchestration_succeeded(state: OrchestrationState) -> bool:
    """Return whether orchestration and delegated compilation both succeeded."""
    if state["errors"]:
        return False

    compiler_result = state["compiler_result"]
    if compiler_result is None:
        return False
    return compiler_result.succeeded


def orchestration_failure_stage(state: OrchestrationState) -> FailureStage | None:
    """Identify whether a failed run failed in orchestration or compilation."""
    if state["errors"]:
        return "orchestration"

    compiler_result = state["compiler_result"]
    if compiler_result is not None and not compiler_result.succeeded:
        return "compiler"
    return None
