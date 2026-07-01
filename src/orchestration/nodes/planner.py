"""Natural-language planner node for the orchestration graph."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from src.catalog.loader import ToolCatalog, load_tool_catalog
from src.catalog.retriever import retrieve_catalog_context
from src.nl_planner import (
    NaturalLanguagePlanningError,
    PlannerLlm,
    create_natural_language_plan,
)
from src.orchestration.state import OrchestrationState
from src.recipes.loader import RecipeCatalog, load_recipe_catalog


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
        events: list[dict[str, Any]] = []
        catalog_retrieval: dict[str, Any] | None = None

        try:
            if not state["request"].strip():
                raise NaturalLanguagePlanningError("natural language request is empty")

            resolved_tool_catalog = tool_catalog or load_tool_catalog()
            resolved_recipe_catalog = recipe_catalog or load_recipe_catalog(tool_catalog=resolved_tool_catalog)

            catalog_started_event = _catalog_event(
                "node.started",
                "Catalog retriever started.",
            )
            events.append(catalog_started_event)
            _emit_planner_event(event_callback, catalog_started_event, state)

            catalog_retrieval = retrieve_catalog_context(
                state["request"],
                resolved_tool_catalog,
                resolved_recipe_catalog,
            )
            catalog_completed_event = _catalog_event(
                "node.completed",
                "Catalog retriever completed.",
                {
                    "strategy": catalog_retrieval["strategy"],
                    "recipe_count": len(catalog_retrieval["recipes"]),
                    "tool_count": len(catalog_retrieval["tools"]),
                    "fallback_used": catalog_retrieval["fallback_used"],
                },
            )
            catalog_artifact_event = _catalog_event(
                "artifact.updated",
                "Catalog retrieval artifact updated.",
                {"artifact": "catalog_retrieval"},
            )
            events.extend([catalog_completed_event, catalog_artifact_event])
            catalog_state = {"catalog_retrieval": catalog_retrieval}
            _emit_planner_events(
                event_callback,
                [catalog_completed_event, catalog_artifact_event],
                catalog_state,
            )

            started_event = _planner_event(
                "node.started",
                "Natural-language planner started.",
                {"model": state["planner_model"]},
            )
            events.append(started_event)
            _emit_planner_event(event_callback, started_event, state)

            plan_result = create_natural_language_plan(
                state["request"],
                model=state["planner_model"],
                llm=llm,
                tool_catalog=resolved_tool_catalog,
                recipe_catalog=resolved_recipe_catalog,
                catalog_retrieval=catalog_retrieval,
            )
        except NaturalLanguagePlanningError as exc:
            update: dict[str, Any] = {
                "catalog_retrieval": catalog_retrieval,
                "plan": None,
                "planner_prompt": None,
                "planner_raw_response": None,
                "errors": [str(exc)],
                "events": [
                    *events,
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
            _emit_planner_events(event_callback, update["events"][len(events) :], update)
            return update
        except Exception as exc:
            update = {
                "catalog_retrieval": catalog_retrieval,
                "plan": None,
                "planner_prompt": None,
                "planner_raw_response": None,
                "errors": [str(exc)],
                "events": [
                    *events,
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
            _emit_planner_events(event_callback, update["events"][len(events) :], update)
            return update

        update = {
            "catalog_retrieval": plan_result.catalog_retrieval,
            "plan": plan_result.plan,
            "planner_prompt": plan_result.planner_prompt,
            "planner_raw_response": plan_result.raw_response,
            "errors": [],
            "events": [
                *events,
                _planner_event("node.completed", "Natural-language planner completed."),
                _planner_event(
                    "artifact.updated",
                    "Recipe Tool Plan artifact updated.",
                    {"artifact": "plan"},
                ),
            ],
        }
        _emit_planner_events(event_callback, update["events"][len(events) :], update)
        return update

    return node


def _planner_event(
    event_type: str,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _node_event(event_type, "planner", summary, payload)


def _catalog_event(
    event_type: str,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _node_event(event_type, "catalog_retriever", summary, payload)


def _node_event(
    event_type: str,
    node: str,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": event_type,
        "node": node,
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
