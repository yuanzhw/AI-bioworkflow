import os
from collections.abc import Mapping

from src.execution.cromwell import (
    DEFAULT_CROMWELL_URL,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    CromwellBackend,
)
from src.execution.disabled import DisabledBackend
from src.execution.protocol import ExecutionBackend

BACKEND_ENV_VAR = "AI_BIOWORKFLOW_RUN_BACKEND"
CROMWELL_URL_ENV_VAR = "CROMWELL_URL"
CROMWELL_POLL_INTERVAL_ENV_VAR = "CROMWELL_POLL_INTERVAL_SECONDS"
CROMWELL_TIMEOUT_ENV_VAR = "CROMWELL_TIMEOUT_SECONDS"
SUPPORTED_BACKENDS = ("disabled", "cromwell", "local-miniwdl")
UNIMPLEMENTED_BACKENDS = {"local-miniwdl"}


def get_execution_backend(name: str | None = None, env: Mapping[str, str] | None = None) -> ExecutionBackend:
    selected = _normalize_backend_name(name if name is not None else _backend_name_from_env(env))

    if selected == "disabled":
        return DisabledBackend()

    if selected == "cromwell":
        source = os.environ if env is None else env
        return CromwellBackend(
            base_url=_string_from_env(source, CROMWELL_URL_ENV_VAR, DEFAULT_CROMWELL_URL),
            poll_interval_seconds=_float_from_env(
                source,
                CROMWELL_POLL_INTERVAL_ENV_VAR,
                DEFAULT_POLL_INTERVAL_SECONDS,
            ),
            timeout_seconds=_float_from_env(source, CROMWELL_TIMEOUT_ENV_VAR, DEFAULT_TIMEOUT_SECONDS),
        )

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


def _string_from_env(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _float_from_env(env: Mapping[str, str], name: str, default: float) -> float:
    raw_value = env.get(name)
    if raw_value is None or raw_value.strip() == "":
        return default

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc

    if value < 0:
        raise ValueError(f"{name} must be non-negative.")
    return value
