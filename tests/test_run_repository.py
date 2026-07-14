import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from src.api.models import DiagnosticReport, RunEventType, RunStatus, WorkflowArtifacts
from src.services.run_repository import SQLITE_BUSY_TIMEOUT_MS, RunRepository


class RunRepositoryTests(unittest.TestCase):
    def test_repository_persists_run_events_artifacts_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")

            run = repository.create_run(
                run_id="run_001",
                kind="structured_compile",
                request={"workflow": {"name": "Demo"}},
                check_performed=False,
                events_url="/api/runs/run_001/events",
            )
            self.assertEqual(run.status, RunStatus.CREATED)

            created = repository.append_event(
                run_id="run_001",
                event_type=RunEventType.RUN_CREATED,
                summary="Run created.",
            )
            started = repository.append_event(
                run_id="run_001",
                event_type=RunEventType.NODE_STARTED,
                node="ir_normalizer",
                summary="IR normalizer started.",
            )

            self.assertEqual(created.sequence, 1)
            self.assertEqual(started.sequence, 2)

            repository.save_artifacts(
                "run_001",
                WorkflowArtifacts(
                    catalog_retrieval={"strategy": "lexical_v1"},
                    plan={"workflow": {"recipe": "demo"}},
                    workflow_ir={"workflow": {"name": "Demo"}},
                    wdl="version 1.0\nworkflow Demo {}",
                ),
            )
            repository.save_diagnostics(
                "run_001",
                DiagnosticReport(
                    validation_message="WDL syntax validation skipped (--no-check).",
                    succeeded=True,
                    check_performed=False,
                ),
            )
            repository.update_status("run_001", RunStatus.SUCCEEDED)

            snapshot = repository.get_snapshot("run_001")
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.run.status, RunStatus.SUCCEEDED)
            self.assertEqual(snapshot.artifacts.catalog_retrieval, {"strategy": "lexical_v1"})
            self.assertEqual(snapshot.artifacts.workflow_ir["workflow"]["name"], "Demo")
            manifest = {artifact.name: artifact for artifact in snapshot.artifacts.manifest}
            self.assertEqual(manifest["catalog_retrieval"].content_type, "application/json")
            self.assertEqual(manifest["plan"].content_type, "application/json")
            self.assertEqual(manifest["workflow_ir"].content_type, "application/json")
            self.assertEqual(manifest["wdl"].content_type, "text/plain")
            self.assertEqual(manifest["diagnostics"].content_type, "application/json")
            self.assertTrue(snapshot.diagnostics.succeeded)
            self.assertFalse(snapshot.diagnostics.check_performed)

            events = repository.list_events("run_001")
            self.assertEqual([event.sequence for event in events], [1, 2])
            self.assertEqual(events[1].node, "ir_normalizer")

            artifact_records = repository.list_artifact_records("run_001")
            self.assertEqual(
                {record.name for record in artifact_records},
                {"catalog_retrieval", "diagnostics", "plan", "wdl", "workflow_ir"},
            )
            wdl_record = next(record for record in artifact_records if record.name == "wdl")
            self.assertIn("workflow Demo", wdl_record.content)

    def test_has_event_type_checks_event_existence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")
            repository.create_run(
                run_id="run_001",
                kind="structured_compile",
                request={},
                check_performed=False,
                events_url="/api/runs/run_001/events",
            )

            self.assertFalse(repository.has_event_type("run_001", RunEventType.NODE_FAILED))

            repository.append_event(
                run_id="run_001",
                event_type=RunEventType.NODE_STARTED,
                node="compiler",
                summary="Workflow compiler started.",
            )
            self.assertFalse(repository.has_event_type("run_001", RunEventType.NODE_FAILED))

            repository.append_event(
                run_id="run_001",
                event_type=RunEventType.NODE_FAILED,
                node="compiler",
                summary="Workflow compiler failed.",
            )
            self.assertTrue(repository.has_event_type("run_001", RunEventType.NODE_FAILED))

    def test_repository_returns_none_for_unknown_run_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")

            self.assertIsNone(repository.get_snapshot("missing"))

    def test_snapshot_reads_artifact_records_without_public_list_helper(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")
            repository.create_run(
                run_id="run_001",
                kind="natural_language",
                request="Run demo.",
                check_performed=False,
                events_url="/api/runs/run_001/events",
            )
            repository.save_json_artifact("run_001", "catalog_retrieval", {"strategy": "lexical_v1"})

            with patch.object(
                repository,
                "list_artifact_records",
                side_effect=AssertionError("snapshot should read artifact records in its own connection"),
            ):
                snapshot = repository.get_snapshot("run_001")

            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.artifacts.extras["catalog_retrieval"]["strategy"], "lexical_v1")

    def test_partial_artifact_updates_preserve_existing_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")
            repository.create_run(
                run_id="run_001",
                kind="natural_language",
                request="Run demo.",
                check_performed=False,
                events_url="/api/runs/run_001/events",
            )
            repository.save_artifacts(
                "run_001",
                WorkflowArtifacts(
                    catalog_retrieval={"strategy": "lexical_v1"},
                    plan={"workflow": {"recipe": "demo"}},
                    workflow_ir={"workflow": {"name": "OldDemo"}},
                    wdl="version 1.0\nworkflow OldDemo {}",
                ),
            )

            repository.save_workflow_ir_artifact("run_001", {"workflow": {"name": "Demo"}})
            repository.save_wdl_artifact("run_001", "version 1.0\nworkflow Demo {}")

            snapshot = repository.get_snapshot("run_001")
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.artifacts.catalog_retrieval, {"strategy": "lexical_v1"})
            self.assertEqual(snapshot.artifacts.plan, {"workflow": {"recipe": "demo"}})
            self.assertEqual(snapshot.artifacts.workflow_ir["workflow"]["name"], "Demo")
            self.assertIn("workflow Demo", snapshot.artifacts.wdl)
            self.assertIn("workflow_ir", {artifact.name for artifact in snapshot.artifacts.manifest})
            self.assertIn("wdl", {artifact.name for artifact in snapshot.artifacts.manifest})

    def test_named_records_override_legacy_fixed_columns_in_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")
            repository.create_run(
                run_id="run_001",
                kind="natural_language",
                request="Run demo.",
                check_performed=False,
                events_url="/api/runs/run_001/events",
            )
            repository.save_artifacts(
                "run_001",
                WorkflowArtifacts(
                    catalog_retrieval={"strategy": "legacy"},
                    plan={"workflow": {"recipe": "legacy"}},
                    workflow_ir={"workflow": {"name": "LegacyDemo"}},
                    wdl="version 1.0\nworkflow LegacyDemo {}",
                ),
            )

            repository.save_json_artifact("run_001", "catalog_retrieval", {"strategy": "record"})
            repository.save_json_artifact("run_001", "plan", {"workflow": {"recipe": "record"}})
            repository.save_json_artifact("run_001", "workflow_ir", {})
            repository.save_text_artifact("run_001", "wdl", "")

            snapshot = repository.get_snapshot("run_001")
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.artifacts.catalog_retrieval, {"strategy": "record"})
            self.assertEqual(snapshot.artifacts.extras["catalog_retrieval"], {"strategy": "record"})
            self.assertEqual(snapshot.artifacts.plan, {"workflow": {"recipe": "record"}})
            self.assertEqual(snapshot.artifacts.workflow_ir, {})
            self.assertEqual(snapshot.artifacts.wdl, "")

    def test_named_extra_artifacts_are_exposed_in_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")
            repository.create_run(
                run_id="run_001",
                kind="natural_language",
                request="Run demo.",
                check_performed=False,
                events_url="/api/runs/run_001/events",
            )

            retrieval = {
                "strategy": "lexical_v1",
                "recipes": [{"id": "rnaseq_differential_expression"}],
            }
            repository.save_json_artifact("run_001", "catalog_retrieval", retrieval)

            snapshot = repository.get_snapshot("run_001")
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.artifacts.extras["catalog_retrieval"], retrieval)
            manifest = {artifact.name: artifact for artifact in snapshot.artifacts.manifest}
            self.assertEqual(manifest["catalog_retrieval"].content_type, "application/json")

            with self.assertRaisesRegex(ValueError, "artifact name"):
                repository.save_json_artifact("run_001", "Bad-Name", {})

    def test_schema_backfills_named_artifacts_from_legacy_fixed_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "runs.sqlite3"
            timestamp = datetime(2026, 6, 16, tzinfo=UTC).isoformat()
            connection = sqlite3.connect(db_path)
            try:
                connection.executescript(
                    """
                    CREATE TABLE runs (
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

                    CREATE TABLE run_events (
                        event_id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        type TEXT NOT NULL,
                        node TEXT,
                        timestamp TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        UNIQUE(run_id, sequence)
                    );

                    CREATE TABLE run_artifacts (
                        run_id TEXT PRIMARY KEY,
                        plan_json TEXT,
                        workflow_ir_json TEXT NOT NULL,
                        wdl TEXT NOT NULL,
                        planner_prompt TEXT,
                        planner_raw_response TEXT
                    );

                    CREATE TABLE run_diagnostics (
                        run_id TEXT PRIMARY KEY,
                        analysis_errors_json TEXT NOT NULL,
                        analysis_warnings_json TEXT NOT NULL,
                        repair_actions_json TEXT NOT NULL,
                        validation_message TEXT NOT NULL,
                        is_valid INTEGER NOT NULL,
                        succeeded INTEGER NOT NULL,
                        check_performed INTEGER NOT NULL
                    );
                    """
                )
                connection.execute(
                    """
                    INSERT INTO runs (
                        run_id, kind, status, request_json, check_performed,
                        events_url, planner_model, created_at, updated_at, completed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                    """,
                    (
                        "run_legacy",
                        "structured_compile",
                        "succeeded",
                        json.dumps({"workflow": {"recipe": "demo"}}),
                        0,
                        "/api/runs/run_legacy/events",
                        timestamp,
                        timestamp,
                        timestamp,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO run_artifacts (
                        run_id, plan_json, workflow_ir_json, wdl,
                        planner_prompt, planner_raw_response
                    )
                    VALUES (?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        "run_legacy",
                        json.dumps({"workflow": {"recipe": "demo"}}),
                        json.dumps({"workflow": {"name": "Demo"}}),
                        "version 1.0\nworkflow Demo {}",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO run_diagnostics (
                        run_id, analysis_errors_json, analysis_warnings_json,
                        repair_actions_json, validation_message, is_valid,
                        succeeded, check_performed
                    )
                    VALUES (?, '[]', '[]', '[]', ?, 0, 1, 0)
                    """,
                    ("run_legacy", "WDL syntax validation skipped (--no-check)."),
                )
                connection.commit()
            finally:
                connection.close()

            repository = RunRepository(db_path)
            records = repository.list_artifact_records("run_legacy")

            self.assertEqual(
                {record.name for record in records},
                {"diagnostics", "plan", "wdl", "workflow_ir"},
            )
            snapshot = repository.get_snapshot("run_legacy")
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.artifacts.workflow_ir["workflow"]["name"], "Demo")
            self.assertEqual(len(snapshot.artifacts.manifest), 4)

            with patch.object(RunRepository, "_backfill_artifact_records") as backfill:
                RunRepository(db_path)
            backfill.assert_not_called()

    def test_catalog_retrieval_artifact_update_preserves_later_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")
            repository.create_run(
                run_id="run_001",
                kind="natural_language",
                request="Run demo.",
                check_performed=False,
                events_url="/api/runs/run_001/events",
            )

            repository.save_catalog_retrieval_artifact(
                "run_001",
                {"strategy": "lexical_v1", "recipes": [{"id": "demo"}]},
            )
            repository.save_plan_artifact("run_001", {"workflow": {"recipe": "demo"}})

            snapshot = repository.get_snapshot("run_001")
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.artifacts.catalog_retrieval["strategy"], "lexical_v1")
            self.assertEqual(snapshot.artifacts.plan, {"workflow": {"recipe": "demo"}})

    def test_schema_migration_adds_catalog_retrieval_column(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "runs.sqlite3"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE run_artifacts (
                        run_id TEXT PRIMARY KEY,
                        plan_json TEXT,
                        workflow_ir_json TEXT NOT NULL,
                        wdl TEXT NOT NULL,
                        planner_prompt TEXT,
                        planner_raw_response TEXT
                    )
                    """
                )
                connection.commit()
            finally:
                connection.close()

            repository = RunRepository(db_path)

            with repository._connect() as connection:
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(run_artifacts)").fetchall()
                }

            self.assertIn("catalog_retrieval_json", columns)

    def test_complete_run_persists_terminal_event_and_status_together(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")
            repository.create_run(
                run_id="run_001",
                kind="structured_compile",
                request={},
                check_performed=False,
                events_url="/api/runs/run_001/events",
            )
            repository.append_event(
                run_id="run_001",
                event_type=RunEventType.RUN_CREATED,
                summary="Run created.",
            )

            completed = repository.complete_run(
                run_id="run_001",
                status=RunStatus.SUCCEEDED,
                summary="Run succeeded.",
                payload={"status": "succeeded"},
            )

            snapshot = repository.get_snapshot("run_001")
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.run.status, RunStatus.SUCCEEDED)
            self.assertIsNotNone(snapshot.run.completed_at)
            self.assertEqual(completed.type, RunEventType.RUN_COMPLETED)

            events = repository.list_events("run_001")
            self.assertEqual(events[-1].type, RunEventType.RUN_COMPLETED)
            self.assertEqual(events[-1].payload["status"], "succeeded")

    def test_list_runs_returns_paginated_summaries_with_status_filter(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")

            repository.create_run(
                run_id="run_failed",
                kind="structured_compile",
                request={"workflow": {"recipe": "bad_recipe"}},
                check_performed=False,
                events_url="/api/runs/run_failed/events",
            )
            repository.save_diagnostics(
                "run_failed",
                DiagnosticReport(
                    analysis_errors=["missing input"],
                    analysis_warnings=["unused output"],
                    repair_actions=["reordered calls"],
                    validation_message="missing input",
                    is_valid=False,
                    succeeded=False,
                    check_performed=False,
                ),
            )
            repository.complete_run(
                run_id="run_failed",
                status=RunStatus.FAILED,
                summary="Run failed.",
            )

            repository.create_run(
                run_id="run_succeeded",
                kind="structured_compile",
                request={"workflow": {"recipe": "rnaseq_differential_expression"}},
                check_performed=True,
                events_url="/api/runs/run_succeeded/events",
            )
            repository.save_diagnostics(
                "run_succeeded",
                DiagnosticReport(
                    validation_message="valid WDL",
                    is_valid=True,
                    succeeded=True,
                    check_performed=True,
                ),
            )
            repository.complete_run(
                run_id="run_succeeded",
                status=RunStatus.SUCCEEDED,
                summary="Run succeeded.",
            )

            first_page, total = repository.list_runs(limit=1)
            self.assertEqual(total, 2)
            self.assertEqual(len(first_page), 1)
            self.assertEqual(first_page[0].run.run_id, "run_succeeded")
            self.assertTrue(first_page[0].diagnostic_summary.is_valid)

            second_page, _ = repository.list_runs(limit=1, offset=1)
            self.assertEqual(second_page[0].run.run_id, "run_failed")

            failed_runs, failed_total = repository.list_runs(status=RunStatus.FAILED)
            self.assertEqual(failed_total, 1)
            self.assertEqual(failed_runs[0].run.run_id, "run_failed")
            self.assertEqual(failed_runs[0].diagnostic_summary.analysis_error_count, 1)
            self.assertEqual(failed_runs[0].diagnostic_summary.analysis_warning_count, 1)
            self.assertEqual(failed_runs[0].diagnostic_summary.repair_action_count, 1)
            self.assertFalse(failed_runs[0].diagnostic_summary.check_performed)

    def test_sqlite_connection_uses_wal_and_busy_timeout(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")

            with repository._connect() as connection:
                journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
                busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

            self.assertEqual(journal_mode.lower(), "wal")
            self.assertEqual(busy_timeout, SQLITE_BUSY_TIMEOUT_MS)


if __name__ == "__main__":
    unittest.main()
