import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.api.models import (
    CompileWorkflowRequest,
    DiagnosticReport,
    NaturalLanguageRunRequest,
    RunEventType,
    RunStatus,
    WorkflowArtifacts,
)
from src.nl_planner import NaturalLanguagePlanningError
from src.services.run_repository import RunRepository
from src.services.run_service import RunService
from src.services.workflow_service import compile_structured_workflow


EXAMPLES_DIR = Path(__file__).parents[1] / "examples"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


def sample_catalog_retrieval() -> dict:
    return {
        "query": "Run RNA-seq DEG.",
        "strategy": "lexical_v1",
        "recipes": [{"id": "rnaseq_differential_expression"}],
        "tools": [{"id": "fastp", "trust_status": "catalog-approved"}],
        "fallback_used": False,
        "fallback_reason": None,
    }


def natural_language_result(
    plan: dict,
    *,
    catalog_retrieval: dict | None = None,
    planner_prompt: str = "planner prompt",
    planner_raw_response: str | None = None,
):
    return replace(
        compile_structured_workflow(plan, check=False),
        catalog_retrieval=catalog_retrieval if catalog_retrieval is not None else sample_catalog_retrieval(),
        planner_prompt=planner_prompt,
        planner_raw_response=planner_raw_response if planner_raw_response is not None else json.dumps(plan),
    )


def repairable_forward_reference_ir() -> dict:
    workflow_ir = load_example("rnaseq_workflow_ir.json")
    workflow_ir["workflow"]["calls"].reverse()
    return workflow_ir


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
            self.assertEqual(snapshot.kind, "structured_compile")
            self.assertIsNotNone(snapshot.created_at)
            self.assertIsNotNone(snapshot.updated_at)
            self.assertIsNotNone(snapshot.completed_at)
            self.assertIsNone(snapshot.artifacts.catalog_retrieval)
            self.assertEqual(snapshot.artifacts.workflow_ir["workflow"]["name"], "RNASeqDEG")
            self.assertIn("workflow RNASeqDEG", snapshot.artifacts.wdl)
            self.assertTrue(snapshot.diagnostics.succeeded)

            events = service.get_events(accepted.run_id)
            self.assertIsNotNone(events)
            assert events is not None
            event_types = [event.type for event in events]
            self.assertIn(RunEventType.RUN_CREATED, event_types)
            self.assertIn(RunEventType.ARTIFACT_UPDATED, event_types)
            self.assertEqual(events[0].payload["stage"], "run")
            self.assertEqual(events[0].payload["status"], "created")
            self.assertEqual(events[0].payload["kind"], "structured_compile")
            self.assertEqual(events[-2].type, RunEventType.ARTIFACT_UPDATED)
            self.assertEqual(events[-2].node, "diagnostics")
            self.assertEqual(events[-2].payload["artifact"], "diagnostics")
            self.assertEqual(events[-2].payload["artifact_name"], "diagnostics")
            self.assertEqual(events[-2].payload["artifact_content_type"], "application/json")
            self.assertEqual(events[-2].payload["stage"], "diagnostics")
            self.assertEqual(events[-2].payload["status"], "updated")
            self.assertTrue(events[-2].payload["succeeded"])
            self.assertEqual(events[-1].type, RunEventType.RUN_COMPLETED)
            self.assertEqual(events[-1].payload["stage"], "run")
            self.assertEqual(events[-1].payload["status"], "succeeded")

    def test_structured_compile_run_replays_repair_artifact_before_repair_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            request = CompileWorkflowRequest(
                payload=repairable_forward_reference_ir(),
                check=False,
            )

            accepted = service.create_structured_compile_run(request)
            service.execute_structured_compile_run(accepted.run_id, request)

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.status, RunStatus.SUCCEEDED)
            self.assertTrue(snapshot.diagnostics.repair_actions)
            self.assertEqual(
                [call["id"] for call in snapshot.artifacts.workflow_ir["workflow"]["calls"]],
                ["qc", "align"],
            )

            events = service.get_events(accepted.run_id)
            self.assertIsNotNone(events)
            assert events is not None
            repair_index = next(
                index for index, event in enumerate(events) if event.type == RunEventType.REPAIR_APPLIED
            )
            workflow_ir_update_index = max(
                index
                for index, event in enumerate(events[:repair_index])
                if event.type == RunEventType.ARTIFACT_UPDATED
                and event.node == "repairer"
                and event.payload.get("artifact") == "workflow_ir"
            )
            self.assertLess(workflow_ir_update_index, repair_index)
            self.assertIn("Reordered workflow steps", events[repair_index].payload["repair_actions"][0])

    def test_structured_compile_run_default_check_records_validation_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            request = CompileWorkflowRequest(payload=load_example("rnaseq_deg_recipe_plan.json"))

            with patch(
                "src.services.workflow_service.checker_node",
                return_value={"is_valid": True, "validation_message": "valid WDL", "error_count": 0},
            ):
                accepted = service.create_structured_compile_run(request)
                service.execute_structured_compile_run(accepted.run_id, request)

            self.assertTrue(request.check)
            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.status, RunStatus.SUCCEEDED)
            self.assertTrue(snapshot.diagnostics.check_performed)
            self.assertTrue(snapshot.diagnostics.is_valid)
            self.assertTrue(snapshot.diagnostics.succeeded)

            events = service.get_events(accepted.run_id)
            self.assertIsNotNone(events)
            assert events is not None
            validation_events = [
                event for event in events if event.type == RunEventType.VALIDATION_COMPLETED
            ]
            self.assertEqual(len(validation_events), 1)
            self.assertEqual(validation_events[0].node, "checker")
            self.assertEqual(validation_events[0].payload["stage"], "compilation")
            self.assertEqual(validation_events[0].payload["status"], "completed")
            self.assertEqual(validation_events[0].payload["check_performed"], True)
            self.assertEqual(validation_events[0].payload["is_valid"], True)
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
            self.assertEqual(compiler_failures[0].payload["error_type"], "RuntimeError")
            self.assertEqual(compiler_failures[0].payload["stage"], "compilation")
            self.assertEqual(compiler_failures[0].payload["status"], "failed")
            self.assertEqual(events[-1].type, RunEventType.RUN_COMPLETED)

    def test_natural_language_run_succeeds_after_planning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            plan = load_example("rnaseq_deg_recipe_plan.json")
            request = NaturalLanguageRunRequest(request="Run RNA-seq DEG.", check=False)
            result = natural_language_result(plan)

            with patch(
                "src.services.run_service.workflow_service.plan_and_compile_workflow",
                return_value=result,
            ) as plan_and_compile:
                accepted = service.create_natural_language_run(request)
                service.execute_natural_language_run(accepted.run_id, request)

            plan_and_compile.assert_called_once()
            self.assertEqual(plan_and_compile.call_args.args, ("Run RNA-seq DEG.",))
            self.assertEqual(plan_and_compile.call_args.kwargs["check"], False)
            self.assertIn("event_callback", plan_and_compile.call_args.kwargs)

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.status, RunStatus.SUCCEEDED)
            self.assertEqual(snapshot.artifacts.plan, plan)
            self.assertEqual(snapshot.artifacts.catalog_retrieval["strategy"], "lexical_v1")
            self.assertIn("workflow RNASeqDEG", snapshot.artifacts.wdl)

    def test_natural_language_run_replays_key_events_and_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            plan = load_example("rnaseq_deg_recipe_plan.json")
            request = NaturalLanguageRunRequest(request="Run RNA-seq DEG.", check=False)
            result = natural_language_result(plan)
            catalog_retrieval = result.catalog_retrieval

            def service_success(*args, **kwargs):
                event_callback = kwargs["event_callback"]
                event_callback(
                    RunEventType.NODE_STARTED.value,
                    "catalog_retriever",
                    "Catalog retriever started.",
                    {"request": "Run RNA-seq DEG."},
                    {},
                )
                event_callback(
                    RunEventType.NODE_COMPLETED.value,
                    "catalog_retriever",
                    "Catalog retriever completed.",
                    {"catalog_retrieval": catalog_retrieval},
                    {
                        "strategy": "lexical_v1",
                        "recipe_count": 1,
                        "tool_count": 1,
                        "fallback_used": False,
                    },
                )
                event_callback(
                    RunEventType.ARTIFACT_UPDATED.value,
                    "catalog_retriever",
                    "Catalog retrieval artifact updated.",
                    {"catalog_retrieval": catalog_retrieval},
                    {"artifact": "catalog_retrieval"},
                )
                event_callback(
                    RunEventType.NODE_STARTED.value,
                    "planner",
                    "Natural-language planner started.",
                    {"planner_model": "deepseek-v4-pro"},
                    {"model": "deepseek-v4-pro"},
                )
                event_callback(
                    RunEventType.NODE_COMPLETED.value,
                    "planner",
                    "Natural-language planner completed.",
                    {"plan": plan},
                    {},
                )
                event_callback(
                    RunEventType.ARTIFACT_UPDATED.value,
                    "planner",
                    "Recipe Tool Plan artifact updated.",
                    {
                        "plan": plan,
                        "planner_prompt": result.planner_prompt,
                        "planner_raw_response": result.planner_raw_response,
                    },
                    {"artifact": "plan"},
                )
                event_callback(
                    RunEventType.NODE_STARTED.value,
                    "compiler_graph",
                    "Compiler graph started.",
                    {"plan": plan},
                    {"check": False},
                )
                event_callback(
                    RunEventType.NODE_STARTED.value,
                    "ir_normalizer",
                    "IR normalizer started.",
                    result.state,
                    {},
                )
                event_callback(
                    RunEventType.NODE_COMPLETED.value,
                    "ir_normalizer",
                    "IR normalizer completed.",
                    result.state,
                    {},
                )
                event_callback(
                    RunEventType.ARTIFACT_UPDATED.value,
                    "ir_normalizer",
                    "Workflow IR artifact updated.",
                    result.state,
                    {"artifact": "workflow_ir"},
                )
                event_callback(
                    RunEventType.NODE_STARTED.value,
                    "analyzer",
                    "Analyzer started.",
                    result.state,
                    {},
                )
                event_callback(
                    RunEventType.NODE_COMPLETED.value,
                    "analyzer",
                    "Analyzer completed.",
                    result.state,
                    {},
                )
                event_callback(
                    RunEventType.NODE_STARTED.value,
                    "renderer",
                    "Renderer started.",
                    result.state,
                    {},
                )
                event_callback(
                    RunEventType.NODE_COMPLETED.value,
                    "renderer",
                    "Renderer completed.",
                    result.state,
                    {},
                )
                event_callback(
                    RunEventType.ARTIFACT_UPDATED.value,
                    "renderer",
                    "WDL artifact updated.",
                    result.state,
                    {"artifact": "wdl"},
                )
                event_callback(
                    RunEventType.VALIDATION_COMPLETED.value,
                    "checker",
                    "WDL syntax validation skipped (--no-check).",
                    result.state,
                    {"is_valid": False, "check_performed": False},
                )
                event_callback(
                    RunEventType.NODE_COMPLETED.value,
                    "compiler_graph",
                    "Compiler graph completed.",
                    {"compiler_result": result},
                    {"succeeded": True, "check_performed": False},
                )
                return result

            with patch(
                "src.services.run_service.workflow_service.plan_and_compile_workflow",
                side_effect=service_success,
            ):
                accepted = service.create_natural_language_run(request)
                service.execute_natural_language_run(accepted.run_id, request)

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.artifacts.catalog_retrieval, catalog_retrieval)
            self.assertEqual(snapshot.artifacts.plan, plan)
            self.assertEqual(snapshot.artifacts.workflow_ir["workflow"]["name"], "RNASeqDEG")
            self.assertIn("workflow RNASeqDEG", snapshot.artifacts.wdl)
            self.assertTrue(snapshot.diagnostics.succeeded)

            events = service.get_events(accepted.run_id)
            self.assertIsNotNone(events)
            assert events is not None
            event_keys = [(event.type.value, event.node) for event in events]
            self.assertEqual(
                event_keys[:8],
                [
                    ("run.created", None),
                    ("node.started", "catalog_retriever"),
                    ("node.completed", "catalog_retriever"),
                    ("artifact.updated", "catalog_retriever"),
                    ("node.started", "planner"),
                    ("node.completed", "planner"),
                    ("artifact.updated", "planner"),
                    ("node.started", "compiler_graph"),
                ],
            )
            self.assertEqual(events[1].payload["stage"], "planning")
            self.assertEqual(events[1].payload["status"], "started")
            self.assertEqual(events[4].payload["stage"], "planning")
            self.assertEqual(events[4].payload["status"], "started")
            self.assertEqual(events[7].payload["stage"], "orchestration")
            self.assertEqual(events[7].payload["status"], "started")
            self.assertIn(("node.started", "ir_normalizer"), event_keys)
            self.assertIn(("node.completed", "analyzer"), event_keys)
            self.assertIn(("artifact.updated", "renderer"), event_keys)
            self.assertIn(("validation.completed", "checker"), event_keys)
            self.assertEqual(event_keys[-2:], [("artifact.updated", "diagnostics"), ("run.completed", None)])
            artifact_order = [
                (event.payload.get("artifact"), event.node)
                for event in events
                if event.type == RunEventType.ARTIFACT_UPDATED
            ]
            self.assertEqual(
                artifact_order,
                [
                    ("catalog_retrieval", "catalog_retriever"),
                    ("plan", "planner"),
                    ("workflow_ir", "ir_normalizer"),
                    ("wdl", "renderer"),
                    ("diagnostics", "diagnostics"),
                ],
            )
            artifact_events = [event for event in events if event.type == RunEventType.ARTIFACT_UPDATED]
            self.assertEqual(artifact_events[0].payload["artifact_name"], "catalog_retrieval")
            self.assertEqual(artifact_events[0].payload["artifact_content_type"], "application/json")
            self.assertEqual(artifact_events[1].payload["artifact_name"], "plan")
            self.assertEqual(artifact_events[1].payload["artifact_content_type"], "application/json")
            self.assertEqual(artifact_events[3].payload["artifact_name"], "wdl")
            self.assertEqual(artifact_events[3].payload["artifact_content_type"], "text/plain")
            diagnostics_event = events[-2]
            self.assertEqual(diagnostics_event.payload["analysis_error_count"], 0)
            self.assertEqual(diagnostics_event.payload["repair_action_count"], 0)
            self.assertFalse(diagnostics_event.payload["check_performed"])
            self.assertTrue(diagnostics_event.payload["succeeded"])

    def test_extra_text_artifact_event_matches_persisted_content_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            request = NaturalLanguageRunRequest(request="Run RNA-seq DEG.", check=False)
            accepted = service.create_natural_language_run(request)
            callback = service._workflow_event_callback(accepted.run_id)

            callback(
                RunEventType.ARTIFACT_UPDATED.value,
                "planner",
                "Planner trace artifact updated.",
                {"planner_trace": "rendered planner trace"},
                {"artifact": "planner_trace"},
            )

            events = service.get_events(accepted.run_id)
            self.assertIsNotNone(events)
            assert events is not None
            event = events[-1]
            self.assertEqual(event.payload["artifact_name"], "planner_trace")
            self.assertEqual(event.payload["artifact_content_type"], "text/plain")

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.artifacts.extras["planner_trace"], "rendered planner trace")
            manifest = {artifact.name: artifact for artifact in snapshot.artifacts.manifest}
            self.assertEqual(manifest["planner_trace"].content_type, "text/plain")

    def test_natural_language_run_preserves_empty_planner_observability_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            plan = load_example("rnaseq_deg_recipe_plan.json")
            request = NaturalLanguageRunRequest(request="Run RNA-seq DEG.", check=False)
            result = natural_language_result(plan, planner_prompt="", planner_raw_response="")

            with patch(
                "src.services.run_service.workflow_service.plan_and_compile_workflow",
                return_value=result,
            ):
                accepted = service.create_natural_language_run(request)
                service.execute_natural_language_run(accepted.run_id, request)

            with service.repository._connect() as connection:
                row = connection.execute(
                    """
                    SELECT planner_prompt, planner_raw_response
                    FROM run_artifacts
                    WHERE run_id = ?
                    """,
                    (accepted.run_id,),
                ).fetchone()

            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row["planner_prompt"], "")
            self.assertEqual(row["planner_raw_response"], "")

    def test_natural_language_compile_exception_preserves_partial_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            plan = load_example("rnaseq_deg_recipe_plan.json")
            workflow_ir = compile_structured_workflow(plan, check=False).workflow_ir
            request = NaturalLanguageRunRequest(request="Run RNA-seq DEG.", check=False)
            catalog_retrieval = sample_catalog_retrieval()

            def service_failure(*args, **kwargs):
                event_callback = kwargs["event_callback"]
                event_callback(
                    "artifact.updated",
                    "catalog_retriever",
                    "Catalog retrieval artifact updated.",
                    {"catalog_retrieval": catalog_retrieval},
                    {"artifact": "catalog_retrieval"},
                )
                event_callback(
                    "artifact.updated",
                    "planner",
                    "Recipe Tool Plan artifact updated.",
                    {
                        "plan": plan,
                        "planner_prompt": "planner prompt",
                        "planner_raw_response": json.dumps(plan),
                    },
                    {"artifact": "plan"},
                )
                event_callback(
                    "artifact.updated",
                    "ir_normalizer",
                    "Workflow IR artifact updated.",
                    {"workflow_ir": workflow_ir, "current_wdl": ""},
                    {"artifact": "workflow_ir"},
                )
                raise RuntimeError("compiler exploded")

            with patch(
                "src.services.run_service.workflow_service.plan_and_compile_workflow",
                side_effect=service_failure,
            ):
                accepted = service.create_natural_language_run(request)
                service.execute_natural_language_run(accepted.run_id, request)

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.status, RunStatus.FAILED)
            self.assertEqual(snapshot.artifacts.catalog_retrieval, catalog_retrieval)
            self.assertEqual(snapshot.artifacts.plan, plan)
            self.assertEqual(snapshot.artifacts.workflow_ir["workflow"]["name"], "RNASeqDEG")
            self.assertEqual(snapshot.artifacts.wdl, "")
            self.assertIn("compiler exploded", snapshot.diagnostics.validation_message)

            events = service.get_events(accepted.run_id)
            self.assertIsNotNone(events)
            assert events is not None
            compiler_failures = [
                event for event in events if event.type == RunEventType.NODE_FAILED and event.node == "compiler"
            ]
            self.assertEqual(len(compiler_failures), 1)
            self.assertEqual(compiler_failures[0].payload["error"], "compiler exploded")
            artifact_order = [
                event.payload.get("artifact")
                for event in events
                if event.type == RunEventType.ARTIFACT_UPDATED
            ]
            self.assertEqual(artifact_order, ["catalog_retrieval", "plan", "workflow_ir", "diagnostics"])
            self.assertEqual(events[-1].type, RunEventType.RUN_COMPLETED)

    def test_natural_language_planner_error_is_persisted_as_failed_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            request = NaturalLanguageRunRequest(request="Run RNA-seq DEG.", check=False)

            with patch(
                "src.services.run_service.workflow_service.plan_and_compile_workflow",
                side_effect=NaturalLanguagePlanningError("LLM planner JSON parsing failed"),
            ):
                accepted = service.create_natural_language_run(request)
                service.execute_natural_language_run(accepted.run_id, request)

            snapshot = service.get_snapshot(accepted.run_id)
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            self.assertEqual(snapshot.status, RunStatus.FAILED)
            self.assertIsNone(snapshot.artifacts.plan)
            self.assertEqual(snapshot.artifacts.workflow_ir, {})
            self.assertEqual(snapshot.artifacts.wdl, "")
            self.assertIn("LLM planner JSON parsing failed", snapshot.diagnostics.validation_message)

            events = service.get_events(accepted.run_id)
            self.assertIsNotNone(events)
            assert events is not None
            self.assertIn(RunEventType.NODE_FAILED, [event.type for event in events])
            artifact_order = [
                event.payload.get("artifact")
                for event in events
                if event.type == RunEventType.ARTIFACT_UPDATED
            ]
            self.assertEqual(artifact_order, ["diagnostics"])

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

    def test_list_runs_returns_api_summaries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = RunService(RunRepository(Path(temp_dir) / "runs.sqlite3"))
            request = CompileWorkflowRequest(
                payload=load_example("rnaseq_deg_recipe_plan.json"),
                check=False,
            )

            accepted = service.create_structured_compile_run(request)
            service.repository.save_diagnostics(
                accepted.run_id,
                DiagnosticReport(
                    validation_message="WDL syntax validation skipped (--no-check).",
                    is_valid=False,
                    succeeded=True,
                    check_performed=False,
                ),
            )
            service.repository.complete_run(
                run_id=accepted.run_id,
                status=RunStatus.SUCCEEDED,
                summary="Run succeeded.",
            )

            response = service.list_runs(status=RunStatus.SUCCEEDED)

            self.assertEqual(response.total, 1)
            self.assertEqual(response.runs[0].run_id, accepted.run_id)
            self.assertEqual(response.runs[0].status, RunStatus.SUCCEEDED)
            self.assertEqual(response.runs[0].kind, "structured_compile")
            self.assertEqual(response.runs[0].request_summary, "rnaseq_differential_expression")
            self.assertFalse(response.runs[0].diagnostic_summary.check_performed)
            self.assertEqual(response.runs[0].diagnostic_summary.analysis_error_count, 0)
            self.assertIsNotNone(response.runs[0].completed_at)


async def _collect_async(stream):
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)
    return "".join(chunks)


if __name__ == "__main__":
    unittest.main()
