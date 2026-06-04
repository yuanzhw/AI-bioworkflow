import logging

from langgraph.graph import END, START, StateGraph

from src.nodes.analyzer import analyzer_node
from src.nodes.checker import checker_node
from src.nodes.ir_normalizer import ir_normalizer_node
from src.nodes.renderer import renderer_node
from src.nodes.repairer import repairer_node
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
    return END


def _can_attempt_repair(state: WorkflowState) -> bool:
    return bool(state.get("workflow_ir")) and state.get("repair_count", 0) < MAX_REPAIR_ATTEMPTS


def _missing_local_validator(state: WorkflowState) -> bool:
    return VALIDATOR_MISSING_MARKER in state.get("validation_message", "")


# 1. 实例化状态图，传入我们的 WorkflowState 笔记本
builder = StateGraph(WorkflowState)

# 2. 添加工作节点
# 第一个参数是节点的内部名称（随便起），第二个参数是我们刚才写的处理函数
builder.add_node("ir_normalizer", ir_normalizer_node)
builder.add_node("analyzer", analyzer_node)
builder.add_node("renderer", renderer_node)
builder.add_node("checker", checker_node)
builder.add_node("repairer", repairer_node)

# 3. 规划工作流向 (连线)
# START -> ir_normalizer -> analyzer -> renderer -> checker -> END
# analyzer/checker can branch to repairer, then repairer returns to analyzer.
builder.add_edge(START, "ir_normalizer")
builder.add_conditional_edges("ir_normalizer", route_after_ir_normalizer)
builder.add_conditional_edges("analyzer", route_after_analyzer)
builder.add_edge("renderer", "checker")
builder.add_conditional_edges("checker", route_after_checker)
builder.add_conditional_edges("repairer", route_after_repairer)
# 4. 编译打包成最终的 Agent
agent = builder.compile()

logger.info("Agent graph compiled.")
