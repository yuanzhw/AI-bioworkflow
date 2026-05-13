from langchain_core.messages import HumanMessage
from src.state import WorkflowState
from src.tools.validator import wdl_validator

def checker_node(state: WorkflowState):
    """
    负责调用 miniwdl 工具校验代码的节点
    """
    print("🔍 Checker 节点正在运行 miniwdl 校验...")
    
    wdl_code = state.get("current_wdl", "")
    current_error_count = state.get("error_count", 0)

    # 1. 直接调用我们之前写好的工具
    result = wdl_validator.invoke({"wdl_code": wdl_code})
    
    is_valid = result.get("is_valid", False) if isinstance(result, dict) else False
    message = result.get("message", f"未知系统错误，返回内容为: {result}") if isinstance(result, dict) else str(result)

    # 2. 判断结果并更新状态笔记本
    if is_valid:
        print("🎉 校验通过！")
        return {"error_count": current_error_count, "is_valid": True} # 没报错，只更新状态，不增加消息
    else:
        print("❌ 校验失败！准备打回重写...")
        # 报错了！伪造一个人类的消息，把报错糊在模型脸上，并记录失败次数
        return {
            "messages": [HumanMessage(content=message)],
            "error_count": current_error_count + 1,
            "is_valid": False
        }