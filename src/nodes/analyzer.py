from langchain_core.messages import HumanMessage

from src.analyzer import analyze_workflow_ir
from src.schema import WorkflowIR
from src.state import WorkflowState


def analyzer_node(state: WorkflowState):
    """
    Validate WorkflowIR before rendering WDL.
    """
    print("🧪 Analyzer 节点正在检查 Workflow IR...")

    try:
        workflow_ir = WorkflowIR.model_validate(state.get("workflow_ir", {}))
    except Exception as exc:
        message = f"Workflow IR 结构校验失败: {exc}"
        return {
            "analysis_errors": [message],
            "analysis_warnings": [],
            "is_valid": False,
            "messages": [HumanMessage(content=message)],
        }

    report = analyze_workflow_ir(workflow_ir)
    messages = []
    if not report.is_valid:
        messages.append(HumanMessage(content="\n".join(report.errors)))

    return {
        "analysis_errors": report.errors,
        "analysis_warnings": report.warnings,
        "is_valid": report.is_valid,
        "messages": messages,
    }
