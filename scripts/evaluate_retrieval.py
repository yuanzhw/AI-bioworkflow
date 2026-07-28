"""Run the approved catalog retriever evaluation fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalog.loader import load_tool_catalog
from src.catalog.retrieval_eval import (
    DEFAULT_TOP_K_RECIPES,
    DEFAULT_TOP_K_TOOLS,
    evaluate_retrieval_queries,
    load_retrieval_queries,
)
from src.recipes.loader import load_recipe_catalog


DEFAULT_QUERY_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "retrieval_queries.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate approved catalog retrieval against labeled query fixtures.",
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=DEFAULT_QUERY_FIXTURE,
        help=f"Path to retrieval query fixture. Default: {DEFAULT_QUERY_FIXTURE}",
    )
    parser.add_argument(
        "--top-k-recipes",
        type=int,
        default=DEFAULT_TOP_K_RECIPES,
        help=f"Recipe Recall@K cutoff. Default: {DEFAULT_TOP_K_RECIPES}",
    )
    parser.add_argument(
        "--top-k-tools",
        type=int,
        default=DEFAULT_TOP_K_TOOLS,
        help=f"Tool Recall@K cutoff. Default: {DEFAULT_TOP_K_TOOLS}",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional path to write the full JSON evaluation artifact.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full JSON evaluation artifact instead of a summary.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tool_catalog = load_tool_catalog()
    recipe_catalog = load_recipe_catalog(tool_catalog=tool_catalog)
    queries = load_retrieval_queries(args.queries)
    evaluation = evaluate_retrieval_queries(
        queries,
        tool_catalog,
        recipe_catalog,
        top_k_recipes=args.top_k_recipes,
        top_k_tools=args.top_k_tools,
    )

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(evaluation, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(evaluation, indent=2, ensure_ascii=False))
    else:
        print(_format_summary(evaluation))
    return 0


def _format_summary(evaluation: dict[str, Any]) -> str:
    metrics = evaluation["metrics"]
    lines = [
        f"Retrieval strategy: {evaluation['strategy']}",
        (
            f"Queries: {evaluation['query_count']} "
            f"({evaluation['supported_query_count']} supported, "
            f"{evaluation['unsupported_query_count']} unsupported)"
        ),
        f"Recipe Recall@{evaluation['top_k_recipes']}: {metrics['recipe_recall_at_k']:.4f}",
        f"Recipe MRR: {metrics['recipe_mrr']:.4f}",
        f"Tool Recall@{evaluation['top_k_tools']}: {metrics['tool_recall_at_k']:.4f}",
        f"Tool MRR: {metrics['tool_mrr']:.4f}",
        f"Role Coverage: {metrics['role_coverage']:.4f}",
        f"Planner Context Tool Recall: {metrics['planner_context_tool_recall']:.4f}",
        f"Planner Context Role Coverage: {metrics['planner_context_role_coverage']:.4f}",
        f"Fallback Rate: {metrics['fallback_rate']:.4f}",
        f"Supported Fallback Rate: {metrics['supported_fallback_rate']:.4f}",
        f"Unsupported Fallback Rate: {metrics['unsupported_fallback_rate']:.4f}",
    ]

    if evaluation["fallback_query_ids"]:
        lines.append("Fallback queries: " + ", ".join(evaluation["fallback_query_ids"]))
    if evaluation["unsupported_direct_match_query_ids"]:
        lines.append(
            "Unsupported direct-match queries: "
            + ", ".join(evaluation["unsupported_direct_match_query_ids"])
        )

    missed = [
        result
        for result in evaluation["queries"]
        if result["missed_expected_recipe"] or result["missed_expected_tools"] or result["missed_roles"]
    ]
    if missed:
        lines.append("Misses:")
        for result in missed:
            details: list[str] = []
            if result["missed_expected_recipe"]:
                details.append(f"recipe={result['missed_expected_recipe']}")
            if result["missed_expected_tools"]:
                details.append("tools=" + ",".join(result["missed_expected_tools"]))
            if result["missed_roles"]:
                details.append("roles=" + ",".join(result["missed_roles"]))
            lines.append(f"  - {result['id']}: " + "; ".join(details))

    planner_context_missed = [
        result
        for result in evaluation["queries"]
        if (
            result["planner_context_missed_expected_tools"]
            or result["planner_context_missed_roles"]
        )
    ]
    if planner_context_missed:
        lines.append("Planner context misses:")
        for result in planner_context_missed:
            details = []
            if result["planner_context_missed_expected_tools"]:
                details.append("tools=" + ",".join(result["planner_context_missed_expected_tools"]))
            if result["planner_context_missed_roles"]:
                details.append("roles=" + ",".join(result["planner_context_missed_roles"]))
            lines.append(f"  - {result['id']}: " + "; ".join(details))

    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
