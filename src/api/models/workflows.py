"""Workflow API DTOs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from src.services.workflow_service import WorkflowCompilationResult


JsonObject = dict[str, Any]


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CompileWorkflowRequest(BaseModel):
    """Request body for deterministic Recipe Tool Plan / Workflow IR compilation."""

    model_config = ConfigDict(extra="forbid")

    payload: JsonObject = Field(
        description="Recipe Tool Plan, Workflow IR, or legacy workflow JSON to compile.",
    )
    check: bool = True

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: JsonObject) -> JsonObject:
        if not value:
            raise ValueError("payload must not be empty")
        return value


class NaturalLanguageRunRequest(BaseModel):
    """Request body for creating a workflow run from natural-language input."""

    model_config = ConfigDict(extra="forbid")

    request: str
    planner_model: str | None = None
    check: bool = True

    @field_validator("request")
    @classmethod
    def validate_request(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("request must not be empty")
        return normalized


class RunAcceptedResponse(BaseModel):
    """Initial response for async run-oriented endpoints."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus = RunStatus.CREATED
    events_url: str


class WorkflowArtifacts(BaseModel):
    """Compiled artifacts exposed to the web UI."""

    model_config = ConfigDict(extra="forbid")

    plan: JsonObject | None = None
    workflow_ir: JsonObject = Field(default_factory=dict)
    wdl: str = ""


class DiagnosticReport(BaseModel):
    """Analyzer, repairer, and checker diagnostics for one compile/run result."""

    model_config = ConfigDict(extra="forbid")

    analysis_errors: list[str] = Field(default_factory=list)
    analysis_warnings: list[str] = Field(default_factory=list)
    repair_actions: list[str] = Field(default_factory=list)
    validation_message: str = ""
    is_valid: bool = False
    succeeded: bool = False
    check_performed: bool = True


class RunDiagnosticSummary(BaseModel):
    """Small diagnostic counters for run list views."""

    model_config = ConfigDict(extra="forbid")

    analysis_error_count: int = Field(default=0, ge=0)
    analysis_warning_count: int = Field(default=0, ge=0)
    repair_action_count: int = Field(default=0, ge=0)
    check_performed: bool = True
    is_valid: bool = False


class RunSummary(BaseModel):
    """Compact run record for history list views."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    kind: str
    request_summary: str | None = None
    events_url: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    diagnostic_summary: RunDiagnosticSummary = Field(default_factory=RunDiagnosticSummary)


class RunListResponse(BaseModel):
    """Paginated response for persistent run history."""

    model_config = ConfigDict(extra="forbid")

    runs: list[RunSummary] = Field(default_factory=list)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    total: int = Field(ge=0)


class CompilationResultResponse(BaseModel):
    """Synchronous compilation response used before persistent run storage exists."""

    model_config = ConfigDict(extra="forbid")

    status: RunStatus
    artifacts: WorkflowArtifacts
    diagnostics: DiagnosticReport
    planner_prompt: str | None = None
    planner_raw_response: str | None = None

    @classmethod
    def from_service_result(cls, result: WorkflowCompilationResult) -> CompilationResultResponse:
        return cls(
            status=RunStatus.SUCCEEDED if result.succeeded else RunStatus.FAILED,
            artifacts=WorkflowArtifacts(
                plan=result.plan,
                workflow_ir=result.workflow_ir,
                wdl=result.wdl,
            ),
            diagnostics=DiagnosticReport(
                analysis_errors=result.analysis_errors,
                analysis_warnings=result.analysis_warnings,
                repair_actions=result.repair_actions,
                validation_message=result.validation_message,
                is_valid=result.is_valid,
                succeeded=result.succeeded,
                check_performed=result.check_performed,
            ),
            planner_prompt=result.planner_prompt,
            planner_raw_response=result.planner_raw_response,
        )


class WorkflowRunSnapshotResponse(BaseModel):
    """Persistable run snapshot shape for the future run detail endpoint."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RunStatus
    kind: str | None = None
    request: str | JsonObject | None = None
    events_url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    artifacts: WorkflowArtifacts = Field(default_factory=WorkflowArtifacts)
    diagnostics: DiagnosticReport = Field(default_factory=DiagnosticReport)
