"""Natural-language orchestration graph shell."""

from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from src.orchestration.nodes.compiler import compile_planned_workflow_node
from src.orchestration.nodes.planner import natural_language_planner_node
from src.orchestration.state import OrchestrationState


OrchestrationNode = Callable[[OrchestrationState], dict[str, Any]]
logger = logging.getLogger(__name__)


def route_after_planner(state: OrchestrationState):
    """Stop after planner failures; otherwise delegate to the compiler graph."""
    if state.get("errors") or state.get("plan") is None:
        return END
    return "compiler_graph"


def build_orchestration_graph(
    *,
    planner_node: OrchestrationNode = natural_language_planner_node,
    compiler_node: OrchestrationNode = compile_planned_workflow_node,
):
    """Build the P1 orchestration graph shell."""
    builder = StateGraph(OrchestrationState)
    builder.add_node("natural_language_planner", planner_node)
    builder.add_node("compiler_graph", compiler_node)

    builder.add_edge(START, "natural_language_planner")
    builder.add_conditional_edges("natural_language_planner", route_after_planner)
    builder.add_edge("compiler_graph", END)
    return builder.compile()


orchestration_graph = build_orchestration_graph()

logger.info("Orchestration graph compiled.")
