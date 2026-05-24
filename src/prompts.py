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
        "- Use only tools and versions listed in the catalog.\n"
        "- Use workflow input names from the recipe required_inputs when possible.\n"
        "- For per-sample scatter steps, connect tool inputs to the array workflow input names; "
        "the compiler will index them inside scatter.\n"
        "- Use call ids that are valid WDL identifiers.\n"
        "- Connect upstream tool outputs with call_id.output_name expressions.\n"
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
        f"{json.dumps(catalog_context, indent=2, ensure_ascii=False)}\n\n"
        "User request:\n"
        f"{request.strip()}\n"
    )
