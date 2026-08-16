import unittest

from pydantic import ValidationError

from src.schema import (
    WorkflowCompatibilityError,
    WorkflowIR,
    coerce_workflow_ir,
    compatibility_calls_match_steps,
    flatten_workflow_calls,
    refresh_compatibility_calls,
)


def call_step(call_id: str = "qc", input_value: str = "raw_fastq") -> dict:
    return {
        "kind": "call",
        "id": call_id,
        "task": "fastp",
        "inputs": {"fastq": input_value},
    }


def workflow_ir(workflow: dict) -> dict:
    return {
        "workflow": {
            "name": "CompatibilityDemo",
            "inputs": {"raw_fastq": "File"},
            "outputs": {},
            **workflow,
        },
        "tasks": {},
    }


class WorkflowSchemaCompatibilityTests(unittest.TestCase):
    def test_calls_only_input_builds_canonical_steps(self):
        legacy_call = call_step()
        legacy_call.pop("kind")

        parsed = coerce_workflow_ir(workflow_ir({"calls": [legacy_call]}))

        self.assertEqual([step.id for step in parsed.workflow.steps], ["qc"])
        self.assertTrue(compatibility_calls_match_steps(parsed.workflow))

    def test_steps_only_input_builds_flattened_compatibility_view(self):
        parsed = coerce_workflow_ir(
            workflow_ir(
                {
                    "steps": [
                        {
                            "kind": "scatter",
                            "id": "per_sample",
                            "item": "i",
                            "over": "range(1)",
                            "body": [call_step()],
                        }
                    ]
                }
            )
        )

        self.assertEqual([call.id for call in parsed.workflow.calls], ["qc"])
        self.assertIsNot(
            parsed.workflow.calls[0],
            flatten_workflow_calls(parsed.workflow.steps)[0],
        )

    def test_coercion_rejects_mismatched_dual_views(self):
        data = workflow_ir(
            {
                "steps": [call_step()],
                "calls": [call_step(input_value="tampered_input")],
            }
        )

        with self.assertRaisesRegex(
            WorkflowCompatibilityError,
            "compatibility calls do not match canonical workflow steps",
        ):
            coerce_workflow_ir(data)

    def test_coercion_accepts_equivalent_default_call_inputs(self):
        canonical_call = call_step()
        canonical_call.pop("inputs")
        compatibility_call = call_step()
        compatibility_call["inputs"] = {}

        parsed = coerce_workflow_ir(
            workflow_ir(
                {
                    "steps": [canonical_call],
                    "calls": [compatibility_call],
                }
            )
        )

        self.assertTrue(compatibility_calls_match_steps(parsed.workflow))

    def test_direct_model_validation_rejects_mismatched_dual_views(self):
        data = workflow_ir(
            {
                "steps": [call_step()],
                "calls": [call_step(input_value="tampered_input")],
            }
        )

        with self.assertRaisesRegex(
            ValidationError,
            "compatibility calls do not match canonical workflow steps",
        ):
            WorkflowIR.model_validate(data)

    def test_refresh_rebuilds_detached_compatibility_snapshot(self):
        parsed = coerce_workflow_ir(workflow_ir({"steps": [call_step()]}))
        canonical_call = flatten_workflow_calls(parsed.workflow.steps)[0]
        canonical_call.inputs["fastq"] = "updated_fastq"

        self.assertFalse(compatibility_calls_match_steps(parsed.workflow))

        refresh_compatibility_calls(parsed.workflow)

        self.assertTrue(compatibility_calls_match_steps(parsed.workflow))
        self.assertIsNot(parsed.workflow.calls[0], canonical_call)
        self.assertEqual(parsed.workflow.calls[0].inputs["fastq"], "updated_fastq")


if __name__ == "__main__":
    unittest.main()
