import json
import re
from typing import Any

from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.catalog.loader import ToolCatalog
from src.catalog.schema import (
    ToolParamSpec,
    ToolSpec,
    validate_identifier,
    validate_mapping_keys,
    validate_value_range,
    validate_value_type,
)
from src.recipes.loader import RecipeCatalog
from src.recipes.schema import RecipeSpec
from src.schema import WorkflowIR


class PlannedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    step: str
    tool: str
    version: str
    inputs: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "step", "tool")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        validate_identifier(value, "planned tool call identifier")
        return value


class PlannedWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    recipe: str
    inputs: dict[str, str] = Field(default_factory=dict)
    tool_calls: list[PlannedToolCall] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)

    @field_validator("name", "recipe")
    @classmethod
    def validate_workflow_ids(cls, value: str) -> str:
        validate_identifier(value, "planned workflow identifier")
        return value

    @field_validator("inputs")
    @classmethod
    def validate_input_names(cls, value: dict[str, str]) -> dict[str, str]:
        validate_mapping_keys(value, "planned workflow input")
        return value

    @field_validator("outputs")
    @classmethod
    def validate_output_names(cls, value: dict[str, str]) -> dict[str, str]:
        validate_mapping_keys(value, "planned workflow output")
        return value

    @model_validator(mode="after")
    def validate_call_ids(self):
        seen_call_ids = set()
        for tool_call in self.tool_calls:
            if tool_call.id in seen_call_ids:
                raise ValueError(f"duplicate tool call id: {tool_call.id}")
            seen_call_ids.add(tool_call.id)
        return self


class ToolCallPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow: PlannedWorkflow


def resolve_tool_plan(
    plan_data: ToolCallPlan | dict[str, Any],
    recipe_catalog: RecipeCatalog,
    tool_catalog: ToolCatalog,
) -> WorkflowIR:
    plan = plan_data if isinstance(plan_data, ToolCallPlan) else ToolCallPlan.model_validate(plan_data)
    recipe = recipe_catalog.get(plan.workflow.recipe)
    validate_recipe_plan(plan, recipe)

    task_defs: dict[str, dict[str, Any]] = {}
    calls: list[dict[str, Any]] = []

    for tool_call in plan.workflow.tool_calls:
        step = recipe.step_by_id(tool_call.step)
        if tool_call.tool not in step.allowed_tools:
            raise ValueError(
                f"tool call '{tool_call.id}' uses tool '{tool_call.tool}', "
                f"which is not allowed for recipe step '{tool_call.step}'"
            )

        tool = tool_catalog.get(tool_call.tool, tool_call.version)
        task_name = _task_name_for_call(tool_call)
        task_inputs = _task_inputs_for_tool(tool)
        params = _resolve_params(tool_call, tool)
        command = _render_command(tool, tool_call, params)

        task_defs[task_name] = {
            "inputs": task_inputs,
            "command": command,
            "outputs": {
                output_name: output.model_dump(mode="json", exclude_none=True)
                for output_name, output in tool.outputs.items()
            },
            "runtime": tool.runtime.model_dump(mode="json", exclude_none=True),
        }

        calls.append(
            {
                "id": tool_call.id,
                "task": task_name,
                "inputs": {
                    **_resolve_inputs(tool_call, tool),
                    **{
                        param_name: _format_wdl_literal(param_value)
                        for param_name, param_value in params.items()
                    },
                },
            }
        )

    workflow_outputs = plan.workflow.outputs or _default_workflow_outputs(calls, task_defs)
    return WorkflowIR.model_validate(
        {
            "version": "1.0",
            "workflow": {
                "name": plan.workflow.name,
                "inputs": plan.workflow.inputs,
                "calls": calls,
                "outputs": workflow_outputs,
            },
            "tasks": task_defs,
        }
    )


def validate_recipe_plan(plan_data: ToolCallPlan | dict[str, Any], recipe: RecipeSpec) -> None:
    plan = plan_data if isinstance(plan_data, ToolCallPlan) else ToolCallPlan.model_validate(plan_data)
    if plan.workflow.recipe != recipe.id:
        raise ValueError(f"plan references recipe '{plan.workflow.recipe}', expected '{recipe.id}'")

    known_steps = {step.id for step in recipe.steps}
    required_steps = {step.id for step in recipe.steps if not step.optional}
    planned_steps = []
    for tool_call in plan.workflow.tool_calls:
        if tool_call.step not in known_steps:
            raise ValueError(f"tool call '{tool_call.id}' references unknown recipe step '{tool_call.step}'")
        planned_steps.append(tool_call.step)

    duplicate_steps = _duplicates(planned_steps)
    if duplicate_steps:
        joined = ", ".join(duplicate_steps)
        raise ValueError(f"duplicate tool calls for recipe step(s): {joined}")

    missing_steps = sorted(required_steps - set(planned_steps))
    if missing_steps:
        joined = ", ".join(missing_steps)
        raise ValueError(f"plan is missing required recipe step(s): {joined}")

    for input_name, spec in recipe.required_inputs.items():
        if input_name not in plan.workflow.inputs:
            raise ValueError(f"plan is missing required workflow input '{input_name}'")

        provided_type = plan.workflow.inputs[input_name]
        if not _types_compatible(spec.type, provided_type):
            raise ValueError(
                f"workflow input '{input_name}' expects {spec.type} "
                f"but received {provided_type}"
            )


def _task_inputs_for_tool(tool: ToolSpec) -> dict[str, str]:
    inputs = {}
    for input_name, input_spec in tool.inputs.items():
        input_type = input_spec.type
        if not input_spec.required and not input_type.endswith("?"):
            input_type = f"{input_type}?"
        inputs[input_name] = input_type

    for param_name, param_spec in tool.params.items():
        inputs[param_name] = param_spec.type

    return inputs


def _duplicates(values: list[str]) -> list[str]:
    seen = set()
    duplicates = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _types_compatible(expected: str, actual: str) -> bool:
    return expected.strip().rstrip("?") == actual.strip().rstrip("?")


def _resolve_inputs(tool_call: PlannedToolCall, tool: ToolSpec) -> dict[str, str]:
    provided = set(tool_call.inputs)
    expected = set(tool.inputs)

    for unexpected in sorted(provided - expected):
        raise ValueError(f"tool call '{tool_call.id}' provides unknown input '{unexpected}'")
    for input_name, spec in tool.inputs.items():
        if spec.required and input_name not in tool_call.inputs:
            raise ValueError(f"tool call '{tool_call.id}' is missing required input '{input_name}'")

    return dict(tool_call.inputs)


def _resolve_params(tool_call: PlannedToolCall, tool: ToolSpec) -> dict[str, Any]:
    provided = set(tool_call.params)
    expected = set(tool.params)

    for unexpected in sorted(provided - expected):
        raise ValueError(f"tool call '{tool_call.id}' provides unknown param '{unexpected}'")

    resolved = {}
    for param_name, spec in tool.params.items():
        if param_name in tool_call.params:
            value = tool_call.params[param_name]
        elif spec.default is not None:
            value = spec.default
        elif spec.required:
            raise ValueError(f"tool call '{tool_call.id}' is missing required param '{param_name}'")
        else:
            continue

        _validate_param_value(tool_call.id, param_name, value, spec)
        resolved[param_name] = value

    return resolved


def _validate_param_value(
    call_id: str,
    param_name: str,
    value: Any,
    spec: ToolParamSpec,
) -> None:
    try:
        validate_value_type(param_name, value, spec.type)
        validate_value_range(param_name, value, spec)
    except ValueError as exc:
        raise ValueError(f"tool call '{call_id}' invalid param '{param_name}': {exc}") from exc


def _render_command(
    tool: ToolSpec,
    tool_call: PlannedToolCall,
    params: dict[str, Any],
) -> str:
    env = Environment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)
    template = env.from_string(tool.command_template)
    context = {
        input_name: input_name in tool_call.inputs
        for input_name in tool.inputs
    }
    context.update(params)

    rendered = template.render(**context)
    return "\n".join(line.rstrip() for line in rendered.strip().splitlines() if line.strip())


def _default_workflow_outputs(
    calls: list[dict[str, Any]],
    task_defs: dict[str, dict[str, Any]],
) -> dict[str, str]:
    if not calls:
        return {}

    last_call = calls[-1]
    last_task = task_defs[last_call["task"]]
    return {
        output_name: f"{last_call['id']}.{output_name}"
        for output_name in last_task["outputs"]
    }


def _task_name_for_call(tool_call: PlannedToolCall) -> str:
    return _sanitize_identifier(f"{tool_call.tool}_{tool_call.id}")


def _sanitize_identifier(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not re.match(r"^[A-Za-z_]", sanitized):
        sanitized = f"task_{sanitized}"
    return sanitized


def _format_wdl_literal(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
