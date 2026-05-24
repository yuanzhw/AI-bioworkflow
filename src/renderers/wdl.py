import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from src.analyzer import AvailableCall, resolve_workflow_output_type
from src.analyzer import _array_inner_type, _resolve_expression_type
from src.schema import CallSpec, ExpressionValue, ScatterSpec, WorkflowIR, coerce_workflow_ir


TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_wdl(workflow_ir: WorkflowIR | dict[str, Any]) -> str:
    ir = coerce_workflow_ir(workflow_ir)
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=StrictUndefined,
    )
    env.filters["wdl_literal"] = _format_wdl_literal
    env.filters["indent_command"] = _indent_command

    template = env.get_template("workflow.wdl.j2")
    workflow_steps, _ = _render_workflow_steps(
        ir=ir,
        steps=ir.workflow.steps,
        available_calls={},
        variables=dict(ir.workflow.inputs),
    )
    return template.render(
        ir=ir,
        runtime_items=_runtime_items,
        workflow_steps=workflow_steps,
        workflow_outputs=_workflow_outputs(ir),
    ).strip() + "\n"


def _workflow_outputs(ir: WorkflowIR) -> list[dict[str, str]]:
    outputs = []
    for name, expression in ir.workflow.outputs.items():
        outputs.append(
            {
                "name": name,
                "type": resolve_workflow_output_type(ir, expression) or "String",
                "expression": expression,
            }
        )
    return outputs


def _runtime_items(runtime: Any) -> list[tuple[str, Any]]:
    values = runtime.model_dump(exclude_none=True)
    return sorted(values.items())


def _render_workflow_steps(
    ir: WorkflowIR,
    steps: list[CallSpec | ScatterSpec],
    indent: int = 2,
    available_calls: dict[str, AvailableCall] | None = None,
    variables: dict[str, str] | None = None,
) -> tuple[str, dict[str, AvailableCall]]:
    scoped_calls = dict(available_calls or {})
    scoped_variables = dict(variables or {})
    rendered = []
    for step in steps:
        if isinstance(step, CallSpec):
            rendered.append(_render_call_step(ir, step, indent, scoped_calls, scoped_variables))
            if step.task in ir.tasks:
                scoped_calls[step.id] = AvailableCall(task=step.task)
        else:
            rendered.append(_render_scatter_step(ir, step, indent, scoped_calls, scoped_variables))
            before_body = dict(scoped_calls)
            inner_after = _available_calls_after_rendered_steps(ir, step.body, before_body)
            for call_id, available in inner_after.items():
                if call_id not in before_body:
                    scoped_calls[call_id] = AvailableCall(
                        task=available.task,
                        array_depth=available.array_depth + 1,
                    )
    return "\n\n".join(rendered), scoped_calls


def _render_call_step(
    ir: WorkflowIR,
    call: CallSpec,
    indent: int,
    available_calls: dict[str, AvailableCall],
    variables: dict[str, str],
) -> str:
    prefix = " " * indent
    nested = " " * (indent + 2)
    input_prefix = " " * (indent + 4)
    alias = f" as {call.id}" if call.id != call.task else ""
    lines = [f"{prefix}call {call.task}{alias} {{"]

    if call.inputs:
        lines.append(f"{nested}input:")
        for index, (input_name, expression) in enumerate(call.inputs.items()):
            comma = "," if index < len(call.inputs) - 1 else ""
            rendered_expression = _render_expression(ir, expression, available_calls, variables)
            lines.append(f"{input_prefix}{input_name} = {rendered_expression}{comma}")

    lines.append(f"{prefix}}}")
    return "\n".join(lines)


def _render_scatter_step(
    ir: WorkflowIR,
    scatter: ScatterSpec,
    indent: int,
    available_calls: dict[str, AvailableCall],
    variables: dict[str, str],
) -> str:
    prefix = " " * indent
    inner_variables = dict(variables)
    inner_variables[scatter.item] = "Int"
    body, _ = _render_workflow_steps(
        ir=ir,
        steps=scatter.body,
        indent=indent + 2,
        available_calls=dict(available_calls),
        variables=inner_variables,
    )
    if body:
        return "\n".join(
            [
                f"{prefix}scatter ({scatter.item} in {scatter.over}) {{",
                body,
                f"{prefix}}}",
            ]
        )
    return "\n".join(
        [
            f"{prefix}scatter ({scatter.item} in {scatter.over}) {{",
            f"{prefix}}}",
        ]
    )


def _render_expression(
    ir: WorkflowIR,
    expression: ExpressionValue,
    available_calls: dict[str, AvailableCall],
    variables: dict[str, str],
) -> str:
    if isinstance(expression, str):
        return expression
    return _render_array_expression(ir, expression, available_calls, variables)


def _render_array_expression(
    ir: WorkflowIR,
    expressions: list[str],
    available_calls: dict[str, AvailableCall],
    variables: dict[str, str],
) -> str:
    if not expressions:
        return "[]"

    item_types = []
    for item in expressions:
        item_type = _resolve_expression_type(ir, item, available_calls, variables)
        item_types.append(item_type)

    if not any(item_type and _array_inner_type(item_type) is not None for item_type in item_types):
        return f"[{', '.join(expressions)}]"

    flattened_items = []
    for item, item_type in zip(expressions, item_types, strict=True):
        if item_type and _array_inner_type(item_type) is not None:
            flattened_items.append(item)
        else:
            flattened_items.append(f"[{item}]")
    return f"flatten([{', '.join(flattened_items)}])"


def _available_calls_after_rendered_steps(
    ir: WorkflowIR,
    steps: list[CallSpec | ScatterSpec],
    available_calls: dict[str, AvailableCall],
) -> dict[str, AvailableCall]:
    scoped_calls = dict(available_calls)
    for step in steps:
        if isinstance(step, CallSpec):
            if step.task in ir.tasks:
                scoped_calls[step.id] = AvailableCall(task=step.task)
            continue

        before_body = dict(scoped_calls)
        inner_after = _available_calls_after_rendered_steps(ir, step.body, before_body)
        for call_id, available in inner_after.items():
            if call_id not in before_body:
                scoped_calls[call_id] = AvailableCall(
                    task=available.task,
                    array_depth=available.array_depth + 1,
                )
    return scoped_calls


def _format_wdl_literal(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _indent_command(command: str, spaces: int = 4) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" if line else "" for line in command.splitlines())
