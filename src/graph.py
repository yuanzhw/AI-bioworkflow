from langgraph.graph import StateGraph, START, END
from src.state import WorkflowState
from src.nodes.coder import coder_node

# 1. 实例化状态图，传入我们的 WorkflowState 笔记本
builder = StateGraph(WorkflowState)

# 2. 添加工作节点
# 第一个参数是节点的内部名称（随便起），第二个参数是我们刚才写的处理函数
builder.add_node("coder", coder_node)

# 3. 规划工作流向 (连线)
# START -> coder -> END
builder.add_edge(START, "coder")
builder.add_edge("coder", END)

# 4. 编译打包成最终的 Agent
agent = builder.compile()

print("✅ Agent 图纸编译完成！")