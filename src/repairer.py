import json
import re
from dataclasses import dataclass, field
from typing import Any

from src.schema import IDENTIFIER_PATTERN, WorkflowIR, coerce_workflow_ir


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
    calls = list(ir.workflow.calls)
    if len(calls) < 2:
        return

    call_by_id = {call.id: call for call in calls}
    original_order = [call.id for call in calls]
    dependencies_by_call = {
        call.id: _call_dependencies(call.inputs.values(), call_by_id)
        for call in calls
    }

    ordered_calls = []
    ordered_ids = set()
    remaining_ids = list(original_order)

    while remaining_ids:
        ready_id = next(
            (
                call_id
                for call_id in remaining_ids
                if dependencies_by_call[call_id].issubset(ordered_ids)
            ),
            None,
        )
        if ready_id is None:
            return

        ordered_calls.append(call_by_id[ready_id])
        ordered_ids.add(ready_id)
        remaining_ids.remove(ready_id)

    repaired_order = [call.id for call in ordered_calls]
    if repaired_order != original_order:
        ir.workflow.calls = ordered_calls
        actions.append(
            "Reordered workflow calls to satisfy upstream output dependencies: "
            f"{' -> '.join(repaired_order)}"
        )


def _call_dependencies(expressions, call_by_id) -> set[str]:
    dependencies = set()
    for expression in expressions:
        match = CALL_OUTPUT_PATTERN.match(expression.strip())
        if match and match.group(1) in call_by_id:
            dependencies.add(match.group(1))
    return dependencies


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
