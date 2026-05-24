import json
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_deepseek import ChatDeepSeek
from pydantic import SecretStr

from src.catalog.loader import ToolCatalog, load_tool_catalog
from src.catalog.resolver import ToolCallPlan, resolve_tool_plan
from src.prompts import render_natural_language_planner_prompt
from src.recipes.loader import RecipeCatalog, load_recipe_catalog


DEFAULT_PLANNER_MODEL = "deepseek-v4-pro"
JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class NaturalLanguagePlanningError(ValueError):
    pass


class PlannerJsonError(NaturalLanguagePlanningError):
    pass


class PlannerSchemaError(NaturalLanguagePlanningError):
    pass


class PlannerCatalogError(NaturalLanguagePlanningError):
    pass


class PlannerLlm(Protocol):
    def invoke(self, input: Any, *args: Any, **kwargs: Any) -> Any:
        ...


@dataclass(frozen=True)
class NaturalLanguagePlanResult:
    plan: dict[str, Any]
    planner_prompt: str
    raw_response: str


def plan_from_natural_language(
    request: str,
    *,
    model: str = DEFAULT_PLANNER_MODEL,
    llm: PlannerLlm | None = None,
    tool_catalog: ToolCatalog | None = None,
    recipe_catalog: RecipeCatalog | None = None,
) -> dict[str, Any]:
    """Convert a natural-language workflow request into a Recipe Tool Plan."""
    return create_natural_language_plan(
        request,
        model=model,
        llm=llm,
        tool_catalog=tool_catalog,
        recipe_catalog=recipe_catalog,
    ).plan


def create_natural_language_plan(
    request: str,
    *,
    model: str = DEFAULT_PLANNER_MODEL,
    llm: PlannerLlm | None = None,
    tool_catalog: ToolCatalog | None = None,
    recipe_catalog: RecipeCatalog | None = None,
) -> NaturalLanguagePlanResult:
    """Convert a natural-language request and retain planner observability details."""
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
    except Exception as exc:
        raise PlannerSchemaError(f"LLM planner plan schema validation failed: {exc}") from exc

    try:
        resolve_tool_plan(plan, recipe_catalog, tool_catalog)
    except Exception as exc:
        raise PlannerCatalogError(f"LLM planner recipe/catalog validation failed: {exc}") from exc

    return NaturalLanguagePlanResult(
        plan=plan,
        planner_prompt=prompt,
        raw_response=raw_content,
    )


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
                        "scatter": step.scatter.model_dump(exclude_none=True) if step.scatter else None,
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

    return render_natural_language_planner_prompt(request, catalog_context)


def build_default_planner_prompt(request: str) -> str:
    tool_catalog = load_tool_catalog()
    recipe_catalog = load_recipe_catalog(tool_catalog=tool_catalog)
    return build_planner_prompt(request, tool_catalog, recipe_catalog)


def parse_json_object(text: str) -> dict[str, Any]:
    candidate = _extract_json_candidate(text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise PlannerJsonError(f"LLM planner JSON parsing failed: {exc}") from exc

    if not isinstance(parsed, dict):
        raise PlannerJsonError("LLM planner JSON must be an object")
    return parsed


def _extract_json_candidate(text: str) -> str:
    stripped = text.strip()
    fenced = JSON_FENCE_PATTERN.search(stripped)
    if fenced:
        return fenced.group(1).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise PlannerJsonError("LLM planner response does not contain a JSON object")
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
