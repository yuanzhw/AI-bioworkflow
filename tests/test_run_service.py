import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.api.models import CompileWorkflowRequest, NaturalLanguageRunRequest, RunEventType, RunStatus, WorkflowArtifacts
from src.nl_planner import NaturalLanguagePlanningError
from src.services.run_repository import RunRepository
from src.services.run_service import RunService


EXAMPLES_DIR = Path(__file__).parents[1] / "examples"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


class RunServiceTests(unittest.TestCase):
    def test_structured_compile_run_succeeds_and_records_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            request = CompileWorkflowRequest(
                payload=load_example("rnaseq_deg_recipe_plan.json"),
                check=False,
            )

            accepted = service.create_structured_compile_run(request)
            service.execute_structured_compile_run(accepted.run_id, request)

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.status, RunStatus.SUCCEEDED)
            self.assertEqual(snapshot.artifacts.workflow_ir["workflow"]["name"], "RNASeqDEG")
            self.assertIn("workflow RNASeqDEG", snapshot.artifacts.wdl)
            self.assertTrue(snapshot.diagnostics.succeeded)

            events = service.get_events(accepted.run_id)
            self.assertIsNotNone(events)
            assert events is not None
            event_types = [event.type for event in events]
            self.assertIn(RunEventType.RUN_CREATED, event_types)
            self.assertIn(RunEventType.ARTIFACT_UPDATED, event_types)
            self.assertEqual(events[-1].type, RunEventType.RUN_COMPLETED)

    def test_structured_compile_run_failure_is_persisted_as_failed_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            plan = load_example("rnaseq_deg_recipe_plan.json")
            plan["workflow"]["inputs"].pop("sample_groups")
            request = CompileWorkflowRequest(payload=plan, check=False)

            accepted = service.create_structured_compile_run(request)
            service.execute_structured_compile_run(accepted.run_id, request)

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.status, RunStatus.FAILED)
            self.assertFalse(snapshot.diagnostics.succeeded)
            self.assertIn("sample_groups", "\n".join(snapshot.diagnostics.analysis_errors))

    def test_structured_compile_exception_records_compiler_failure_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            request = CompileWorkflowRequest(
                payload=load_example("rnaseq_deg_recipe_plan.json"),
                check=False,
            )

            with patch(
                "src.services.run_service.workflow_service.compile_structured_workflow",
                side_effect=RuntimeError("compiler exploded"),
            ):
                accepted = service.create_structured_compile_run(request)
                service.execute_structured_compile_run(accepted.run_id, request)

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.status, RunStatus.FAILED)
            self.assertIsNone(snapshot.artifacts.plan)
            self.assertIn("compiler exploded", snapshot.diagnostics.validation_message)

            events = service.get_events(accepted.run_id)
            self.assertIsNotNone(events)
            assert events is not None
            compiler_failures = [
                event for event in events if event.type == RunEventType.NODE_FAILED and event.node == "compiler"
            ]
            self.assertEqual(len(compiler_failures), 1)
            self.assertEqual(compiler_failures[0].payload["error"], "compiler exploded")
            self.assertEqual(events[-1].type, RunEventType.RUN_COMPLETED)

    def test_natural_language_run_succeeds_after_planning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            plan = load_example("rnaseq_deg_recipe_plan.json")
            request = NaturalLanguageRunRequest(request="Run RNA-seq DEG.", check=False)
            plan_result = SimpleNamespace(
                plan=plan,
                planner_prompt="planner prompt",
                raw_response=json.dumps(plan),
            )

            with patch("src.services.run_service.create_natural_language_plan", return_value=plan_result):
                accepted = service.create_natural_language_run(request)
                service.execute_natural_language_run(accepted.run_id, request)

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.status, RunStatus.SUCCEEDED)
            self.assertEqual(snapshot.artifacts.plan, plan)
            self.assertIn("workflow RNASeqDEG", snapshot.artifacts.wdl)

    def test_natural_language_compile_exception_preserves_planner_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            plan = load_example("rnaseq_deg_recipe_plan.json")
            request = NaturalLanguageRunRequest(request="Run RNA-seq DEG.", check=False)
            plan_result = SimpleNamespace(
                plan=plan,
                planner_prompt="planner prompt",
                raw_response=json.dumps(plan),
            )

            with (
                patch("src.services.run_service.create_natural_language_plan", return_value=plan_result),
                patch(
                    "src.services.run_service.workflow_service.compile_structured_workflow",
                    side_effect=RuntimeError("compiler exploded"),
                ),
            ):
                accepted = service.create_natural_language_run(request)
                service.execute_natural_language_run(accepted.run_id, request)

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.status, RunStatus.FAILED)
            self.assertEqual(snapshot.artifacts.plan, plan)
            self.assertIn("compiler exploded", snapshot.diagnostics.validation_message)

            events = service.get_events(accepted.run_id)
            self.assertIsNotNone(events)
            assert events is not None
            compiler_failures = [
                event for event in events if event.type == RunEventType.NODE_FAILED and event.node == "compiler"
            ]
            self.assertEqual(len(compiler_failures), 1)
            self.assertEqual(compiler_failures[0].payload["error"], "compiler exploded")
            self.assertEqual(events[-1].type, RunEventType.RUN_COMPLETED)

    def test_natural_language_planner_error_is_persisted_as_failed_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            request = NaturalLanguageRunRequest(request="Run RNA-seq DEG.", check=False)

            with patch(
                "src.services.run_service.create_natural_language_plan",
                side_effect=NaturalLanguagePlanningError("LLM planner JSON parsing failed"),
            ):
                accepted = service.create_natural_language_run(request)
                service.execute_natural_language_run(accepted.run_id, request)

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.status, RunStatus.FAILED)
            self.assertIn("LLM planner JSON parsing failed", snapshot.diagnostics.validation_message)

            events = service.get_events(accepted.run_id)
            self.assertIsNotNone(events)
            assert events is not None
            self.assertIn(RunEventType.NODE_FAILED, [event.type for event in events])

    def test_sse_stream_formats_events_until_run_completed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            request = CompileWorkflowRequest(
                payload=load_example("rnaseq_deg_recipe_plan.json"),
                check=False,
            )
            accepted = service.create_structured_compile_run(request)
            service.execute_structured_compile_run(accepted.run_id, request)

            to_thread_calls = []

            async def fake_to_thread(func, /, *args, **kwargs):
                to_thread_calls.append(func.__name__)
                return func(*args, **kwargs)

            with patch("src.services.run_service.asyncio.to_thread", side_effect=fake_to_thread):
                stream = asyncio.run(_collect_async(service.iter_sse_events(accepted.run_id)))

            self.assertIn("event: run.created", stream)
            self.assertIn("event: run.completed", stream)
            self.assertIn("list_events", to_thread_calls)

    def test_sse_stream_drains_completion_event_after_terminal_status_race(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            request = CompileWorkflowRequest(
                payload=load_example("rnaseq_deg_recipe_plan.json"),
                check=False,
            )
            accepted = service.create_structured_compile_run(request)
            completed_during_status_read = False
            to_thread_calls = []

            async def fake_to_thread(func, /, *args, **kwargs):
                nonlocal completed_during_status_read
                to_thread_calls.append(func.__name__)
                if func.__name__ == "get_run" and not completed_during_status_read:
                    completed_during_status_read = True
                    service.repository.complete_run(
                        run_id=accepted.run_id,
                        status=RunStatus.SUCCEEDED,
                        summary="Run succeeded.",
                        payload={"status": RunStatus.SUCCEEDED.value},
                    )
                return func(*args, **kwargs)

            with patch("src.services.run_service.asyncio.to_thread", side_effect=fake_to_thread):
                stream = asyncio.run(_collect_async(service.iter_sse_events(accepted.run_id)))

            self.assertTrue(completed_during_status_read)
            self.assertGreaterEqual(to_thread_calls.count("list_events"), 2)
            self.assertIn("event: run.created", stream)
            self.assertIn("event: run.completed", stream)

    def test_compiler_artifact_update_persists_snapshot_before_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            request = CompileWorkflowRequest(
                payload=load_example("rnaseq_deg_recipe_plan.json"),
                check=False,
            )
            accepted = service.create_structured_compile_run(request)
            service.repository.save_artifacts(
                accepted.run_id,
                WorkflowArtifacts(plan={"workflow": {"recipe": "demo"}}),
            )

            callback = service._compiler_event_callback(accepted.run_id)
            workflow_ir = {"workflow": {"name": "Demo"}}
            callback(
                RunEventType.ARTIFACT_UPDATED.value,
                "ir_normalizer",
                "Workflow IR artifact updated.",
                {"workflow_ir": workflow_ir, "current_wdl": ""},
                {"artifact": "workflow_ir"},
            )

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.artifacts.plan, {"workflow": {"recipe": "demo"}})
            self.assertEqual(snapshot.artifacts.workflow_ir, workflow_ir)

            callback(
                RunEventType.ARTIFACT_UPDATED.value,
                "renderer",
                "WDL artifact updated.",
                {"workflow_ir": workflow_ir, "current_wdl": "version 1.0\nworkflow Demo {}"},
                {"artifact": "wdl"},
            )

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.artifacts.plan, {"workflow": {"recipe": "demo"}})
            self.assertIn("workflow Demo", snapshot.artifacts.wdl)


async def _collect_async(stream):
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return "".join(chunks)


if __name__ == "__main__":
    unittest.main()
