import copy
import json
import unittest
from pathlib import Path

from src.catalog.loader import load_tool_catalog
from src.catalog.resolver import resolve_tool_plan
from src.nodes.reviewer_repair import (
    make_reviewer_repair_node,
    reviewer_repair_node,
)
from src.recipes.loader import load_recipe_catalog
from src.reviewer_provider import (
    ReviewerProviderError,
    ReviewerProviderUnavailableError,
)
from src.reviewer_request import build_reviewer_repair_request
from src.reviewer_repair import ReviewerFailureStage, ReviewerRepairStatus
from src.services.workflow_service import build_initial_state


REPO_ROOT = Path(__file__).resolve().parents[1]


class RecordingReviewerProvider:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def repair(self, request):
        self.requests.append(request)
        return self.result


class FailingReviewerProvider:
    def __init__(self):
        self.call_count = 0

    def repair(self, request):
        self.call_count += 1
        raise AssertionError("disabled Reviewer provider must not be called")


class RaisingReviewerProvider:
    def repair(self, request):
        raise RuntimeError("TOP_SECRET raw provider failure")


class RaisingTypedReviewerProvider:
    def repair(self, request):
        raise ReviewerProviderError("TOP_SECRET provider failure")


class ReviewerNodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool_catalog = load_tool_catalog()
        cls.recipe_catalog = load_recipe_catalog(tool_catalog=cls.tool_catalog)
        cls.plan = json.loads(
            (
                REPO_ROOT / "examples" / "rnaseq_reference_prep_recipe_plan.json"
            ).read_text(encoding="utf-8")
        )
        cls.workflow_ir = resolve_tool_plan(
            cls.plan,
            cls.recipe_catalog,
            cls.tool_catalog,
        ).model_dump(mode="json")

    def sample_state(self):
        state = build_initial_state(copy.deepcopy(self.plan))
        state["workflow_ir"] = copy.deepcopy(self.workflow_ir)
        state["analysis_errors"] = ["workflow output is missing"]
        state["analysis_warnings"] = ["review output wiring"]
        return state

    def make_node(self, provider, **kwargs):
        return make_reviewer_repair_node(
            enabled=True,
            provider=provider,
            tool_catalog=self.tool_catalog,
            recipe_catalog=self.recipe_catalog,
            **kwargs,
        )

    def test_default_reviewer_node_is_callable_and_disabled(self):
        self.assertTrue(callable(reviewer_repair_node))
        provider = FailingReviewerProvider()
        state = self.sample_state()

        update = make_reviewer_repair_node(
            enabled=False,
            provider=provider,
        )(state)

        self.assertEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.NO_ACTION.value,
        )
        self.assertEqual(update["reviewer_attempt_count"], 0)
        self.assertIsNone(update["reviewer_repair_request"])
        self.assertFalse(update["reviewer_patch_applied"])
        self.assertNotIn("workflow_ir", update)
        self.assertEqual(provider.call_count, 0)

    def test_reviewer_node_returns_no_action_when_provider_is_unavailable(self):
        def unavailable_provider_factory(model):
            raise ReviewerProviderUnavailableError("Reviewer provider unavailable.")

        state = self.sample_state()
        update = make_reviewer_repair_node(
            enabled=True,
            provider_factory=unavailable_provider_factory,
        )(state)

        self.assertEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.NO_ACTION.value,
        )
        self.assertEqual(update["reviewer_attempt_count"], 0)
        self.assertIn("unavailable", update["reviewer_diagnostics"][0])
        self.assertNotIn("workflow_ir", update)

    def test_reviewer_node_applies_valid_patch_with_minimal_approved_context(self):
        provider = RecordingReviewerProvider(
            {
                "status": "patch_proposed",
                "patch": {
                    "summary": "Expose a validated index output alias.",
                    "actions": [
                        {
                            "operation": "add",
                            "path": "/workflow/outputs/index_copy",
                            "value": "index.index_archive",
                            "reason": "Use an existing call output.",
                        }
                    ],
                    "diagnostic_references": ["workflow output is missing"],
                    "catalog_references": ["salmon_index:1.9.0"],
                    "confidence": 0.9,
                },
                "diagnostics": ["Patch uses only existing Workflow IR values."],
            }
        )
        state = self.sample_state()

        update = self.make_node(provider)(state)

        self.assertTrue(update["reviewer_patch_applied"])
        self.assertEqual(update["reviewer_attempt_count"], 1)
        self.assertEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.PATCH_PROPOSED.value,
        )
        self.assertEqual(
            update["workflow_ir"]["workflow"]["outputs"]["index_copy"],
            "index.index_archive",
        )
        self.assertNotIn(
            "index_copy",
            state["workflow_ir"]["workflow"]["outputs"],
        )
        self.assertEqual(update["analysis_errors"], [])
        self.assertEqual(len(provider.requests), 1)

        request = provider.requests[0]
        self.assertEqual(request.attempt_index, 1)
        self.assertEqual(
            [recipe.recipe_id for recipe in request.catalog_context.recipes],
            ["rnaseq_reference_preparation"],
        )
        self.assertEqual(
            {tool.tool_id for tool in request.catalog_context.tools},
            {"salmon_index", "gtf_tx2gene"},
        )
        self.assertNotIn(
            "fastp",
            json.dumps(update["reviewer_repair_request"]),
        )
        self.assertNotIn("raw_response", update)

    def test_reviewer_node_rejects_invalid_provider_output_without_raw_payload(self):
        provider = RecordingReviewerProvider(
            {
                "status": "patch_proposed",
                "patch": {
                    "secret_marker": "TOP_SECRET",
                },
            }
        )
        state = self.sample_state()

        update = self.make_node(provider)(state)

        self.assertEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.MODEL_ERROR.value,
        )
        self.assertEqual(update["reviewer_attempt_count"], 1)
        self.assertFalse(update["reviewer_patch_applied"])
        self.assertNotIn("workflow_ir", update)
        self.assertNotIn("TOP_SECRET", json.dumps(update, default=str))

    def test_reviewer_node_records_provider_failure_as_model_error(self):
        state = self.sample_state()

        update = self.make_node(RaisingReviewerProvider())(state)

        self.assertEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.MODEL_ERROR.value,
        )
        self.assertEqual(update["reviewer_attempt_count"], 1)
        self.assertIn("RuntimeError", update["reviewer_diagnostics"][0])
        self.assertNotIn("TOP_SECRET", json.dumps(update, default=str))
        self.assertFalse(update["reviewer_patch_applied"])
        self.assertNotIn("workflow_ir", update)

    def test_reviewer_node_does_not_persist_typed_provider_error_payload(self):
        state = self.sample_state()

        update = self.make_node(RaisingTypedReviewerProvider())(state)

        self.assertEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.MODEL_ERROR.value,
        )
        self.assertIn("ReviewerProviderError", update["reviewer_diagnostics"][0])
        self.assertNotIn("TOP_SECRET", json.dumps(update, default=str))

    def test_reviewer_node_sanitizes_request_construction_errors(self):
        invalid_states = []

        invalid_workflow_ir = self.sample_state()
        invalid_workflow_ir["workflow_ir"] = {
            "workflow": {"name": "TOP_SECRET"},
        }
        invalid_states.append(("workflow_ir", invalid_workflow_ir))

        invalid_recipe_plan = self.sample_state()
        invalid_recipe_plan["parsed_json"]["workflow"]["tool_calls"][0]["tool"] = {
            "secret": "TOP_SECRET",
        }
        invalid_states.append(("recipe_plan", invalid_recipe_plan))

        invalid_request_contract = self.sample_state()
        invalid_request_contract["analysis_errors"] = [
            {"secret": "TOP_SECRET"},
        ]
        invalid_states.append(("request_contract", invalid_request_contract))

        for label, state in invalid_states:
            with self.subTest(label=label):
                provider = RecordingReviewerProvider({"status": "no_action"})

                update = self.make_node(provider)(state)

                self.assertEqual(
                    update["reviewer_repair_status"],
                    ReviewerRepairStatus.INVALID_REQUEST.value,
                )
                self.assertEqual(update["reviewer_attempt_count"], 0)
                self.assertEqual(provider.requests, [])
                self.assertNotIn("TOP_SECRET", json.dumps(update, default=str))

    def test_reviewer_node_rejects_policy_violation_without_mutating_ir(self):
        provider = RecordingReviewerProvider(
            {
                "status": "patch_proposed",
                "patch": {
                    "summary": "Attempt a forbidden runtime edit.",
                    "actions": [
                        {
                            "operation": "replace",
                            "path": "/tasks/salmon_index_index/runtime/docker",
                            "value": "ubuntu:22.04",
                            "reason": "Reviewer must not change runtime images.",
                        }
                    ],
                },
            }
        )
        state = self.sample_state()

        update = self.make_node(provider)(state)

        self.assertEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.POLICY_REJECTED.value,
        )
        self.assertIsNotNone(update["reviewer_ir_patch"])
        self.assertIn("forbidden", update["reviewer_rejection_reason"])
        self.assertFalse(update["reviewer_patch_applied"])
        self.assertNotIn("workflow_ir", update)
        self.assertEqual(
            state["workflow_ir"]["tasks"]["salmon_index_index"]["runtime"]["docker"],
            self.tool_catalog.get("salmon_index", "1.9.0").runtime.docker,
        )

    def test_reviewer_node_classifies_application_failure_separately_from_policy(self):
        provider = RecordingReviewerProvider(
            {
                "status": "patch_proposed",
                "patch": {
                    "summary": "Replace a missing workflow output.",
                    "actions": [
                        {
                            "operation": "replace",
                            "path": "/workflow/outputs/missing_output",
                            "value": "index.index_archive",
                            "reason": "The target must already exist for replace.",
                        }
                    ],
                },
            }
        )
        state = self.sample_state()

        update = self.make_node(provider)(state)

        self.assertEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.INVALID_REQUEST.value,
        )
        self.assertIn("does not exist", update["reviewer_rejection_reason"])
        self.assertNotEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.POLICY_REJECTED.value,
        )
        self.assertFalse(update["reviewer_patch_applied"])
        self.assertNotIn("workflow_ir", update)

    def test_reviewer_node_sanitizes_schema_application_failure(self):
        state = self.sample_state()
        output_name = next(iter(state["workflow_ir"]["workflow"]["outputs"]))
        provider = RecordingReviewerProvider(
            {
                "status": "patch_proposed",
                "patch": {
                    "summary": "Propose an invalid workflow output value type.",
                    "actions": [
                        {
                            "operation": "replace",
                            "path": f"/workflow/outputs/{output_name}",
                            "value": ["TOP_SECRET"],
                            "reason": "Exercise schema rejection diagnostics.",
                        }
                    ],
                },
            }
        )

        update = self.make_node(provider)(state)

        self.assertEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.INVALID_REQUEST.value,
        )
        self.assertIsNotNone(update["reviewer_ir_patch"])
        self.assertNotIn("TOP_SECRET", update["reviewer_rejection_reason"])
        self.assertNotIn(
            "TOP_SECRET",
            json.dumps(update["reviewer_diagnostics"]),
        )
        self.assertFalse(update["reviewer_patch_applied"])
        self.assertNotIn("workflow_ir", update)

    def test_reviewer_node_builds_checker_request_without_routing_it(self):
        provider = RecordingReviewerProvider(
            {
                "status": "no_action",
                "diagnostics": ["Checker failure has no safe IR-only repair."],
            }
        )
        state = self.sample_state()
        state["validation_message"] = "WOMtool rejected the generated WDL."

        update = self.make_node(
            provider,
            failure_stage=ReviewerFailureStage.CHECKER,
        )(state)

        self.assertEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.NO_ACTION.value,
        )
        self.assertFalse(update["reviewer_patch_applied"])
        self.assertNotIn("workflow_ir", update)
        request = provider.requests[0]
        self.assertEqual(request.failure_stage, ReviewerFailureStage.CHECKER)
        self.assertEqual(
            request.validation_message,
            "WOMtool rejected the generated WDL.",
        )

    def test_direct_workflow_ir_request_uses_empty_catalog_context(self):
        state = self.sample_state()
        state["parsed_json"] = copy.deepcopy(state["workflow_ir"])

        request = build_reviewer_repair_request(
            state,
            failure_stage=ReviewerFailureStage.ANALYZER,
            tool_catalog=self.tool_catalog,
            recipe_catalog=self.recipe_catalog,
        )

        self.assertEqual(request.catalog_context.recipes, [])
        self.assertEqual(request.catalog_context.tools, [])

    def test_recipe_plan_context_rejects_modified_catalog_controlled_task(self):
        provider = RecordingReviewerProvider(
            {
                "status": "no_action",
                "diagnostics": ["No repair needed."],
            }
        )
        state = self.sample_state()
        task_name = state["workflow_ir"]["workflow"]["steps"][0]["task"]
        state["workflow_ir"]["tasks"][task_name]["command"] = "echo tampered"

        update = self.make_node(provider)(state)

        self.assertEqual(
            update["reviewer_repair_status"],
            ReviewerRepairStatus.INVALID_REQUEST.value,
        )
        self.assertEqual(update["reviewer_attempt_count"], 0)
        self.assertIn("Catalog-controlled", update["reviewer_rejection_reason"])
        self.assertEqual(provider.requests, [])

    def test_recipe_plan_context_uses_canonical_scatter_steps(self):
        plan = json.loads(
            (REPO_ROOT / "examples" / "rnaseq_deg_recipe_plan.json").read_text(
                encoding="utf-8"
            )
        )
        workflow_ir = resolve_tool_plan(
            plan,
            self.recipe_catalog,
            self.tool_catalog,
        ).model_dump(mode="json")
        self.assertEqual(workflow_ir["workflow"]["steps"][0]["kind"], "scatter")

        valid_provider = RecordingReviewerProvider(
            {
                "status": "no_action",
                "diagnostics": ["Canonical scatter steps are consistent."],
            }
        )
        valid_state = build_initial_state(copy.deepcopy(plan))
        valid_state["workflow_ir"] = copy.deepcopy(workflow_ir)

        valid_update = self.make_node(valid_provider)(valid_state)

        self.assertEqual(
            valid_update["reviewer_repair_status"],
            ReviewerRepairStatus.NO_ACTION.value,
        )
        self.assertEqual(len(valid_provider.requests), 1)

        invalid_provider = RecordingReviewerProvider({"status": "no_action"})
        invalid_state = build_initial_state(copy.deepcopy(plan))
        invalid_state["workflow_ir"] = copy.deepcopy(workflow_ir)
        invalid_state["workflow_ir"]["workflow"]["steps"][0]["body"][0][
            "inputs"
        ]["r1"] = "tampered_input"

        invalid_update = self.make_node(invalid_provider)(invalid_state)

        self.assertEqual(
            invalid_update["reviewer_repair_status"],
            ReviewerRepairStatus.INVALID_REQUEST.value,
        )
        self.assertEqual(invalid_update["reviewer_attempt_count"], 0)
        self.assertIn(
            "compatibility calls do not match canonical workflow steps",
            invalid_update["reviewer_rejection_reason"],
        )
        self.assertEqual(invalid_provider.requests, [])


if __name__ == "__main__":
    unittest.main()
