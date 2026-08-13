import json
from typing import Any


def render_natural_language_planner_prompt(
    request: str,
    catalog_context: dict[str, Any],
) -> str:
    return (
        "You are a bioinformatics workflow planner. Convert the user's natural-language "
        "request into a strict JSON Recipe Tool Plan for AI-bioworkflow.\n\n"
        "Rules:\n"
        "- Return JSON only. Do not include markdown or explanations.\n"
        "- Prefer an existing recipe from the catalog.\n"
        "- Treat the retrieved approved catalog context below as the primary recipe/tool candidates.\n"
        "- Prefer the retrieved tools and versions when they satisfy the requested workflow.\n"
        "- Do not invent recipes, tools, versions, inputs, params, outputs, or container images.\n"
        "- The system will validate the final plan against the complete approved catalog.\n"
        "- Use workflow input names from the recipe required_inputs when possible.\n"
        "- For per-sample scatter steps, connect tool inputs to the array workflow input names; "
        "the compiler will index them inside scatter.\n"
        "- Use call ids that are valid WDL identifiers.\n"
        "- Connect upstream tool outputs with call_id.output_name expressions.\n"
        "- For Array inputs, use JSON arrays of expressions like "
        '["qc.html_report", "qc.json_report"]; do not join expressions with +.\n'
        "- For MultiQC report_files, provide a JSON array of QC output expressions or omit it "
        "so tagged QC outputs can be collected automatically.\n"
        "- Include explicit workflow outputs requested by the user, or the final useful output.\n\n"
        "Output shape:\n"
        "{\n"
        '  "workflow": {\n'
        '    "name": "ValidWorkflowName",\n'
        '    "recipe": "recipe_id",\n'
        '    "inputs": {"input_name": "WDLType"},\n'
        '    "tool_calls": [\n'
        '      {"id": "call_id", "step": "recipe_step_id", "tool": "tool_id", '
        '"version": "tool_version", "inputs": {}, "params": {}}\n'
        "    ],\n"
        '    "outputs": {"output_name": "call_id.output_name"}\n'
        "  }\n"
        "}\n\n"
        "Catalog:\n"
        "Retrieved approved catalog context; this is a planner candidate set, "
        "not the final validation boundary:\n"
        f"{json.dumps(catalog_context, indent=2, ensure_ascii=False)}\n\n"
        "User request:\n"
        f"{request.strip()}\n"
    )


def render_reviewer_repair_prompt(request_payload: dict[str, Any]) -> str:
    """Render a bounded Workflow IR repair request for the Reviewer provider."""
    return (
        "You are a constrained reviewer for a deterministic bioinformatics workflow compiler.\n\n"
        "Rules:\n"
        "- Return one JSON object only. Do not include markdown or prose outside JSON.\n"
        "- Propose only Workflow IR patch actions allowed by the request constraints.\n"
        "- Never generate or edit final WDL text.\n"
        "- Never change tool or recipe catalogs, task commands, runtime settings, container "
        "images, trust fields, or resource sizing.\n"
        "- Use only recipe and tool references present in catalog_context.\n"
        "- Treat workflow.steps as canonical. workflow.calls is compatibility-only and must "
        "not be patched.\n"
        "- For add/replace include a non-null value and omit from_path.\n"
        "- For remove omit both value and from_path.\n"
        "- For move include from_path and omit value.\n"
        "- status must be one of patch_proposed, no_action, invalid_request, "
        "policy_rejected, or model_error.\n"
        "- Set patch to an object only when status is patch_proposed; otherwise set patch "
        "to null.\n"
        "- Set rejection_reason to a non-empty string only when status is policy_rejected; "
        "otherwise set rejection_reason to null.\n"
        "- If no safe patch is available, return status no_action with diagnostics.\n"
        "- Do not echo secrets, credentials, or unrelated request data.\n\n"
        "patch_proposed example:\n"
        "{\n"
        '  "status": "patch_proposed",\n'
        '  "patch": {\n'
        '    "summary": "short repair summary",\n'
        '    "actions": [\n'
        '      {"operation": "add", "path": "/workflow/outputs/example", '
        '"value": "call.output", '
        '"reason": "why this repairs a referenced diagnostic"}\n'
        "    ],\n"
        '    "diagnostic_references": [],\n'
        '    "catalog_references": [],\n'
        '    "confidence": 0.0\n'
        "  },\n"
        '  "rejection_reason": null,\n'
        '  "diagnostics": []\n'
        "}\n\n"
        "Structured Reviewer request:\n"
        f"{json.dumps(request_payload, indent=2, ensure_ascii=False)}\n"
    )
