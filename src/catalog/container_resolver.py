from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from src.catalog.schema import ToolSpec


@dataclass(frozen=True)
class ContainerImageCandidate:
    image: str
    source: str = "static"


class ContainerResolutionError(ValueError):
    pass


class ContainerImageNotFoundError(ContainerResolutionError):
    pass


class AmbiguousContainerImageError(ContainerResolutionError):
    pass


class ContainerImageProvider(Protocol):
    def search(
        self,
        tool_id: str,
        version: str,
        aliases: Sequence[str] = (),
    ) -> Sequence[ContainerImageCandidate]:
        ...


ImageCandidateInput = str | ContainerImageCandidate


class StaticContainerImageProvider:
    """Offline provider used by tests and deterministic local development."""

    def __init__(self, images: Mapping[tuple[str, str], Sequence[ImageCandidateInput]]):
        self._images = {
            key: tuple(_coerce_candidate(candidate) for candidate in candidates)
            for key, candidates in images.items()
        }

    def search(
        self,
        tool_id: str,
        version: str,
        aliases: Sequence[str] = (),
    ) -> Sequence[ContainerImageCandidate]:
        return list(self._images.get((tool_id, version), ()))


def static_provider_from_image_map(
    images: Mapping[str, str | Sequence[ImageCandidateInput]],
) -> StaticContainerImageProvider:
    normalized: dict[tuple[str, str], list[ImageCandidateInput]] = {}
    for key, candidates in images.items():
        tool_id, version = parse_tool_version_key(key)
        if isinstance(candidates, str) or isinstance(candidates, ContainerImageCandidate):
            candidate_values = [candidates]
        else:
            candidate_values = list(candidates)
        normalized[(tool_id, version)] = candidate_values
    return StaticContainerImageProvider(normalized)


def parse_tool_version_key(key: str) -> tuple[str, str]:
    if "@" not in key:
        raise ValueError(f"container image key must use '<tool>@<version>': {key!r}")

    tool_id, version = key.split("@", 1)
    if not tool_id or not version:
        raise ValueError(f"container image key must use '<tool>@<version>': {key!r}")
    return tool_id, version


def resolve_tool_container(
    tool: ToolSpec,
    provider: ContainerImageProvider,
) -> str:
    """Return the docker image for a tool, consulting the provider only when missing."""
    if tool.runtime.docker:
        return tool.runtime.docker

    candidates = list(provider.search(tool.id, tool.version, aliases=tool.aliases))
    if not candidates:
        raise ContainerImageNotFoundError(
            f"no container image found for tool '{tool.id}@{tool.version}'"
        )
    if len(candidates) > 1:
        images = ", ".join(candidate.image for candidate in candidates)
        raise AmbiguousContainerImageError(
            f"multiple container images found for tool '{tool.id}@{tool.version}': {images}"
        )

    return candidates[0].image


def fill_missing_tool_container(
    tool: ToolSpec,
    provider: ContainerImageProvider,
) -> ToolSpec:
    """Return a ToolSpec with runtime.docker populated when it is missing."""
    if tool.runtime.docker:
        return tool

    docker = resolve_tool_container(tool, provider)
    runtime = tool.runtime.model_copy(update={"docker": docker})
    return tool.model_copy(update={"runtime": runtime})


def _coerce_candidate(candidate: ImageCandidateInput) -> ContainerImageCandidate:
    if isinstance(candidate, ContainerImageCandidate):
        return candidate
    return ContainerImageCandidate(image=candidate)
