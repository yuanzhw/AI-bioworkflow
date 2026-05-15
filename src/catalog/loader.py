from pathlib import Path

import yaml

from src.catalog.schema import ToolSpec


DEFAULT_TOOL_DIR = Path(__file__).parent / "tools"


class ToolCatalog:
    def __init__(self, tools: dict[tuple[str, str], ToolSpec]):
        self._tools = tools

    def get(self, tool_id: str, version: str) -> ToolSpec:
        key = (tool_id, version)
        if key not in self._tools:
            raise KeyError(f"unknown tool version: {tool_id}@{version}")
        return self._tools[key]

    def has_tool_id(self, tool_id: str) -> bool:
        return any(candidate_id == tool_id for candidate_id, _version in self._tools)

    def versions(self, tool_id: str) -> list[str]:
        return sorted(version for candidate_id, version in self._tools if candidate_id == tool_id)

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())


def load_tool_catalog(root: str | Path = DEFAULT_TOOL_DIR) -> ToolCatalog:
    root_path = Path(root)
    tools: dict[tuple[str, str], ToolSpec] = {}

    for yaml_path in sorted(root_path.rglob("*.yaml")):
        spec = ToolSpec.model_validate(_load_yaml(yaml_path))
        key = (spec.id, spec.version)
        if key in tools:
            raise ValueError(f"duplicate tool definition: {spec.id}@{spec.version}")
        tools[key] = spec

    return ToolCatalog(tools)


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return data
