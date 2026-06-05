import os
from collections.abc import Mapping

from src.execution.disabled import DisabledBackend
from src.execution.protocol import ExecutionBackend

BACKEND_ENV_VAR = "AI_BIOWORKFLOW_RUN_BACKEND"
SUPPORTED_BACKENDS = ("disabled", "cromwell", "local-miniwdl")
UNIMPLEMENTED_BACKENDS = {"cromwell", "local-miniwdl"}


def get_execution_backend(name: str | None = None, env: Mapping[str, str] | None = None) -> ExecutionBackend:
    selected = _normalize_backend_name(name if name is not None else _backend_name_from_env(env))

    if selected == "disabled":
        return DisabledBackend()

    if selected in UNIMPLEMENTED_BACKENDS:
        raise ValueError(f"Execution backend '{selected}' is not implemented in phase 2.")

    raise ValueError(
        f"Unknown execution backend '{selected}'. Supported backends: {', '.join(SUPPORTED_BACKENDS)}."
    )


def _backend_name_from_env(env: Mapping[str, str] | None) -> str | None:
    source = os.environ if env is None else env
    return source.get(BACKEND_ENV_VAR)


def _normalize_backend_name(name: str | None) -> str:
    normalized = (name or "disabled").strip().lower()
    return normalized or "disabled"
