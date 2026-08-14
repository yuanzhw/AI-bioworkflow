from __future__ import annotations

from typing import Any

from src.catalog.loader import ToolCatalog, load_tool_catalog
from src.catalog.resolver import ToolCallPlan, resolve_tool_plan, validate_recipe_plan
from src.recipes.loader import RecipeCatalog, load_recipe_catalog
from src.reviewer_repair import (
    ApprovedCatalogContext,
    ApprovedRecipeMetadata,
    ApprovedToolMetadata,
    ReviewerFailureStage,
    ReviewerRepairRequest,
)
from src.schema import CallSpec, ScatterSpec, WorkflowIR, coerce_workflow_ir
from src.state import WorkflowState


class ReviewerRequestBuildError(ValueError):
    """Raised when a safe structured Reviewer request cannot be constructed."""


def build_reviewer_repair_request(
    state: WorkflowState,
    *,
    failure_stage: ReviewerFailureStage,
    tool_catalog: ToolCatalog | None = None,
    recipe_catalog: RecipeCatalog | None = None,
) -> ReviewerRepairRequest:
    """Build a structured request with only current-workflow approved metadata."""
    try:
        workflow_ir = coerce_workflow_ir(state.get("workflow_ir", {}))
    except Exception as exc:
        raise ReviewerRequestBuildError(
            f"Workflow IR is unavailable or invalid ({exc.__class__.__name__})."
        ) from exc

    catalog_context = build_approved_catalog_context(
        state.get("parsed_json", {}),
        workflow_ir,
        tool_catalog=tool_catalog,
        recipe_catalog=recipe_catalog,
    )
    return ReviewerRepairRequest(
        workflow_ir=workflow_ir,
        failure_stage=failure_stage,
        analysis_errors=list(state.get("analysis_errors", [])),
        analysis_warnings=list(state.get("analysis_warnings", [])),
        validation_message=state.get("validation_message", ""),
        repair_history=_repair_history(state),
        catalog_context=catalog_context,
        attempt_index=state.get("reviewer_attempt_count", 0) + 1,
    )


def build_approved_catalog_context(
    parsed_json: dict[str, Any],
    workflow_ir: WorkflowIR,
    *,
    tool_catalog: ToolCatalog | None = None,
    recipe_catalog: RecipeCatalog | None = None,
) -> ApprovedCatalogContext:
    """Select approved metadata only for recipe/tool calls proven by the current plan."""
    if not _looks_like_tool_call_plan(parsed_json):
        return ApprovedCatalogContext()

    try:
        plan = ToolCallPlan.model_validate(parsed_json)
        resolved_tool_catalog = tool_catalog or load_tool_catalog()
        resolved_recipe_catalog = recipe_catalog or load_recipe_catalog(
            tool_catalog=resolved_tool_catalog
        )
        recipe = resolved_recipe_catalog.get(plan.workflow.recipe)
        validate_recipe_plan(plan, recipe)
        expected_workflow_ir = resolve_tool_plan(
            plan,
            resolved_recipe_catalog,
            resolved_tool_catalog,
        )
    except Exception as exc:
        raise ReviewerRequestBuildError(
            "Recipe Tool Plan cannot provide approved Reviewer context "
            f"({exc.__class__.__name__})."
        ) from exc

    workflow_calls = _canonical_call_map(workflow_ir, label="Current")
    expected_workflow_calls = _canonical_call_map(
        expected_workflow_ir,
        label="Resolved",
    )
    planned_call_ids = {tool_call.id for tool_call in plan.workflow.tool_calls}
    if set(workflow_calls) != planned_call_ids:
        raise ReviewerRequestBuildError(
            "Recipe Tool Plan calls do not match the current canonical Workflow IR steps."
        )
    _validate_catalog_provenance(
        workflow_ir,
        expected_workflow_ir,
        workflow_calls=workflow_calls,
        expected_workflow_calls=expected_workflow_calls,
    )

    step_ids: list[str] = []
    tool_ids: list[str] = []
    tool_metadata: list[ApprovedToolMetadata] = []
    seen_tools: set[tuple[str, str]] = set()

    for tool_call in plan.workflow.tool_calls:
        try:
            step = recipe.step_by_id(tool_call.step)
            if tool_call.tool not in step.allowed_tools:
                raise ValueError(
                    f"tool '{tool_call.tool}' is not approved for recipe step '{step.id}'"
                )
            tool = resolved_tool_catalog.get(tool_call.tool, tool_call.version)
            workflow_call = workflow_calls[tool_call.id]
            workflow_task = workflow_ir.tasks[workflow_call.task]
        except Exception as exc:
            raise ReviewerRequestBuildError(
                "A planned tool call cannot provide approved Reviewer context "
                f"({exc.__class__.__name__})."
            ) from exc

        if workflow_task.runtime.docker != tool.runtime.docker:
            raise ReviewerRequestBuildError(
                f"Tool call '{tool_call.id}' runtime does not match its approved Catalog entry."
            )

        if tool_call.step not in step_ids:
            step_ids.append(tool_call.step)
        if tool_call.tool not in tool_ids:
            tool_ids.append(tool_call.tool)

        tool_key = (tool.id, tool.version)
        if tool_key in seen_tools:
            continue
        seen_tools.add(tool_key)
        tool_metadata.append(
            ApprovedToolMetadata(
                tool_id=tool.id,
                version=tool.version,
                inputs=sorted(tool.inputs),
                outputs=sorted(tool.outputs),
                trust_status="catalog-approved",
                runtime_docker=tool.runtime.docker,
            )
        )

    return ApprovedCatalogContext(
        recipes=[
            ApprovedRecipeMetadata(
                recipe_id=recipe.id,
                step_ids=step_ids,
                tool_ids=tool_ids,
            )
        ],
        tools=tool_metadata,
    )


def _repair_history(state: WorkflowState) -> list[str]:
    history = list(state.get("repair_actions", []))
    previous_patch = state.get("reviewer_ir_patch")
    if isinstance(previous_patch, dict) and previous_patch.get("summary"):
        history.append(f"Reviewer patch: {previous_patch['summary']}")
    previous_rejection = state.get("reviewer_rejection_reason")
    if previous_rejection:
        history.append(f"Reviewer rejection: {previous_rejection}")
    return history


def _validate_catalog_provenance(
    workflow_ir: WorkflowIR,
    expected_workflow_ir: WorkflowIR,
    *,
    workflow_calls: dict[str, CallSpec],
    expected_workflow_calls: dict[str, CallSpec],
) -> None:
    """Verify fields outside the patch allowlist still match formal plan resolution."""
    if (
        workflow_ir.version != expected_workflow_ir.version
        or workflow_ir.workflow.name != expected_workflow_ir.workflow.name
        or workflow_ir.workflow.inputs != expected_workflow_ir.workflow.inputs
    ):
        raise ReviewerRequestBuildError(
            "Current Workflow IR does not match Recipe Tool Plan provenance."
        )

    if set(workflow_ir.tasks) != set(expected_workflow_ir.tasks):
        raise ReviewerRequestBuildError(
            "Current Workflow IR tasks do not match Recipe Tool Plan provenance."
        )

    for call_id, expected_call in expected_workflow_calls.items():
        if workflow_calls[call_id].task != expected_call.task:
            raise ReviewerRequestBuildError(
                f"Tool call '{call_id}' task does not match Recipe Tool Plan provenance."
            )

    for task_name, expected_task in expected_workflow_ir.tasks.items():
        current_task = workflow_ir.tasks[task_name]
        if _catalog_controlled_task_data(current_task) != _catalog_controlled_task_data(
            expected_task
        ):
            raise ReviewerRequestBuildError(
                f"Task '{task_name}' Catalog-controlled fields do not match "
                "Recipe Tool Plan provenance."
            )


def _canonical_call_map(
    workflow_ir: WorkflowIR,
    *,
    label: str,
) -> dict[str, CallSpec]:
    canonical_calls = _flatten_canonical_calls(workflow_ir.workflow.steps)
    call_map = {call.id: call for call in canonical_calls}
    if len(call_map) != len(canonical_calls):
        raise ReviewerRequestBuildError(
            f"{label} Workflow IR contains duplicate canonical call IDs."
        )

    if workflow_ir.workflow.calls != canonical_calls:
        raise ReviewerRequestBuildError(
            f"{label} Workflow IR compatibility calls do not match canonical workflow steps."
        )
    return call_map


def _flatten_canonical_calls(
    steps: list[CallSpec | ScatterSpec],
) -> list[CallSpec]:
    calls: list[CallSpec] = []
    for step in steps:
        if isinstance(step, CallSpec):
            calls.append(step)
        else:
            calls.extend(_flatten_canonical_calls(step.body))
    return calls


def _catalog_controlled_task_data(task: Any) -> dict[str, Any]:
    return {
        "inputs": task.inputs,
        "command": task.command,
        "outputs": {
            output_name: {
                "type": output.type,
                "tags": output.tags,
            }
            for output_name, output in task.outputs.items()
        },
        "runtime": task.runtime.model_dump(mode="json"),
    }


def _looks_like_tool_call_plan(value: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    workflow = value.get("workflow")
    return (
        isinstance(workflow, dict)
        and "recipe" in workflow
        and "tool_calls" in workflow
    )
