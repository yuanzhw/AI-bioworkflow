from pathlib import Path

from src.execution.protocol import BackendAvailability, ExecutionResult


class DisabledBackend:
    def availability(self) -> BackendAvailability:
        return BackendAvailability(
            available=False,
            reason="WDL execution backend is disabled. Set AI_BIOWORKFLOW_RUN_BACKEND to an implemented backend.",
        )

    def run(
        self,
        wdl_path: Path,
        inputs_path: Path,
        *,
        options_path: Path | None = None,
        dependencies_path: Path | None = None,
        labels_path: Path | None = None,
    ) -> ExecutionResult:
        raise RuntimeError("WDL execution backend is disabled")
