"""Run event API DTOs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunEventType(StrEnum):
    RUN_CREATED = "run.created"
    NODE_STARTED = "node.started"
    NODE_COMPLETED = "node.completed"
    NODE_FAILED = "node.failed"
    ARTIFACT_UPDATED = "artifact.updated"
    REPAIR_PROPOSED = "repair.proposed"
    REPAIR_REJECTED = "repair.rejected"
    REPAIR_APPLIED = "repair.applied"
    VALIDATION_COMPLETED = "validation.completed"
    RUN_COMPLETED = "run.completed"


class RunEvent(BaseModel):
    """Persistable event envelope shared by SSE and run history."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    run_id: str
    sequence: int = Field(ge=1)
    type: RunEventType
    timestamp: datetime
    summary: str
    node: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
