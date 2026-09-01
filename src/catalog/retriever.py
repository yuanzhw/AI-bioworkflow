"""Deterministic retrieval over approved local recipe and tool catalogs."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from src.catalog.loader import ToolCatalog
from src.catalog.schema import ToolSpec
from src.recipes.loader import RecipeCatalog
from src.recipes.schema import RecipeSpec


LEXICAL_RETRIEVER_STRATEGY = "lexical_v1"
CATALOG_APPROVED_TRUST_STATUS = "catalog-approved"
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class _WeightedField:
    name: str
    text: str
    weight: float


@dataclass(frozen=True)
class _ScoredItem:
    item: RecipeSpec | ToolSpec
    score: float
    matched_terms: list[str]
    matched_fields: list[str]


_CatalogItem = TypeVar("_CatalogItem", RecipeSpec, ToolSpec)


def retrieve_catalog_context(
    query: str,
    tool_catalog: ToolCatalog,
    recipe_catalog: RecipeCatalog,
    top_k_recipes: int = 3,
    top_k_tools: int = 8,
) -> dict[str, Any]:
    """Retrieve approved recipe and tool candidates for a natural-language query."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty")
    if top_k_recipes < 1:
        raise ValueError("top_k_recipes must be >= 1")
    if top_k_tools < 1:
        raise ValueError("top_k_tools must be >= 1")

    query_tokens = tokenize_for_retrieval(normalized_query)
    recipe_matches = _rank_recipes(query_tokens, recipe_catalog)[:top_k_recipes]
    tool_matches = _rank_tools(query_tokens, tool_catalog)[:top_k_tools]

    fallback_used = False
    fallback_reasons: list[str] = []

    if not recipe_matches:
        fallback_used = True
        fallback_reasons.append("recipe recall returned no matches; used complete recipe catalog")
        recipes = _fallback_recipe_results(recipe_catalog, top_k_recipes)
    else:
        recipes = [_recipe_result(match) for match in recipe_matches]

    if not tool_matches:
        fallback_used = True
        fallback_tools = _allowed_tools_from_recipe_results(recipes, recipe_catalog, tool_catalog)
        if fallback_tools:
            fallback_reasons.append(
                "tool recall returned no matches; used allowed tools from retrieved recipes"
            )
            tools = [_fallback_tool_result(tool) for tool in fallback_tools[:top_k_tools]]
        else:
            fallback_reasons.append("tool recall returned no matches; used complete tool catalog")
            tools = _fallback_tool_results(tool_catalog, top_k_tools)
    else:
        tools = [_tool_result(match) for match in tool_matches]

    return {
        "query": normalized_query,
        "strategy": LEXICAL_RETRIEVER_STRATEGY,
        "recipes": recipes,
        "tools": tools,
        "fallback_used": fallback_used,
        "fallback_reason": "; ".join(fallback_reasons) if fallback_reasons else None,
    }


def tokenize_for_retrieval(text: str) -> list[str]:
    """Tokenize catalog text and natural-language queries without external dependencies."""
    normalized = _normalize_common_variants(text.lower())
    tokens = [token for token in _TOKEN_PATTERN.findall(normalized) if len(token) > 1]

    for cjk_sequence in _cjk_sequences(normalized):
        tokens.extend(cjk_sequence)
        tokens.extend(
            cjk_sequence[index : index + 2]
            for index in range(0, max(len(cjk_sequence) - 1, 0))
        )

    return _unique_preserving_order(tokens)


def _normalize_common_variants(text: str) -> str:
    normalized = re.sub(r"\brnaseq\b", "rna seq rnaseq", text)
    return re.sub(r"\bchipseq\b", "chip seq chipseq", normalized)


def _cjk_sequences(text: str) -> list[str]:
    sequences: list[str] = []
    current: list[str] = []
    for char in text:
        if _is_cjk(char):
            current.append(char)
            continue
        if current:
            sequences.append("".join(current))
            current = []
    if current:
        sequences.append("".join(current))
    return sequences


def _is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0x3040 <= codepoint <= 0x30FF
        or 0xAC00 <= codepoint <= 0xD7AF
    )


def _rank_recipes(query_tokens: list[str], recipe_catalog: RecipeCatalog) -> list[_ScoredItem]:
    return _rank_items(
        recipe_catalog.all(),
        query_tokens,
        fields_for_item=_recipe_fields,
        stable_key=lambda recipe: (recipe.id,),
    )


def _rank_tools(query_tokens: list[str], tool_catalog: ToolCatalog) -> list[_ScoredItem]:
    return _rank_items(
        tool_catalog.all(),
        query_tokens,
        fields_for_item=_tool_fields,
        stable_key=lambda tool: (tool.id, _version_sort_key(tool.version)),
    )


def _rank_items(
    items: Sequence[_CatalogItem],
    query_tokens: list[str],
    *,
    fields_for_item: Callable[[_CatalogItem], list[_WeightedField]],
    stable_key: Callable[[_CatalogItem], tuple[Any, ...]],
) -> list[_ScoredItem]:
    matches = [
        scored
        for scored in (
            _score_item(item, query_tokens, fields_for_item(item))
            for item in items
        )
        if scored.score > 0
    ]
    return sorted(matches, key=lambda match: (-match.score, *stable_key(match.item)))


def _score_item(
    item: RecipeSpec | ToolSpec,
    query_tokens: list[str],
    fields: list[_WeightedField],
) -> _ScoredItem:
    score = 0.0
    matched_terms: list[str] = []
    matched_fields: list[str] = []

    for field in fields:
        field_tokens = set(tokenize_for_retrieval(field.text))
        field_matches = [token for token in query_tokens if token in field_tokens]
        if not field_matches:
            continue
        unique_matches = _unique_preserving_order(field_matches)
        score += len(unique_matches) * field.weight
        matched_terms.extend(unique_matches)
        matched_fields.append(field.name)

    return _ScoredItem(
        item=item,
        score=score,
        matched_terms=_unique_preserving_order(matched_terms),
        matched_fields=_unique_preserving_order(matched_fields),
    )


def _recipe_fields(recipe: RecipeSpec) -> list[_WeightedField]:
    fields = [
        _WeightedField("id", recipe.id, 5.0),
        _WeightedField("name", recipe.name, 4.0),
        _WeightedField("aliases", " ".join(recipe.aliases), 5.0),
        _WeightedField("description", recipe.description, 3.0),
        _WeightedField("required_inputs.name", " ".join(recipe.required_inputs), 2.0),
        _WeightedField(
            "required_inputs.description",
            " ".join(
                spec.description or ""
                for spec in recipe.required_inputs.values()
            ),
            1.0,
        ),
        _WeightedField("steps.id", " ".join(step.id for step in recipe.steps), 2.0),
        _WeightedField("steps.role", " ".join(step.role for step in recipe.steps), 4.0),
        _WeightedField(
            "steps.allowed_tools",
            " ".join(tool_id for step in recipe.steps for tool_id in step.allowed_tools),
            2.0,
        ),
    ]
    return fields


def _tool_fields(tool: ToolSpec) -> list[_WeightedField]:
    return [
        _WeightedField("id", tool.id, 5.0),
        _WeightedField("version", tool.version, 0.5),
        _WeightedField("aliases", " ".join(tool.aliases), 5.0),
        _WeightedField("description", tool.description, 3.0),
        _WeightedField("inputs.name", " ".join(tool.inputs), 2.0),
        _WeightedField("inputs.type", " ".join(spec.type for spec in tool.inputs.values()), 1.0),
        _WeightedField(
            "inputs.description",
            " ".join(spec.description or "" for spec in tool.inputs.values()),
            1.0,
        ),
        _WeightedField("params.name", " ".join(tool.params), 2.0),
        _WeightedField("params.type", " ".join(spec.type for spec in tool.params.values()), 1.0),
        _WeightedField(
            "params.description",
            " ".join(spec.description or "" for spec in tool.params.values()),
            1.0,
        ),
        _WeightedField("outputs.name", " ".join(tool.outputs), 2.0),
        _WeightedField(
            "outputs.description",
            " ".join(spec.description or "" for spec in tool.outputs.values()),
            1.0,
        ),
        _WeightedField(
            "outputs.tags",
            " ".join(tag for spec in tool.outputs.values() for tag in spec.tags),
            2.0,
        ),
        _WeightedField("runtime.docker", tool.runtime.docker or "", 0.5),
    ]


def _recipe_result(match: _ScoredItem) -> dict[str, Any]:
    recipe = _as_recipe(match.item)
    return {
        "id": recipe.id,
        "score": _json_score(match.score),
        "matched_terms": match.matched_terms,
        "matched_fields": match.matched_fields,
        "reason": _match_reason("recipe", match.matched_terms, match.matched_fields),
    }


def _tool_result(match: _ScoredItem) -> dict[str, Any]:
    tool = _as_tool(match.item)
    return {
        "id": tool.id,
        "version": tool.version,
        "score": _json_score(match.score),
        "matched_terms": match.matched_terms,
        "matched_fields": match.matched_fields,
        "trust_status": CATALOG_APPROVED_TRUST_STATUS,
        "execution_verification": tool.execution_verification.model_dump(mode="json"),
        "reason": _match_reason("tool", match.matched_terms, match.matched_fields),
    }


def _fallback_recipe_results(recipe_catalog: RecipeCatalog, top_k: int) -> list[dict[str, Any]]:
    return [
        _fallback_recipe_result(recipe)
        for recipe in sorted(recipe_catalog.all(), key=lambda recipe: recipe.id)[:top_k]
    ]


def _fallback_tool_results(tool_catalog: ToolCatalog, top_k: int) -> list[dict[str, Any]]:
    return [
        _fallback_tool_result(tool)
        for tool in sorted(tool_catalog.all(), key=lambda tool: (tool.id, _version_sort_key(tool.version)))[:top_k]
    ]


def _fallback_recipe_result(recipe: RecipeSpec) -> dict[str, Any]:
    return {
        "id": recipe.id,
        "score": 0.0,
        "matched_terms": [],
        "matched_fields": [],
        "reason": "Fallback result from approved recipe catalog.",
    }


def _fallback_tool_result(tool: ToolSpec) -> dict[str, Any]:
    return {
        "id": tool.id,
        "version": tool.version,
        "score": 0.0,
        "matched_terms": [],
        "matched_fields": [],
        "trust_status": CATALOG_APPROVED_TRUST_STATUS,
        "execution_verification": tool.execution_verification.model_dump(mode="json"),
        "reason": "Fallback result from approved tool catalog.",
    }


def _allowed_tools_from_recipe_results(
    recipes: list[dict[str, Any]],
    recipe_catalog: RecipeCatalog,
    tool_catalog: ToolCatalog,
) -> list[ToolSpec]:
    allowed_tool_ids: set[str] = set()
    for recipe_result in recipes:
        try:
            recipe = recipe_catalog.get(str(recipe_result["id"]))
        except KeyError:
            continue
        allowed_tool_ids.update(tool_id for step in recipe.steps for tool_id in step.allowed_tools)

    return [
        tool
        for tool in sorted(tool_catalog.all(), key=lambda tool: (tool.id, _version_sort_key(tool.version)))
        if tool.id in allowed_tool_ids
    ]


def _match_reason(kind: str, matched_terms: list[str], matched_fields: list[str]) -> str:
    terms = ", ".join(matched_terms[:6])
    fields = ", ".join(matched_fields[:4])
    return f"Matched approved catalog {kind} fields ({fields}) using terms: {terms}."


def _json_score(score: float) -> float:
    return round(score, 3)


def _unique_preserving_order(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        unique.append(value)
        seen.add(value)
    return unique


def _version_sort_key(version: str) -> tuple[Any, ...]:
    parts: list[Any] = []
    for part in re.split(r"([0-9]+)", version):
        if not part:
            continue
        parts.append(int(part) if part.isdigit() else part)
    return tuple(parts)


def _as_recipe(item: RecipeSpec | ToolSpec) -> RecipeSpec:
    if isinstance(item, RecipeSpec):
        return item
    raise TypeError("expected RecipeSpec")


def _as_tool(item: RecipeSpec | ToolSpec) -> ToolSpec:
    if isinstance(item, ToolSpec):
        return item
    raise TypeError("expected ToolSpec")
