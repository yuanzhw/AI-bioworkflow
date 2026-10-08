"""Build the deterministic approved Catalog retrieval document corpus."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalog.loader import load_tool_catalog
from src.catalog.retrieval_documents import build_catalog_retrieval_corpus
from src.recipes.loader import load_recipe_catalog


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build versioned retrieval documents from the approved Catalog.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Without it, the artifact is written to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    tool_catalog = load_tool_catalog()
    recipe_catalog = load_recipe_catalog(tool_catalog=tool_catalog)
    corpus = build_catalog_retrieval_corpus(tool_catalog, recipe_catalog)
    serialized = json.dumps(
        corpus.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
    ) + "\n"

    if args.output is None:
        sys.stdout.write(serialized)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
