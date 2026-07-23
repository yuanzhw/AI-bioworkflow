import unittest

from src.reviewer_patcher import (
    ReviewerPatchApplicationError,
    apply_reviewer_patch,
)
from src.reviewer_repair import (
    ApprovedCatalogContext,
    ReviewerIRPatch,
    ReviewerPatchPolicyError,
)
from src.schema import WorkflowIR


def sample_workflow_ir():
    return {
        "workflow": {
            "name": "ReviewerPatchDemo",
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
            "calls": [
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
                "legacy_report": "qc.clean_r1",
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
                        "value": "\"old_clean_R1.fq.gz\"",
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


def sample_ordering_ir():
    workflow_ir = sample_workflow_ir()
    workflow_ir["workflow"]["steps"] = [
        {
            "kind": "call",
            "id": "align",
            "task": "bwa_mem",
            "inputs": {
                "r1": "qc.clean_r1",
            },
        },
        workflow_ir["workflow"]["steps"][0],
    ]
    workflow_ir["workflow"]["calls"] = [
        {
            "kind": "call",
            "id": "align",
            "task": "bwa_mem",
            "inputs": {
                "r1": "qc.clean_r1",
            },
        },
        workflow_ir["workflow"]["calls"][0],
    ]
    workflow_ir["tasks"]["bwa_mem"] = {
        "inputs": {
            "r1": "File",
        },
        "command": "bwa mem ref.fa ~{r1}",
        "outputs": {
            "bam": {
                "type": "File",
                "value": "\"aligned.bam\"",
            }
        },
        "runtime": {
            "docker": "ubuntu:22.04",
        },
    }
    return workflow_ir


def sample_catalog_context():
    return ApprovedCatalogContext.model_validate(
        {
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
    )


class ReviewerPatcherTests(unittest.TestCase):
    def test_apply_reviewer_patch_updates_allowed_workflow_ir_paths(self):
        original = sample_workflow_ir()
        patch = ReviewerIRPatch.model_validate(
            {
                "summary": "Repair missing call input and output literals.",
                "actions": [
                    {
                        "operation": "add",
                        "path": "/workflow/steps/0/inputs/r2",
                        "value": "raw_r2",
                        "reason": "Use an existing workflow input for the missing task input.",
                    },
                    {
                        "operation": "replace",
                        "path": "/workflow/outputs/clean_r1",
                        "value": "qc.clean_r1",
                        "reason": "Keep the workflow output wired to an existing call output.",
                    },
                    {
                        "operation": "replace",
                        "path": "/tasks/fastp/outputs/clean_r1/value",
                        "value": "\"clean_R1.fq.gz\"",
                        "reason": "Use the repaired output literal.",
                    },
                ],
                "catalog_references": ["fastp:1.3.3"],
            }
        )

        patched = apply_reviewer_patch(original, patch, catalog_context=sample_catalog_context())

        self.assertIsInstance(patched, WorkflowIR)
        self.assertEqual(patched.workflow.steps[0].inputs["r2"], "raw_r2")
        self.assertEqual(patched.workflow.calls[0].inputs["r2"], "raw_r2")
        self.assertEqual(patched.workflow.outputs["clean_r1"], "qc.clean_r1")
        self.assertEqual(patched.tasks["fastp"].outputs["clean_r1"].value, "\"clean_R1.fq.gz\"")
        self.assertNotIn("r2", original["workflow"]["steps"][0]["inputs"])
        self.assertNotIn("r2", original["workflow"]["calls"][0]["inputs"])

    def test_apply_reviewer_patch_removes_workflow_output_without_mutating_original(self):
        original = sample_workflow_ir()
        patch = ReviewerIRPatch.model_validate(
            {
                "summary": "Remove obsolete workflow output.",
                "actions": [
                    {
                        "operation": "remove",
                        "path": "/workflow/outputs/legacy_report",
                        "reason": "The output references an obsolete report.",
                    }
                ],
            }
        )

        patched = apply_reviewer_patch(original, patch)

        self.assertNotIn("legacy_report", patched.workflow.outputs)
        self.assertIn("legacy_report", original["workflow"]["outputs"])

    def test_apply_reviewer_patch_moves_workflow_steps_and_syncs_calls(self):
        original = sample_ordering_ir()
        patch = ReviewerIRPatch.model_validate(
            {
                "summary": "Move upstream call before dependent call.",
                "actions": [
                    {
                        "operation": "move",
                        "from_path": "/workflow/steps/1",
                        "path": "/workflow/steps/0",
                        "reason": "The qc call must run before align consumes qc.clean_r1.",
                    }
                ],
            }
        )

        patched = apply_reviewer_patch(original, patch)

        self.assertEqual([step.id for step in patched.workflow.steps], ["qc", "align"])
        self.assertEqual([call.id for call in patched.workflow.calls], ["qc", "align"])
        self.assertEqual(original["workflow"]["steps"][0]["id"], "align")

    def test_apply_reviewer_patch_rejects_forbidden_path_without_mutating_original(self):
        original = sample_workflow_ir()
        patch = ReviewerIRPatch.model_validate(
            {
                "summary": "Attempt forbidden runtime edit.",
                "actions": [
                    {
                        "operation": "replace",
                        "path": "/tasks/fastp/runtime/docker",
                        "value": "ubuntu:22.04",
                        "reason": "Reviewer must not change runtime images.",
                    }
                ],
            }
        )

        with self.assertRaises(ReviewerPatchPolicyError):
            apply_reviewer_patch(original, patch)

        self.assertEqual(
            original["tasks"]["fastp"]["runtime"]["docker"],
            "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0",
        )

    def test_apply_reviewer_patch_rejects_missing_replace_target_without_mutating_original(self):
        original = sample_workflow_ir()
        patch = ReviewerIRPatch.model_validate(
            {
                "summary": "Replace a missing call input.",
                "actions": [
                    {
                        "operation": "replace",
                        "path": "/workflow/steps/0/inputs/r2",
                        "value": "raw_r2",
                        "reason": "The input must exist for replace.",
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ReviewerPatchApplicationError, "does not exist"):
            apply_reviewer_patch(original, patch)

        self.assertNotIn("r2", original["workflow"]["steps"][0]["inputs"])

    def test_apply_reviewer_patch_rejects_schema_invalid_candidate_without_mutating_original(self):
        original = sample_workflow_ir()
        patch = ReviewerIRPatch.model_validate(
            {
                "summary": "Set workflow output to an invalid value type.",
                "actions": [
                    {
                        "operation": "replace",
                        "path": "/workflow/outputs/clean_r1",
                        "value": ["qc.clean_r1"],
                        "reason": "Workflow outputs must remain string expressions.",
                    }
                ],
            }
        )

        with self.assertRaisesRegex(ReviewerPatchApplicationError, "invalid Workflow IR"):
            apply_reviewer_patch(original, patch)

        self.assertEqual(original["workflow"]["outputs"]["clean_r1"], "qc.clean_r1")


if __name__ == "__main__":
    unittest.main()
