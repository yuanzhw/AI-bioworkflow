import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.nl_planner import DEFAULT_PLANNER_MODEL, NaturalLanguagePlanningError
from src.services.catalog_service import get_recipe, get_tool, list_recipes, list_tools
from src.services.workflow_service import compile_structured_workflow


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
        result = compile_structured_workflow(plan, check=False)

        with patch("src.api.routes.workflows.workflow_service.compile_structured_workflow", return_value=result) as service:
            response = self.client.post(
                "/api/compile",
                json={"payload": plan, "check": False},
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(plan, check=False)
        body = response.json()
        self.assertEqual(body["status"], "succeeded")
        self.assertFalse(body["diagnostics"]["check_performed"])
        self.assertEqual(body["artifacts"]["workflow_ir"]["workflow"]["name"], "RNASeqDEG")
        self.assertIn("workflow RNASeqDEG", body["artifacts"]["wdl"])

    def test_compile_invalid_plan_returns_diagnostics(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")
        plan["workflow"]["inputs"].pop("sample_groups")

        response = self.client.post(
            "/api/compile",
            json={"payload": plan, "check": False},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "failed")
        self.assertFalse(body["diagnostics"]["succeeded"])
        self.assertEqual(body["artifacts"]["wdl"], "")
        self.assertIn("sample_groups", "\n".join(body["diagnostics"]["analysis_errors"]))

    def test_compile_rejects_empty_payload(self):
        response = self.client.post(
            "/api/compile",
            json={"payload": {}, "check": False},
        )

        self.assertEqual(response.status_code, 422)

    def test_create_run_uses_natural_language_service(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")
        result = compile_structured_workflow(plan, check=False)

        with patch(
            "src.api.routes.workflows.workflow_service.plan_and_compile_workflow",
            return_value=result,
        ) as service:
            response = self.client.post(
                "/api/runs",
                json={"request": "Run RNA-seq DEG.", "check": False},
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(
            "Run RNA-seq DEG.",
            model=DEFAULT_PLANNER_MODEL,
            check=False,
        )
        self.assertEqual(response.json()["status"], "succeeded")

    def test_create_run_passes_requested_planner_model(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")
        result = compile_structured_workflow(plan, check=False)

        with patch("src.api.routes.workflows.workflow_service.plan_and_compile_workflow", return_value=result) as service:
            response = self.client.post(
                "/api/runs",
                json={
                    "request": "Run RNA-seq DEG.",
                    "planner_model": "custom-planner",
                    "check": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        service.assert_called_once_with(
            "Run RNA-seq DEG.",
            model="custom-planner",
            check=False,
        )

    def test_create_run_reports_planning_errors(self):
        with patch(
            "src.api.routes.workflows.workflow_service.plan_and_compile_workflow",
            side_effect=NaturalLanguagePlanningError("LLM planner JSON parsing failed"),
        ):
            response = self.client.post(
                "/api/runs",
                json={"request": "Run RNA-seq DEG.", "check": False},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("LLM planner JSON parsing failed", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
