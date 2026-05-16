import json
import os
import re
from typing import Any, Protocol

from langchain_deepseek import ChatDeepSeek
from pydantic import SecretStr

from src.catalog.loader import ToolCatalog, load_tool_catalog
from src.catalog.resolver import ToolCallPlan, resolve_tool_plan
from src.recipes.loader import RecipeCatalog, load_recipe_catalog


DEFAULT_PLANNER_MODEL = "deepseek-v4-pro"
JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class NaturalLanguagePlanningError(ValueError):
    pass


class PlannerLlm(Protocol):
    def invoke(self, input: Any, *args: Any, **kwargs: Any) -> Any:
        ...


def plan_from_natural_language(
    request: str,
    *,
    model: str = DEFAULT_PLANNER_MODEL,
    llm: PlannerLlm | None = None,
    tool_catalog: ToolCatalog | None = None,
    recipe_catalog: RecipeCatalog | None = None,
) -> dict[str, Any]:
    """Convert a natural-language workflow request into a Recipe Tool Plan."""
    if not request.strip():
        raise NaturalLanguagePlanningError("natural language request is empty")

    tool_catalog = tool_catalog or load_tool_catalog()
    recipe_catalog = recipe_catalog or load_recipe_catalog(tool_catalog=tool_catalog)
    planner_llm = llm if llm is not None else _make_planner_llm(model)

    prompt = build_planner_prompt(request, tool_catalog, recipe_catalog)
    response = planner_llm.invoke(prompt)
    raw_content = str(getattr(response, "content", response))
    plan = parse_json_object(raw_content)

    try:
        ToolCallPlan.model_validate(plan)
        resolve_tool_plan(plan, recipe_catalog, tool_catalog)
    except Exception as exc:
        raise NaturalLanguagePlanningError(f"LLM planner produced an invalid Recipe Tool Plan: {exc}") from exc

    return plan


def build_planner_prompt(
    request: str,
    tool_catalog: ToolCatalog,
    recipe_catalog: RecipeCatalog,
) -> str:
    catalog_context = {
        "recipes": [
            {
                "id": recipe.id,
                "name": recipe.name,
                "description": recipe.description,
                "required_inputs": {
                    input_name: spec.model_dump(exclude_none=True)
                    for input_name, spec in recipe.required_inputs.items()
                },
                "steps": [
                    {
                        "id": step.id,
                        "role": step.role,
                        "optional": step.optional,
                        "allowed_tools": step.allowed_tools,
                    }
                    for step in recipe.steps
                ],
            }
            for recipe in recipe_catalog.all()
        ],
        "tools": [
            {
                "id": tool.id,
                "version": tool.version,
                "description": tool.description,
                "inputs": {
                    input_name: spec.model_dump(exclude_none=True)
                    for input_name, spec in tool.inputs.items()
                },
                "params": {
                    param_name: spec.model_dump(exclude_none=True)
                    for param_name, spec in tool.params.items()
                },
                "outputs": {
                    output_name: spec.model_dump(exclude_none=True)
                    for output_name, spec in tool.outputs.items()
                },
            }
            for tool in tool_catalog.all()
        ],
    }

    return (
        "You are a bioinformatics workflow planner. Convert the user's natural-language "
        "request into a strict JSON Recipe Tool Plan for AI-bioworkflow.\n\n"
        "Rules:\n"
        "- Return JSON only. Do not include markdown or explanations.\n"
        "- Prefer an existing recipe from the catalog.\n"
        "- Use only tools and versions listed in the catalog.\n"
        "- Use workflow input names from the recipe required_inputs when possible.\n"
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


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = _extract_json_candidate(text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise NaturalLanguagePlanningError(f"LLM planner did not return valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise NaturalLanguagePlanningError("LLM planner JSON must be an object")
    return parsed


def _extract_json_candidate(text: str) -> str:
    stripped = text.strip()
    fenced = JSON_FENCE_PATTERN.search(stripped)
    if fenced:
        return fenced.group(1).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise NaturalLanguagePlanningError("LLM planner response does not contain a JSON object")
    return stripped[start : end + 1]


def _make_planner_llm(model: str) -> PlannerLlm:
    api_key_raw = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key_raw:
        raise NaturalLanguagePlanningError(
            "DEEPSEEK_API_KEY is required for natural language planning. "
            "Set it in .env or use --input with a structured JSON/YAML plan."
        )

    return ChatDeepSeek(
        model=model,
        api_key=SecretStr(api_key_raw),
        base_url="https://api.deepseek.com",
        temperature=0,
    )
