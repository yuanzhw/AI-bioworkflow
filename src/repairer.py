import json
import re
from dataclasses import dataclass, field
from typing import Any

from src.schema import (
    IDENTIFIER_PATTERN,
    CallSpec,
    ExpressionValue,
    ScatterSpec,
    WorkflowIR,
    coerce_workflow_ir,
    refresh_compatibility_calls,
)


CALL_OUTPUT_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)$")
SAFE_LITERAL_PATTERN = re.compile(r"^[A-Za-z0-9_./-]+$")


@dataclass
class RepairReport:
    workflow_ir: WorkflowIR
    actions: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.actions)


def repair_workflow_ir(workflow_ir: WorkflowIR | dict[str, Any]) -> RepairReport:
    """Apply conservative, deterministic repairs to Workflow IR."""
    repaired = coerce_workflow_ir(workflow_ir).model_copy(deep=True)
    actions: list[str] = []

    _repair_call_order(repaired, actions)
    _repair_output_literals(repaired, actions)

    return RepairReport(workflow_ir=repaired, actions=actions)


def _repair_call_order(ir: WorkflowIR, actions: list[str]) -> None:
    repaired_steps, changed = _repair_step_order(list(ir.workflow.steps))
    if not changed:
        return

    ir.workflow.steps = repaired_steps
    refresh_compatibility_calls(ir.workflow)
    actions.append(
        "Reordered workflow steps to satisfy upstream output dependencies: "
        f"{' -> '.join(_step_labels(repaired_steps))}"
    )


def _repair_step_order(steps: list[CallSpec | ScatterSpec]) -> tuple[list[CallSpec | ScatterSpec], bool]:
    if not steps:
        return steps, False

    changed = False
    repaired_steps = []
    for step in steps:
        if isinstance(step, ScatterSpec):
            repaired_body, body_changed = _repair_step_order(list(step.body))
            if body_changed:
                step.body = repaired_body
                changed = True
        repaired_steps.append(step)

    if len(repaired_steps) < 2:
        return repaired_steps, changed

    produced_by_step = [_step_produced_calls(step) for step in repaired_steps]
    all_produced = set().union(*produced_by_step)
    dependencies_by_index = []
    for index, step in enumerate(repaired_steps):
        dependencies = _call_dependencies(_step_expressions(step), all_produced)
        dependencies -= produced_by_step[index]
        dependencies_by_index.append(dependencies)

    ordered_steps = []
    ordered_call_ids = set()
    remaining_indexes = list(range(len(repaired_steps)))

    while remaining_indexes:
        ready_index = next(
            (
                index
                for index in remaining_indexes
                if dependencies_by_index[index].issubset(ordered_call_ids)
            ),
            None,
        )
        if ready_index is None:
            return repaired_steps, changed

        ordered_steps.append(repaired_steps[ready_index])
        ordered_call_ids.update(produced_by_step[ready_index])
        remaining_indexes.remove(ready_index)

    if _step_labels(ordered_steps) != _step_labels(repaired_steps):
        changed = True
        repaired_steps = ordered_steps

    return repaired_steps, changed


def _call_dependencies(expressions, available_call_ids) -> set[str]:
    dependencies = set()
    for expression in expressions:
        match = CALL_OUTPUT_PATTERN.match(expression.strip())
        if match and match.group(1) in available_call_ids:
            dependencies.add(match.group(1))
    return dependencies


def _step_expressions(step: CallSpec | ScatterSpec) -> list[str]:
    if isinstance(step, CallSpec):
        return _flatten_expression_values(step.inputs.values())

    expressions = [step.over]
    for child in step.body:
        expressions.extend(_step_expressions(child))
    return expressions


def _flatten_expression_values(expressions) -> list[str]:
    flattened = []
    for expression in expressions:
        flattened.extend(_flatten_expression_value(expression))
    return flattened


def _flatten_expression_value(expression: ExpressionValue) -> list[str]:
    if isinstance(expression, list):
        return list(expression)
    return [expression]


def _step_produced_calls(step: CallSpec | ScatterSpec) -> set[str]:
    if isinstance(step, CallSpec):
        return {step.id}

    produced = set()
    for child in step.body:
        produced.update(_step_produced_calls(child))
    return produced


def _step_labels(steps: list[CallSpec | ScatterSpec]) -> list[str]:
    labels = []
    for step in steps:
        if isinstance(step, CallSpec):
            labels.append(step.id)
        else:
            labels.append(step.id)
    return labels


def _repair_output_literals(ir: WorkflowIR, actions: list[str]) -> None:
    for task_name, task in ir.tasks.items():
        task_input_names = set(task.inputs)

        for output_name, output in task.outputs.items():
            repaired_value = _repair_output_value(
                output_name=output_name,
                output_type=output.type,
                value=output.value,
                task_input_names=task_input_names,
            )
            if repaired_value != output.value:
                output.value = repaired_value
                actions.append(
                    f"Repaired task '{task_name}' output '{output_name}' value to {repaired_value}"
                )


def _repair_output_value(
    output_name: str,
    output_type: str,
    value: str,
    task_input_names: set[str],
) -> str:
    stripped = value.strip()
    base_type = output_type.strip().rstrip("?")

    if not stripped:
        return _default_output_value(output_name, base_type)

    if base_type not in {"File", "String"}:
        return stripped

    if _is_quoted(stripped) or _is_expression_like(stripped):
        return stripped

    if IDENTIFIER_PATTERN.match(stripped) and stripped in task_input_names:
        return stripped

    if SAFE_LITERAL_PATTERN.match(stripped):
        return json.dumps(stripped)

    return stripped


def _is_quoted(value: str) -> bool:
    return len(value) >= 2 and value[0] == '"' and value[-1] == '"'


def _is_expression_like(value: str) -> bool:
    return any(char in value for char in "()[]{}~+*?:<>=!|&")


def _default_output_value(output_name: str, base_type: str) -> str:
    if base_type in {"File", "String"}:
        return json.dumps(output_name)
    if base_type == "Boolean":
        return "false"
    if base_type == "Float":
        return "0.0"
    if base_type == "Int":
        return "0"
    return output_name
