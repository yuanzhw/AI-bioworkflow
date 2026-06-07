from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Protocol

import requests

from src.execution.protocol import BackendAvailability, ExecutionResult


DEFAULT_CROMWELL_URL = "http://localhost:8000"
DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_TIMEOUT_SECONDS = 1800.0
REQUEST_TIMEOUT_SECONDS = 30.0
TERMINAL_STATUSES = {"Succeeded", "Failed", "Aborted"}


class ResponseLike(Protocol):
    status_code: int

    def json(self) -> Any:
        ...


class RequestsSessionLike(Protocol):
    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ResponseLike:
        ...

    def post(
        self,
        url: str,
        *,
        files: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> ResponseLike:
        ...


class CromwellBackend:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_CROMWELL_URL,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        session: RequestsSessionLike | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be non-negative")
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")

        self.base_url = base_url.rstrip("/")
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self._session = session or requests.Session()
        self._sleep = sleep
        self._monotonic = monotonic

    def availability(self) -> BackendAvailability:
        try:
            response = self._session.get(
                self._url("/engine/v1/status"),
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return BackendAvailability(False, f"Cromwell status check failed: {exc}")

        if not _is_success(response):
            return BackendAvailability(
                False,
                f"Cromwell status check failed with HTTP {response.status_code}{_response_preview(response)}",
            )

        try:
            _decode_json_object(response, "Cromwell status response")
        except ValueError as exc:
            return BackendAvailability(False, str(exc))

        return BackendAvailability(True)

    def run(
        self,
        wdl_path: Path,
        inputs_path: Path,
        *,
        options_path: Path | None = None,
        dependencies_path: Path | None = None,
        labels_path: Path | None = None,
    ) -> ExecutionResult:
        availability = self.availability()
        if not availability.available:
            return ExecutionResult(
                succeeded=False,
                message=f"Cromwell backend is unavailable: {availability.reason}",
            )

        try:
            submit_response = self._submit_workflow(
                wdl_path,
                inputs_path,
                options_path=options_path,
                dependencies_path=dependencies_path,
                labels_path=labels_path,
            )
        except Exception as exc:
            return ExecutionResult(succeeded=False, message=f"Cromwell workflow submit failed: {exc}")

        if not _is_success(submit_response):
            return ExecutionResult(
                succeeded=False,
                message=f"Cromwell workflow submit failed with HTTP {submit_response.status_code}"
                f"{_response_preview(submit_response)}",
            )

        try:
            submit_payload = _decode_json_object(submit_response, "Cromwell submit response")
        except ValueError as exc:
            return ExecutionResult(succeeded=False, message=str(exc))

        workflow_id = submit_payload.get("id")
        if not isinstance(workflow_id, str) or not workflow_id:
            return ExecutionResult(
                succeeded=False,
                status=_string_or_none(submit_payload.get("status")),
                message="Cromwell submit response did not include workflow id.",
            )

        return self._poll_until_terminal(workflow_id, _string_or_none(submit_payload.get("status")))

    def _submit_workflow(
        self,
        wdl_path: Path,
        inputs_path: Path,
        *,
        options_path: Path | None,
        dependencies_path: Path | None,
        labels_path: Path | None,
    ) -> ResponseLike:
        with ExitStack() as stack:
            files = {
                "workflowSource": (wdl_path.name, stack.enter_context(wdl_path.open("rb")), "text/plain"),
                "workflowInputs": (inputs_path.name, stack.enter_context(inputs_path.open("rb")), "application/json"),
            }
            if options_path is not None:
                files["workflowOptions"] = (
                    options_path.name,
                    stack.enter_context(options_path.open("rb")),
                    "application/json",
                )
            if dependencies_path is not None:
                files["workflowDependencies"] = (
                    dependencies_path.name,
                    stack.enter_context(dependencies_path.open("rb")),
                    "application/zip",
                )
            if labels_path is not None:
                files["labels"] = (labels_path.name, stack.enter_context(labels_path.open("rb")), "application/json")

            return self._session.post(
                self._url("/api/workflows/v1"),
                files=files,
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

    def _poll_until_terminal(self, workflow_id: str, initial_status: str | None) -> ExecutionResult:
        deadline = self._monotonic() + self.timeout_seconds
        status = initial_status

        while True:
            status_payload, status_error = self._request_json(
                "GET",
                f"/api/workflows/v1/{workflow_id}/status",
                "Cromwell workflow status response",
            )
            if status_error is not None:
                return ExecutionResult(
                    succeeded=False,
                    workflow_id=workflow_id,
                    status=status,
                    message=status_error,
                )

            status = _string_or_none(status_payload.get("status"))
            if status is None:
                return ExecutionResult(
                    succeeded=False,
                    workflow_id=workflow_id,
                    message="Cromwell workflow status response did not include status.",
                )

            if status in TERMINAL_STATUSES:
                return self._terminal_result(workflow_id, status)

            if self._monotonic() >= deadline:
                metadata = self._fetch_metadata(workflow_id)
                return ExecutionResult(
                    succeeded=False,
                    workflow_id=workflow_id,
                    status=status,
                    metadata=metadata,
                    message=(
                        f"Cromwell workflow {workflow_id} timed out after "
                        f"{self.timeout_seconds:g} seconds with last status {status}."
                    ),
                )

            if self.poll_interval_seconds > 0:
                remaining = max(0.0, deadline - self._monotonic())
                self._sleep(min(self.poll_interval_seconds, remaining))

    def _terminal_result(self, workflow_id: str, status: str) -> ExecutionResult:
        outputs = self._fetch_outputs(workflow_id)
        metadata = self._fetch_metadata(workflow_id)
        succeeded = status == "Succeeded"
        return ExecutionResult(
            succeeded=succeeded,
            workflow_id=workflow_id,
            status=status,
            outputs=outputs,
            metadata=metadata,
            message="" if succeeded else _failure_message(workflow_id, status, metadata),
        )

    def _fetch_outputs(self, workflow_id: str) -> dict[str, Any]:
        payload, _ = self._request_json(
            "GET",
            f"/api/workflows/v1/{workflow_id}/outputs",
            "Cromwell workflow outputs response",
        )
        outputs = payload.get("outputs")
        return outputs if isinstance(outputs, dict) else payload

    def _fetch_metadata(self, workflow_id: str) -> dict[str, Any]:
        payload, _ = self._request_json(
            "GET",
            f"/api/workflows/v1/{workflow_id}/metadata",
            "Cromwell workflow metadata response",
        )
        return payload

    def _request_json(self, method: str, path: str, context: str) -> tuple[dict[str, Any], str | None]:
        try:
            response = self._request(method, self._url(path))
        except Exception as exc:
            return {}, f"{context} failed: {exc}"

        if not _is_success(response):
            return (
                {},
                f"{context} failed with HTTP {response.status_code}{_response_preview(response)}",
            )

        try:
            return _decode_json_object(response, context), None
        except ValueError as exc:
            return {}, str(exc)

    def _request(self, method: str, url: str) -> ResponseLike:
        if method == "GET":
            return self._session.get(url, headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT_SECONDS)
        raise ValueError(f"Unsupported Cromwell HTTP method: {method}")

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"


def _decode_json_object(response: ResponseLike, context: str) -> dict[str, Any]:
    try:
        decoded = response.json()
    except ValueError as exc:
        raise ValueError(f"{context} was not valid JSON: {exc}") from exc

    if not isinstance(decoded, dict):
        raise ValueError(f"{context} JSON was not an object.")
    return decoded


def _failure_message(workflow_id: str, status: str, metadata: Mapping[str, Any]) -> str:
    summary = _metadata_failure_summary(metadata)
    if summary:
        return f"Cromwell workflow {workflow_id} finished with status {status}: {summary}"
    return f"Cromwell workflow {workflow_id} finished with status {status}."


def _metadata_failure_summary(metadata: Mapping[str, Any]) -> str:
    failures = metadata.get("failures")
    if isinstance(failures, list):
        summary = _first_failure_summary(failures)
        if summary:
            return summary

    calls = metadata.get("calls")
    if isinstance(calls, dict):
        for call_name, attempts in calls.items():
            if not isinstance(attempts, list):
                continue
            call_failures = []
            for attempt in attempts:
                if not isinstance(attempt, dict):
                    continue
                attempt_failures = attempt.get("failures", [])
                if isinstance(attempt_failures, list):
                    call_failures.extend(attempt_failures)
            summary = _first_failure_summary(call_failures)
            if summary:
                stderr = _first_stderr(attempts)
                return f"{call_name}: {summary}" + (f" stderr: {stderr}" if stderr else "")

    return ""


def _first_failure_summary(failures: Iterable[Any]) -> str:
    for failure in failures:
        if isinstance(failure, dict):
            message = failure.get("message")
            if isinstance(message, str) and message:
                return message
        elif isinstance(failure, str) and failure:
            return failure
    return ""


def _first_stderr(attempts: Sequence[Any]) -> str:
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        stderr = attempt.get("stderr")
        if isinstance(stderr, str) and stderr:
            return stderr
    return ""


def _is_success(response: ResponseLike) -> bool:
    return 200 <= response.status_code < 300


def _response_preview(response: ResponseLike) -> str:
    text = getattr(response, "text", "")
    if not isinstance(text, str):
        text = ""
    if not text:
        content = getattr(response, "content", b"")
        if isinstance(content, bytes):
            text = content.decode("utf-8", errors="replace")
    text = text.strip()
    return f": {text[:200]}" if text else "."


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None
