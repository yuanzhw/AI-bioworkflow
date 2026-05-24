import re
from dataclasses import dataclass, field

from src.schema import (
    IDENTIFIER_PATTERN,
    CallSpec,
    ExpressionValue,
    ScatterSpec,
    WorkflowIR,
    extract_command_inputs,
)


INDEX_EXPRESSION_PATTERN = re.compile(r"^(.+)\[([^\[\]]+)\]$")
LENGTH_EXPRESSION_PATTERN = re.compile(r"^length\((.+)\)$")
RANGE_EXPRESSION_PATTERN = re.compile(r"^range\((.+)\)$")


@dataclass
class AnalysisReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class AvailableCall:
    task: str
    array_depth: int = 0


def analyze_workflow_ir(ir: WorkflowIR) -> AnalysisReport:
    report = AnalysisReport()

    if not ir.tasks:
        report.errors.append("workflow IR must define at least one task")
    if not ir.workflow.steps:
        report.errors.append("workflow must contain at least one step")

    _analyze_tasks(ir, report)
    available_calls = _analyze_steps(
        ir=ir,
        steps=ir.workflow.steps,
        report=report,
        available_calls={},
        variables=dict(ir.workflow.inputs),
        seen_call_ids=set(),
    )
    _analyze_workflow_outputs(ir, report, available_calls)

    return report


def resolve_workflow_output_type(ir: WorkflowIR, expression: str) -> str | None:
    return _resolve_expression_type(
        ir=ir,
        expression=expression,
        available_calls=_available_calls_after_steps(ir, ir.workflow.steps),
        variables=dict(ir.workflow.inputs),
    )


def _analyze_tasks(ir: WorkflowIR, report: AnalysisReport) -> None:
    for task_name, task in ir.tasks.items():
        placeholders = extract_command_inputs(task.command)
        for placeholder in sorted(placeholders):
            if placeholder not in task.inputs:
                report.errors.append(
                    f"task '{task_name}' command references '~{{{placeholder}}}' "
                    "but the input is not declared"
                )

        if not task.outputs:
            report.warnings.append(f"task '{task_name}' does not declare outputs")

        for output_name, output_spec in task.outputs.items():
            if not output_spec.type:
                report.errors.append(f"task '{task_name}' output '{output_name}' has empty type")
            if not output_spec.value:
                report.errors.append(f"task '{task_name}' output '{output_name}' has empty value")


def _analyze_steps(
    ir: WorkflowIR,
    steps: list[CallSpec | ScatterSpec],
    report: AnalysisReport,
    available_calls: dict[str, AvailableCall],
    variables: dict[str, str],
    seen_call_ids: set[str],
) -> dict[str, AvailableCall]:
    scoped_calls = dict(available_calls)

    for step in steps:
        if isinstance(step, CallSpec):
            if _analyze_call(ir, step, report, scoped_calls, variables, seen_call_ids):
                scoped_calls[step.id] = AvailableCall(task=step.task)
            continue

        if not step.body:
            report.errors.append(f"scatter '{step.id}' must contain at least one step")

        over_type = _resolve_expression_type(ir, step.over, scoped_calls, variables)
        if over_type is None:
            report.errors.append(f"scatter '{step.id}' iterates over unknown value '{step.over}'")
        elif _array_inner_type(over_type) is None:
            report.errors.append(f"scatter '{step.id}' expects an Array expression but received {over_type}")

        inner_variables = dict(variables)
        inner_variables[step.item] = "Int"
        before_body = dict(scoped_calls)
        inner_after = _analyze_steps(
            ir=ir,
            steps=step.body,
            report=report,
            available_calls=before_body,
            variables=inner_variables,
            seen_call_ids=seen_call_ids,
        )

        for call_id, available in inner_after.items():
            if call_id not in before_body:
                scoped_calls[call_id] = AvailableCall(
                    task=available.task,
                    array_depth=available.array_depth + 1,
                )

    return scoped_calls


def _analyze_call(
    ir: WorkflowIR,
    call: CallSpec,
    report: AnalysisReport,
    available_calls: dict[str, AvailableCall],
    variables: dict[str, str],
    seen_call_ids: set[str],
) -> bool:
    if call.id in seen_call_ids:
        report.errors.append(f"duplicate call id '{call.id}'")
        return False
    seen_call_ids.add(call.id)

    task = ir.tasks.get(call.task)
    if task is None:
        report.errors.append(f"call '{call.id}' references unknown task '{call.task}'")
        return False

    expected_inputs = {
        input_name
        for input_name, input_type in task.inputs.items()
        if not _is_optional_type(input_type)
    }
    declared_inputs = set(task.inputs)
    provided_inputs = set(call.inputs)

    for missing in sorted(expected_inputs - provided_inputs):
        report.errors.append(f"call '{call.id}' is missing input '{missing}'")
    for unexpected in sorted(provided_inputs - declared_inputs):
        report.errors.append(f"call '{call.id}' provides unknown input '{unexpected}'")

    for input_name, expression in call.inputs.items():
        if input_name not in task.inputs:
            continue

        source_type = _resolve_expression_type(ir, expression, available_calls, variables)
        target_type = task.inputs[input_name]

        if source_type is None:
            if isinstance(expression, list):
                report.errors.append(
                    f"call '{call.id}' input '{input_name}' has invalid array expression "
                    f"'{_format_expression(expression)}'"
                )
            elif "." in expression:
                report.errors.append(
                    f"call '{call.id}' input '{input_name}' references unavailable output "
                    f"'{expression}'"
                )
            elif _looks_like_unknown_expression(expression):
                report.errors.append(
                    f"call '{call.id}' input '{input_name}' references unknown value '{expression}'"
                )
            continue

        if not _types_compatible(target_type, source_type):
            report.errors.append(
                f"call '{call.id}' input '{input_name}' expects {target_type} "
                f"but received {source_type} from '{_format_expression(expression)}'"
            )

    return True


def _analyze_workflow_outputs(
    ir: WorkflowIR,
    report: AnalysisReport,
    available_calls: dict[str, AvailableCall],
) -> None:
    for output_name, expression in ir.workflow.outputs.items():
        output_type = _resolve_expression_type(ir, expression, available_calls, dict(ir.workflow.inputs))
        if output_type is None:
            report.errors.append(
                f"workflow output '{output_name}' references unknown value '{expression}'"
            )


def _resolve_expression_type(
    ir: WorkflowIR,
    expression: ExpressionValue,
    available_calls: dict[str, AvailableCall],
    variables: dict[str, str],
) -> str | None:
    if isinstance(expression, list):
        return _resolve_array_expression_type(ir, expression, available_calls, variables)

    expression = expression.strip()

    if expression in variables:
        return variables[expression]

    literal_type = _infer_literal_type(expression)
    if literal_type:
        return literal_type

    index_match = INDEX_EXPRESSION_PATTERN.match(expression)
    if index_match:
        source_type = _resolve_expression_type(ir, index_match.group(1).strip(), available_calls, variables)
        index_type = _resolve_expression_type(ir, index_match.group(2).strip(), available_calls, variables)
        inner_type = _array_inner_type(source_type or "")
        if inner_type and index_type == "Int":
            return inner_type
        return None

    length_match = LENGTH_EXPRESSION_PATTERN.match(expression)
    if length_match:
        source_type = _resolve_expression_type(ir, length_match.group(1).strip(), available_calls, variables)
        if source_type and (_array_inner_type(source_type) is not None or _normalize_type(source_type) == "String"):
            return "Int"
        return None

    range_match = RANGE_EXPRESSION_PATTERN.match(expression)
    if range_match:
        source_type = _resolve_expression_type(ir, range_match.group(1).strip(), available_calls, variables)
        if source_type == "Int":
            return "Array[Int]"
        return None

    if "." in expression:
        call_id, output_name = expression.split(".", 1)
        available = available_calls.get(call_id)
        if available is None:
            return None
        task = ir.tasks.get(available.task)
        if task is None or output_name not in task.outputs:
            return None
        return _wrap_array_type(task.outputs[output_name].type, available.array_depth)

    return None


def _resolve_array_expression_type(
    ir: WorkflowIR,
    expressions: list[str],
    available_calls: dict[str, AvailableCall],
    variables: dict[str, str],
) -> str | None:
    if not expressions:
        return None

    element_type: str | None = None
    for item in expressions:
        item_type = _resolve_expression_type(ir, item, available_calls, variables)
        if item_type is None:
            return None

        item_inner_type = _array_inner_type(item_type)
        candidate_type = _normalize_type(item_inner_type or item_type)
        if element_type is None:
            element_type = candidate_type
        elif element_type != candidate_type:
            return None

    return f"Array[{element_type}]"


def _available_calls_after_steps(
    ir: WorkflowIR,
    steps: list[CallSpec | ScatterSpec],
    available_calls: dict[str, AvailableCall] | None = None,
) -> dict[str, AvailableCall]:
    scoped_calls = dict(available_calls or {})
    for step in steps:
        if isinstance(step, CallSpec):
            if step.task in ir.tasks:
                scoped_calls[step.id] = AvailableCall(task=step.task)
            continue

        before_body = dict(scoped_calls)
        inner_after = _available_calls_after_steps(ir, step.body, before_body)
        for call_id, available in inner_after.items():
            if call_id not in before_body:
                scoped_calls[call_id] = AvailableCall(
                    task=available.task,
                    array_depth=available.array_depth + 1,
                )
    return scoped_calls


def _infer_literal_type(expression: str) -> str | None:
    if expression.startswith('"') and expression.endswith('"'):
        return "String"
    if expression in {"true", "false"}:
        return "Boolean"
    if expression.isdigit() or (expression.startswith("-") and expression[1:].isdigit()):
        return "Int"
    try:
        float(expression)
    except ValueError:
        return None
    return "Float"


def _looks_like_unknown_expression(expression: str) -> bool:
    expression = expression.strip()
    if IDENTIFIER_PATTERN.match(expression):
        return True
    return INDEX_EXPRESSION_PATTERN.match(expression) is not None


def _format_expression(expression: ExpressionValue) -> str:
    if isinstance(expression, list):
        return "[" + ", ".join(expression) + "]"
    return expression


def _types_compatible(expected: str, actual: str) -> bool:
    return _normalize_type(expected) == _normalize_type(actual)


def _normalize_type(value: str) -> str:
    return value.strip().rstrip("?")


def _array_inner_type(value: str) -> str | None:
    normalized = _normalize_type(value)
    if not normalized.startswith("Array[") or not normalized.endswith("]"):
        return None
    return normalized[len("Array["):-1]


def _wrap_array_type(value: str, depth: int) -> str:
    wrapped = _normalize_type(value)
    for _ in range(depth):
        wrapped = f"Array[{wrapped}]"
    return wrapped


def _is_optional_type(value: str) -> bool:
    return value.strip().endswith("?")
