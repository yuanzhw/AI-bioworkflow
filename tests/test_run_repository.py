import tempfile
import unittest
from pathlib import Path

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
            self.assertEqual(snapshot.artifacts.workflow_ir["workflow"]["name"], "Demo")
            self.assertTrue(snapshot.diagnostics.succeeded)
            self.assertFalse(snapshot.diagnostics.check_performed)

            events = repository.list_events("run_001")
            self.assertEqual([event.sequence for event in events], [1, 2])
            self.assertEqual(events[1].node, "ir_normalizer")

    def test_repository_returns_none_for_unknown_run_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = RunRepository(Path(temp_dir) / "runs.sqlite3")

            self.assertIsNone(repository.get_snapshot("missing"))

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
