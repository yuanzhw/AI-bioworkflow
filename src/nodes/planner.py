import logging

from langchain_core.messages import AIMessage, HumanMessage

from src.catalog import load_tool_catalog, resolve_tool_plan, static_provider_from_image_map
from src.recipes import load_recipe_catalog
from src.schema import coerce_workflow_ir
from src.state import WorkflowState


logger = logging.getLogger(__name__)


def planner_node(state: WorkflowState):
    """
    Normalize user JSON into the internal WorkflowIR.

    This node is intentionally deterministic for structured inputs. A future
    LLM planner can sit before this step and produce the same IR schema from
    natural language or incomplete forms.
    """
    logger.info("Planner node is normalizing Workflow IR.")

    raw_input = state.get("workflow_ir") or state.get("parsed_json", {})

    try:
        workflow_ir, message = _normalize_planner_input(raw_input, state)
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
        "messages": [AIMessage(content=message)],
    }


def _normalize_planner_input(raw_input: dict, state: WorkflowState):
    if _is_tool_call_plan(raw_input):
        tool_catalog = load_tool_catalog()
        recipe_catalog = load_recipe_catalog(tool_catalog=tool_catalog)
        container_provider = _container_provider_from_state(state)
        workflow_ir = resolve_tool_plan(
            raw_input,
            recipe_catalog,
            tool_catalog,
            container_provider=container_provider,
        )
        return workflow_ir, "Recipe tool plan 已解析为 Workflow IR。"

    workflow_ir = coerce_workflow_ir(raw_input)
    return workflow_ir, "Workflow IR 已标准化。"


def _container_provider_from_state(state: WorkflowState):
    if not state.get("fill_containers"):
        return None
    return static_provider_from_image_map(state.get("container_image_candidates", {}))


def _is_tool_call_plan(raw_input: dict) -> bool:
    if not isinstance(raw_input, dict):
        return False

    workflow = raw_input.get("workflow")
    if not isinstance(workflow, dict):
        return False

    return "recipe" in workflow and "tool_calls" in workflow
