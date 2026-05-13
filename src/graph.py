from langgraph.graph import END, START, StateGraph

from src.nodes.checker import checker_node
from src.nodes.coder import coder_node
from src.state import WorkflowState


# --- 定义路由逻辑 (大脑) ---
def router(state: WorkflowState):
    """
    决定下一步去哪里的十字路口警察
    """
    # 1. 安全锁：如果重试了 3 次还是错，强制下班，防止破产
    if state["error_count"] >= 3:
        print("⚠️ 超过最大重试次数 (3次)，强制结束流转。")
        return END
        
    # 2. 检查最后一条消息的内容
    last_message = state["messages"][-1]
    
    # 如果is_valid 是 False，说明 Checker 打回了错误消息，那么就让它回去 coder 重写
    # 那就打回给 coder 重新写
    if state.get("is_valid") is False:
        return "coder"
        
    # 如果顺利通过（没有报错产生新的 HumanMessage），就顺利结束
    return END

# 1. 实例化状态图，传入我们的 WorkflowState 笔记本
builder = StateGraph(WorkflowState)

# 2. 添加工作节点
# 第一个参数是节点的内部名称（随便起），第二个参数是我们刚才写的处理函数
builder.add_node("coder", coder_node)
builder.add_node("checker", checker_node)

# 3. 规划工作流向 (连线)
# START -> coder -> checker -> END
builder.add_edge(START, "coder")
builder.add_edge("coder", "checker")
builder.add_conditional_edges("checker", router)  # 根据 router 的判断，checker 可以去 coder 重试，或者直接去 END 结束
# 4. 编译打包成最终的 Agent
agent = builder.compile()

print("✅ Agent 图纸编译完成！")