import json
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_deepseek import ChatDeepSeek
from pydantic import SecretStr

from src.analyzer import analyze_workflow_ir
from src.catalog.loader import ToolCatalog, load_tool_catalog
from src.catalog.retriever import CATALOG_APPROVED_TRUST_STATUS, retrieve_catalog_context
from src.catalog.resolver import ToolCallPlan, resolve_tool_plan
from src.catalog.schema import ToolSpec
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
    catalog_retrieval: dict[str, Any]


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
    catalog_retrieval: dict[str, Any] | None = None,
) -> NaturalLanguagePlanResult:
    """Convert a natural-language request and retain planner observability details."""
    if not request.strip():
        raise NaturalLanguagePlanningError("natural language request is empty")

    tool_catalog = tool_catalog or load_tool_catalog()
    recipe_catalog = recipe_catalog or load_recipe_catalog(tool_catalog=tool_catalog)
    planner_llm = llm if llm is not None else _make_planner_llm(model)

    if catalog_retrieval is None:
        catalog_retrieval = retrieve_catalog_context(request, tool_catalog, recipe_catalog)
    prompt = build_planner_prompt(
        request,
        tool_catalog,
        recipe_catalog,
        catalog_retrieval=catalog_retrieval,
    )
    response = planner_llm.invoke(prompt)
    raw_content = str(getattr(response, "content", response))
    plan = parse_json_object(raw_content)

    try:
        ToolCallPlan.model_validate(plan)
    except Exception as exc:
        raise PlannerSchemaError(f"LLM planner plan schema validation failed: {exc}") from exc

    try:
        workflow_ir = resolve_tool_plan(plan, recipe_catalog, tool_catalog)
        analysis_report = analyze_workflow_ir(workflow_ir)
        if not analysis_report.is_valid:
            joined_errors = "; ".join(analysis_report.errors)
            raise ValueError(joined_errors)
    except Exception as exc:
        raise PlannerCatalogError(f"LLM planner recipe/catalog validation failed: {exc}") from exc

    return NaturalLanguagePlanResult(
        plan=plan,
        planner_prompt=prompt,
        raw_response=raw_content,
        catalog_retrieval=catalog_retrieval,
    )


def build_planner_prompt(
    request: str,
    tool_catalog: ToolCatalog,
    recipe_catalog: RecipeCatalog,
    *,
    catalog_retrieval: dict[str, Any] | None = None,
) -> str:
    if catalog_retrieval is None:
        catalog_retrieval = retrieve_catalog_context(request, tool_catalog, recipe_catalog)

    catalog_context = _build_retrieved_catalog_context(
        catalog_retrieval,
        tool_catalog,
        recipe_catalog,
    )

    return render_natural_language_planner_prompt(request, catalog_context)


def build_default_planner_prompt(request: str) -> str:
    tool_catalog = load_tool_catalog()
    recipe_catalog = load_recipe_catalog(tool_catalog=tool_catalog)
    return build_planner_prompt(request, tool_catalog, recipe_catalog)


def _build_retrieved_catalog_context(
    catalog_retrieval: dict[str, Any],
    tool_catalog: ToolCatalog,
    recipe_catalog: RecipeCatalog,
) -> dict[str, Any]:
    return {
        "retrieval": catalog_retrieval,
        "validation_boundary": (
            "Planner context is narrowed by Approved Catalog Retriever; final "
            "recipe/tool validation uses the complete approved Catalog."
        ),
        "recipes": [
            _recipe_prompt_context(recipe_result, recipe_catalog)
            for recipe_result in catalog_retrieval.get("recipes", [])
        ],
        "tools": _tool_prompt_contexts(
            catalog_retrieval,
            tool_catalog,
            recipe_catalog,
        ),
    }


def _recipe_prompt_context(
    recipe_result: dict[str, Any],
    recipe_catalog: RecipeCatalog,
) -> dict[str, Any]:
    recipe = recipe_catalog.get(str(recipe_result["id"]))
    return {
        "id": recipe.id,
        "name": recipe.name,
        "description": recipe.description,
        "retrieval": recipe_result,
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


def _tool_prompt_context(
    tool_result: dict[str, Any],
    tool_catalog: ToolCatalog,
) -> dict[str, Any]:
    tool = tool_catalog.get(str(tool_result["id"]), str(tool_result["version"]))
    return _tool_spec_prompt_context(
        tool,
        context_source="retriever_match",
        retrieval=tool_result,
    )


def _tool_prompt_contexts(
    catalog_retrieval: dict[str, Any],
    tool_catalog: ToolCatalog,
    recipe_catalog: RecipeCatalog,
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for tool_result in catalog_retrieval.get("tools", []):
        context = _tool_prompt_context(tool_result, tool_catalog)
        seen.add((context["id"], context["version"]))
        contexts.append(context)

    for recipe_result in catalog_retrieval.get("recipes", []):
        recipe = recipe_catalog.get(str(recipe_result["id"]))
        for step in recipe.steps:
            for tool_id in step.allowed_tools:
                for version in tool_catalog.versions(tool_id):
                    tool = tool_catalog.get(tool_id, version)
                    key = (tool.id, tool.version)
                    if key in seen:
                        continue
                    seen.add(key)
                    contexts.append(
                        _tool_spec_prompt_context(
                            tool,
                            context_source="retrieved_recipe_allowed_tool",
                            inclusion_reason=(
                                f"Included because retrieved recipe '{recipe.id}' "
                                f"step '{step.id}' allows this tool."
                            ),
                        )
                    )

    return contexts


def _tool_spec_prompt_context(
    tool: ToolSpec,
    *,
    context_source: str,
    retrieval: dict[str, Any] | None = None,
    inclusion_reason: str | None = None,
) -> dict[str, Any]:
    context = {
        "context_source": context_source,
        "id": tool.id,
        "version": tool.version,
        "description": tool.description,
        "trust_status": CATALOG_APPROVED_TRUST_STATUS,
        "execution_verification": tool.execution_verification.model_dump(mode="json"),
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
    if retrieval is not None:
        context["retrieval"] = retrieval
    if inclusion_reason is not None:
        context["inclusion_reason"] = inclusion_reason
    return context


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
