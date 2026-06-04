import logging

from langchain_core.messages import HumanMessage

from src.state import WorkflowState
from src.tools.validator import wdl_validator

logger = logging.getLogger(__name__)


def checker_node(state: WorkflowState):
    """
    负责调用 WDL 校验工具校验代码的节点
    """
    logger.info("Checker node is running WDL validation.")
    
    wdl_code = state.get("current_wdl", "")
    current_error_count = state.get("error_count", 0)

    # 1. 直接调用我们之前写好的工具
    result = wdl_validator.invoke({"wdl_code": wdl_code})
    
    is_valid = result.get("is_valid", False) if isinstance(result, dict) else False
    message = result.get("message", f"未知系统错误，返回内容为: {result}") if isinstance(result, dict) else str(result)

    # 2. 判断结果并更新状态笔记本
    if is_valid:
        logger.info("WDL validation passed.")
        return {
            "error_count": current_error_count,
            "is_valid": True,
            "validation_message": message,
        }
    else:
        logger.info("WDL validation failed.")
        # 报错了！把校验错误写入消息，后续 LLM repairer 可以基于它修复 IR
        return {
            "messages": [HumanMessage(content=message)],
            "error_count": current_error_count + 1,
            "is_valid": False,
            "validation_message": message,
        }
