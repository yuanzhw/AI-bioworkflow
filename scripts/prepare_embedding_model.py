"""Explicitly download the pinned vector_v1 model and write its local manifest."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.catalog.vector_retrieval import (DEFAULT_EMBEDDING_MODEL_ID,
                                          DEFAULT_EMBEDDING_MODEL_REVISION,
                                          EMBEDDING_MODEL_MANIFEST_FILENAME,
                                          embedding_model_manifest)

DEFAULT_MODEL_OUTPUT = (
    PROJECT_ROOT / ".cache" / "models" / "multilingual-e5-small"
)
MODEL_ALLOW_PATTERNS = (
    "1_Pooling/*",
    "*.json",
    "*.model",
    "model.safetensors",
)
SnapshotDownloader = Callable[..., str]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Explicitly prepare the pinned local multilingual embedding model. "
            "This is the only project command that downloads model files."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_MODEL_OUTPUT,
        help=f"Local model directory. Default: {DEFAULT_MODEL_OUTPUT}",
    )
    return parser.parse_args(argv)


def prepare_embedding_model(
    output: Path,
    *,
    downloader: SnapshotDownloader | None = None,
) -> dict[str, Any]:
    """Download one pinned snapshot through an explicitly invoked command."""
    if downloader is None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "model preparation requires the optional vector dependencies; run "
                "'uv sync --extra vector'"
            ) from exc
        downloader = snapshot_download

    model_path = output.expanduser().resolve()
    model_path.mkdir(parents=True, exist_ok=True)
    manifest_path = model_path / EMBEDDING_MODEL_MANIFEST_FILENAME
    manifest_path.unlink(missing_ok=True)
    try:
        downloader(
            repo_id=DEFAULT_EMBEDDING_MODEL_ID,
            revision=DEFAULT_EMBEDDING_MODEL_REVISION,
            local_dir=str(model_path),
            allow_patterns=list(MODEL_ALLOW_PATTERNS),
            token=False,
        )
    except Exception as exc:
        raise RuntimeError(
            "failed to download the pinned embedding model snapshot"
        ) from exc

    manifest = embedding_model_manifest().model_dump(mode="json")
    pending_manifest_path = manifest_path.with_name(f".{manifest_path.name}.tmp")
    pending_manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    pending_manifest_path.replace(manifest_path)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = prepare_embedding_model(args.output)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
