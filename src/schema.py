from __future__ import annotations

import copy
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
COMMAND_INTERPOLATION_PATTERN = re.compile(r"~\{([^}]*)\}")
EXPRESSION_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
WDL_BUILTIN_IDENTIFIERS = {
    "false",
    "length",
    "range",
    "sep",
    "true",
    "write_lines",
}

ExpressionValue = str | list[str]


class RuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    docker: str | None = None
    cpu: int | None = None
    memory: str | None = None
    disks: str | None = None


class OutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    value: str
    tags: list[str] = Field(default_factory=list)


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: dict[str, str] = Field(default_factory=dict)
    command: str
    outputs: dict[str, OutputSpec] = Field(default_factory=dict)
    runtime: RuntimeSpec = Field(default_factory=RuntimeSpec)

    @field_validator("inputs")
    @classmethod
    def validate_input_names(cls, value: dict[str, str]) -> dict[str, str]:
        _validate_mapping_keys(value, "task input")
        return value

    @field_validator("outputs")
    @classmethod
    def validate_output_names(cls, value: dict[str, OutputSpec]) -> dict[str, OutputSpec]:
        _validate_mapping_keys(value, "task output")
        return value


class CallSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["call"] = "call"
    id: str
    task: str
    inputs: dict[str, ExpressionValue] = Field(default_factory=dict)

    @field_validator("id", "task")
    @classmethod
    def validate_call_identifiers(cls, value: str) -> str:
        _validate_identifier(value, "call or task name")
        return value

    @field_validator("inputs")
    @classmethod
    def validate_call_input_names(cls, value: dict[str, ExpressionValue]) -> dict[str, ExpressionValue]:
        _validate_mapping_keys(value, "call input")
        return value


class ScatterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["scatter"] = "scatter"
    id: str
    item: str
    over: str
    body: list[WorkflowStepSpec] = Field(default_factory=list)

    @field_validator("id", "item")
    @classmethod
    def validate_scatter_identifiers(cls, value: str) -> str:
        _validate_identifier(value, "scatter identifier")
        return value


WorkflowStepSpec = Annotated[CallSpec | ScatterSpec, Field(discriminator="kind")]


WORKFLOW_CALLS_MISMATCH_MESSAGE = (
    "compatibility calls do not match canonical workflow steps"
)


class WorkflowCompatibilityError(ValueError):
    """Raised when legacy workflow.calls diverges from canonical workflow.steps."""


def flatten_workflow_calls(
    steps: list[CallSpec | ScatterSpec],
) -> list[CallSpec]:
    """Return canonical calls in workflow step traversal order."""
    calls: list[CallSpec] = []
    for step in steps:
        if isinstance(step, CallSpec):
            calls.append(step)
        else:
            calls.extend(flatten_workflow_calls(step.body))
    return calls


class WorkflowSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    inputs: dict[str, str] = Field(default_factory=dict)
    calls: list[CallSpec] = Field(default_factory=list)
    steps: list[WorkflowStepSpec] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_workflow_name(cls, value: str) -> str:
        _validate_identifier(value, "workflow name")
        return value

    @field_validator("inputs")
    @classmethod
    def validate_workflow_input_names(cls, value: dict[str, str]) -> dict[str, str]:
        _validate_mapping_keys(value, "workflow input")
        return value

    @field_validator("outputs")
    @classmethod
    def validate_workflow_output_names(cls, value: dict[str, str]) -> dict[str, str]:
        _validate_mapping_keys(value, "workflow output")
        return value

    @model_validator(mode="after")
    def normalize_compatibility_calls(self):
        calls_provided = "calls" in self.model_fields_set
        steps_provided = "steps" in self.model_fields_set

        if calls_provided and not steps_provided:
            self.steps = [call.model_copy(deep=True) for call in self.calls]

        canonical_calls = flatten_workflow_calls(self.steps)
        if calls_provided and steps_provided and self.calls != canonical_calls:
            raise WorkflowCompatibilityError(WORKFLOW_CALLS_MISMATCH_MESSAGE)

        self.calls = [call.model_copy(deep=True) for call in canonical_calls]
        return self


def compatibility_calls_match_steps(workflow: WorkflowSpec) -> bool:
    """Check that the legacy calls view is an exact snapshot of canonical steps."""
    return workflow.calls == flatten_workflow_calls(workflow.steps)


def ensure_compatibility_calls_match_steps(workflow: WorkflowSpec) -> None:
    if not compatibility_calls_match_steps(workflow):
        raise WorkflowCompatibilityError(WORKFLOW_CALLS_MISMATCH_MESSAGE)


def refresh_compatibility_calls(workflow: WorkflowSpec) -> None:
    """Regenerate the legacy calls view from canonical workflow steps."""
    workflow.calls = [
        call.model_copy(deep=True)
        for call in flatten_workflow_calls(workflow.steps)
    ]


class WorkflowIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    workflow: WorkflowSpec
    tasks: dict[str, TaskSpec]

    @field_validator("tasks")
    @classmethod
    def validate_task_names(cls, value: dict[str, TaskSpec]) -> dict[str, TaskSpec]:
        _validate_mapping_keys(value, "task")
        return value


def coerce_workflow_ir(data: WorkflowIR | dict[str, Any]) -> WorkflowIR:
    """Normalize supported user JSON shapes into the internal WorkflowIR."""
    if isinstance(data, WorkflowIR):
        ensure_compatibility_calls_match_steps(data.workflow)
        return data
    if not isinstance(data, dict):
        raise TypeError("workflow input must be a dictionary")

    if "workflow" in data and "tasks" in data:
        return WorkflowIR.model_validate(_normalize_ir_dict(data))

    if "workflow_name" in data and "tasks" in data:
        return WorkflowIR.model_validate(_legacy_to_ir_dict(data))

    raise ValueError(
        "unsupported workflow JSON: expected either {'workflow', 'tasks'} "
        "or legacy {'workflow_name', 'tasks'}"
    )


def extract_command_inputs(command: str) -> set[str]:
    inputs = set()
    for interpolation in COMMAND_INTERPOLATION_PATTERN.findall(command or ""):
        for identifier in EXPRESSION_IDENTIFIER_PATTERN.findall(interpolation):
            if identifier not in WDL_BUILTIN_IDENTIFIERS:
                inputs.add(identifier)
    return inputs


def _normalize_ir_dict(data: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(data)
    tasks = normalized.get("tasks", {})
    workflow = normalized.get("workflow", {})

    if isinstance(tasks, list):
        normalized["tasks"] = {
            task["name"]: _normalize_task_dict(task)
            for task in tasks
        }
    elif isinstance(tasks, dict):
        normalized["tasks"] = {
            task_name: _normalize_task_dict(task_data)
            for task_name, task_data in tasks.items()
        }

    if isinstance(workflow, dict):
        calls_provided = "calls" in workflow
        calls = workflow.get("calls", [])
        steps = workflow.get("steps")

        if steps is None:
            workflow["steps"] = [_normalize_call_step(call) for call in calls]
        else:
            workflow["steps"] = [_normalize_step_dict(step) for step in steps]

        canonical_calls = _flatten_call_step_dicts(workflow["steps"])
        if calls_provided:
            normalized_calls = [_normalize_call_step(call) for call in calls]
            if normalized_calls != canonical_calls:
                raise WorkflowCompatibilityError(WORKFLOW_CALLS_MISMATCH_MESSAGE)
        workflow["calls"] = canonical_calls

    return normalized


def _legacy_to_ir_dict(data: dict[str, Any]) -> dict[str, Any]:
    workflow_inputs = dict(data.get("inputs", {}))
    task_defs: dict[str, dict[str, Any]] = {}
    steps: list[dict[str, Any]] = []
    previous_task_outputs: dict[str, dict[str, str]] = {}

    for raw_task in data.get("tasks", []):
        task_name = raw_task["name"]
        call_inputs = dict(raw_task.get("inputs", {}))
        command = raw_task.get("command", "")

        if not call_inputs:
            call_inputs = {
                input_name: input_name
                for input_name in sorted(extract_command_inputs(command))
            }

        task_inputs = {
            input_name: _infer_source_type(source, workflow_inputs, previous_task_outputs)
            for input_name, source in call_inputs.items()
        }

        outputs = _normalize_outputs(raw_task.get("outputs", {}))
        task_defs[task_name] = {
            "inputs": task_inputs,
            "command": command,
            "outputs": outputs,
            "runtime": _normalize_runtime(raw_task),
        }
        steps.append(
            {
                "kind": "call",
                "id": task_name,
                "task": task_name,
                "inputs": call_inputs,
            }
        )
        previous_task_outputs[task_name] = {
            output_name: output_spec["type"]
            for output_name, output_spec in outputs.items()
        }

    workflow_outputs = dict(data.get("outputs", {}))
    if not workflow_outputs and steps:
        last_call_id = steps[-1]["id"]
        workflow_outputs = {
            output_name: f"{last_call_id}.{output_name}"
            for output_name in task_defs[last_call_id]["outputs"]
        }

    return {
        "version": "1.0",
        "workflow": {
            "name": data["workflow_name"],
            "inputs": workflow_inputs,
            "steps": steps,
            "outputs": workflow_outputs,
        },
        "tasks": task_defs,
    }


def _normalize_task_dict(task_data: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(task_data)
    normalized.pop("name", None)
    normalized["outputs"] = _normalize_outputs(normalized.get("outputs", {}))
    normalized["runtime"] = _normalize_runtime(normalized)
    normalized.pop("docker", None)
    return normalized


def _normalize_outputs(outputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized = {}
    for output_name, output_spec in outputs.items():
        if isinstance(output_spec, str):
            normalized[output_name] = {
                "type": output_spec,
                "value": _default_output_value(output_name, output_spec),
            }
        else:
            normalized[output_name] = output_spec
    return normalized


def _normalize_runtime(task_data: dict[str, Any]) -> dict[str, Any]:
    runtime = dict(task_data.get("runtime", {}))
    docker = task_data.get("docker")
    if docker and "docker" not in runtime:
        runtime["docker"] = docker
    return runtime


def _normalize_call_step(call: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(call)
    normalized.setdefault("kind", "call")
    normalized.setdefault("inputs", {})
    return normalized


def _normalize_step_dict(step: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(step)
    normalized.setdefault("kind", "call")

    if normalized["kind"] == "call":
        return _normalize_call_step(normalized)

    if normalized["kind"] == "scatter":
        normalized["body"] = [
            _normalize_step_dict(child)
            for child in normalized.get("body", [])
        ]
        return normalized

    return normalized


def _flatten_call_step_dicts(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls = []
    for step in steps:
        if step.get("kind", "call") == "call":
            calls.append(_normalize_call_step(step))
        elif step.get("kind") == "scatter":
            calls.extend(_flatten_call_step_dicts(step.get("body", [])))
    return calls


def _infer_source_type(
    source: str,
    workflow_inputs: dict[str, str],
    previous_task_outputs: dict[str, dict[str, str]],
) -> str:
    if source in workflow_inputs:
        return workflow_inputs[source]
    if "." in source:
        call_id, output_name = source.split(".", 1)
        return previous_task_outputs.get(call_id, {}).get(output_name, "String")
    if source.startswith('"') and source.endswith('"'):
        return "String"
    if source in {"true", "false"}:
        return "Boolean"
    if source.isdigit():
        return "Int"
    return "String"


def _default_output_value(output_name: str, output_type: str) -> str:
    base_type = output_type.rstrip("?")
    if base_type in {"File", "String"}:
        return f'"{output_name}"'
    if base_type == "Boolean":
        return "false"
    if base_type == "Float":
        return "0.0"
    if base_type == "Int":
        return "0"
    return output_name


def _validate_mapping_keys(value: dict[str, Any], label: str) -> None:
    for key in value:
        _validate_identifier(key, label)


def _validate_identifier(value: str, label: str) -> None:
    if not IDENTIFIER_PATTERN.match(value):
        raise ValueError(f"invalid {label}: {value!r}")
