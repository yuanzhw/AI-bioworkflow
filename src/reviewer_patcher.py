from __future__ import annotations

from typing import Any

from src.reviewer_repair import (
    ApprovedCatalogContext,
    ReviewerIRPatch,
    ReviewerPatchAction,
    ReviewerPatchOperation,
    ReviewerPatchPolicyError,
    validate_reviewer_patch_policy,
)
from src.schema import WorkflowIR, coerce_workflow_ir


class ReviewerPatchApplicationError(ValueError):
    """Raised when a policy-allowed Reviewer patch cannot be applied safely."""


def apply_reviewer_patch(
    workflow_ir: WorkflowIR | dict[str, Any],
    patch: ReviewerIRPatch,
    catalog_context: ApprovedCatalogContext | None = None,
) -> WorkflowIR:
    """Apply a policy-checked Reviewer patch to a Workflow IR copy.

    The original Workflow IR object is never mutated. The returned candidate has
    already been revalidated against the WorkflowIR schema.
    """

    source_ir = coerce_workflow_ir(workflow_ir)
    validate_reviewer_patch_policy(patch, catalog_context=catalog_context)

    candidate = source_ir.model_dump(mode="python")
    for action in patch.actions:
        _apply_action(candidate, action)

    workflow = candidate.get("workflow")
    if isinstance(workflow, dict):
        workflow.pop("calls", None)

    try:
        return coerce_workflow_ir(candidate)
    except (TypeError, ValueError) as exc:
        raise ReviewerPatchApplicationError(
            "applied Reviewer patch produced invalid Workflow IR."
        ) from exc


def _apply_action(candidate: dict[str, Any], action: ReviewerPatchAction) -> None:
    if action.operation == ReviewerPatchOperation.MOVE:
        _apply_move(candidate, action)
    elif action.operation == ReviewerPatchOperation.ADD:
        _apply_add(candidate, action.path, action.value)
    elif action.operation == ReviewerPatchOperation.REPLACE:
        _apply_replace(candidate, action.path, action.value)
    elif action.operation == ReviewerPatchOperation.REMOVE:
        _apply_remove(candidate, action.path)
    else:
        raise ReviewerPatchApplicationError(f"unsupported Reviewer patch operation: {action.operation}")


def _apply_add(candidate: dict[str, Any], path: str, value: Any) -> None:
    parent, key = _resolve_parent(candidate, path)
    if not isinstance(parent, dict):
        raise ReviewerPatchApplicationError(f"add target parent for '{path}' is not an object")
    if key in parent:
        raise ReviewerPatchApplicationError(f"add target '{path}' already exists")
    parent[key] = value


def _apply_replace(candidate: dict[str, Any], path: str, value: Any) -> None:
    parent, key = _resolve_parent(candidate, path)
    if isinstance(parent, dict):
        if key not in parent:
            raise ReviewerPatchApplicationError(f"replace target '{path}' does not exist")
        parent[key] = value
        return

    if isinstance(parent, list):
        index = _parse_existing_index(key, parent, path)
        parent[index] = value
        return

    raise ReviewerPatchApplicationError(f"replace target parent for '{path}' is not editable")


def _apply_remove(candidate: dict[str, Any], path: str) -> None:
    parent, key = _resolve_parent(candidate, path)
    if isinstance(parent, dict):
        if key not in parent:
            raise ReviewerPatchApplicationError(f"remove target '{path}' does not exist")
        del parent[key]
        return

    if isinstance(parent, list):
        index = _parse_existing_index(key, parent, path)
        parent.pop(index)
        return

    raise ReviewerPatchApplicationError(f"remove target parent for '{path}' is not editable")


def _apply_move(candidate: dict[str, Any], action: ReviewerPatchAction) -> None:
    if action.from_path is None:
        raise ReviewerPatchApplicationError("move patch actions require from_path")

    source_parent, source_key = _resolve_parent(candidate, action.from_path)
    target_parent, target_key = _resolve_parent(candidate, action.path)
    if source_parent is not target_parent or not isinstance(source_parent, list):
        raise ReviewerPatchApplicationError(
            f"move paths must resolve to the same workflow list: {action.from_path} -> {action.path}"
        )

    source_index = _parse_existing_index(source_key, source_parent, action.from_path)
    item = source_parent.pop(source_index)
    target_index = _parse_insert_index(target_key, source_parent, action.path)
    source_parent.insert(target_index, item)


def _resolve_parent(candidate: dict[str, Any], path: str) -> tuple[Any, str]:
    segments = _json_pointer_segments(path)
    if not segments:
        raise ReviewerPatchApplicationError("patch path must not target the Workflow IR root")

    current: Any = candidate
    for segment in segments[:-1]:
        if isinstance(current, dict):
            if segment not in current:
                raise ReviewerPatchApplicationError(f"patch path '{path}' does not exist")
            current = current[segment]
            continue

        if isinstance(current, list):
            index = _parse_existing_index(segment, current, path)
            current = current[index]
            continue

        raise ReviewerPatchApplicationError(f"patch path '{path}' crosses a scalar value")

    return current, segments[-1]


def _parse_existing_index(segment: str, values: list[Any], path: str) -> int:
    index = _parse_index(segment, path)
    if index >= len(values):
        raise ReviewerPatchApplicationError(f"list index in patch path '{path}' is out of range")
    return index


def _parse_insert_index(segment: str, values: list[Any], path: str) -> int:
    index = _parse_index(segment, path)
    if index > len(values):
        raise ReviewerPatchApplicationError(f"list insert index in patch path '{path}' is out of range")
    return index


def _parse_index(segment: str, path: str) -> int:
    try:
        index = int(segment)
    except ValueError as exc:
        raise ReviewerPatchApplicationError(f"patch path '{path}' contains a non-integer list index") from exc
    if index < 0:
        raise ReviewerPatchApplicationError(f"patch path '{path}' contains a negative list index")
    return index


def _json_pointer_segments(path: str) -> list[str]:
    return [segment.replace("~1", "/").replace("~0", "~") for segment in path.split("/")[1:]]
