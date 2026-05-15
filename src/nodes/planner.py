from langchain_core.messages import AIMessage, HumanMessage

from src.schema import coerce_workflow_ir
from src.state import WorkflowState


def planner_node(state: WorkflowState):
    """
    Normalize user JSON into the internal WorkflowIR.

    This node is intentionally deterministic for structured inputs. A future
    LLM planner can sit before this step and produce the same IR schema from
    natural language or incomplete forms.
    """
    print("🧭 Planner 节点正在标准化 Workflow IR...")

    raw_input = state.get("workflow_ir") or state.get("parsed_json", {})

    try:
        workflow_ir = coerce_workflow_ir(raw_input)
    except Exception as exc:
        message = f"Workflow JSON 无法转换为标准 IR: {exc}"
        return {
            "analysis_errors": [message],
            "analysis_warnings": [],
            "is_valid": False,
            "messages": [HumanMessage(content=message)],
        }

    return {
        "workflow_ir": workflow_ir.model_dump(mode="json"),
        "analysis_errors": [],
        "analysis_warnings": [],
        "messages": [AIMessage(content="Workflow IR 已标准化。")],
    }
