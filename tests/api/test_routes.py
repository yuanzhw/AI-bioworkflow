import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.models import RunAcceptedResponse, RunListResponse, RunStatus, RunSummary, WorkflowRunSnapshotResponse
from src.services.catalog_service import get_recipe, get_tool, list_recipes, list_tools


EXAMPLES_DIR = Path(__file__).parents[2] / "examples"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


class ApiRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())

    def test_list_recipes(self):
        recipe_records = list_recipes()

        with patch("src.api.routes.catalog.catalog_service.list_recipes", return_value=recipe_records) as service:
            response = self.client.get("/api/recipes")

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with()
        body = response.json()
        self.assertGreaterEqual(len(body["recipes"]), 1)
        self.assertEqual(body["recipes"][0]["id"], "rnaseq_differential_expression")

    def test_get_recipe_not_found(self):
        with patch(
            "src.api.routes.catalog.catalog_service.get_recipe",
            side_effect=KeyError("unknown recipe: missing_recipe"),
        ) as service:
            response = self.client.get("/api/recipes/missing_recipe")

        self.assertEqual(response.status_code, 404)
        service.assert_called_once_with("missing_recipe")
        self.assertIn("unknown recipe", response.json()["detail"])

    def test_get_recipe_uses_catalog_service(self):
        recipe_record = get_recipe("rnaseq_differential_expression")

        with patch(
            "src.api.routes.catalog.catalog_service.get_recipe",
            return_value=recipe_record,
        ) as service:
            response = self.client.get("/api/recipes/rnaseq_differential_expression")

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with("rnaseq_differential_expression")
        self.assertEqual(response.json()["id"], "rnaseq_differential_expression")

    def test_list_tools(self):
        tool_records = list_tools()

        with patch("src.api.routes.catalog.catalog_service.list_tools", return_value=tool_records) as service:
            response = self.client.get("/api/tools")

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with()
        tools = response.json()["tools"]
        fastp = next(tool for tool in tools if tool["id"] == "fastp")
        self.assertEqual(fastp["version"], "1.3.3")
        self.assertEqual(fastp["trust_status"], "catalog-approved")

    def test_get_tool_with_version(self):
        tool_record = get_tool("salmon", "1.9.0")

        with patch(
            "src.api.routes.catalog.catalog_service.get_tool",
            return_value=tool_record,
        ) as service:
            response = self.client.get("/api/tools/salmon?version=1.9.0")

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with("salmon", "1.9.0")
        body = response.json()
        self.assertEqual(body["id"], "salmon")
        self.assertEqual(body["version"], "1.9.0")

    def test_get_tool_not_found(self):
        with patch(
            "src.api.routes.catalog.catalog_service.get_tool",
            side_effect=KeyError("unknown tool: missing_tool"),
        ) as service:
            response = self.client.get("/api/tools/missing_tool")

        self.assertEqual(response.status_code, 404)
        service.assert_called_once_with("missing_tool", None)
        self.assertIn("unknown tool", response.json()["detail"])

    def test_compile_recipe_plan(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")
        accepted = RunAcceptedResponse(
            run_id="run_123",
            status=RunStatus.CREATED,
            events_url="/api/runs/run_123/events",
        )

        with (
            patch("src.api.routes.workflows.run_service.create_structured_compile_run", return_value=accepted) as create_run,
            patch("src.api.routes.workflows.run_service.execute_structured_compile_run") as execute_run,
        ):
            response = self.client.post(
                "/api/compile",
                json={"payload": plan, "check": False},
            )

        self.assertEqual(response.status_code, 202)
        create_run.assert_called_once()
        execute_run.assert_called_once()
        body = response.json()
        self.assertEqual(body["run_id"], "run_123")
        self.assertEqual(body["status"], "created")
        self.assertEqual(body["events_url"], "/api/runs/run_123/events")

    def test_compile_rejects_empty_payload(self):
        response = self.client.post(
            "/api/compile",
            json={"payload": {}, "check": False},
        )

        self.assertEqual(response.status_code, 422)

    def test_create_run_uses_natural_language_service(self):
        accepted = RunAcceptedResponse(
            run_id="run_456",
            status=RunStatus.CREATED,
            events_url="/api/runs/run_456/events",
        )

        with (
            patch("src.api.routes.workflows.run_service.create_natural_language_run", return_value=accepted) as create_run,
            patch("src.api.routes.workflows.run_service.execute_natural_language_run") as execute_run,
        ):
            response = self.client.post(
                "/api/runs",
                json={"request": "Run RNA-seq DEG.", "check": False},
            )

        self.assertEqual(response.status_code, 202)
        create_run.assert_called_once()
        execute_run.assert_called_once()
        self.assertEqual(response.json()["run_id"], "run_456")

    def test_create_run_passes_requested_planner_model(self):
        accepted = RunAcceptedResponse(
            run_id="run_789",
            status=RunStatus.CREATED,
            events_url="/api/runs/run_789/events",
        )

        with (
            patch("src.api.routes.workflows.run_service.create_natural_language_run", return_value=accepted) as create_run,
            patch("src.api.routes.workflows.run_service.execute_natural_language_run"),
        ):
            response = self.client.post(
                "/api/runs",
                json={
                    "request": "Run RNA-seq DEG.",
                    "planner_model": "custom-planner",
                    "check": False,
                },
            )

        self.assertEqual(response.status_code, 202)
        created_request = create_run.call_args.args[0]
        self.assertEqual(created_request.planner_model, "custom-planner")

    def test_list_runs_uses_run_service_with_filters(self):
        response_body = RunListResponse(
            runs=[
                RunSummary(
                    run_id="run_123",
                    status=RunStatus.SUCCEEDED,
                    kind="structured_compile",
                    request_summary="rnaseq_differential_expression",
                    events_url="/api/runs/run_123/events",
                    created_at="2026-06-16T00:00:00Z",
                    updated_at="2026-06-16T00:00:01Z",
                    completed_at="2026-06-16T00:00:01Z",
                    diagnostic_summary={
                        "analysis_error_count": 0,
                        "analysis_warning_count": 0,
                        "repair_action_count": 0,
                        "check_performed": True,
                        "is_valid": True,
                    },
                )
            ],
            limit=5,
            offset=10,
            total=42,
        )

        with patch("src.api.routes.workflows.run_service.list_runs", return_value=response_body) as list_runs:
            response = self.client.get("/api/runs?limit=5&offset=10&status=succeeded")

        self.assertEqual(response.status_code, 200)
        list_runs.assert_called_once_with(limit=5, offset=10, status=RunStatus.SUCCEEDED)
        body = response.json()
        self.assertEqual(body["runs"][0]["run_id"], "run_123")
        self.assertEqual(body["total"], 42)

    def test_get_run_returns_snapshot(self):
        snapshot = WorkflowRunSnapshotResponse(
            run_id="run_123",
            status=RunStatus.SUCCEEDED,
            request="Run RNA-seq DEG.",
            events_url="/api/runs/run_123/events",
        )

        with patch("src.api.routes.workflows.run_service.get_snapshot", return_value=snapshot) as get_snapshot:
            response = self.client.get("/api/runs/run_123")

        self.assertEqual(response.status_code, 200)
        get_snapshot.assert_called_once_with("run_123")
        self.assertEqual(response.json()["run_id"], "run_123")

    def test_get_run_not_found(self):
        with patch("src.api.routes.workflows.run_service.get_snapshot", return_value=None):
            response = self.client.get("/api/runs/missing")

        self.assertEqual(response.status_code, 404)
        self.assertIn("unknown run", response.json()["detail"])

    def test_stream_run_events(self):
        event_stream = iter(
            [
                'id: 1\nevent: run.created\ndata: {"run_id":"run_123"}\n\n',
                'id: 2\nevent: run.completed\ndata: {"run_id":"run_123"}\n\n',
            ]
        )

        with patch("src.api.routes.workflows.run_service.iter_sse_events", return_value=event_stream) as stream:
            response = self.client.get("/api/runs/run_123/events")

        self.assertEqual(response.status_code, 200)
        stream.assert_called_once_with("run_123", after_sequence=0)
        self.assertIn("event: run.created", response.text)

    def test_stream_run_events_not_found(self):
        with patch(
            "src.api.routes.workflows.run_service.iter_sse_events",
            side_effect=KeyError("unknown run: missing"),
        ):
            response = self.client.get("/api/runs/missing/events")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
