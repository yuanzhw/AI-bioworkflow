from langchain_core.messages import AIMessage

from src.renderers import render_wdl
from src.state import WorkflowState


def renderer_node(state: WorkflowState):
    """
    Deterministically compile WorkflowIR into WDL.
    """
    print("🧱 Renderer 节点正在从 IR 编译 WDL...")

    wdl_code = render_wdl(state.get("workflow_ir", {}))
    return {
        "current_wdl": wdl_code,
        "messages": [AIMessage(content="WDL 已由 Workflow IR 编译完成。")],
    }
