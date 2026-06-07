import json
import unittest
from types import SimpleNamespace

from src.catalog import load_tool_catalog
from src.nl_planner import (
    PlannerCatalogError,
    PlannerJsonError,
    PlannerSchemaError,
    build_default_planner_prompt,
    build_planner_prompt,
    create_natural_language_plan,
    parse_json_object,
    plan_from_natural_language,
)
from src.recipes import load_recipe_catalog


def sample_rnaseq_tool_plan():
    return {
        "workflow": {
            "name": "RNASeqDEG",
            "recipe": "rnaseq_differential_expression",
            "inputs": {
                "sample_ids": "Array[String]",
                "raw_r1s": "Array[File]",
                "raw_r2s": "Array[File]",
                "transcriptome_index": "File",
                "tx2gene": "File",
                "sample_groups": "File",
            },
            "tool_calls": [
                {
                    "id": "qc",
                    "step": "qc",
                    "tool": "fastp",
                    "version": "1.3.3",
                    "inputs": {
                        "r1": "raw_r1s",
                        "r2": "raw_r2s",
                    },
                    "params": {
                        "thread": 4,
                    },
                },
                {
                    "id": "quantify",
                    "step": "quantify",
                    "tool": "salmon",
                    "version": "1.11.4",
                    "inputs": {
                        "r1": "qc.clean_r1",
                        "r2": "qc.clean_r2",
                        "index": "transcriptome_index",
                    },
                    "params": {
                        "thread": 8,
                    },
                },
                {
                    "id": "summarize",
                    "step": "summarize_transcripts",
                    "tool": "tximport",
                    "version": "1.30.0",
                    "inputs": {
                        "quant_files": "quantify.quant_file",
                        "sample_ids": "sample_ids",
                        "tx2gene": "tx2gene",
                    },
                    "params": {},
                },
                {
                    "id": "deg",
                    "step": "differential_expression",
                    "tool": "deseq2",
                    "version": "1.42.0",
                    "inputs": {
                        "counts": "summarize.gene_counts",
                        "sample_groups": "sample_groups",
                    },
                    "params": {
                        "contrast": "condition",
                    },
                },
                {
                    "id": "report",
                    "step": "qc_report",
                    "tool": "multiqc",
                    "version": "1.21",
                    "inputs": {
                        "report_files": [
                            "qc.html_report",
                            "qc.json_report",
                            "quantify.log_file",
                        ],
                    },
                    "params": {},
                },
            ],
            "outputs": {
                "deg_table": "deg.deg_table",
                "multiqc_report": "report.multiqc_report",
            },
        }
    }


class FakePlannerLlm:
    def __init__(self, response: str):
        self.response = response
        self.prompts = []

    def invoke(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.response)


class NaturalLanguagePlannerTests(unittest.TestCase):
    def test_parse_json_object_accepts_fenced_json(self):
        parsed = parse_json_object('```json\n{"workflow": {"name": "Demo"}}\n```')

        self.assertEqual(parsed["workflow"]["name"], "Demo")

    def test_parse_json_object_rejects_non_json(self):
        with self.assertRaisesRegex(PlannerJsonError, "does not contain a JSON object"):
            parse_json_object("I would run fastp first.")

    def test_build_planner_prompt_includes_catalog_and_request(self):
        tool_catalog = load_tool_catalog()
        recipe_catalog = load_recipe_catalog(tool_catalog=tool_catalog)

        prompt = build_planner_prompt(
            "Run RNA-seq differential expression.",
            tool_catalog,
            recipe_catalog,
        )

        self.assertIn("rnaseq_differential_expression", prompt)
        self.assertIn("fastp", prompt)
        self.assertIn("per_sample", prompt)
        self.assertIn("tximport", prompt)
        self.assertIn("Run RNA-seq differential expression.", prompt)

    def test_plan_from_natural_language_validates_llm_plan(self):
        fake_llm = FakePlannerLlm(json.dumps(sample_rnaseq_tool_plan()))

        plan = plan_from_natural_language(
            "Run RNA-seq differential expression.",
            llm=fake_llm,
        )

        self.assertEqual(plan["workflow"]["recipe"], "rnaseq_differential_expression")
        self.assertIn("Run RNA-seq differential expression.", fake_llm.prompts[0])

    def test_create_natural_language_plan_returns_observability_details(self):
        fake_llm = FakePlannerLlm(json.dumps(sample_rnaseq_tool_plan()))

        result = create_natural_language_plan(
            "Run RNA-seq differential expression.",
            llm=fake_llm,
        )

        self.assertEqual(result.plan["workflow"]["recipe"], "rnaseq_differential_expression")
        self.assertIn("Catalog:", result.planner_prompt)
        self.assertIn("RNASeqDEG", result.raw_response)

    def test_plan_from_natural_language_reports_schema_error(self):
        fake_llm = FakePlannerLlm(json.dumps({"workflow": {"name": "RNASeqDEG"}}))

        with self.assertRaisesRegex(PlannerSchemaError, "plan schema validation failed"):
            plan_from_natural_language(
                "Run RNA-seq differential expression.",
                llm=fake_llm,
            )

    def test_plan_from_natural_language_reports_catalog_error(self):
        plan = sample_rnaseq_tool_plan()
        plan["workflow"]["tool_calls"] = [
            tool_call
            for tool_call in plan["workflow"]["tool_calls"]
            if tool_call["step"] != "differential_expression"
        ]
        fake_llm = FakePlannerLlm(json.dumps(plan))

        with self.assertRaisesRegex(PlannerCatalogError, "recipe/catalog validation failed"):
            plan_from_natural_language(
                "Run RNA-seq differential expression.",
                llm=fake_llm,
            )

    def test_plan_from_natural_language_rejects_unanalyzable_array_concatenation(self):
        plan = sample_rnaseq_tool_plan()
        plan["workflow"]["tool_calls"][-1]["inputs"] = {
            "report_files": "qc.html_report + qc.json_report",
        }
        fake_llm = FakePlannerLlm(json.dumps(plan))

        with self.assertRaisesRegex(PlannerCatalogError, "references unavailable output"):
            plan_from_natural_language(
                "Run RNA-seq differential expression.",
                llm=fake_llm,
            )

    def test_build_default_planner_prompt_loads_catalog(self):
        prompt = build_default_planner_prompt("Run RNA-seq differential expression.")

        self.assertIn("rnaseq_differential_expression", prompt)
        self.assertIn("Run RNA-seq differential expression.", prompt)


if __name__ == "__main__":
    unittest.main()
