import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from src.analyzer import resolve_workflow_output_type
from src.schema import CallSpec, ScatterSpec, WorkflowIR, coerce_workflow_ir


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
    return template.render(
        ir=ir,
        runtime_items=_runtime_items,
        workflow_steps=_render_workflow_steps(ir.workflow.steps),
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


def _render_workflow_steps(steps: list[CallSpec | ScatterSpec], indent: int = 2) -> str:
    rendered = []
    for step in steps:
        if isinstance(step, CallSpec):
            rendered.append(_render_call_step(step, indent))
        else:
            rendered.append(_render_scatter_step(step, indent))
    return "\n\n".join(rendered)


def _render_call_step(call: CallSpec, indent: int) -> str:
    prefix = " " * indent
    nested = " " * (indent + 2)
    input_prefix = " " * (indent + 4)
    alias = f" as {call.id}" if call.id != call.task else ""
    lines = [f"{prefix}call {call.task}{alias} {{"]

    if call.inputs:
        lines.append(f"{nested}input:")
        for index, (input_name, expression) in enumerate(call.inputs.items()):
            comma = "," if index < len(call.inputs) - 1 else ""
            lines.append(f"{input_prefix}{input_name} = {expression}{comma}")

    lines.append(f"{prefix}}}")
    return "\n".join(lines)


def _render_scatter_step(scatter: ScatterSpec, indent: int) -> str:
    prefix = " " * indent
    body = _render_workflow_steps(scatter.body, indent + 2)
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


def _format_wdl_literal(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _indent_command(command: str, spaces: int = 4) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" if line else "" for line in command.splitlines())
