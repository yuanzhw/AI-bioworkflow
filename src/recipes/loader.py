from pathlib import Path

import yaml

from src.catalog.loader import ToolCatalog, load_tool_catalog
from src.recipes.schema import RecipeSpec


DEFAULT_RECIPE_DIR = Path(__file__).parent / "definitions"


class RecipeCatalog:
    def __init__(self, recipes: dict[str, RecipeSpec]):
        self._recipes = recipes

    def get(self, recipe_id: str) -> RecipeSpec:
        if recipe_id not in self._recipes:
            raise KeyError(f"unknown recipe: {recipe_id}")
        return self._recipes[recipe_id]

    def all(self) -> list[RecipeSpec]:
        return list(self._recipes.values())


def load_recipe_catalog(
    root: str | Path = DEFAULT_RECIPE_DIR,
    tool_catalog: ToolCatalog | None = None,
) -> RecipeCatalog:
    root_path = Path(root)
    tool_catalog = tool_catalog or load_tool_catalog()
    recipes: dict[str, RecipeSpec] = {}

    for yaml_path in sorted(root_path.rglob("*.yaml")):
        spec = RecipeSpec.model_validate(_load_yaml(yaml_path))
        if spec.id in recipes:
            raise ValueError(f"duplicate recipe definition: {spec.id}")
        _validate_recipe_tools(spec, tool_catalog)
        recipes[spec.id] = spec

    return RecipeCatalog(recipes)


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return data


def _validate_recipe_tools(recipe: RecipeSpec, tool_catalog: ToolCatalog) -> None:
    for step in recipe.steps:
        for tool_id in step.allowed_tools:
            if not tool_catalog.has_tool_id(tool_id):
                raise ValueError(
                    f"recipe '{recipe.id}' step '{step.id}' allows unknown tool '{tool_id}'"
                )
