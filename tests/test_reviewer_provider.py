import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.reviewer_provider import (
    LlmReviewerRepairProvider,
    ReviewerProviderResponseError,
    ReviewerProviderUnavailableError,
    make_default_reviewer_provider,
    parse_reviewer_repair_response,
)
from src.reviewer_repair import ReviewerRepairRequest, ReviewerRepairStatus


def sample_reviewer_request() -> ReviewerRepairRequest:
    return ReviewerRepairRequest.model_validate(
        {
            "workflow_ir": {
                "workflow": {
                    "name": "ReferencePrep",
                    "inputs": {"transcriptome_fasta": "File"},
                    "steps": [
                        {
                            "kind": "call",
                            "id": "index",
                            "task": "salmon_index",
                            "inputs": {
                                "transcriptome_fasta": "transcriptome_fasta",
                            },
                        }
                    ],
                    "outputs": {
                        "transcriptome_index": "index.index_archive",
                    },
                },
                "tasks": {
                    "salmon_index": {
                        "inputs": {"transcriptome_fasta": "File"},
                        "command": "salmon index -t ~{transcriptome_fasta}",
                        "outputs": {
                            "index_archive": {
                                "type": "File",
                                "value": '"salmon_index.tar.gz"',
                            }
                        },
                        "runtime": {
                            "docker": "quay.io/biocontainers/salmon:1.9.0--h7e5ed60_1",
                        },
                    }
                },
            },
            "failure_stage": "analyzer",
            "analysis_errors": ["workflow output is missing"],
            "catalog_context": {
                "recipes": [
                    {
                        "recipe_id": "rnaseq_reference_preparation",
                        "step_ids": ["build_salmon_index"],
                        "tool_ids": ["salmon_index"],
                    }
                ],
                "tools": [
                    {
                        "tool_id": "salmon_index",
                        "version": "1.9.0",
                        "inputs": ["transcriptome_fasta"],
                        "outputs": ["index_archive"],
                        "trust_status": "catalog-approved",
                        "runtime_docker": (
                            "quay.io/biocontainers/salmon:1.9.0--h7e5ed60_1"
                        ),
                    }
                ],
            },
            "attempt_index": 1,
        }
    )


class FakeReviewerLlm:
    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.response)


class ReviewerProviderTests(unittest.TestCase):
    def test_llm_provider_renders_structured_request_and_parses_fenced_result(self):
        response = {
            "status": "no_action",
            "diagnostics": ["No safe IR-only repair is available."],
        }
        fake_llm = FakeReviewerLlm(
            f"```json\n{json.dumps(response)}\n```"
        )
        provider = LlmReviewerRepairProvider(fake_llm)

        result = provider.repair(sample_reviewer_request())

        self.assertEqual(result.status, ReviewerRepairStatus.NO_ACTION)
        self.assertEqual(
            result.diagnostics,
            ["No safe IR-only repair is available."],
        )
        self.assertEqual(len(fake_llm.prompts), 1)
        prompt = fake_llm.prompts[0]
        self.assertIn('"failure_stage": "analyzer"', prompt)
        self.assertIn('"tool_id": "salmon_index"', prompt)
        self.assertIn("workflow.steps as canonical", prompt)
        self.assertIn(
            "patch to an object only when status is patch_proposed",
            prompt,
        )
        self.assertIn(
            "rejection_reason to a non-empty string only when status is policy_rejected",
            prompt,
        )
        self.assertIn("patch_proposed example", prompt)
        self.assertNotIn('"tool_id": "fastp"', prompt)

    def test_parse_reviewer_response_rejects_non_json_without_echoing_raw_text(self):
        raw_response = "TOP_SECRET provider prose without JSON"

        with self.assertRaises(ReviewerProviderResponseError) as raised:
            parse_reviewer_repair_response(raw_response)

        self.assertNotIn("TOP_SECRET", str(raised.exception))

    def test_parse_reviewer_response_rejects_invalid_schema_without_echoing_values(self):
        raw_response = json.dumps(
            {
                "status": "patch_proposed",
                "patch": {
                    "secret_marker": "TOP_SECRET",
                },
            }
        )

        with self.assertRaises(ReviewerProviderResponseError) as raised:
            parse_reviewer_repair_response(raw_response)

        self.assertIn("does not match the result schema", str(raised.exception))
        self.assertNotIn("TOP_SECRET", str(raised.exception))

    def test_default_reviewer_provider_requires_api_key(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            with self.assertRaisesRegex(
                ReviewerProviderUnavailableError,
                "DEEPSEEK_API_KEY",
            ):
                make_default_reviewer_provider()


if __name__ == "__main__":
    unittest.main()
