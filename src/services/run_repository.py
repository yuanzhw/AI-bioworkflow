"""SQLite-backed storage for workflow runs and run events."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from src.api.models import (
    DiagnosticReport,
    RunEvent,
    RunEventType,
    RunStatus,
    WorkflowArtifactSummary,
    WorkflowArtifacts,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / ".cache" / "ai-bioworkflow.sqlite3"
SQLITE_CONNECT_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = 30_000
ARTIFACT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
JSON_CONTENT_TYPE = "application/json"
TEXT_CONTENT_TYPE = "text/plain"
CORE_ARTIFACT_NAMES = {"plan", "workflow_ir", "wdl", "diagnostics"}


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


@dataclass(frozen=True)
class RunArtifactRecord:
    run_id: str
    name: str
    content_type: str
    content: Any
    updated_at: datetime


@dataclass(frozen=True)
class RunDiagnosticSummaryRecord:
    analysis_error_count: int
    analysis_warning_count: int
    repair_action_count: int
    check_performed: bool
    is_valid: bool


@dataclass(frozen=True)
class RunSummaryRecord:
    run: RunRecord
    diagnostic_summary: RunDiagnosticSummaryRecord


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

    def list_runs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: RunStatus | None = None,
    ) -> tuple[list[RunSummaryRecord], int]:
        if limit < 1:
            raise ValueError("limit must be greater than or equal to 1")
        if offset < 0:
            raise ValueError("offset must be greater than or equal to 0")

        filters = []
        params: list[Any] = []
        if status is not None:
            filters.append("runs.status = ?")
            params.append(status.value)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

        with self._connect() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM runs {where_clause}",
                tuple(params),
            ).fetchone()
            rows = connection.execute(
                f"""
                SELECT
                    runs.*,
                    run_diagnostics.analysis_errors_json,
                    run_diagnostics.analysis_warnings_json,
                    run_diagnostics.repair_actions_json,
                    run_diagnostics.check_performed AS diagnostic_check_performed,
                    run_diagnostics.is_valid
                FROM runs
                LEFT JOIN run_diagnostics ON run_diagnostics.run_id = runs.run_id
                {where_clause}
                ORDER BY runs.created_at DESC, runs.run_id DESC
                LIMIT ? OFFSET ?
                """,
                tuple([*params, limit, offset]),
            ).fetchall()

        total = int(total_row["total"]) if total_row is not None else 0
        return [_row_to_run_summary(row) for row in rows], total

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

    def has_event_type(self, run_id: str, event_type: RunEventType) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM run_events
                WHERE run_id = ? AND type = ?
                LIMIT 1
                """,
                (run_id, event_type.value),
            ).fetchone()
        return row is not None

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
                    run_id, catalog_retrieval_json, plan_json, workflow_ir_json, wdl,
                    planner_prompt, planner_raw_response
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    catalog_retrieval_json = excluded.catalog_retrieval_json,
                    plan_json = excluded.plan_json,
                    workflow_ir_json = excluded.workflow_ir_json,
                    wdl = excluded.wdl,
                    planner_prompt = excluded.planner_prompt,
                    planner_raw_response = excluded.planner_raw_response
                """,
                (
                    run_id,
                    _to_json(artifacts.catalog_retrieval),
                    _to_json(artifacts.plan),
                    _to_json(artifacts.workflow_ir),
                    artifacts.wdl,
                    planner_prompt,
                    planner_raw_response,
                ),
            )
            if artifacts.catalog_retrieval is not None:
                self._save_artifact_record(
                    connection,
                    run_id=run_id,
                    name="catalog_retrieval",
                    content=artifacts.catalog_retrieval,
                    content_type=JSON_CONTENT_TYPE,
                )
            if artifacts.plan is not None:
                self._save_artifact_record(
                    connection,
                    run_id=run_id,
                    name="plan",
                    content=artifacts.plan,
                    content_type=JSON_CONTENT_TYPE,
                )
            if artifacts.workflow_ir:
                self._save_artifact_record(
                    connection,
                    run_id=run_id,
                    name="workflow_ir",
                    content=artifacts.workflow_ir,
                    content_type=JSON_CONTENT_TYPE,
                )
            if artifacts.wdl:
                self._save_artifact_record(
                    connection,
                    run_id=run_id,
                    name="wdl",
                    content=artifacts.wdl,
                    content_type=TEXT_CONTENT_TYPE,
                )

    def save_catalog_retrieval_artifact(
        self,
        run_id: str,
        catalog_retrieval: dict[str, Any],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO run_artifacts (
                    run_id, catalog_retrieval_json, plan_json, workflow_ir_json, wdl,
                    planner_prompt, planner_raw_response
                )
                VALUES (?, ?, NULL, '{}', '', NULL, NULL)
                ON CONFLICT(run_id) DO UPDATE SET
                    catalog_retrieval_json = excluded.catalog_retrieval_json
                """,
                (run_id, _to_json(catalog_retrieval)),
            )
            self._save_artifact_record(
                connection,
                run_id=run_id,
                name="catalog_retrieval",
                content=catalog_retrieval,
                content_type=JSON_CONTENT_TYPE,
            )

    def save_plan_artifact(
        self,
        run_id: str,
        plan: dict[str, Any],
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
                VALUES (?, ?, '{}', '', ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    plan_json = excluded.plan_json,
                    planner_prompt = excluded.planner_prompt,
                    planner_raw_response = excluded.planner_raw_response
                """,
                (
                    run_id,
                    _to_json(plan),
                    planner_prompt,
                    planner_raw_response,
                ),
            )
            self._save_artifact_record(
                connection,
                run_id=run_id,
                name="plan",
                content=plan,
                content_type=JSON_CONTENT_TYPE,
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
            self._save_artifact_record(
                connection,
                run_id=run_id,
                name="workflow_ir",
                content=workflow_ir,
                content_type=JSON_CONTENT_TYPE,
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
            self._save_artifact_record(
                connection,
                run_id=run_id,
                name="wdl",
                content=wdl,
                content_type=TEXT_CONTENT_TYPE,
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
            self._save_artifact_record(
                connection,
                run_id=run_id,
                name="diagnostics",
                content=diagnostics.model_dump(mode="json"),
                content_type=JSON_CONTENT_TYPE,
            )

    def save_json_artifact(self, run_id: str, name: str, content: Any) -> None:
        """Persist a named JSON artifact for future orchestration stages."""
        with self._connect() as connection:
            self._save_artifact_record(
                connection,
                run_id=run_id,
                name=name,
                content=content,
                content_type=JSON_CONTENT_TYPE,
            )

    def save_text_artifact(self, run_id: str, name: str, content: str) -> None:
        """Persist a named text artifact for future orchestration stages."""
        with self._connect() as connection:
            self._save_artifact_record(
                connection,
                run_id=run_id,
                name=name,
                content=content,
                content_type=TEXT_CONTENT_TYPE,
            )

    def list_artifact_records(self, run_id: str) -> list[RunArtifactRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM run_artifact_records
                WHERE run_id = ?
                ORDER BY name ASC
                """,
                (run_id,),
            ).fetchall()
        return [_row_to_artifact_record(row) for row in rows]

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

        artifact_records = self.list_artifact_records(run_id)

        return RunSnapshotRecord(
            run=run,
            artifacts=_row_to_artifacts(artifact_row, artifact_records),
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
                    catalog_retrieval_json TEXT,
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

                CREATE TABLE IF NOT EXISTS run_artifact_records (
                    run_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    content_json TEXT,
                    content_text TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, name),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );
                """
            )
            _ensure_column(connection, "run_artifacts", "catalog_retrieval_json", "TEXT")
            self._backfill_artifact_records(connection)

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

    def _save_artifact_record(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        name: str,
        content: Any,
        content_type: str,
        updated_at: datetime | None = None,
        replace_existing: bool = True,
    ) -> None:
        _validate_artifact_name(name)
        if content_type not in {JSON_CONTENT_TYPE, TEXT_CONTENT_TYPE}:
            raise ValueError(f"unsupported artifact content type: {content_type}")

        timestamp = updated_at or _utc_now()
        content_json = _to_json(content) if content_type == JSON_CONTENT_TYPE else None
        content_text = str(content) if content_type == TEXT_CONTENT_TYPE else None
        if replace_existing:
            connection.execute(
                """
                INSERT INTO run_artifact_records (
                    run_id, name, content_type, content_json, content_text, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, name) DO UPDATE SET
                    content_type = excluded.content_type,
                    content_json = excluded.content_json,
                    content_text = excluded.content_text,
                    updated_at = excluded.updated_at
                """,
                (
                    run_id,
                    name,
                    content_type,
                    content_json,
                    content_text,
                    _dt_to_text(timestamp),
                ),
            )
            return

        connection.execute(
            """
            INSERT OR IGNORE INTO run_artifact_records (
                run_id, name, content_type, content_json, content_text, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                name,
                content_type,
                content_json,
                content_text,
                _dt_to_text(timestamp),
            ),
        )

    def _backfill_artifact_records(self, connection: sqlite3.Connection) -> None:
        artifact_rows = connection.execute(
            """
            SELECT run_artifacts.*, runs.updated_at AS artifact_updated_at
            FROM run_artifacts
            JOIN runs ON runs.run_id = run_artifacts.run_id
            """
        ).fetchall()
        for row in artifact_rows:
            updated_at = _dt_from_text(row["artifact_updated_at"])
            catalog_retrieval = _from_json(row["catalog_retrieval_json"])
            plan = _from_json(row["plan_json"])
            workflow_ir = _from_json(row["workflow_ir_json"]) or {}
            wdl = row["wdl"] or ""
            if catalog_retrieval is not None:
                self._save_artifact_record(
                    connection,
                    run_id=row["run_id"],
                    name="catalog_retrieval",
                    content=catalog_retrieval,
                    content_type=JSON_CONTENT_TYPE,
                    updated_at=updated_at,
                    replace_existing=False,
                )
            if plan is not None:
                self._save_artifact_record(
                    connection,
                    run_id=row["run_id"],
                    name="plan",
                    content=plan,
                    content_type=JSON_CONTENT_TYPE,
                    updated_at=updated_at,
                    replace_existing=False,
                )
            if workflow_ir:
                self._save_artifact_record(
                    connection,
                    run_id=row["run_id"],
                    name="workflow_ir",
                    content=workflow_ir,
                    content_type=JSON_CONTENT_TYPE,
                    updated_at=updated_at,
                    replace_existing=False,
                )
            if wdl:
                self._save_artifact_record(
                    connection,
                    run_id=row["run_id"],
                    name="wdl",
                    content=wdl,
                    content_type=TEXT_CONTENT_TYPE,
                    updated_at=updated_at,
                    replace_existing=False,
                )

        diagnostic_rows = connection.execute(
            """
            SELECT run_diagnostics.*, runs.updated_at AS artifact_updated_at
            FROM run_diagnostics
            JOIN runs ON runs.run_id = run_diagnostics.run_id
            """
        ).fetchall()
        for row in diagnostic_rows:
            diagnostics = DiagnosticReport(
                analysis_errors=_from_json(row["analysis_errors_json"]) or [],
                analysis_warnings=_from_json(row["analysis_warnings_json"]) or [],
                repair_actions=_from_json(row["repair_actions_json"]) or [],
                validation_message=row["validation_message"] or "",
                is_valid=bool(row["is_valid"]),
                succeeded=bool(row["succeeded"]),
                check_performed=bool(row["check_performed"]),
            )
            self._save_artifact_record(
                connection,
                run_id=row["run_id"],
                name="diagnostics",
                content=diagnostics.model_dump(mode="json"),
                content_type=JSON_CONTENT_TYPE,
                updated_at=_dt_from_text(row["artifact_updated_at"]),
                replace_existing=False,
            )


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


def _row_to_run_summary(row: sqlite3.Row) -> RunSummaryRecord:
    return RunSummaryRecord(
        run=_row_to_run(row),
        diagnostic_summary=RunDiagnosticSummaryRecord(
            analysis_error_count=_json_list_length(row["analysis_errors_json"]),
            analysis_warning_count=_json_list_length(row["analysis_warnings_json"]),
            repair_action_count=_json_list_length(row["repair_actions_json"]),
            check_performed=bool(
                row["diagnostic_check_performed"]
                if row["diagnostic_check_performed"] is not None
                else row["check_performed"]
            ),
            is_valid=bool(row["is_valid"]) if row["is_valid"] is not None else False,
        ),
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


def _row_to_artifact_record(row: sqlite3.Row) -> RunArtifactRecord:
    content_type = row["content_type"]
    if content_type == JSON_CONTENT_TYPE:
        content = _from_json(row["content_json"])
    elif content_type == TEXT_CONTENT_TYPE:
        content = row["content_text"] or ""
    else:
        content = row["content_text"] or row["content_json"] or ""

    return RunArtifactRecord(
        run_id=row["run_id"],
        name=row["name"],
        content_type=content_type,
        content=content,
        updated_at=_dt_from_text(row["updated_at"]),
    )


def _row_to_artifacts(
    row: sqlite3.Row | None,
    artifact_records: list[RunArtifactRecord],
) -> WorkflowArtifacts:
    record_by_name = {record.name: record for record in artifact_records}
    catalog_retrieval = _artifact_record_content(record_by_name, "catalog_retrieval")
    plan = _artifact_record_content(record_by_name, "plan")
    workflow_ir = _artifact_record_content(record_by_name, "workflow_ir") or {}
    wdl = _artifact_record_content(record_by_name, "wdl") or ""

    if row is not None:
        catalog_retrieval = _from_json(row["catalog_retrieval_json"])
        plan = _from_json(row["plan_json"])
        workflow_ir = _from_json(row["workflow_ir_json"]) or {}
        wdl = row["wdl"] or ""

    return WorkflowArtifacts(
        catalog_retrieval=catalog_retrieval if isinstance(catalog_retrieval, dict) else None,
        plan=plan if isinstance(plan, dict) else None,
        workflow_ir=workflow_ir if isinstance(workflow_ir, dict) else {},
        wdl=wdl if isinstance(wdl, str) else "",
        extras={
            record.name: record.content
            for record in artifact_records
            if record.name not in CORE_ARTIFACT_NAMES
        },
        manifest=[
            WorkflowArtifactSummary(
                name=record.name,
                content_type=record.content_type,
                updated_at=record.updated_at,
            )
            for record in artifact_records
        ],
    )


def _artifact_record_content(
    record_by_name: dict[str, RunArtifactRecord],
    name: str,
) -> Any:
    record = record_by_name.get(name)
    return record.content if record is not None else None


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


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _json_list_length(value: str | None) -> int:
    parsed = _from_json(value)
    return len(parsed) if isinstance(parsed, list) else 0


def _validate_artifact_name(name: str) -> None:
    if not ARTIFACT_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "artifact name must start with a lowercase letter and contain only "
            "lowercase letters, numbers, and underscores"
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _dt_to_text(value: datetime) -> str:
    return value.isoformat()


def _dt_from_text(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _missing_run(run_id: str) -> RunRecord:
    raise KeyError(f"run was not created: {run_id}")
