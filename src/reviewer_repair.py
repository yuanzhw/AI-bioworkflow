from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.schema import WorkflowIR


class ReviewerFailureStage(StrEnum):
    """Compiler stage that produced diagnostics for Reviewer repair."""

    ANALYZER = "analyzer"
    # The current checker node is the WDL validation stage, not a separate validator.
    CHECKER = "checker"


class ReviewerPatchOperation(StrEnum):
    ADD = "add"
    REPLACE = "replace"
    REMOVE = "remove"
    MOVE = "move"


class ReviewerRepairStatus(StrEnum):
    PATCH_PROPOSED = "patch_proposed"
    NO_ACTION = "no_action"
    INVALID_REQUEST = "invalid_request"
    POLICY_REJECTED = "policy_rejected"
    MODEL_ERROR = "model_error"


class ApprovedToolMetadata(BaseModel):
    """Minimal approved tool context for the current workflow only."""

    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(min_length=1)
    version: str | None = None
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    trust_status: str = "catalog-approved"
    runtime_docker: str | None = None

    @field_validator("trust_status")
    @classmethod
    def validate_approved_trust_status(cls, value: str) -> str:
        if value != "catalog-approved":
            raise ValueError("Reviewer catalog context must contain only catalog-approved tools")
        return value


class ApprovedRecipeMetadata(BaseModel):
    """Minimal approved recipe context for the current workflow only."""

    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(min_length=1)
    step_ids: list[str] = Field(default_factory=list)
    tool_ids: list[str] = Field(default_factory=list)


class ApprovedCatalogContext(BaseModel):
    """Approved recipe/tool metadata already used by the current workflow."""

    model_config = ConfigDict(extra="forbid")

    recipes: list[ApprovedRecipeMetadata] = Field(default_factory=list)
    tools: list[ApprovedToolMetadata] = Field(default_factory=list)

    def approved_reference_ids(self) -> set[str]:
        references = set()
        for recipe in self.recipes:
            references.add(recipe.recipe_id)
        for tool in self.tools:
            references.add(tool.tool_id)
            if tool.version:
                references.add(f"{tool.tool_id}:{tool.version}")
        return references


def _default_allowed_operations() -> list[ReviewerPatchOperation]:
    return [
        ReviewerPatchOperation.ADD,
        ReviewerPatchOperation.REPLACE,
        ReviewerPatchOperation.REMOVE,
        ReviewerPatchOperation.MOVE,
    ]


def _default_allowed_path_descriptions() -> list[str]:
    return [
        "/workflow/steps ordering and call input wiring",
        "/workflow/calls compatibility call input wiring",
        "/workflow/outputs expressions",
        "/tasks/<task>/outputs/<output>/value literal repairs",
    ]


def _default_forbidden_path_descriptions() -> list[str]:
    return [
        "final WDL text",
        "Tool Catalog or Recipe Catalog data",
        "task command templates",
        "task runtime settings, including container images and resource fields",
        "resource sizing fields",
    ]


class ReviewerRepairConstraints(BaseModel):
    """Machine-readable policy summary included in Reviewer repair requests."""

    model_config = ConfigDict(extra="forbid")

    allowed_operations: list[ReviewerPatchOperation] = Field(
        default_factory=_default_allowed_operations,
        min_length=1,
    )
    allowed_path_descriptions: list[str] = Field(default_factory=_default_allowed_path_descriptions)
    forbidden_path_descriptions: list[str] = Field(default_factory=_default_forbidden_path_descriptions)
    notes: list[str] = Field(
        default_factory=lambda: [
            "Reviewer may only propose Workflow IR patches.",
            "Accepted patches must be revalidated by schema, Analyzer, Renderer, and Checker.",
        ]
    )


class ReviewerPatchAction(BaseModel):
    """One policy-checked patch action against Workflow IR."""

    model_config = ConfigDict(extra="forbid")

    operation: ReviewerPatchOperation
    path: str = Field(min_length=1)
    value: Any | None = None
    from_path: str | None = None
    reason: str = Field(min_length=1)

    @field_validator("path", "from_path")
    @classmethod
    def validate_json_pointer(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.startswith("/"):
            raise ValueError("patch paths must be absolute JSON pointers")
        return value

    @model_validator(mode="after")
    def validate_move_source(self) -> ReviewerPatchAction:
        if self.operation == ReviewerPatchOperation.MOVE and not self.from_path:
            raise ValueError("move patch actions require from_path")
        if self.operation != ReviewerPatchOperation.MOVE and self.from_path is not None:
            raise ValueError("from_path is only allowed for move patch actions")
        return self


class ReviewerIRPatch(BaseModel):
    """Structured patch proposed by Reviewer repair."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    actions: list[ReviewerPatchAction] = Field(min_length=1)
    diagnostic_references: list[str] = Field(default_factory=list)
    catalog_references: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ReviewerRepairRequest(BaseModel):
    """Structured request passed to Reviewer repair provider."""

    model_config = ConfigDict(extra="forbid")

    workflow_ir: WorkflowIR
    failure_stage: ReviewerFailureStage
    analysis_errors: list[str] = Field(default_factory=list)
    analysis_warnings: list[str] = Field(default_factory=list)
    validation_message: str = ""
    repair_history: list[str] = Field(default_factory=list)
    catalog_context: ApprovedCatalogContext = Field(default_factory=ApprovedCatalogContext)
    attempt_index: int = Field(ge=1)
    constraints: ReviewerRepairConstraints = Field(default_factory=ReviewerRepairConstraints)


class ReviewerRepairResult(BaseModel):
    """Parsed Reviewer repair provider result; raw model output is not persisted."""

    model_config = ConfigDict(extra="forbid")

    status: ReviewerRepairStatus
    patch: ReviewerIRPatch | None = None
    rejection_reason: str | None = None
    diagnostics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status_payload(self) -> ReviewerRepairResult:
        if self.status == ReviewerRepairStatus.PATCH_PROPOSED and self.patch is None:
            raise ValueError("patch_proposed results must include a parsed patch")
        if self.status == ReviewerRepairStatus.POLICY_REJECTED and not self.rejection_reason:
            raise ValueError("policy_rejected results must include a rejection_reason")
        return self


class ReviewerPatchPolicyError(ValueError):
    """Raised when a Reviewer patch attempts to cross the P2 policy boundary."""


_TASK_OUTPUT_VALUE_PATTERN = re.compile(r"^/tasks/[^/]+/outputs/[^/]+/value$")
_FORBIDDEN_TOP_LEVEL_SEGMENTS = {
    "catalog",
    "current_wdl",
    "final_wdl",
    "generated_wdl",
    "recipe_catalog",
    "recipes",
    "tool_catalog",
    "tools",
    "wdl",
}
_RESOURCE_FIELD_SEGMENTS = {
    "cpu",
    "disks",
    "gpu",
    "memory",
    "preemptible",
}


def validate_reviewer_patch_policy(
    patch: ReviewerIRPatch,
    catalog_context: ApprovedCatalogContext | None = None,
) -> ReviewerIRPatch:
    """Validate P2 Reviewer patch boundaries without applying the patch."""

    violations: list[str] = []
    for action in patch.actions:
        violations.extend(_validate_action_policy(action))

    if patch.catalog_references and catalog_context is None:
        violations.append("catalog_references require approved current-workflow catalog_context")
    elif catalog_context is not None:
        allowed_references = catalog_context.approved_reference_ids()
        for reference in patch.catalog_references:
            if reference not in allowed_references:
                violations.append(
                    f"catalog reference '{reference}' is not in the approved current-workflow context"
                )

    if violations:
        raise ReviewerPatchPolicyError("; ".join(violations))
    return patch


def _validate_action_policy(action: ReviewerPatchAction) -> list[str]:
    violations = []
    if action.operation == ReviewerPatchOperation.MOVE:
        violations.extend(_validate_move_policy(action))

    for label, path in _iter_action_paths(action):
        if _is_forbidden_path(path):
            violations.append(f"{label} path '{path}' crosses a forbidden Reviewer repair boundary")
            continue
        if not _is_allowed_path(path, action.operation):
            violations.append(f"{label} path '{path}' is outside the P2 Reviewer patch allowlist")
    return violations


def _validate_move_policy(action: ReviewerPatchAction) -> list[str]:
    source_collection = _workflow_step_or_call_collection(action.from_path or "")
    target_collection = _workflow_step_or_call_collection(action.path)
    if source_collection is None or target_collection is None:
        return []
    if source_collection != target_collection:
        return [
            "move patch actions must stay within the same workflow steps or calls collection"
        ]
    return []


def _iter_action_paths(action: ReviewerPatchAction) -> list[tuple[str, str]]:
    paths = [("target", action.path)]
    if action.from_path is not None:
        paths.append(("source", action.from_path))
    return paths


def _is_allowed_path(path: str, operation: ReviewerPatchOperation) -> bool:
    if operation == ReviewerPatchOperation.MOVE:
        return _is_workflow_step_or_call_path(path)

    if _is_workflow_output_path(path):
        return True

    if _TASK_OUTPUT_VALUE_PATTERN.match(path):
        return True

    if _is_call_input_path(path):
        return True

    return False


def _is_call_input_path(path: str) -> bool:
    return bool(re.match(r"^/workflow/(steps|calls)/[0-9]+/inputs/[^/]+$", path))


def _is_workflow_output_path(path: str) -> bool:
    return bool(re.match(r"^/workflow/outputs/[A-Za-z_][A-Za-z0-9_]*$", path))


def _is_workflow_step_or_call_path(path: str) -> bool:
    return _workflow_step_or_call_collection(path) is not None


def _workflow_step_or_call_collection(path: str) -> str | None:
    match = re.match(r"^/workflow/(steps|calls)/[0-9]+$", path)
    if match is None:
        return None
    return match.group(1)


def _is_forbidden_path(path: str) -> bool:
    segments = _json_pointer_segments(path)
    if not segments:
        return True

    if segments[0] in _FORBIDDEN_TOP_LEVEL_SEGMENTS:
        return True

    if len(segments) >= 3 and segments[0] == "tasks" and segments[2] in {"command", "runtime"}:
        return True

    for index, segment in enumerate(segments):
        previous = segments[index - 1] if index else ""
        if segment in _RESOURCE_FIELD_SEGMENTS and previous in {"resources", "runtime"}:
            return True

    return False


def _json_pointer_segments(path: str) -> list[str]:
    return [segment.replace("~1", "/").replace("~0", "~") for segment in path.split("/")[1:]]
