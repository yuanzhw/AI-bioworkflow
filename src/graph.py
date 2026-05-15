from langgraph.graph import END, START, StateGraph

from src.nodes.analyzer import analyzer_node
from src.nodes.checker import checker_node
from src.nodes.planner import planner_node
from src.nodes.renderer import renderer_node
from src.state import WorkflowState


def route_after_planner(state: WorkflowState):
    if state.get("analysis_errors"):
        return END
    return "analyzer"


def route_after_analyzer(state: WorkflowState):
    if state.get("analysis_errors"):
        return END
    return "renderer"


def route_after_checker(_state: WorkflowState):
    """
    End after syntax validation. A future repairer can branch from here.
    """
    return END


# 1. 实例化状态图，传入我们的 WorkflowState 笔记本
builder = StateGraph(WorkflowState)

# 2. 添加工作节点
# 第一个参数是节点的内部名称（随便起），第二个参数是我们刚才写的处理函数
builder.add_node("planner", planner_node)
builder.add_node("analyzer", analyzer_node)
builder.add_node("renderer", renderer_node)
builder.add_node("checker", checker_node)

# 3. 规划工作流向 (连线)
# START -> planner -> analyzer -> renderer -> checker -> END
builder.add_edge(START, "planner")
builder.add_conditional_edges("planner", route_after_planner)
builder.add_conditional_edges("analyzer", route_after_analyzer)
builder.add_edge("renderer", "checker")
builder.add_conditional_edges("checker", route_after_checker)
# 4. 编译打包成最终的 Agent
agent = builder.compile()

print("✅ Agent 图纸编译完成！")
