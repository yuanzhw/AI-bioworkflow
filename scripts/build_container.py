#!/usr/bin/env python
"""Build, smoke-test, and optionally push project-maintained containers."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_IMAGE_PREFIX = "ghcr.io/yuanzhw/ai-bioworkflow"


@dataclass(frozen=True)
class ContainerSpec:
    tool: str
    version: str
    context_dir: Path

    @property
    def dockerfile(self) -> Path:
        return self.context_dir / "Dockerfile"

    @property
    def smoke_test(self) -> Path:
        return self.context_dir / "smoke_test.sh"

    def image(self, image_prefix: str) -> str:
        return f"{image_prefix.rstrip('/')}/{self.tool}:{self.version}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    containers_root = repo_root / "containers"

    specs = select_specs(
        containers_root=containers_root,
        all_containers=args.all,
        tool=args.tool,
        version=args.version,
    )

    for spec in specs:
        image = spec.image(args.image_prefix)
        build_image(spec, image, args)
        if not args.skip_smoke:
            run_smoke_test(spec, image, args)
        if args.push:
            push_image(image, args)

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build, smoke-test, and optionally push containers under containers/<tool>/<version>.",
    )
    parser.add_argument("tool", nargs="?", help="Tool name, for example tximport.")
    parser.add_argument("version", nargs="?", help="Tool version, for example 1.30.0.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Build every container directory that contains a Dockerfile.",
    )
    parser.add_argument(
        "--image-prefix",
        default=DEFAULT_IMAGE_PREFIX,
        help=f"Image prefix to tag builds with. Default: {DEFAULT_IMAGE_PREFIX}",
    )
    parser.add_argument(
        "--platform",
        help="Optional platform forwarded to docker build, for example linux/amd64.",
    )
    parser.add_argument(
        "--docker",
        default="docker",
        help="Docker-compatible executable to run. Default: docker",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push images after a successful build and smoke test.",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Skip smoke_test.sh. Use only for troubleshooting build issues.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print docker commands without running them.",
    )
    args = parser.parse_args(argv)

    if args.all and (args.tool or args.version):
        parser.error("--all cannot be combined with positional tool/version arguments")
    if not args.all and (not args.tool or not args.version):
        parser.error("provide TOOL VERSION, or use --all")

    return args


def select_specs(
    *,
    containers_root: Path,
    all_containers: bool,
    tool: str | None,
    version: str | None,
) -> list[ContainerSpec]:
    if all_containers:
        specs = discover_specs(containers_root)
        if not specs:
            raise SystemExit(f"No container Dockerfiles found under {containers_root}")
        return specs

    assert tool is not None
    assert version is not None
    spec = ContainerSpec(
        tool=tool,
        version=version,
        context_dir=containers_root / tool / version,
    )
    validate_spec(spec)
    return [spec]


def discover_specs(containers_root: Path) -> list[ContainerSpec]:
    specs: list[ContainerSpec] = []
    for tool_dir in sorted(path for path in containers_root.iterdir() if path.is_dir()):
        for version_dir in sorted(path for path in tool_dir.iterdir() if path.is_dir()):
            spec = ContainerSpec(
                tool=tool_dir.name,
                version=version_dir.name,
                context_dir=version_dir,
            )
            if spec.dockerfile.exists():
                validate_spec(spec)
                specs.append(spec)
    return specs


def validate_spec(spec: ContainerSpec) -> None:
    if not spec.context_dir.exists():
        raise SystemExit(f"Container directory not found: {spec.context_dir}")
    if not spec.dockerfile.exists():
        raise SystemExit(f"Dockerfile not found: {spec.dockerfile}")
    if not spec.smoke_test.exists():
        raise SystemExit(f"smoke_test.sh not found: {spec.smoke_test}")


def build_image(spec: ContainerSpec, image: str, args: argparse.Namespace) -> None:
    command = [
        args.docker,
        "build",
        "--build-arg",
        f"TOOL_NAME={spec.tool}",
        "--build-arg",
        f"TOOL_VERSION={spec.version}",
        "-t",
        image,
    ]
    if args.platform:
        command.extend(["--platform", args.platform])
    command.append(str(spec.context_dir))
    run(command, dry_run=args.dry_run)


def run_smoke_test(spec: ContainerSpec, image: str, args: argparse.Namespace) -> None:
    command = [
        args.docker,
        "run",
        "--rm",
        "-v",
        f"{spec.smoke_test.resolve()}:/tmp/smoke_test.sh:ro",
        image,
        "bash",
        "/tmp/smoke_test.sh",
    ]
    run(command, dry_run=args.dry_run)


def push_image(image: str, args: argparse.Namespace) -> None:
    run([args.docker, "push", image], dry_run=args.dry_run)


def run(command: list[str], *, dry_run: bool) -> None:
    print(format_command(command))
    if dry_run:
        return
    subprocess.run(command, check=True)


def format_command(command: list[str]) -> str:
    return " ".join(quote_arg(part) for part in command)


def quote_arg(value: str) -> str:
    if not value or any(char.isspace() for char in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {format_command(exc.cmd)}", file=sys.stderr)
        raise SystemExit(exc.returncode)
