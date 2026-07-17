#!/usr/bin/env python

from __future__ import annotations

import argparse
import gzip
from pathlib import Path


def main() -> int:
    args = parse_args()
    mappings = extract_tx2gene(args.annotation_gtf)
    if not mappings:
        raise SystemExit("no transcript_id/gene_id pairs found in GTF")

    with args.output.open("w", encoding="utf-8", newline="") as handle:
        handle.write("TXNAME\tGENEID\n")
        for transcript_id, gene_id in sorted(mappings):
            handle.write(f"{transcript_id}\t{gene_id}\n")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract a tx2gene table from a GTF file.")
    parser.add_argument("--annotation-gtf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def extract_tx2gene(path: Path) -> set[tuple[str, str]]:
    mappings: set[tuple[str, str]] = set()
    with open_text(path) as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 9:
                continue
            attributes = parse_gtf_attributes(fields[8])
            transcript_id = attributes.get("transcript_id")
            gene_id = attributes.get("gene_id")
            if transcript_id and gene_id:
                mappings.add((transcript_id, gene_id))
    return mappings


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def parse_gtf_attributes(value: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for raw_part in value.split(";"):
        part = raw_part.strip()
        if not part:
            continue
        if " " not in part:
            continue
        key, raw_value = part.split(None, 1)
        attributes[key] = raw_value.strip().strip('"')
    return attributes


if __name__ == "__main__":
    raise SystemExit(main())
