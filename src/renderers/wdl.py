import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from src.analyzer import resolve_workflow_output_type
from src.schema import WorkflowIR, coerce_workflow_ir


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


def _format_wdl_literal(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _indent_command(command: str, spaces: int = 4) -> str:
    prefix = " " * spaces
    return "\n".join(f"{prefix}{line}" if line else "" for line in command.splitlines())
