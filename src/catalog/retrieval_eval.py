"""Evaluation helpers for approved catalog retrieval baselines."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.catalog.loader import ToolCatalog
from src.catalog.retriever import retrieve_catalog_context
from src.recipes.loader import RecipeCatalog


DEFAULT_TOP_K_RECIPES = 3
DEFAULT_TOP_K_TOOLS = 8
METRIC_PRECISION = 4
STRICT_TOOL_RECALL_CUTOFFS = (3, 5)
NO_RECIPE_MATCH_FAMILY = "no_match"
UNMAPPED_RECIPE_FAMILY = "unmapped"
MISS_CATEGORY_KEYS = (
    "recipe_top_1_miss",
    "recipe_top_k_miss",
    "recipe_no_match",
    "recipe_family_confusion",
    "raw_tool_miss",
    "raw_role_miss",
    "raw_tool_miss_recovered_by_recipe_context",
    "raw_role_miss_recovered_by_recipe_context",
    "planner_context_tool_miss",
    "planner_context_role_miss",
    "unsupported_direct_match",
)
MACRO_FAMILY_METRIC_KEYS = (
    "recipe_recall_at_1",
    "recipe_recall_at_k",
    "recipe_mrr",
    "tool_recall_at_3",
    "tool_recall_at_5",
    "tool_recall_at_k",
    "tool_mrr",
    "role_coverage",
    "planner_context_tool_recall",
    "planner_context_role_coverage",
)
PER_QUERY_METRIC_KEYS = (
    "expected_recipe_reciprocal_rank",
    "tool_recall_at_3",
    "tool_recall_at_5",
    "tool_recall",
    "first_expected_tool_reciprocal_rank",
    "planner_context_tool_recall",
    "role_coverage",
    "planner_context_role_coverage",
)
RetrievalFn = Callable[[str, ToolCatalog, RecipeCatalog, int, int], dict[str, Any]]


@dataclass(frozen=True)
class RetrievalQuery:
    """A labeled natural-language query for retriever evaluation."""

    id: str
    query: str
    supported: bool
    workflow_family: str
    expected_recipe: str | None
    expected_tools: list[str]
    expected_roles: dict[str, list[str]]
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetrievalQuery":
        query_id = _required_str(data, "id")
        query = _required_str(data, "query")
        supported = data.get("supported", True)
        if not isinstance(supported, bool):
            raise ValueError(f"{query_id}: supported must be a boolean")
        workflow_family = _required_str(data, "workflow_family")

        expected_recipe_raw = data.get("expected_recipe")
        if expected_recipe_raw is not None and not isinstance(expected_recipe_raw, str):
            raise ValueError(f"{query_id}: expected_recipe must be a string or null")

        expected_tools = _string_list(data.get("expected_tools", []), f"{query_id}: expected_tools")
        expected_roles = _expected_roles(data.get("expected_roles", {}), query_id)
        notes = data.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise ValueError(f"{query_id}: notes must be a string or null")
        if not supported and (expected_recipe_raw is not None or expected_tools or expected_roles):
            raise ValueError(f"{query_id}: unsupported queries must not define expected hits")

        return cls(
            id=query_id,
            query=query,
            supported=supported,
            workflow_family=workflow_family,
            expected_recipe=expected_recipe_raw,
            expected_tools=expected_tools,
            expected_roles=expected_roles,
            notes=notes,
        )


def load_retrieval_queries(path: str | Path) -> list[RetrievalQuery]:
    """Load a JSON query fixture and validate its public schema."""
    fixture_path = Path(path)
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("retrieval query fixture must contain a JSON array")

    queries: list[RetrievalQuery] = []
    seen_ids: set[str] = set()
    duplicate_ids: list[str] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"retrieval query entry at index {index} must be an object")
        query = RetrievalQuery.from_dict(item)
        if query.id in seen_ids:
            duplicate_ids.append(query.id)
        else:
            seen_ids.add(query.id)
        queries.append(query)

    if duplicate_ids:
        duplicate_summary = ", ".join(sorted(set(duplicate_ids)))
        raise ValueError(f"duplicate retrieval query ids: {duplicate_summary}")
    return queries


def evaluate_retrieval_queries(
    queries: Sequence[RetrievalQuery],
    tool_catalog: ToolCatalog,
    recipe_catalog: RecipeCatalog,
    *,
    top_k_recipes: int = DEFAULT_TOP_K_RECIPES,
    top_k_tools: int = DEFAULT_TOP_K_TOOLS,
    retriever: RetrievalFn = retrieve_catalog_context,
) -> dict[str, Any]:
    """Evaluate a retriever over labeled current-catalog query fixtures."""
    if top_k_recipes < 1:
        raise ValueError("top_k_recipes must be >= 1")
    minimum_tool_cutoff = max(STRICT_TOOL_RECALL_CUTOFFS)
    if top_k_tools < minimum_tool_cutoff:
        raise ValueError(
            f"top_k_tools must be >= {minimum_tool_cutoff} "
            "to compute the fixed Tool Recall@3/@5 metrics"
        )

    recipe_family_by_id = _recipe_family_map(queries)
    per_query = [
        _evaluate_one_query(
            query,
            tool_catalog,
            recipe_catalog,
            recipe_family_by_id=recipe_family_by_id,
            top_k_recipes=top_k_recipes,
            top_k_tools=top_k_tools,
            retriever=retriever,
        )
        for query in queries
    ]

    supported_results = [result for result in per_query if result["supported"]]
    fallback_query_ids = [result["id"] for result in per_query if result["fallback_used"]]
    unsupported_results = [result for result in per_query if not result["supported"]]
    unsupported_direct_match_query_ids = [
        result["id"] for result in unsupported_results if not result["fallback_used"]
    ]
    family_metrics = _family_metrics(per_query)
    macro_family_metrics = _macro_family_metrics(family_metrics)
    recipe_family_confusion = _recipe_family_confusion(per_query)

    return {
        "strategy": _first_strategy(per_query),
        "top_k_recipes": top_k_recipes,
        "top_k_tools": top_k_tools,
        "query_count": len(per_query),
        "supported_query_count": len(supported_results),
        "unsupported_query_count": len(unsupported_results),
        "metrics": _round_metrics(_aggregate_metrics(per_query)),
        "family_metrics": _round_family_metrics(family_metrics),
        "macro_family_metrics": _round_metrics(macro_family_metrics),
        "recipe_family_confusion": recipe_family_confusion,
        "miss_categories": _miss_category_summary(per_query),
        "fallback_query_ids": fallback_query_ids,
        "unsupported_direct_match_query_ids": unsupported_direct_match_query_ids,
        "queries": [_round_query_metrics(result) for result in per_query],
    }


def _evaluate_one_query(
    query: RetrievalQuery,
    tool_catalog: ToolCatalog,
    recipe_catalog: RecipeCatalog,
    *,
    recipe_family_by_id: dict[str, str],
    top_k_recipes: int,
    top_k_tools: int,
    retriever: RetrievalFn,
) -> dict[str, Any]:
    retrieval = retriever(
        query.query,
        tool_catalog,
        recipe_catalog,
        top_k_recipes,
        top_k_tools,
    )
    recipe_fallback_used, tool_fallback_used, fallback_used = _fallback_provenance(
        retrieval,
        query_id=query.id,
    )
    retrieved_recipe_ids = [str(recipe["id"]) for recipe in retrieval.get("recipes", [])]
    retrieved_tool_ids = [str(tool["id"]) for tool in retrieval.get("tools", [])]
    ranked_recipe_ids = [] if recipe_fallback_used else retrieved_recipe_ids
    ranked_tool_ids = [] if tool_fallback_used else retrieved_tool_ids
    planner_context_tool_ids = _planner_context_tool_ids(
        retrieved_recipe_ids,
        retrieved_tool_ids,
        recipe_catalog,
    )

    expected_recipe_rank = _rank_of(query.expected_recipe, ranked_recipe_ids)
    expected_tool_ranks = {
        tool_id: _rank_of(tool_id, ranked_tool_ids)
        for tool_id in query.expected_tools
    }
    planner_context_tool_ranks = {
        tool_id: _rank_of(tool_id, planner_context_tool_ids)
        for tool_id in query.expected_tools
    }
    recalled_tools = [
        tool_id for tool_id, rank in expected_tool_ranks.items() if rank is not None
    ]
    missed_tools = [
        tool_id for tool_id, rank in expected_tool_ranks.items() if rank is None
    ]
    planner_context_recalled_tools = [
        tool_id
        for tool_id, rank in planner_context_tool_ranks.items()
        if rank is not None
    ]
    planner_context_missed_tools = [
        tool_id
        for tool_id, rank in planner_context_tool_ranks.items()
        if rank is None
    ]
    role_coverage = _role_coverage(query.expected_roles, ranked_tool_ids)
    planner_context_role_coverage = _role_coverage(
        query.expected_roles,
        planner_context_tool_ids,
    )
    top_recipe_id = ranked_recipe_ids[0] if ranked_recipe_ids else None
    top_recipe_family = _top_recipe_family(top_recipe_id, recipe_family_by_id)

    result = {
        "id": query.id,
        "query": query.query,
        "supported": query.supported,
        "workflow_family": query.workflow_family,
        "expected_recipe": query.expected_recipe,
        "expected_tools": query.expected_tools,
        "expected_roles": query.expected_roles,
        "retrieved_recipes": retrieved_recipe_ids,
        "top_recipe_id": top_recipe_id,
        "top_recipe_family": top_recipe_family,
        "retrieved_tools": retrieved_tool_ids,
        "planner_context_tools": planner_context_tool_ids,
        "expected_recipe_recalled": expected_recipe_rank is not None,
        "expected_recipe_recalled_at_1": expected_recipe_rank == 1,
        "expected_recipe_rank": expected_recipe_rank,
        "expected_recipe_reciprocal_rank": _reciprocal_rank(expected_recipe_rank),
        "missed_expected_recipe": (
            query.expected_recipe if query.expected_recipe and expected_recipe_rank is None else None
        ),
        "recalled_expected_tools": recalled_tools,
        "missed_expected_tools": missed_tools,
        "tool_recall": _rate(len(recalled_tools), len(query.expected_tools)),
        "tool_recall_at_3": _rank_recall(expected_tool_ranks.values(), 3),
        "tool_recall_at_5": _rank_recall(expected_tool_ranks.values(), 5),
        "first_expected_tool_reciprocal_rank": _first_reciprocal_rank(expected_tool_ranks.values()),
        "planner_context_recalled_expected_tools": planner_context_recalled_tools,
        "planner_context_missed_expected_tools": planner_context_missed_tools,
        "planner_context_tool_recall": _rate(
            len(planner_context_recalled_tools),
            len(query.expected_tools),
        ),
        "covered_roles": role_coverage["covered_roles"],
        "missed_roles": role_coverage["missed_roles"],
        "role_coverage": role_coverage["coverage"],
        "planner_context_covered_roles": planner_context_role_coverage["covered_roles"],
        "planner_context_missed_roles": planner_context_role_coverage["missed_roles"],
        "planner_context_role_coverage": planner_context_role_coverage["coverage"],
        "recipe_fallback_used": recipe_fallback_used,
        "tool_fallback_used": tool_fallback_used,
        "fallback_used": fallback_used,
        "fallback_reason": retrieval.get("fallback_reason"),
        "strategy": retrieval.get("strategy"),
        "notes": query.notes,
    }
    result["miss_categories"] = _classify_misses(result)
    return result


def _fallback_provenance(
    retrieval: dict[str, Any],
    *,
    query_id: str,
) -> tuple[bool, bool, bool]:
    fallback_used = retrieval.get("fallback_used", False)
    if not isinstance(fallback_used, bool):
        raise ValueError(f"{query_id}: fallback_used must be a boolean")

    component_fields = ("recipe_fallback_used", "tool_fallback_used")
    for field_name in component_fields:
        if field_name in retrieval and not isinstance(retrieval[field_name], bool):
            raise ValueError(f"{query_id}: {field_name} must be a boolean")

    if fallback_used and any(field_name not in retrieval for field_name in component_fields):
        raise ValueError(
            f"{query_id}: fallback_used=true requires boolean "
            "recipe_fallback_used and tool_fallback_used"
        )

    recipe_fallback_used = retrieval.get("recipe_fallback_used", False)
    tool_fallback_used = retrieval.get("tool_fallback_used", False)
    if fallback_used != (recipe_fallback_used or tool_fallback_used):
        raise ValueError(
            f"{query_id}: fallback_used must equal recipe_fallback_used or "
            "tool_fallback_used"
        )
    return recipe_fallback_used, tool_fallback_used, fallback_used


def _recipe_family_map(queries: Sequence[RetrievalQuery]) -> dict[str, str]:
    recipe_families: dict[str, str] = {}
    for query in queries:
        if not query.supported or query.expected_recipe is None:
            continue
        existing_family = recipe_families.get(query.expected_recipe)
        if existing_family is not None and existing_family != query.workflow_family:
            recipe_families[query.expected_recipe] = UNMAPPED_RECIPE_FAMILY
        elif existing_family is None:
            recipe_families[query.expected_recipe] = query.workflow_family
    return recipe_families


def _top_recipe_family(
    top_recipe_id: str | None,
    recipe_family_by_id: dict[str, str],
) -> str:
    if top_recipe_id is None:
        return NO_RECIPE_MATCH_FAMILY
    return recipe_family_by_id.get(top_recipe_id, UNMAPPED_RECIPE_FAMILY)


def _classify_misses(result: dict[str, Any]) -> list[str]:
    categories: list[str] = []
    if result["supported"]:
        if result["expected_recipe"] is not None:
            if not result["expected_recipe_recalled_at_1"]:
                categories.append("recipe_top_1_miss")
            if not result["expected_recipe_recalled"]:
                categories.append("recipe_top_k_miss")
            if result["top_recipe_family"] == NO_RECIPE_MATCH_FAMILY:
                categories.append("recipe_no_match")
            elif result["top_recipe_family"] != result["workflow_family"]:
                categories.append("recipe_family_confusion")
        if result["missed_expected_tools"]:
            categories.append("raw_tool_miss")
            if not result["planner_context_missed_expected_tools"]:
                categories.append("raw_tool_miss_recovered_by_recipe_context")
        if result["missed_roles"]:
            categories.append("raw_role_miss")
            if not result["planner_context_missed_roles"]:
                categories.append("raw_role_miss_recovered_by_recipe_context")
        if result["planner_context_missed_expected_tools"]:
            categories.append("planner_context_tool_miss")
        if result["planner_context_missed_roles"]:
            categories.append("planner_context_role_miss")
    elif not result["fallback_used"]:
        categories.append("unsupported_direct_match")
    return categories


def _recipe_family_confusion(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    included_results = [
        result
        for result in results
        if result["supported"] and result["expected_recipe"] is not None
    ]
    actual_labels = sorted({result["workflow_family"] for result in included_results})
    observed_predictions = {
        result["top_recipe_family"] for result in included_results
    }
    predicted_labels = sorted(set(actual_labels) | observed_predictions)
    counts = {
        actual_label: {predicted_label: 0 for predicted_label in predicted_labels}
        for actual_label in actual_labels
    }
    same_family_count = 0
    for result in included_results:
        actual_family = result["workflow_family"]
        predicted_family = result["top_recipe_family"]
        counts[actual_family][predicted_family] += 1
        if actual_family == predicted_family:
            same_family_count += 1
    return {
        "query_count": len(included_results),
        "actual_labels": actual_labels,
        "predicted_labels": predicted_labels,
        "counts": counts,
        "same_family_count": same_family_count,
        "same_family_rate": round(
            _rate(same_family_count, len(included_results)),
            METRIC_PRECISION,
        ),
    }


def _miss_category_summary(
    results: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for category in MISS_CATEGORY_KEYS:
        query_ids = [
            result["id"]
            for result in results
            if category in result["miss_categories"]
        ]
        summary[category] = {
            "count": len(query_ids),
            "query_ids": query_ids,
        }
    return summary


def _aggregate_metrics(results: Sequence[dict[str, Any]]) -> dict[str, float]:
    supported_results = [result for result in results if result["supported"]]
    unsupported_results = [result for result in results if not result["supported"]]
    recipe_results = [result for result in supported_results if result["expected_recipe"]]
    tool_results = [result for result in supported_results if result["expected_tools"]]
    role_results = [result for result in supported_results if result["expected_roles"]]

    return {
        "recipe_recall_at_1": _mean(
            1.0 if result["expected_recipe_recalled_at_1"] else 0.0
            for result in recipe_results
        ),
        "recipe_recall_at_k": _mean(
            1.0 if result["expected_recipe_recalled"] else 0.0
            for result in recipe_results
        ),
        "recipe_mrr": _mean(
            result["expected_recipe_reciprocal_rank"] for result in recipe_results
        ),
        "tool_recall_at_3": _mean(result["tool_recall_at_3"] for result in tool_results),
        "tool_recall_at_5": _mean(result["tool_recall_at_5"] for result in tool_results),
        "tool_recall_at_k": _mean(result["tool_recall"] for result in tool_results),
        "tool_mrr": _mean(
            result["first_expected_tool_reciprocal_rank"] for result in tool_results
        ),
        "role_coverage": _mean(result["role_coverage"] for result in role_results),
        "planner_context_tool_recall": _mean(
            result["planner_context_tool_recall"] for result in tool_results
        ),
        "planner_context_role_coverage": _mean(
            result["planner_context_role_coverage"] for result in role_results
        ),
        "fallback_rate": _rate(
            sum(1 for result in results if result["fallback_used"]),
            len(results),
        ),
        "supported_fallback_rate": _rate(
            sum(1 for result in supported_results if result["fallback_used"]),
            len(supported_results),
        ),
        "unsupported_fallback_rate": _rate(
            sum(1 for result in unsupported_results if result["fallback_used"]),
            len(unsupported_results),
        ),
        "unsupported_direct_match_rate": _rate(
            sum(1 for result in unsupported_results if not result["fallback_used"]),
            len(unsupported_results),
        ),
    }


def _family_metrics(results: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    families: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        families.setdefault(result["workflow_family"], []).append(result)

    metrics: dict[str, dict[str, Any]] = {}
    for family, family_results in sorted(families.items()):
        supported_results = [result for result in family_results if result["supported"]]
        unsupported_results = [result for result in family_results if not result["supported"]]
        metrics[family] = {
            "query_count": len(family_results),
            "supported_query_count": len(supported_results),
            "unsupported_query_count": len(unsupported_results),
            "query_ids": [result["id"] for result in family_results],
            "supported_query_ids": [result["id"] for result in supported_results],
            "unsupported_query_ids": [result["id"] for result in unsupported_results],
            "metrics": _aggregate_metrics(family_results),
        }
    return metrics


def _macro_family_metrics(
    family_metrics: dict[str, dict[str, Any]],
) -> dict[str, float]:
    supported_family_metrics = [
        family["metrics"]
        for family in family_metrics.values()
        if family["supported_query_count"] > 0
    ]
    return {
        metric: _mean(family[metric] for family in supported_family_metrics)
        for metric in MACRO_FAMILY_METRIC_KEYS
    }


def _round_metrics(metrics: dict[str, float]) -> dict[str, float]:
    return {
        metric: round(value, METRIC_PRECISION)
        for metric, value in metrics.items()
    }


def _round_family_metrics(
    family_metrics: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        family_id: {
            **family,
            "metrics": _round_metrics(family["metrics"]),
        }
        for family_id, family in family_metrics.items()
    }


def _round_query_metrics(result: dict[str, Any]) -> dict[str, Any]:
    rounded = dict(result)
    for metric in PER_QUERY_METRIC_KEYS:
        rounded[metric] = round(rounded[metric], METRIC_PRECISION)
    return rounded


def _planner_context_tool_ids(
    retrieved_recipe_ids: list[str],
    retrieved_tool_ids: list[str],
    recipe_catalog: RecipeCatalog,
) -> list[str]:
    tool_ids: list[str] = []
    seen: set[str] = set()
    for tool_id in retrieved_tool_ids:
        if tool_id in seen:
            continue
        tool_ids.append(tool_id)
        seen.add(tool_id)

    for recipe_id in retrieved_recipe_ids:
        try:
            recipe = recipe_catalog.get(recipe_id)
        except KeyError:
            continue
        for step in recipe.steps:
            for tool_id in step.allowed_tools:
                if tool_id in seen:
                    continue
                tool_ids.append(tool_id)
                seen.add(tool_id)
    return tool_ids


def _role_coverage(
    expected_roles: dict[str, list[str]],
    retrieved_tool_ids: list[str],
) -> dict[str, Any]:
    retrieved = set(retrieved_tool_ids)
    covered_roles: list[str] = []
    missed_roles: list[str] = []
    for role, tools in expected_roles.items():
        if any(tool_id in retrieved for tool_id in tools):
            covered_roles.append(role)
        else:
            missed_roles.append(role)
    return {
        "covered_roles": covered_roles,
        "missed_roles": missed_roles,
        "coverage": _rate(len(covered_roles), len(expected_roles)),
    }


def _first_strategy(per_query: list[dict[str, Any]]) -> str | None:
    for result in per_query:
        strategy = result.get("strategy")
        if isinstance(strategy, str):
            return strategy
    return None


def _rank_of(expected: str | None, retrieved_ids: list[str]) -> int | None:
    if expected is None:
        return None
    try:
        return retrieved_ids.index(expected) + 1
    except ValueError:
        return None


def _reciprocal_rank(rank: int | None) -> float:
    return 0.0 if rank is None else 1.0 / rank


def _first_reciprocal_rank(ranks: Iterable[int | None]) -> float:
    concrete_ranks = [rank for rank in ranks if rank is not None]
    if not concrete_ranks:
        return 0.0
    return 1.0 / min(concrete_ranks)


def _rank_recall(ranks: Iterable[int | None], cutoff: int) -> float:
    rank_list = list(ranks)
    return _rate(
        sum(1 for rank in rank_list if rank is not None and rank <= cutoff),
        len(rank_list),
    )


def _mean(values: Any) -> float:
    concrete_values = list(values)
    if not concrete_values:
        return 0.0
    return sum(concrete_values) / len(concrete_values)


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of strings")
    return value


def _expected_roles(value: Any, query_id: str) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError(f"{query_id}: expected_roles must be an object")
    roles: dict[str, list[str]] = {}
    for role, tools in value.items():
        if not isinstance(role, str):
            raise ValueError(f"{query_id}: expected_roles keys must be strings")
        roles[role] = _string_list(tools, f"{query_id}: expected_roles.{role}")
    return roles
