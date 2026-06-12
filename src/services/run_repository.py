"""SQLite-backed storage for workflow runs and run events."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from src.api.models import DiagnosticReport, RunEvent, RunEventType, RunStatus, WorkflowArtifacts


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / ".cache" / "ai-bioworkflow.sqlite3"
SQLITE_CONNECT_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = 30_000


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    kind: str
    status: RunStatus
    request: str | dict[str, Any] | None
    check_performed: bool
    events_url: str
    planner_model: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class RunSnapshotRecord:
    run: RunRecord
    artifacts: WorkflowArtifacts
    diagnostics: DiagnosticReport


class RunRepository:
    """Store run snapshots and append-only run events in SQLite."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or default_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def create_run(
        self,
        *,
        run_id: str,
        kind: str,
        request: str | dict[str, Any] | None,
        check_performed: bool,
        events_url: str,
        planner_model: str | None = None,
    ) -> RunRecord:
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, kind, status, request_json, check_performed,
                    events_url, planner_model, created_at, updated_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    run_id,
                    kind,
                    RunStatus.CREATED.value,
                    _to_json(request),
                    int(check_performed),
                    events_url,
                    planner_model,
                    _dt_to_text(now),
                    _dt_to_text(now),
                ),
            )
        return self.get_run(run_id) or _missing_run(run_id)

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return _row_to_run(row) if row is not None else None

    def update_status(self, run_id: str, status: RunStatus) -> None:
        completed_at = _utc_now() if status in {RunStatus.SUCCEEDED, RunStatus.FAILED} else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = ?, updated_at = ?, completed_at = COALESCE(?, completed_at)
                WHERE run_id = ?
                """,
                (
                    status.value,
                    _dt_to_text(_utc_now()),
                    _dt_to_text(completed_at) if completed_at else None,
                    run_id,
                ),
            )

    def append_event(
        self,
        *,
        run_id: str,
        event_type: RunEventType,
        summary: str,
        node: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RunEvent:
        timestamp = _utc_now()
        with self._connect() as connection:
            event = self._append_event(
                connection,
                run_id=run_id,
                event_type=event_type,
                timestamp=timestamp,
                summary=summary,
                node=node,
                payload=payload,
            )
            connection.execute(
                "UPDATE runs SET updated_at = ? WHERE run_id = ?",
                (_dt_to_text(timestamp), run_id),
            )
        return event

    def complete_run(
        self,
        *,
        run_id: str,
        status: RunStatus,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> RunEvent:
        if status not in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            raise ValueError(f"terminal run status required, got {status.value}")

        timestamp = _utc_now()
        with self._connect() as connection:
            event = self._append_event(
                connection,
                run_id=run_id,
                event_type=RunEventType.RUN_COMPLETED,
                timestamp=timestamp,
                summary=summary,
                payload=payload,
            )
            connection.execute(
                """
                UPDATE runs
                SET status = ?, updated_at = ?, completed_at = ?
                WHERE run_id = ?
                """,
                (
                    status.value,
                    _dt_to_text(timestamp),
                    _dt_to_text(timestamp),
                    run_id,
                ),
            )
        return event

    def list_events(self, run_id: str, after_sequence: int = 0) -> list[RunEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM run_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (run_id, after_sequence),
            ).fetchall()
        return [_row_to_event(row) for row in rows]

    def save_artifacts(
        self,
        run_id: str,
        artifacts: WorkflowArtifacts,
        *,
        planner_prompt: str | None = None,
        planner_raw_response: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO run_artifacts (
                    run_id, plan_json, workflow_ir_json, wdl,
                    planner_prompt, planner_raw_response
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    plan_json = excluded.plan_json,
                    workflow_ir_json = excluded.workflow_ir_json,
                    wdl = excluded.wdl,
                    planner_prompt = excluded.planner_prompt,
                    planner_raw_response = excluded.planner_raw_response
                """,
                (
                    run_id,
                    _to_json(artifacts.plan),
                    _to_json(artifacts.workflow_ir),
                    artifacts.wdl,
                    planner_prompt,
                    planner_raw_response,
                ),
            )

    def save_workflow_ir_artifact(self, run_id: str, workflow_ir: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO run_artifacts (
                    run_id, plan_json, workflow_ir_json, wdl,
                    planner_prompt, planner_raw_response
                )
                VALUES (?, NULL, ?, '', NULL, NULL)
                ON CONFLICT(run_id) DO UPDATE SET
                    workflow_ir_json = excluded.workflow_ir_json
                """,
                (run_id, _to_json(workflow_ir)),
            )

    def save_wdl_artifact(self, run_id: str, wdl: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO run_artifacts (
                    run_id, plan_json, workflow_ir_json, wdl,
                    planner_prompt, planner_raw_response
                )
                VALUES (?, NULL, '{}', ?, NULL, NULL)
                ON CONFLICT(run_id) DO UPDATE SET
                    wdl = excluded.wdl
                """,
                (run_id, wdl),
            )

    def save_diagnostics(self, run_id: str, diagnostics: DiagnosticReport) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO run_diagnostics (
                    run_id, analysis_errors_json, analysis_warnings_json,
                    repair_actions_json, validation_message, is_valid,
                    succeeded, check_performed
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    analysis_errors_json = excluded.analysis_errors_json,
                    analysis_warnings_json = excluded.analysis_warnings_json,
                    repair_actions_json = excluded.repair_actions_json,
                    validation_message = excluded.validation_message,
                    is_valid = excluded.is_valid,
                    succeeded = excluded.succeeded,
                    check_performed = excluded.check_performed
                """,
                (
                    run_id,
                    _to_json(diagnostics.analysis_errors),
                    _to_json(diagnostics.analysis_warnings),
                    _to_json(diagnostics.repair_actions),
                    diagnostics.validation_message,
                    int(diagnostics.is_valid),
                    int(diagnostics.succeeded),
                    int(diagnostics.check_performed),
                ),
            )

    def get_snapshot(self, run_id: str) -> RunSnapshotRecord | None:
        run = self.get_run(run_id)
        if run is None:
            return None

        with self._connect() as connection:
            artifact_row = connection.execute(
                "SELECT * FROM run_artifacts WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            diagnostic_row = connection.execute(
                "SELECT * FROM run_diagnostics WHERE run_id = ?",
                (run_id,),
            ).fetchone()

        return RunSnapshotRecord(
            run=run,
            artifacts=_row_to_artifacts(artifact_row),
            diagnostics=_row_to_diagnostics(diagnostic_row, check_performed=run.check_performed),
        )

    def ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT,
                    check_performed INTEGER NOT NULL,
                    events_url TEXT NOT NULL,
                    planner_model TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS run_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    node TEXT,
                    timestamp TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(run_id, sequence),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS run_artifacts (
                    run_id TEXT PRIMARY KEY,
                    plan_json TEXT,
                    workflow_ir_json TEXT NOT NULL,
                    wdl TEXT NOT NULL,
                    planner_prompt TEXT,
                    planner_raw_response TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS run_diagnostics (
                    run_id TEXT PRIMARY KEY,
                    analysis_errors_json TEXT NOT NULL,
                    analysis_warnings_json TEXT NOT NULL,
                    repair_actions_json TEXT NOT NULL,
                    validation_message TEXT NOT NULL,
                    is_valid INTEGER NOT NULL,
                    succeeded INTEGER NOT NULL,
                    check_performed INTEGER NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=SQLITE_CONNECT_TIMEOUT_SECONDS)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _next_sequence(connection: sqlite3.Connection, run_id: str) -> int:
        row = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM run_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row["next_sequence"])

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        event_type: RunEventType,
        timestamp: datetime,
        summary: str,
        node: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RunEvent:
        next_sequence = self._next_sequence(connection, run_id)
        event = RunEvent(
            event_id=f"{run_id}_evt_{next_sequence:06d}",
            run_id=run_id,
            sequence=next_sequence,
            type=event_type,
            timestamp=timestamp,
            summary=summary,
            node=node,
            payload=payload or {},
        )
        connection.execute(
            """
            INSERT INTO run_events (
                event_id, run_id, sequence, type, node, timestamp, summary, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.run_id,
                event.sequence,
                event.type.value,
                event.node,
                _dt_to_text(event.timestamp),
                event.summary,
                _to_json(event.payload),
            ),
        )
        return event


def default_db_path() -> Path:
    configured = os.environ.get("AI_BIOWORKFLOW_DB_PATH")
    return Path(configured).expanduser() if configured else DEFAULT_DB_PATH


def _row_to_run(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        kind=row["kind"],
        status=RunStatus(row["status"]),
        request=_from_json(row["request_json"]),
        check_performed=bool(row["check_performed"]),
        events_url=row["events_url"],
        planner_model=row["planner_model"],
        created_at=_dt_from_text(row["created_at"]),
        updated_at=_dt_from_text(row["updated_at"]),
        completed_at=_dt_from_text(row["completed_at"]) if row["completed_at"] else None,
    )


def _row_to_event(row: sqlite3.Row) -> RunEvent:
    return RunEvent(
        event_id=row["event_id"],
        run_id=row["run_id"],
        sequence=row["sequence"],
        type=RunEventType(row["type"]),
        timestamp=_dt_from_text(row["timestamp"]),
        summary=row["summary"],
        node=row["node"],
        payload=_from_json(row["payload_json"]) or {},
    )


def _row_to_artifacts(row: sqlite3.Row | None) -> WorkflowArtifacts:
    if row is None:
        return WorkflowArtifacts()
    return WorkflowArtifacts(
        plan=_from_json(row["plan_json"]),
        workflow_ir=_from_json(row["workflow_ir_json"]) or {},
        wdl=row["wdl"] or "",
    )


def _row_to_diagnostics(row: sqlite3.Row | None, *, check_performed: bool) -> DiagnosticReport:
    if row is None:
        return DiagnosticReport(check_performed=check_performed)
    return DiagnosticReport(
        analysis_errors=_from_json(row["analysis_errors_json"]) or [],
        analysis_warnings=_from_json(row["analysis_warnings_json"]) or [],
        repair_actions=_from_json(row["repair_actions_json"]) or [],
        validation_message=row["validation_message"] or "",
        is_valid=bool(row["is_valid"]),
        succeeded=bool(row["succeeded"]),
        check_performed=bool(row["check_performed"]),
    )


def _to_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _from_json(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _dt_to_text(value: datetime) -> str:
    return value.isoformat()


def _dt_from_text(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _missing_run(run_id: str) -> RunRecord:
    raise KeyError(f"run was not created: {run_id}")
