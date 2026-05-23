import logging

from langchain_core.messages import AIMessage

from src.repairer import repair_workflow_ir
from src.state import WorkflowState


logger = logging.getLogger(__name__)


def repairer_node(state: WorkflowState):
    """
    Deterministically repair WorkflowIR when the analyzer/checker finds a safe fix.
    """
    logger.info("Repairer node is attempting to repair Workflow IR.")

    try:
        report = repair_workflow_ir(state.get("workflow_ir", {}))
    except Exception as exc:
        message = f"Workflow IR 修复失败: {exc}"
        return {
            "repair_actions": [],
            "messages": [AIMessage(content=message)],
        }

    repair_count = state.get("repair_count", 0) + 1
    if not report.changed:
        return {
            "repair_actions": [],
            "repair_count": repair_count,
            "messages": [AIMessage(content="Repairer 未找到可安全自动修复的 IR 问题。")],
        }

    action_summary = "\n".join(f"- {action}" for action in report.actions)
    return {
        "workflow_ir": report.workflow_ir.model_dump(mode="json"),
        "analysis_errors": [],
        "analysis_warnings": [],
        "current_wdl": "",
        "is_valid": False,
        "repair_actions": report.actions,
        "repair_count": repair_count,
        "messages": [AIMessage(content=f"Workflow IR 已修复：\n{action_summary}")],
    }
