import unittest

from pydantic import ValidationError

from src.reviewer_repair import (
    ApprovedCatalogContext,
    ReviewerFailureStage,
    ReviewerIRPatch,
    ReviewerPatchPolicyError,
    ReviewerRepairRequest,
    ReviewerRepairResult,
    ReviewerRepairStatus,
    validate_reviewer_patch_policy,
)


def sample_workflow_ir():
    return {
        "workflow": {
            "name": "ReviewerRepairDemo",
            "inputs": {
                "raw_r1": "File",
                "raw_r2": "File",
            },
            "steps": [
                {
                    "kind": "call",
                    "id": "qc",
                    "task": "fastp",
                    "inputs": {
                        "r1": "raw_r1",
                    },
                }
            ],
            "outputs": {
                "clean_r1": "qc.clean_r1",
            },
        },
        "tasks": {
            "fastp": {
                "inputs": {
                    "r1": "File",
                    "r2": "File",
                },
                "command": "fastp -i ~{r1} -I ~{r2} -o clean_R1.fq.gz -O clean_R2.fq.gz",
                "outputs": {
                    "clean_r1": {
                        "type": "File",
                        "value": "\"clean_R1.fq.gz\"",
                    }
                },
                "runtime": {
                    "docker": "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0",
                    "cpu": 4,
                    "memory": "8G",
                },
            }
        },
    }


def sample_catalog_context():
    return {
        "recipes": [
            {
                "recipe_id": "rnaseq_differential_expression",
                "step_ids": ["qc"],
                "tool_ids": ["fastp"],
            }
        ],
        "tools": [
            {
                "tool_id": "fastp",
                "version": "1.3.3",
                "inputs": ["r1", "r2"],
                "outputs": ["clean_r1"],
                "trust_status": "catalog-approved",
                "runtime_docker": "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0",
            }
        ],
    }


class ReviewerRepairContractTests(unittest.TestCase):
    def test_reviewer_repair_request_accepts_workflow_ir_and_minimal_catalog_context(self):
        request = ReviewerRepairRequest.model_validate(
            {
                "workflow_ir": sample_workflow_ir(),
                "failure_stage": ReviewerFailureStage.ANALYZER,
                "analysis_errors": ["call 'qc' is missing input 'r2'"],
                "analysis_warnings": [],
                "validation_message": "",
                "repair_history": [],
                "catalog_context": sample_catalog_context(),
                "attempt_index": 1,
            }
        )

        self.assertEqual(request.failure_stage, ReviewerFailureStage.ANALYZER)
        self.assertEqual(request.workflow_ir.workflow.name, "ReviewerRepairDemo")
        self.assertEqual(request.catalog_context.tools[0].tool_id, "fastp")
        self.assertEqual(request.constraints.allowed_operations[0].value, "add")

    def test_reviewer_patch_model_rejects_invalid_shape(self):
        with self.assertRaises(ValidationError):
            ReviewerIRPatch.model_validate(
                {
                    "summary": "Invalid patch.",
                    "actions": [
                        {
                            "operation": "rewrite",
                            "path": "workflow/steps/0/inputs/r2",
                            "value": "raw_r2",
                            "reason": "Unsupported operation and non-pointer path.",
                        }
                    ],
                    "confidence": 1.5,
                }
            )

    def test_policy_accepts_allowed_workflow_ir_patch(self):
        patch = ReviewerIRPatch.model_validate(
            {
                "summary": "Repair missing call input wiring.",
                "actions": [
                    {
                        "operation": "add",
                        "path": "/workflow/steps/0/inputs/r2",
                        "value": "raw_r2",
                        "reason": "The existing workflow input satisfies the missing task input.",
                    }
                ],
                "diagnostic_references": ["call 'qc' is missing input 'r2'"],
                "catalog_references": ["fastp:1.3.3"],
                "confidence": 0.8,
            }
        )
        context = ApprovedCatalogContext.model_validate(sample_catalog_context())

        validated = validate_reviewer_patch_policy(patch, catalog_context=context)

        self.assertIs(validated, patch)

    def test_policy_rejects_wdl_catalog_runtime_and_resource_edits(self):
        forbidden_paths = [
            "/current_wdl",
            "/catalog/tools/fastp",
            "/workflow/steps",
            "/workflow/calls",
            "/workflow/steps/0/task",
            "/tasks/fastp/command",
            "/tasks/fastp/runtime/docker",
            "/tasks/fastp/runtime/cpu",
        ]

        for path in forbidden_paths:
            with self.subTest(path=path):
                patch = ReviewerIRPatch.model_validate(
                    {
                        "summary": "Forbidden edit.",
                        "actions": [
                            {
                                "operation": "replace",
                                "path": path,
                                "value": "forbidden",
                                "reason": "This crosses the P2 repair boundary.",
                            }
                        ],
                    }
                )

                with self.assertRaises(ReviewerPatchPolicyError):
                    validate_reviewer_patch_policy(patch)

    def test_policy_rejects_catalog_references_outside_current_workflow_context(self):
        patch = ReviewerIRPatch.model_validate(
            {
                "summary": "Use an unavailable catalog tool.",
                "actions": [
                    {
                        "operation": "replace",
                        "path": "/workflow/outputs/clean_r1",
                        "value": "qc.clean_r1",
                        "reason": "Output expression stays inside Workflow IR.",
                    }
                ],
                "catalog_references": ["star:2.7.11b"],
            }
        )
        context = ApprovedCatalogContext.model_validate(sample_catalog_context())

        with self.assertRaisesRegex(ReviewerPatchPolicyError, "not in the approved"):
            validate_reviewer_patch_policy(patch, catalog_context=context)

    def test_policy_rejects_catalog_references_without_context(self):
        patch = ReviewerIRPatch.model_validate(
            {
                "summary": "Repair missing call input wiring.",
                "actions": [
                    {
                        "operation": "add",
                        "path": "/workflow/steps/0/inputs/r2",
                        "value": "raw_r2",
                        "reason": "The existing workflow input satisfies the missing task input.",
                    }
                ],
                "catalog_references": ["fastp:1.3.3"],
            }
        )

        with self.assertRaisesRegex(ReviewerPatchPolicyError, "catalog_references require"):
            validate_reviewer_patch_policy(patch)

    def test_policy_rejects_empty_or_nested_workflow_output_paths(self):
        invalid_paths = [
            "/workflow/outputs/",
            "/workflow/outputs/clean_r1/value",
        ]

        for path in invalid_paths:
            with self.subTest(path=path):
                patch = ReviewerIRPatch.model_validate(
                    {
                        "summary": "Patch invalid workflow output path.",
                        "actions": [
                            {
                                "operation": "replace",
                                "path": path,
                                "value": "qc.clean_r1",
                                "reason": "Workflow outputs are direct string expressions.",
                            }
                        ],
                    }
                )

                with self.assertRaises(ReviewerPatchPolicyError):
                    validate_reviewer_patch_policy(patch)

    def test_policy_allows_move_only_for_workflow_step_or_call_items(self):
        patch = ReviewerIRPatch.model_validate(
            {
                "summary": "Move a call to satisfy dependencies.",
                "actions": [
                    {
                        "operation": "move",
                        "from_path": "/workflow/steps/1",
                        "path": "/workflow/steps/0",
                        "reason": "Move the upstream call before the dependent call.",
                    }
                ],
            }
        )

        validated = validate_reviewer_patch_policy(patch)

        self.assertIs(validated, patch)

    def test_policy_rejects_move_outside_workflow_step_or_call_items(self):
        move_paths = [
            "/workflow/outputs/clean_r1",
            "/workflow/steps/0/inputs/r2",
            "/tasks/fastp/outputs/clean_r1/value",
        ]

        for path in move_paths:
            with self.subTest(path=path):
                patch = ReviewerIRPatch.model_validate(
                    {
                        "summary": "Move a non-ordering path.",
                        "actions": [
                            {
                                "operation": "move",
                                "from_path": path,
                                "path": path,
                                "reason": "MOVE is reserved for step or call item ordering.",
                            }
                        ],
                    }
                )

                with self.assertRaises(ReviewerPatchPolicyError):
                    validate_reviewer_patch_policy(patch)

    def test_repair_result_requires_parsed_patch_or_rejection_reason(self):
        patch = ReviewerIRPatch.model_validate(
            {
                "summary": "Repair output expression.",
                "actions": [
                    {
                        "operation": "replace",
                        "path": "/workflow/outputs/clean_r1",
                        "value": "qc.clean_r1",
                        "reason": "Use an existing call output.",
                    }
                ],
            }
        )

        result = ReviewerRepairResult(status=ReviewerRepairStatus.PATCH_PROPOSED, patch=patch)
        self.assertEqual(result.patch.summary, "Repair output expression.")

        with self.assertRaises(ValidationError):
            ReviewerRepairResult(status=ReviewerRepairStatus.PATCH_PROPOSED)

        with self.assertRaises(ValidationError):
            ReviewerRepairResult(status=ReviewerRepairStatus.POLICY_REJECTED)


if __name__ == "__main__":
    unittest.main()
