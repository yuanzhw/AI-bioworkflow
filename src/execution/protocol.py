from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class BackendAvailability:
    available: bool
    reason: str = ""


@dataclass
class ExecutionResult:
    succeeded: bool
    workflow_id: str | None = None
    status: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    message: str = ""


class ExecutionBackend(Protocol):
    def availability(self) -> BackendAvailability:
        ...

    def run(
        self,
        wdl_path: Path,
        inputs_path: Path,
        *,
        options_path: Path | None = None,
        dependencies_path: Path | None = None,
        labels_path: Path | None = None,
    ) -> ExecutionResult:
        ...
