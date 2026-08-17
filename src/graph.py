import logging

from langgraph.graph import END, START, StateGraph

from src.nodes.analyzer import analyzer_node
from src.nodes.checker import checker_node
from src.nodes.ir_normalizer import ir_normalizer_node
from src.nodes.renderer import renderer_node
from src.nodes.repairer import repairer_node
from src.nodes.reviewer_repair import (
    ReviewerNode,
    reviewer_repair_node as default_reviewer_repair_node,
)
from src.state import WorkflowState
from src.tools.validator import VALIDATOR_MISSING_MARKER

MAX_REPAIR_ATTEMPTS = 2
logger = logging.getLogger(__name__)


def route_after_ir_normalizer(state: WorkflowState):
    if state.get("analysis_errors"):
        return END
    return "analyzer"


def route_after_analyzer(state: WorkflowState):
    if state.get("analysis_errors"):
        if _can_attempt_repair(state):
            return "repairer"
        if state.get("workflow_ir"):
            return "reviewer_repair"
        return END
    return "renderer"


def route_after_checker(state: WorkflowState):
    if state.get("is_valid"):
        return END
    if _missing_local_validator(state):
        return END
    if _can_attempt_repair(state):
        return "repairer"
    return END


def route_after_repairer(state: WorkflowState):
    if state.get("repair_actions"):
        return "analyzer"
    if state.get("analysis_errors") and state.get("workflow_ir"):
        return "reviewer_repair"
    return END


def route_after_reviewer(state: WorkflowState):
    if state.get("reviewer_patch_applied"):
        return "analyzer"
    return END


def _can_attempt_repair(state: WorkflowState) -> bool:
    return bool(state.get("workflow_ir")) and state.get("repair_count", 0) < MAX_REPAIR_ATTEMPTS


def _missing_local_validator(state: WorkflowState) -> bool:
    return VALIDATOR_MISSING_MARKER in state.get("validation_message", "")


def build_compiler_graph(*, reviewer_node: ReviewerNode | None = None):
    """Build the compiler graph with an explicitly injected Reviewer node."""
    resolved_reviewer_node = (
        reviewer_node
        if reviewer_node is not None
        else default_reviewer_repair_node
    )
    builder = StateGraph(WorkflowState)
    builder.add_node("ir_normalizer", ir_normalizer_node)
    builder.add_node("analyzer", analyzer_node)
    builder.add_node("renderer", renderer_node)
    builder.add_node("checker", checker_node)
    builder.add_node("repairer", repairer_node)
    builder.add_node("reviewer_repair", resolved_reviewer_node)

    builder.add_edge(START, "ir_normalizer")
    builder.add_conditional_edges("ir_normalizer", route_after_ir_normalizer)
    builder.add_conditional_edges("analyzer", route_after_analyzer)
    builder.add_edge("renderer", "checker")
    builder.add_conditional_edges("checker", route_after_checker)
    builder.add_conditional_edges("repairer", route_after_repairer)
    builder.add_conditional_edges("reviewer_repair", route_after_reviewer)
    return builder.compile()


compiler_graph = build_compiler_graph()

# Backward-compatible alias for older imports. New code should use
# compiler_graph to make the graph boundary explicit.
agent = compiler_graph

logger.info("Compiler graph compiled.")
