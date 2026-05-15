from dataclasses import dataclass, field

from src.schema import IDENTIFIER_PATTERN, WorkflowIR, extract_command_inputs


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


def analyze_workflow_ir(ir: WorkflowIR) -> AnalysisReport:
    report = AnalysisReport()

    if not ir.tasks:
        report.errors.append("workflow IR must define at least one task")
    if not ir.workflow.calls:
        report.errors.append("workflow must contain at least one call")

    _analyze_tasks(ir, report)
    _analyze_calls(ir, report)
    _analyze_workflow_outputs(ir, report)

    return report


def resolve_workflow_output_type(ir: WorkflowIR, expression: str) -> str | None:
    call_by_id = {call.id: call for call in ir.workflow.calls}
    return _resolve_expression_type(ir, expression, call_by_id)


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


def _analyze_calls(ir: WorkflowIR, report: AnalysisReport) -> None:
    seen_calls = {}

    for call in ir.workflow.calls:
        if call.id in seen_calls:
            report.errors.append(f"duplicate call id '{call.id}'")
            continue

        task = ir.tasks.get(call.task)
        if task is None:
            report.errors.append(f"call '{call.id}' references unknown task '{call.task}'")
            continue

        expected_inputs = set(task.inputs)
        provided_inputs = set(call.inputs)

        for missing in sorted(expected_inputs - provided_inputs):
            report.errors.append(f"call '{call.id}' is missing input '{missing}'")
        for unexpected in sorted(provided_inputs - expected_inputs):
            report.errors.append(f"call '{call.id}' provides unknown input '{unexpected}'")

        for input_name, expression in call.inputs.items():
            if input_name not in task.inputs:
                continue

            source_type = _resolve_expression_type(ir, expression, seen_calls)
            target_type = task.inputs[input_name]

            if source_type is None:
                if "." in expression:
                    report.errors.append(
                        f"call '{call.id}' input '{input_name}' references unavailable output "
                        f"'{expression}'"
                    )
                elif _looks_like_unknown_identifier(expression):
                    report.errors.append(
                        f"call '{call.id}' input '{input_name}' references unknown value '{expression}'"
                    )
                continue

            if not _types_compatible(target_type, source_type):
                report.errors.append(
                    f"call '{call.id}' input '{input_name}' expects {target_type} "
                    f"but received {source_type} from '{expression}'"
                )

        seen_calls[call.id] = call


def _analyze_workflow_outputs(ir: WorkflowIR, report: AnalysisReport) -> None:
    call_by_id = {call.id: call for call in ir.workflow.calls}
    for output_name, expression in ir.workflow.outputs.items():
        output_type = _resolve_expression_type(ir, expression, call_by_id)
        if output_type is None:
            report.errors.append(
                f"workflow output '{output_name}' references unknown value '{expression}'"
            )


def _resolve_expression_type(
    ir: WorkflowIR,
    expression: str,
    available_calls: dict,
) -> str | None:
    expression = expression.strip()

    if expression in ir.workflow.inputs:
        return ir.workflow.inputs[expression]

    literal_type = _infer_literal_type(expression)
    if literal_type:
        return literal_type

    if "." in expression:
        call_id, output_name = expression.split(".", 1)
        call = available_calls.get(call_id)
        if call is None:
            return None
        task = ir.tasks.get(call.task)
        if task is None or output_name not in task.outputs:
            return None
        return task.outputs[output_name].type

    return None


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


def _looks_like_unknown_identifier(expression: str) -> bool:
    return bool(IDENTIFIER_PATTERN.match(expression))


def _types_compatible(expected: str, actual: str) -> bool:
    return _normalize_type(expected) == _normalize_type(actual)


def _normalize_type(value: str) -> str:
    return value.strip().rstrip("?")
