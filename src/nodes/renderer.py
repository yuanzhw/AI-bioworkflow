import logging

from langchain_core.messages import AIMessage

from src.renderers import render_wdl
from src.state import WorkflowState


logger = logging.getLogger(__name__)


def renderer_node(state: WorkflowState):
    """
    Deterministically compile WorkflowIR into WDL.
    """
    logger.info("Renderer node is compiling Workflow IR into WDL.")

    wdl_code = render_wdl(state.get("workflow_ir", {}))
    return {
        "current_wdl": wdl_code,
        "messages": [AIMessage(content="WDL 已由 Workflow IR 编译完成。")],
    }
