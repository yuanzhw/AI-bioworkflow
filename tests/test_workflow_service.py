import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services.workflow_service import compile_structured_workflow, plan_and_compile_workflow


EXAMPLES_DIR = Path(__file__).parents[1] / "examples"


class FakePlannerLlm:
    def __init__(self, response: str):
        self.response = response
        self.prompts = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.response)


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


class WorkflowServiceTests(unittest.TestCase):
    def test_compile_structured_workflow_compiles_recipe_plan_without_check(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")

        result = compile_structured_workflow(plan, check=False)

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertIs(result.plan, plan)
        self.assertEqual(result.workflow_ir["workflow"]["name"], "RNASeqDEG")
        self.assertIn("workflow RNASeqDEG", result.wdl)
        self.assertEqual(result.validation_message, "WDL syntax validation skipped (--no-check).")
        self.assertFalse(result.check_performed)

    def test_compile_structured_workflow_compiles_workflow_ir_without_plan(self):
        workflow_ir = load_example("rnaseq_workflow_ir.json")

        result = compile_structured_workflow(workflow_ir, check=False)

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertIsNone(result.plan)
        self.assertEqual(result.workflow_ir["workflow"]["name"], "RNASeqPipeline")
        self.assertIn("workflow RNASeqPipeline", result.wdl)

    def test_compile_structured_workflow_without_check_does_not_invoke_graph(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")

        with patch(
            "src.services.workflow_service.agent.invoke",
            side_effect=AssertionError("compiled graph should not run when check=False"),
        ) as graph:
            result = compile_structured_workflow(plan, check=False)

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertFalse(result.check_performed)
        graph.assert_not_called()

    def test_compile_structured_workflow_returns_diagnostics_for_invalid_plan(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")
        plan["workflow"]["inputs"].pop("sample_groups")

        result = compile_structured_workflow(plan, check=False)

        self.assertFalse(result.succeeded)
        self.assertEqual(result.wdl, "")
        self.assertIn("missing required workflow input 'sample_groups'", "\n".join(result.analysis_errors))

    def test_plan_and_compile_workflow_plans_then_compiles(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")
        fake_llm = FakePlannerLlm(json.dumps(plan))

        result = plan_and_compile_workflow(
            "Run bulk RNA-seq differential expression.",
            llm=fake_llm,
            check=False,
        )

        self.assertTrue(result.succeeded, result.analysis_errors)
        self.assertEqual(result.plan, plan)
        self.assertIn("Catalog:", result.planner_prompt or "")
        self.assertIn("RNASeqDEG", result.planner_raw_response or "")
        self.assertIn("workflow RNASeqDEG", result.wdl)
        self.assertEqual(len(fake_llm.prompts), 1)

    def test_result_to_dict_exposes_json_ready_service_fields(self):
        plan = load_example("rnaseq_deg_recipe_plan.json")

        result = compile_structured_workflow(plan, check=False).to_dict()

        self.assertEqual(result["plan"], plan)
        self.assertIn("workflow", result["workflow_ir"])
        self.assertIn("workflow RNASeqDEG", result["wdl"])
        self.assertEqual(result["analysis_errors"], [])
        self.assertTrue(result["succeeded"])


if __name__ == "__main__":
    unittest.main()
