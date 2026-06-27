"""Natural-language planner node for the orchestration graph."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from src.catalog.loader import ToolCatalog
from src.nl_planner import (
    NaturalLanguagePlanningError,
    PlannerLlm,
    create_natural_language_plan,
)
from src.orchestration.state import OrchestrationState
from src.recipes.loader import RecipeCatalog


OrchestrationEventCallback = Callable[
    [str, str | None, str, Mapping[str, Any] | None, dict[str, Any] | None],
    None,
]
PlannerNode = Callable[[OrchestrationState], dict[str, Any]]


def natural_language_planner_node(state: OrchestrationState) -> dict[str, Any]:
    """Plan from natural language using the default planner dependencies."""
    return make_natural_language_planner_node()(state)


def make_natural_language_planner_node(
    *,
    llm: PlannerLlm | None = None,
    tool_catalog: ToolCatalog | None = None,
    recipe_catalog: RecipeCatalog | None = None,
    event_callback: OrchestrationEventCallback | None = None,
) -> PlannerNode:
    """Create a planner node, optionally injecting dependencies for tests."""

    def node(state: OrchestrationState) -> dict[str, Any]:
        started_event = _planner_event(
            "node.started",
            "Natural-language planner started.",
            {"model": state["planner_model"]},
        )
        _emit_planner_event(event_callback, started_event, state)

        try:
            plan_result = create_natural_language_plan(
                state["request"],
                model=state["planner_model"],
                llm=llm,
                tool_catalog=tool_catalog,
                recipe_catalog=recipe_catalog,
            )
        except NaturalLanguagePlanningError as exc:
            update: dict[str, Any] = {
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
            _emit_planner_events(event_callback, update["events"][1:], update)
            return update
        except Exception as exc:
            update = {
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
            _emit_planner_events(event_callback, update["events"][1:], update)
            return update

        update = {
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
        _emit_planner_events(event_callback, update["events"][1:], update)
        return update

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


def _emit_planner_events(
    event_callback: OrchestrationEventCallback | None,
    events: list[dict[str, Any]],
    state: Mapping[str, Any] | None,
) -> None:
    for event in events:
        _emit_planner_event(event_callback, event, state)


def _emit_planner_event(
    event_callback: OrchestrationEventCallback | None,
    event: dict[str, Any],
    state: Mapping[str, Any] | None,
) -> None:
    if event_callback is None:
        return
    event_callback(
        event["type"],
        event.get("node"),
        event["summary"],
        state,
        event.get("payload"),
    )
