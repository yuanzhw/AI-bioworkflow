"""Catalog API routes."""

from fastapi import APIRouter, HTTPException, Query

from src.api.models import RecipeDto, RecipeListResponse, ToolDto, ToolListResponse
from src.services.catalog_service import get_recipe, get_tool, list_recipes, list_tools


router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/recipes", response_model=RecipeListResponse)
def read_recipes() -> RecipeListResponse:
    return RecipeListResponse(
        recipes=[RecipeDto.model_validate(recipe) for recipe in list_recipes()],
    )


@router.get("/recipes/{recipe_id}", response_model=RecipeDto)
def read_recipe(recipe_id: str) -> RecipeDto:
    try:
        return RecipeDto.model_validate(get_recipe(recipe_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_error_detail(exc)) from exc


@router.get("/tools", response_model=ToolListResponse)
def read_tools() -> ToolListResponse:
    return ToolListResponse(
        tools=[ToolDto.model_validate(tool) for tool in list_tools()],
    )


@router.get("/tools/{tool_id}", response_model=ToolDto)
def read_tool(
    tool_id: str,
    version: str | None = Query(default=None),
) -> ToolDto:
    try:
        return ToolDto.model_validate(get_tool(tool_id, version))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=_error_detail(exc)) from exc


def _error_detail(exc: KeyError) -> str:
    return str(exc).strip("'")
