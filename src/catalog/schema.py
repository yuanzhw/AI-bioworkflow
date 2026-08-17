from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.schema import IDENTIFIER_PATTERN, RuntimeSpec, extract_command_inputs


WDL_PRIMITIVE_TYPES = {"Boolean", "File", "Float", "Int", "String"}
ExecutionVerificationStatus = Literal["unverified", "smoke-tested", "e2e-validated"]


class ExecutionVerificationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ExecutionVerificationStatus
    evidence: list[str] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def validate_evidence(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            evidence = item.strip()
            if not evidence:
                raise ValueError("execution verification evidence must not be empty")
            if evidence in normalized:
                raise ValueError("execution verification evidence must be unique")
            normalized.append(evidence)
        return normalized

    @model_validator(mode="after")
    def validate_status_evidence(self):
        if self.status == "unverified" and self.evidence:
            raise ValueError("unverified tools must not declare execution verification evidence")
        if self.status != "unverified" and not self.evidence:
            raise ValueError(f"{self.status} tools must declare execution verification evidence")
        return self


class ToolInputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    required: bool = True
    description: str | None = None


class ToolParamSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["Boolean", "Float", "Int", "String"]
    required: bool = False
    default: Any = None
    min: int | float | None = None
    max: int | float | None = None
    choices: list[Any] | None = None
    description: str | None = None

    @model_validator(mode="after")
    def validate_default(self):
        if self.default is not None:
            validate_value_type("default", self.default, self.type)
            validate_value_range("default", self.default, self)
        return self


class ToolOutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    value: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        for tag in value:
            validate_identifier(tag, "tool output tag")
        return value


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    execution_verification: ExecutionVerificationSpec
    inputs: dict[str, ToolInputSpec] = Field(default_factory=dict)
    params: dict[str, ToolParamSpec] = Field(default_factory=dict)
    outputs: dict[str, ToolOutputSpec] = Field(default_factory=dict)
    command_template: str
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        validate_identifier(value, "tool id")
        return value

    @field_validator("inputs")
    @classmethod
    def validate_input_names(cls, value: dict[str, ToolInputSpec]) -> dict[str, ToolInputSpec]:
        validate_mapping_keys(value, "tool input")
        return value

    @field_validator("params")
    @classmethod
    def validate_param_names(cls, value: dict[str, ToolParamSpec]) -> dict[str, ToolParamSpec]:
        validate_mapping_keys(value, "tool param")
        return value

    @field_validator("outputs")
    @classmethod
    def validate_output_names(cls, value: dict[str, ToolOutputSpec]) -> dict[str, ToolOutputSpec]:
        validate_mapping_keys(value, "tool output")
        return value

    @model_validator(mode="after")
    def validate_tool_spec(self):
        if not self.runtime.docker:
            raise ValueError(f"tool '{self.id}@{self.version}' must define runtime.docker")

        duplicate_names = set(self.inputs).intersection(self.params)
        if duplicate_names:
            joined = ", ".join(sorted(duplicate_names))
            raise ValueError(f"tool '{self.id}' has duplicate input/param names: {joined}")

        known_variables = set(self.inputs) | set(self.params)
        for variable in sorted(extract_command_inputs(self.command_template) - known_variables):
            raise ValueError(
                f"tool '{self.id}' command_template references unknown variable '{variable}'"
            )
        return self


def validate_identifier(value: str, label: str) -> None:
    if not IDENTIFIER_PATTERN.match(value):
        raise ValueError(f"invalid {label}: {value!r}")


def validate_mapping_keys(value: dict[str, Any], label: str) -> None:
    for key in value:
        validate_identifier(key, label)


def validate_value_type(label: str, value: Any, expected_type: str) -> None:
    if expected_type == "Boolean" and not isinstance(value, bool):
        raise ValueError(f"{label} must be Boolean")
    if expected_type == "Float" and (not isinstance(value, int | float) or isinstance(value, bool)):
        raise ValueError(f"{label} must be Float")
    if expected_type == "Int" and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValueError(f"{label} must be Int")
    if expected_type == "String" and not isinstance(value, str):
        raise ValueError(f"{label} must be String")


def validate_value_range(label: str, value: Any, spec: ToolParamSpec) -> None:
    if spec.choices is not None and value not in spec.choices:
        raise ValueError(f"{label} must be one of {spec.choices}")
    if isinstance(value, int | float) and spec.min is not None and value < spec.min:
        raise ValueError(f"{label} must be >= {spec.min}")
    if isinstance(value, int | float) and spec.max is not None and value > spec.max:
        raise ValueError(f"{label} must be <= {spec.max}")
