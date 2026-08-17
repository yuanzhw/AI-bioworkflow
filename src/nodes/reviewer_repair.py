from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage

from src.catalog.loader import ToolCatalog
from src.recipes.loader import RecipeCatalog
from src.reviewer_patcher import (
    ReviewerPatchApplicationError,
    apply_reviewer_patch,
)
from src.reviewer_provider import (
    DEFAULT_REVIEWER_MODEL,
    ReviewerProviderError,
    ReviewerProviderResponseError,
    ReviewerProviderUnavailableError,
    ReviewerRepairProvider,
    coerce_reviewer_repair_result,
    make_default_reviewer_provider,
)
from src.reviewer_request import (
    ReviewerRequestBuildError,
    build_reviewer_repair_request,
)
from src.reviewer_repair import (
    ReviewerFailureStage,
    ReviewerIRPatch,
    ReviewerPatchPolicyError,
    ReviewerRepairRequest,
    ReviewerRepairStatus,
)
from src.state import WorkflowState


ReviewerNode = Callable[[WorkflowState], dict[str, Any]]
ReviewerProviderFactory = Callable[[str], ReviewerRepairProvider]
DEFAULT_MAX_REVIEWER_ATTEMPTS = 1
logger = logging.getLogger(__name__)


def reviewer_repair_node(state: WorkflowState) -> dict[str, Any]:
    """Run the default-disabled Reviewer branch used by the Compiler Graph."""
    return make_reviewer_repair_node()(state)


def make_reviewer_repair_node(
    *,
    enabled: bool = False,
    failure_stage: ReviewerFailureStage = ReviewerFailureStage.ANALYZER,
    model: str = DEFAULT_REVIEWER_MODEL,
    provider: ReviewerRepairProvider | None = None,
    provider_factory: ReviewerProviderFactory = make_default_reviewer_provider,
    tool_catalog: ToolCatalog | None = None,
    recipe_catalog: RecipeCatalog | None = None,
    max_attempts: int = DEFAULT_MAX_REVIEWER_ATTEMPTS,
) -> ReviewerNode:
    """Create a Reviewer node with injectable provider and Catalog dependencies."""
    if max_attempts < 1:
        raise ValueError("Reviewer max_attempts must be at least 1.")

    def node(state: WorkflowState) -> dict[str, Any]:
        current_attempt_count = state.get("reviewer_attempt_count", 0)
        if current_attempt_count >= max_attempts:
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.NO_ACTION,
                diagnostics=[
                    f"Reviewer repair attempt budget exhausted ({max_attempts})."
                ],
                message=(
                    "Reviewer repair attempt budget is exhausted; "
                    "no model call was made."
                ),
                preserve_existing=True,
            )

        if not enabled:
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.NO_ACTION,
                diagnostics=["Reviewer repair is disabled."],
                message="Reviewer repair is disabled; no model call was made.",
            )

        try:
            resolved_provider = (
                provider if provider is not None else provider_factory(model)
            )
        except ReviewerProviderUnavailableError as exc:
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.NO_ACTION,
                diagnostics=[str(exc)],
                message="Reviewer repair is unavailable; no model call was made.",
            )
        except Exception as exc:
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.MODEL_ERROR,
                diagnostics=[
                    f"Reviewer provider setup failed with {exc.__class__.__name__}."
                ],
                message="Reviewer provider setup failed.",
            )

        try:
            request = build_reviewer_repair_request(
                state,
                failure_stage=failure_stage,
                tool_catalog=tool_catalog,
                recipe_catalog=recipe_catalog,
            )
        except ReviewerRequestBuildError as exc:
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.INVALID_REQUEST,
                rejection_reason=str(exc),
                diagnostics=[f"Reviewer request could not be constructed: {exc}"],
                message="Reviewer request construction failed.",
            )
        except Exception as exc:
            safe_error = (
                "Reviewer request construction failed with "
                f"{exc.__class__.__name__}."
            )
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.INVALID_REQUEST,
                rejection_reason=safe_error,
                diagnostics=[safe_error],
                message="Reviewer request construction failed unexpectedly.",
            )

        attempt_count = current_attempt_count + 1
        try:
            raw_result = resolved_provider.repair(request)
            result = coerce_reviewer_repair_result(raw_result)
        except ReviewerProviderResponseError as exc:
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.MODEL_ERROR,
                request=request,
                attempt_count=attempt_count,
                rejection_reason=str(exc),
                diagnostics=[str(exc)],
                message="Reviewer returned an invalid structured response.",
            )
        except ReviewerProviderError as exc:
            safe_error = (
                f"Reviewer provider failed with {exc.__class__.__name__}."
            )
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.MODEL_ERROR,
                request=request,
                attempt_count=attempt_count,
                rejection_reason=safe_error,
                diagnostics=[safe_error],
                message="Reviewer provider failed.",
            )
        except Exception as exc:
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.MODEL_ERROR,
                request=request,
                attempt_count=attempt_count,
                rejection_reason=(
                    f"Reviewer provider failed with {exc.__class__.__name__}."
                ),
                diagnostics=[
                    f"Reviewer provider failed with {exc.__class__.__name__}."
                ],
                message="Reviewer provider failed unexpectedly.",
            )

        if result.status != ReviewerRepairStatus.PATCH_PROPOSED:
            diagnostics = result.diagnostics or [
                f"Reviewer returned {result.status.value} without additional diagnostics."
            ]
            return _reviewer_update(
                state,
                status=result.status,
                request=request,
                attempt_count=attempt_count,
                rejection_reason=result.rejection_reason,
                diagnostics=diagnostics,
                message=f"Reviewer returned {result.status.value}.",
            )

        patch = result.patch
        if patch is None:
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.MODEL_ERROR,
                request=request,
                attempt_count=attempt_count,
                diagnostics=["Reviewer patch_proposed result did not include a patch."],
                message="Reviewer returned an invalid patch result.",
            )

        try:
            patched_ir = apply_reviewer_patch(
                request.workflow_ir,
                patch,
                catalog_context=request.catalog_context,
            )
        except ReviewerPatchPolicyError as exc:
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.POLICY_REJECTED,
                request=request,
                patch=patch,
                attempt_count=attempt_count,
                rejection_reason=str(exc),
                diagnostics=[*result.diagnostics, str(exc)],
                message="Reviewer patch was rejected by policy.",
            )
        except ReviewerPatchApplicationError as exc:
            return _reviewer_update(
                state,
                status=ReviewerRepairStatus.INVALID_REQUEST,
                request=request,
                patch=patch,
                attempt_count=attempt_count,
                rejection_reason=str(exc),
                diagnostics=[*result.diagnostics, str(exc)],
                message="Reviewer patch could not be applied to the current Workflow IR.",
            )

        logger.info("Reviewer patch was applied to a Workflow IR candidate.")
        return {
            **_reviewer_update(
                state,
                status=ReviewerRepairStatus.PATCH_PROPOSED,
                request=request,
                patch=patch,
                attempt_count=attempt_count,
                diagnostics=[
                    *result.diagnostics,
                    "Reviewer patch applied to Workflow IR candidate.",
                ],
                patch_applied=True,
                message="Reviewer patch was applied to a Workflow IR candidate.",
            ),
            "workflow_ir": patched_ir.model_dump(mode="json"),
            "analysis_errors": [],
            "analysis_warnings": [],
            "current_wdl": "",
            "validation_message": "",
            "is_valid": False,
        }

    return node


def _reviewer_update(
    state: WorkflowState,
    *,
    status: ReviewerRepairStatus,
    diagnostics: list[str],
    message: str,
    request: ReviewerRepairRequest | None = None,
    patch: ReviewerIRPatch | None = None,
    rejection_reason: str | None = None,
    attempt_count: int | None = None,
    patch_applied: bool = False,
    preserve_existing: bool = False,
) -> dict[str, Any]:
    request_payload = (
        request.model_dump(mode="json") if request is not None else None
    )
    patch_payload = patch.model_dump(mode="json") if patch is not None else None
    resolved_rejection_reason = rejection_reason
    resolved_diagnostics = diagnostics
    if preserve_existing:
        if request_payload is None:
            request_payload = state.get("reviewer_repair_request")
        if patch_payload is None:
            patch_payload = state.get("reviewer_ir_patch")
        if resolved_rejection_reason is None:
            resolved_rejection_reason = state.get("reviewer_rejection_reason")
        resolved_diagnostics = [
            *list(state.get("reviewer_diagnostics") or []),
            *diagnostics,
        ]

    return {
        "reviewer_attempt_count": (
            state.get("reviewer_attempt_count", 0)
            if attempt_count is None
            else attempt_count
        ),
        "reviewer_repair_status": status.value,
        "reviewer_repair_request": request_payload,
        "reviewer_ir_patch": patch_payload,
        "reviewer_rejection_reason": resolved_rejection_reason,
        "reviewer_diagnostics": resolved_diagnostics,
        "reviewer_patch_applied": patch_applied,
        "messages": [AIMessage(content=message)],
    }
