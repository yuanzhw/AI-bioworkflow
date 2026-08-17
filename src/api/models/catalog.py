"""Catalog API DTOs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.catalog.schema import ExecutionVerificationStatus


TrustStatus = Literal["catalog-approved", "auto-validated", "experimental", "rejected"]


class RecipeInputDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    description: str | None = None


class RecipeScatterDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    item: str
    over: str


class RecipeStepDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    role: str
    optional: bool = False
    scatter: RecipeScatterDto | None = None
    allowed_tools: list[str] = Field(default_factory=list)


class RecipeDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    required_inputs: dict[str, RecipeInputDto] = Field(default_factory=dict)
    steps: list[RecipeStepDto] = Field(default_factory=list)


class RecipeListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipes: list[RecipeDto] = Field(default_factory=list)


class RuntimeDto(BaseModel):
    model_config = ConfigDict(extra="allow")

    docker: str | None = None
    cpu: int | None = None
    memory: str | None = None
    disks: str | None = None


class ExecutionVerificationDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ExecutionVerificationStatus
    evidence: list[str] = Field(default_factory=list)


class ToolInputDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    required: bool = True
    description: str | None = None


class ToolParamDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["Boolean", "Float", "Int", "String"]
    required: bool = False
    default: Any = None
    min: int | float | None = None
    max: int | float | None = None
    choices: list[Any] | None = None
    description: str | None = None


class ToolOutputDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    value: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)


class ToolDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    versions: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    inputs: dict[str, ToolInputDto] = Field(default_factory=dict)
    params: dict[str, ToolParamDto] = Field(default_factory=dict)
    outputs: dict[str, ToolOutputDto] = Field(default_factory=dict)
    runtime: RuntimeDto = Field(default_factory=RuntimeDto)
    trust_status: TrustStatus
    execution_verification: ExecutionVerificationDto


class ToolListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[ToolDto] = Field(default_factory=list)
