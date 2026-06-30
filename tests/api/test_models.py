import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from src.api.models import (
    CompileWorkflowRequest,
    CompilationResultResponse,
    NaturalLanguageRunRequest,
    RecipeListResponse,
    RunAcceptedResponse,
    RunEvent,
    RunEventType,
    RunListResponse,
    RunStatus,
    RunSummary,
    WorkflowArtifactSummary,
    WorkflowArtifacts,
    ToolListResponse,
    WorkflowRunSnapshotResponse,
)
from src.services.catalog_service import list_recipes, list_tools
from src.services.workflow_service import compile_structured_workflow


EXAMPLES_DIR = Path(__file__).parents[2] / "examples"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


class WorkflowDtoTests(unittest.TestCase):
    def test_compile_workflow_request_accepts_structured_payload(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")

        request = CompileWorkflowRequest(payload=plan)

        self.assertEqual(request.payload, plan)
        self.assertTrue(request.check)

    def test_compile_workflow_request_rejects_empty_payload(self):
        with self.assertRaisesRegex(ValidationError, "payload must not be empty"):
            CompileWorkflowRequest(payload={})

    def test_natural_language_request_strips_and_validates_text(self):
        request = NaturalLanguageRunRequest(request="  Run RNA-seq DEG.  ", check=False)

        self.assertEqual(request.request, "Run RNA-seq DEG.")
        self.assertFalse(request.check)

        with self.assertRaisesRegex(ValidationError, "request must not be empty"):
            NaturalLanguageRunRequest(request="  ")

    def test_compilation_result_response_maps_successful_service_result(self):
        result = compile_structured_workflow(
            load_example("rnaseq_deg_recipe_plan.json"),
            check=False,
        )

        response = CompilationResultResponse.from_service_result(result)

        self.assertEqual(response.status, RunStatus.SUCCEEDED)
        self.assertTrue(response.diagnostics.succeeded)
        self.assertFalse(response.diagnostics.check_performed)
        self.assertEqual(response.diagnostics.analysis_errors, [])
        self.assertIsNone(response.artifacts.catalog_retrieval)
        self.assertEqual(response.artifacts.workflow_ir["workflow"]["name"], "RNASeqDEG")
        self.assertIn("workflow RNASeqDEG", response.artifacts.wdl)

    def test_compilation_result_response_maps_failed_service_result(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")
        plan["workflow"]["inputs"].pop("sample_groups")

        result = compile_structured_workflow(plan, check=False)
        response = CompilationResultResponse.from_service_result(result)

        self.assertEqual(response.status, RunStatus.FAILED)
        self.assertFalse(response.diagnostics.succeeded)
        self.assertEqual(response.artifacts.wdl, "")
        self.assertIn("sample_groups", "\n".join(response.diagnostics.analysis_errors))

    def test_run_accepted_response_exposes_event_stream_url(self):
        response = RunAcceptedResponse(
            run_id="run_001",
            status=RunStatus.CREATED,
            events_url="/api/runs/run_001/events",
        )

        self.assertEqual(response.run_id, "run_001")
        self.assertEqual(response.status, RunStatus.CREATED)
        self.assertEqual(response.events_url, "/api/runs/run_001/events")

    def test_run_snapshot_response_defaults_to_empty_artifacts_and_diagnostics(self):
        response = WorkflowRunSnapshotResponse(
            run_id="run_001",
            status=RunStatus.RUNNING,
            request="Run RNA-seq DEG.",
            events_url="/api/runs/run_001/events",
        )

        self.assertEqual(response.artifacts.workflow_ir, {})
        self.assertIsNone(response.artifacts.catalog_retrieval)
        self.assertEqual(response.artifacts.wdl, "")
        self.assertFalse(response.diagnostics.succeeded)
        self.assertIsNone(response.kind)
        self.assertIsNone(response.created_at)
        self.assertIsNone(response.updated_at)
        self.assertIsNone(response.completed_at)

    def test_workflow_artifacts_expose_manifest_and_extra_artifacts(self):
        updated_at = datetime(2026, 6, 16, tzinfo=UTC)
        artifacts = WorkflowArtifacts(
            extras={
                "catalog_retrieval": {
                    "strategy": "lexical_v1",
                    "recipes": [{"id": "rnaseq_differential_expression"}],
                }
            },
            manifest=[
                WorkflowArtifactSummary(
                    name="catalog_retrieval",
                    content_type="application/json",
                    updated_at=updated_at,
                )
            ],
        )

        self.assertEqual(artifacts.extras["catalog_retrieval"]["strategy"], "lexical_v1")
        self.assertEqual(artifacts.manifest[0].name, "catalog_retrieval")
        self.assertEqual(artifacts.manifest[0].content_type, "application/json")

    def test_run_list_response_accepts_history_summaries(self):
        created_at = datetime(2026, 6, 16, tzinfo=UTC)
        response = RunListResponse(
            runs=[
                RunSummary(
                    run_id="run_001",
                    status=RunStatus.SUCCEEDED,
                    kind="structured_compile",
                    request_summary="rnaseq_differential_expression",
                    events_url="/api/runs/run_001/events",
                    created_at=created_at,
                    updated_at=created_at,
                    completed_at=created_at,
                    diagnostic_summary={
                        "analysis_error_count": 0,
                        "analysis_warning_count": 1,
                        "repair_action_count": 0,
                        "check_performed": True,
                        "is_valid": True,
                    },
                )
            ],
            limit=20,
            offset=0,
            total=1,
        )

        self.assertEqual(response.runs[0].run_id, "run_001")
        self.assertEqual(response.runs[0].diagnostic_summary.analysis_warning_count, 1)
        self.assertTrue(response.runs[0].diagnostic_summary.is_valid)


class CatalogDtoTests(unittest.TestCase):
    def test_recipe_list_response_accepts_catalog_service_records(self):
        response = RecipeListResponse.model_validate({"recipes": list_recipes()})

        self.assertGreaterEqual(len(response.recipes), 1)
        recipe = response.recipes[0]
        self.assertEqual(recipe.id, "rnaseq_differential_expression")
        self.assertEqual(recipe.required_inputs["sample_ids"].type, "Array[String]")
        self.assertEqual(recipe.steps[0].allowed_tools, ["fastp"])

    def test_tool_list_response_accepts_catalog_service_records(self):
        response = ToolListResponse.model_validate({"tools": list_tools()})

        fastp = next(tool for tool in response.tools if tool.id == "fastp")
        self.assertEqual(fastp.version, "1.3.3")
        self.assertEqual(fastp.trust_status, "catalog-approved")
        self.assertEqual(fastp.runtime.docker, "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0")
        self.assertIn("clean_r1", fastp.outputs)


class EventDtoTests(unittest.TestCase):
    def test_run_event_defines_persistable_event_envelope(self):
        event = RunEvent(
            event_id="evt_001",
            run_id="run_001",
            sequence=1,
            type=RunEventType.RUN_CREATED,
            timestamp=datetime(2026, 6, 6, tzinfo=UTC),
            summary="Run created.",
        )

        self.assertEqual(event.type, RunEventType.RUN_CREATED)
        self.assertEqual(event.payload, {})

    def test_run_event_requires_positive_sequence(self):
        with self.assertRaisesRegex(ValidationError, "greater than or equal to 1"):
            RunEvent(
                event_id="evt_001",
                run_id="run_001",
                sequence=0,
                type=RunEventType.RUN_CREATED,
                timestamp=datetime(2026, 6, 6, tzinfo=UTC),
                summary="Run created.",
            )


if __name__ == "__main__":
    unittest.main()
