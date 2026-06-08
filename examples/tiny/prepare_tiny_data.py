from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parents[2]

SAMPLES = [
    {"sample_id": "ctrl_1", "condition": "control", "gene_a_pairs": 48, "gene_b_pairs": 12},
    {"sample_id": "ctrl_2", "condition": "control", "gene_a_pairs": 44, "gene_b_pairs": 14},
    {"sample_id": "treat_1", "condition": "treated", "gene_a_pairs": 12, "gene_b_pairs": 48},
    {"sample_id": "treat_2", "condition": "treated", "gene_a_pairs": 14, "gene_b_pairs": 44},
]
TRANSCRIPTS = {
    "tx_gene_a": {
        "gene_id": "gene_a",
        "sequence": (
            "ACGTTGCAAGTCGATCGTACGATGCTAGCTAGGATCCGATGCAACTGATCGTACCTGACT"
            "TACGATCGTAGCTAGTCCGATGACTGACGATCGTACGATCGTAGCATCGATGCTACGATC"
            "GATCGTACGATGCTAGCTAGGATCCGATGCAACTGATCGTACCTGACTTACGATCGTAGC"
            "TAGTCCGATGACTGACGATCGTACGATCGTAGCATCGATGCTACGATCGATCGTACGATG"
        ),
    },
    "tx_gene_b": {
        "gene_id": "gene_b",
        "sequence": (
            "TGCAACGTCAGTACGATCGGATCGTAGCTAGCTACGATCGATGCTAGTCGATCGTAACG"
            "GCTAGCATCGATCGTACGACTGACGTAGCTAGCATCGATGCTAGTCGATCGATGCAACGT"
            "CAGTACGATCGGATCGTAGCTAGCTACGATCGATGCTAGTCGATCGTAACGGCTAGCATC"
            "GATCGTACGACTGACGTAGCTAGCATCGATGCTAGTCGATCGATGCAACGTCAGTACGAT"
        ),
    },
}
READ_LENGTH = 50
CONTAINER_FIXTURE_ROOT = "/fixture"
SALMON_TOOL_ID = "salmon"
SALMON_TOOL_VERSION = "1.9.0"
SALMON_TOOL_PATH = PROJECT_ROOT / "src" / "catalog" / "tools" / SALMON_TOOL_ID / f"{SALMON_TOOL_VERSION}.yaml"
TEMPLATE_PATH = Path(__file__).with_name("rnaseq_deg.inputs.template.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare tiny RNA-seq DEG fixture data for Cromwell e2e tests.")
    parser.add_argument("--fixture-root", required=True, type=Path, help="Directory to create or update.")
    parser.add_argument(
        "--write-inputs",
        type=Path,
        help="Optional path for the rendered Cromwell inputs JSON.",
    )
    parser.add_argument(
        "--cromwell-root",
        help="Cromwell-visible fixture root to render into inputs JSON. Defaults to --fixture-root.",
    )
    parser.add_argument("--kmer-length", default=7, type=int, help="Salmon index k-mer length for tiny transcripts.")
    parser.add_argument(
        "--container-runtime",
        choices=("auto", "docker", "podman"),
        default="auto",
        help="Container runtime used to build the Salmon index from the Catalog image.",
    )
    args = parser.parse_args(argv)

    fixture_root = args.fixture_root.resolve()
    paths = prepare_fixture(
        fixture_root=fixture_root,
        container_runtime=resolve_container_runtime(args.container_runtime),
        salmon_image=load_salmon_image(),
        kmer_length=args.kmer_length,
    )

    if args.write_inputs is not None:
        cromwell_root = args.cromwell_root or fixture_root.as_posix()
        write_inputs_json(args.write_inputs, cromwell_root)
        paths.append(args.write_inputs)

    validate_paths(paths)
    return 0


def prepare_fixture(
    *,
    fixture_root: Path,
    container_runtime: str,
    salmon_image: str,
    kmer_length: int,
) -> list[Path]:
    data_dir = fixture_root / "data"
    reads_dir = data_dir / "reads"
    index_dir = fixture_root / "salmon_index"
    reads_dir.mkdir(parents=True, exist_ok=True)

    transcripts_path = data_dir / "transcripts.fa"
    tx2gene_path = data_dir / "tx2gene.tsv"
    sample_groups_path = data_dir / "sample_groups.tsv"

    write_transcripts(transcripts_path)
    write_tx2gene(tx2gene_path)
    write_sample_groups(sample_groups_path)
    read_paths = write_reads(reads_dir)
    prepare_salmon_index(
        transcripts_path=transcripts_path,
        index_dir=index_dir,
        fixture_root=fixture_root,
        container_runtime=container_runtime,
        salmon_image=salmon_image,
        kmer_length=kmer_length,
    )

    return [
        transcripts_path,
        tx2gene_path,
        sample_groups_path,
        index_dir,
        *read_paths,
    ]


def write_transcripts(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for transcript_id, record in TRANSCRIPTS.items():
            handle.write(f">{transcript_id}\n")
            sequence = record["sequence"]
            for offset in range(0, len(sequence), 80):
                handle.write(sequence[offset : offset + 80] + "\n")


def write_tx2gene(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("TXNAME\tGENEID\n")
        for transcript_id, record in TRANSCRIPTS.items():
            handle.write(f"{transcript_id}\t{record['gene_id']}\n")


def write_sample_groups(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("sample_id\tcondition\n")
        for sample in SAMPLES:
            handle.write(f"{sample['sample_id']}\t{sample['condition']}\n")


def write_reads(reads_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for sample in SAMPLES:
        sample_id = sample["sample_id"]
        r1_path = reads_dir / f"{sample_id}_R1.fastq.gz"
        r2_path = reads_dir / f"{sample_id}_R2.fastq.gz"
        records = []
        records.extend(_read_pairs(sample_id, "tx_gene_a", sample["gene_a_pairs"]))
        records.extend(_read_pairs(sample_id, "tx_gene_b", sample["gene_b_pairs"]))
        _write_fastq_pair(r1_path, r2_path, records)
        paths.extend([r1_path, r2_path])
    return paths


def prepare_salmon_index(
    *,
    transcripts_path: Path,
    index_dir: Path,
    fixture_root: Path,
    container_runtime: str,
    salmon_image: str,
    kmer_length: int,
) -> None:
    if _salmon_index_complete(index_dir):
        return
    if index_dir.exists():
        shutil.rmtree(index_dir)

    index_dir.parent.mkdir(parents=True, exist_ok=True)
    transcripts_in_container = _container_path(fixture_root, transcripts_path)
    index_in_container = _container_path(fixture_root, index_dir)
    command = [
        container_runtime,
        "run",
        "--rm",
        "-e",
        "LC_ALL=C",
        "-e",
        "LANG=C",
        "-e",
        "LANGUAGE=C",
        "-v",
        f"{fixture_root.as_posix()}:{CONTAINER_FIXTURE_ROOT}",
        salmon_image,
        "salmon",
        "index",
        "-t",
        transcripts_in_container,
        "-i",
        index_in_container,
        "-k",
        str(kmer_length),
    ]
    subprocess.run(command, check=True)


def _salmon_index_complete(index_dir: Path) -> bool:
    return (index_dir / "versionInfo.json").is_file()


def load_salmon_image() -> str:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        if exc.name != "yaml":
            raise
        return _load_salmon_image_from_catalog_yaml(SALMON_TOOL_PATH)

    with SALMON_TOOL_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise RuntimeError(f"{SALMON_TOOL_PATH} must contain a YAML mapping")
    runtime = data.get("runtime")
    if not isinstance(runtime, dict):
        raise RuntimeError(f"{SALMON_TOOL_PATH} does not define runtime")
    image = runtime.get("docker")
    if not isinstance(image, str) or not image:
        raise RuntimeError(f"{SALMON_TOOL_PATH} does not define runtime.docker")
    return image


def _load_salmon_image_from_catalog_yaml(path: Path) -> str:
    in_runtime = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw_line == stripped and stripped.endswith(":"):
            in_runtime = stripped == "runtime:"
            continue
        if in_runtime and stripped.startswith("docker:"):
            image = stripped.split(":", 1)[1].strip().strip("\"'")
            if image:
                return image
    raise RuntimeError(f"{path} does not define runtime.docker")


def resolve_container_runtime(selected: str) -> str:
    if selected != "auto":
        runtime = shutil.which(selected)
        if runtime is None:
            raise RuntimeError(f"container runtime is not available on PATH: {selected}")
        return runtime

    for candidate in ("docker", "podman"):
        runtime = shutil.which(candidate)
        if runtime is not None:
            return runtime

    raise RuntimeError("Docker or Podman is required to build the tiny Salmon index from the Catalog image")


def _container_path(fixture_root: Path, path: Path) -> str:
    relative_path = path.resolve().relative_to(fixture_root.resolve()).as_posix()
    return f"{CONTAINER_FIXTURE_ROOT}/{relative_path}"


def write_inputs_json(path: Path, cromwell_root: str) -> None:
    template = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
    rendered = _render_template(template, _normalize_root(cromwell_root))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rendered, indent=2) + "\n", encoding="utf-8")


def validate_paths(paths: list[Path]) -> None:
    missing = [path for path in paths if not path.exists()]
    empty_dirs = [path for path in paths if path.is_dir() and not any(path.iterdir())]
    if missing or empty_dirs:
        details = [f"missing: {path}" for path in missing]
        details.extend(f"empty directory: {path}" for path in empty_dirs)
        raise RuntimeError("tiny fixture validation failed: " + "; ".join(details))


def _read_pairs(sample_id: str, transcript_id: str, count: int) -> list[tuple[str, str, str]]:
    sequence = TRANSCRIPTS[transcript_id]["sequence"]
    max_start = len(sequence) - (READ_LENGTH * 3)
    if max_start <= 0:
        raise ValueError(f"transcript is too short for paired reads: {transcript_id}")

    records = []
    for index in range(count):
        start = (index * 7) % max_start
        r1 = sequence[start : start + READ_LENGTH]
        r2_source = sequence[start + READ_LENGTH + 20 : start + READ_LENGTH + 20 + READ_LENGTH]
        records.append((f"{sample_id}_{transcript_id}_{index:03d}", r1, _reverse_complement(r2_source)))
    return records


def _write_fastq_pair(r1_path: Path, r2_path: Path, records: list[tuple[str, str, str]]) -> None:
    with gzip.open(r1_path, "wt", encoding="utf-8", newline="\n") as r1_handle:
        with gzip.open(r2_path, "wt", encoding="utf-8", newline="\n") as r2_handle:
            for read_id, r1, r2 in records:
                r1_handle.write(_fastq_record(f"{read_id}/1", r1))
                r2_handle.write(_fastq_record(f"{read_id}/2", r2))


def _fastq_record(read_id: str, sequence: str) -> str:
    return f"@{read_id}\n{sequence}\n+\n{'I' * len(sequence)}\n"


def _reverse_complement(sequence: str) -> str:
    table = str.maketrans("ACGT", "TGCA")
    return sequence.translate(table)[::-1]


def _render_template(value: Any, fixture_root: str) -> Any:
    if isinstance(value, str):
        return value.replace("{{ fixture_root }}", fixture_root)
    if isinstance(value, list):
        return [_render_template(item, fixture_root) for item in value]
    if isinstance(value, dict):
        return {key: _render_template(item, fixture_root) for key, item in value.items()}
    return value


def _normalize_root(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized or "/"


if __name__ == "__main__":
    raise SystemExit(main())
