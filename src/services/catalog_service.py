"""Catalog query service for recipes and approved tools."""

import re
from typing import Any

from src.catalog.loader import ToolCatalog, load_tool_catalog
from src.catalog.schema import ToolSpec
from src.recipes.loader import RecipeCatalog, load_recipe_catalog
from src.recipes.schema import RecipeSpec

CATALOG_APPROVED_TRUST_STATUS = "catalog-approved"


def list_recipes(
    *,
    recipe_catalog: RecipeCatalog | None = None,
    tool_catalog: ToolCatalog | None = None,
) -> list[dict[str, Any]]:
    """Return all supported recipes as JSON-ready API records."""
    recipe_catalog = _recipe_catalog(recipe_catalog, tool_catalog)
    return [_recipe_to_record(recipe) for recipe in sorted(recipe_catalog.all(), key=lambda recipe: recipe.id)]


def get_recipe(
    recipe_id: str,
    *,
    recipe_catalog: RecipeCatalog | None = None,
    tool_catalog: ToolCatalog | None = None,
) -> dict[str, Any]:
    """Return one supported recipe as a JSON-ready API record."""
    recipe_catalog = _recipe_catalog(recipe_catalog, tool_catalog)
    return _recipe_to_record(recipe_catalog.get(recipe_id))


def list_tools(
    *,
    tool_catalog: ToolCatalog | None = None,
) -> list[dict[str, Any]]:
    """Return all approved tools as JSON-ready API records."""
    tool_catalog = tool_catalog or load_tool_catalog()
    tools = sorted(tool_catalog.all(), key=lambda tool: (tool.id, _version_sort_key(tool.version)))
    return [_tool_to_record(tool, tool_catalog=tool_catalog) for tool in tools]


def get_tool(
    tool_id: str,
    version: str | None = None,
    *,
    tool_catalog: ToolCatalog | None = None,
) -> dict[str, Any]:
    """Return one approved tool version as a JSON-ready API record."""
    tool_catalog = tool_catalog or load_tool_catalog()
    selected_version = version or _latest_tool_version(tool_catalog, tool_id)
    return _tool_to_record(tool_catalog.get(tool_id, selected_version), tool_catalog=tool_catalog)


def _recipe_catalog(
    recipe_catalog: RecipeCatalog | None,
    tool_catalog: ToolCatalog | None,
) -> RecipeCatalog:
    if recipe_catalog is not None:
        return recipe_catalog
    tool_catalog = tool_catalog or load_tool_catalog()
    return load_recipe_catalog(tool_catalog=tool_catalog)


def _recipe_to_record(recipe: RecipeSpec) -> dict[str, Any]:
    return {
        "id": recipe.id,
        "name": recipe.name,
        "description": recipe.description,
        "aliases": recipe.aliases,
        "required_inputs": {
            input_name: spec.model_dump(mode="json", exclude_none=True)
            for input_name, spec in sorted(recipe.required_inputs.items())
        },
        "steps": [
            {
                "id": step.id,
                "role": step.role,
                "optional": step.optional,
                "scatter": step.scatter.model_dump(mode="json", exclude_none=True) if step.scatter else None,
                "allowed_tools": sorted(step.allowed_tools),
            }
            for step in recipe.steps
        ],
    }


def _tool_to_record(tool: ToolSpec, *, tool_catalog: ToolCatalog) -> dict[str, Any]:
    return {
        "id": tool.id,
        "version": tool.version,
        "versions": tool_catalog.versions(tool.id),
        "aliases": tool.aliases,
        "description": tool.description,
        "inputs": {
            input_name: spec.model_dump(mode="json", exclude_none=True)
            for input_name, spec in sorted(tool.inputs.items())
        },
        "params": {
            param_name: spec.model_dump(mode="json", exclude_none=True)
            for param_name, spec in sorted(tool.params.items())
        },
        "outputs": {
            output_name: spec.model_dump(mode="json", exclude_none=True)
            for output_name, spec in sorted(tool.outputs.items())
        },
        "runtime": tool.runtime.model_dump(mode="json", exclude_none=True),
        "trust_status": CATALOG_APPROVED_TRUST_STATUS,
        "execution_verification": tool.execution_verification.model_dump(mode="json"),
    }


def _latest_tool_version(tool_catalog: ToolCatalog, tool_id: str) -> str:
    versions = tool_catalog.versions(tool_id)
    if not versions:
        raise KeyError(f"unknown tool: {tool_id}")
    return max(versions, key=_version_sort_key)


def _version_sort_key(version: str) -> tuple[Any, ...]:
    parts: list[Any] = []
    for part in re.split(r"([0-9]+)", version):
        if not part:
            continue
        parts.append(int(part) if part.isdigit() else part)
    return tuple(parts)
