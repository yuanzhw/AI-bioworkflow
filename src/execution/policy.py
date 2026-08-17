"""Application-level policy for executing Catalog tools."""

from collections.abc import Iterable

from src.catalog.schema import ToolSpec


class UnverifiedToolExecutionError(ValueError):
    """Raised when real execution includes tools without verification evidence."""


def ensure_tools_execution_eligible(
    tools: Iterable[ToolSpec],
    *,
    allow_unverified: bool = False,
) -> None:
    """Reject unverified tools unless the caller explicitly accepts that risk."""
    if allow_unverified:
        return

    unverified = sorted(
        {
            f"{tool.id}@{tool.version}"
            for tool in tools
            if tool.execution_verification.status == "unverified"
        }
    )
    if not unverified:
        return

    joined = ", ".join(unverified)
    raise UnverifiedToolExecutionError(
        "Execution blocked for unverified Catalog tools: "
        f"{joined}. Set allow_unverified=True to opt in explicitly."
    )
