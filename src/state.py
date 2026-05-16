import operator

from langchain_core.messages import AnyMessage
from typing_extensions import Annotated, TypedDict


class WorkflowState(TypedDict):
    # 存放 LLM 的所有对话记录（必须用 operator.add 保证是追加模式）
    messages: Annotated[list[AnyMessage], operator.add]
    
    # 存放用户从前端传来的结构化表单数据（JSON格式）
    parsed_json: dict 

    # 标准化后的内部工作流表示，后续节点只处理这个 IR
    workflow_ir: dict

    # IR 静态分析阶段产生的错误
    analysis_errors: list[str]

    # IR 静态分析阶段产生的警告
    analysis_warnings: list[str]
    
    # 存放模型生成的 WDL 代码（用于后续验证器检查）
    current_wdl: str 

    # miniwdl 或系统校验阶段返回的最后一条消息
    validation_message: str
    
    # 记录当前重试或循环的次数，防止死循环
    error_count: int

    # 记录 IR repairer 已经尝试的次数，防止修复循环
    repair_count: int

    # 记录最近一次 IR repairer 执行的具体修复动作
    repair_actions: list[str]
    
    # 用一个明确的布尔值来记录校验状态，True 代表校验通过，False 代表校验失败
    is_valid: bool
