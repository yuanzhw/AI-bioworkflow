from typing_extensions import TypedDict, Annotated
from langchain_core.messages import AnyMessage
import operator

class WorkflowState(TypedDict):
    # 存放 LLM 的所有对话记录（必须用 operator.add 保证是追加模式）
    messages: Annotated[list[AnyMessage], operator.add]
    
    # 存放用户从前端传来的结构化表单数据（JSON格式）
    parsed_json: dict 
    
    # 存放模型生成的 WDL 代码（用于后续验证器检查）
    current_wdl: str 
    
    # 记录当前重试或循环的次数，防止死循环
    error_count: int