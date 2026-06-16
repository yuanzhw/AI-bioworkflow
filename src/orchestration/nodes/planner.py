"""Natural-language planner node for the orchestration graph."""

from __future__ import annotations

from typing import Any, Callable

from src.catalog.loader import ToolCatalog
from src.nl_planner import (
    NaturalLanguagePlanningError,
    PlannerLlm,
    create_natural_language_plan,
)
from src.orchestration.state import OrchestrationState
from src.recipes.loader import RecipeCatalog


PlannerNode = Callable[[OrchestrationState], dict[str, Any]]


def natural_language_planner_node(state: OrchestrationState) -> dict[str, Any]:
    """Plan from natural language using the default planner dependencies."""
    return make_natural_language_planner_node()(state)


def make_natural_language_planner_node(
    *,
    llm: PlannerLlm | None = None,
    tool_catalog: ToolCatalog | None = None,
    recipe_catalog: RecipeCatalog | None = None,
) -> PlannerNode:
    """Create a planner node, optionally injecting dependencies for tests."""

    def node(state: OrchestrationState) -> dict[str, Any]:
        started_event = _planner_event(
            "node.started",
            "Natural-language planner started.",
            {"model": state["planner_model"]},
        )

        try:
            plan_result = create_natural_language_plan(
                state["request"],
                model=state["planner_model"],
                llm=llm,
                tool_catalog=tool_catalog,
                recipe_catalog=recipe_catalog,
            )
        except NaturalLanguagePlanningError as exc:
            return {
                "plan": None,
                "planner_prompt": None,
                "planner_raw_response": None,
                "errors": [str(exc)],
                "events": [
                    started_event,
                    _planner_event(
                        "node.failed",
                        "Natural-language planner failed.",
                        {
                            "error_type": exc.__class__.__name__,
                            "error": str(exc),
                        },
                    ),
                ],
            }
        except Exception as exc:
            return {
                "plan": None,
                "planner_prompt": None,
                "planner_raw_response": None,
                "errors": [str(exc)],
                "events": [
                    started_event,
                    _planner_event(
                        "node.failed",
                        "Natural-language planner failed unexpectedly.",
                        {
                            "error_type": exc.__class__.__name__,
                            "error": str(exc),
                        },
                    ),
                ],
            }

        return {
            "plan": plan_result.plan,
            "planner_prompt": plan_result.planner_prompt,
            "planner_raw_response": plan_result.raw_response,
            "errors": [],
            "events": [
                started_event,
                _planner_event("node.completed", "Natural-language planner completed."),
                _planner_event(
                    "artifact.updated",
                    "Recipe Tool Plan artifact updated.",
                    {"artifact": "plan"},
                ),
            ],
        }

    return node


def _planner_event(
    event_type: str,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": event_type,
        "node": "planner",
        "summary": summary,
    }
    if payload is not None:
        event["payload"] = payload
    return event
