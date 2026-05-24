import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import main as cli
from src.nl_planner import NaturalLanguagePlanningError, NaturalLanguagePlanResult


EXAMPLES_DIR = Path(__file__).parents[1] / "examples"


class CliTests(unittest.TestCase):
    def test_load_workflow_input_reads_recipe_plan_example(self):
        data = cli.load_workflow_input(EXAMPLES_DIR / "rnaseq_deg_recipe_plan.json")

        self.assertEqual(data["workflow"]["name"], "RNASeqDEG")
        self.assertEqual(data["workflow"]["recipe"], "rnaseq_differential_expression")

    def test_load_prompt_reads_prompt_file(self):
        prompt = cli.load_prompt(prompt_file=EXAMPLES_DIR / "rnaseq_deg_request.txt")

        self.assertIn("bulk RNA-seq differential expression", prompt)

    def test_cli_compiles_natural_language_prompt_with_mock_planner(self):
        planned = cli.load_workflow_input(EXAMPLES_DIR / "rnaseq_deg_recipe_plan.json")
        plan_result = NaturalLanguagePlanResult(
            plan=planned,
            planner_prompt="planner prompt",
            raw_response=json.dumps(planned),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "rnaseq_deg.wdl"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch("main.create_natural_language_plan", return_value=plan_result) as planner:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    exit_code = cli.main(
                        [
                            "--prompt",
                            "Run bulk RNA-seq differential expression.",
                            "--output",
                            str(output_path),
                            "--print-plan",
                            "--no-check",
                        ]
                    )

            self.assertEqual(exit_code, 0, stderr.getvalue())
            planner.assert_called_once()
            self.assertIn('"recipe": "rnaseq_differential_expression"', stdout.getvalue())
            self.assertIn("workflow RNASeqDEG", output_path.read_text(encoding="utf-8"))

    def test_cli_saves_natural_language_plan_and_planner_prompt(self):
        planned = cli.load_workflow_input(EXAMPLES_DIR / "rnaseq_deg_recipe_plan.json")
        plan_result = NaturalLanguagePlanResult(
            plan=planned,
            planner_prompt="planner prompt",
            raw_response=json.dumps(planned),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "rnaseq_deg.wdl"
            plan_path = Path(tmpdir) / "plan.json"
            prompt_path = Path(tmpdir) / "planner_prompt.txt"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch("main.build_default_planner_prompt", return_value="planner prompt"):
                with patch("main.create_natural_language_plan", return_value=plan_result):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        exit_code = cli.main(
                            [
                                "--prompt",
                                "Run bulk RNA-seq differential expression.",
                                "--output",
                                str(output_path),
                                "--save-plan",
                                str(plan_path),
                                "--save-planner-prompt",
                                str(prompt_path),
                                "--no-check",
                            ]
                        )

            self.assertEqual(exit_code, 0, stderr.getvalue())
            self.assertEqual(json.loads(plan_path.read_text(encoding="utf-8")), planned)
            self.assertEqual(prompt_path.read_text(encoding="utf-8"), "planner prompt")
            self.assertIn("Planner plan written to", stderr.getvalue())
            self.assertIn("Planner prompt written to", stderr.getvalue())

    def test_cli_reports_natural_language_planning_failure(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch(
            "main.create_natural_language_plan",
            side_effect=NaturalLanguagePlanningError("LLM planner JSON parsing failed: bad json"),
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli.main(["--prompt", "Run RNA-seq differential expression."])

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Natural language planning failed", stderr.getvalue())
        self.assertIn("JSON parsing failed", stderr.getvalue())

    def test_cli_saves_planner_prompt_even_when_planning_fails(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / "planner_prompt.txt"
            with patch("main.build_default_planner_prompt", return_value="planner prompt"):
                with patch(
                    "main.create_natural_language_plan",
                    side_effect=NaturalLanguagePlanningError("LLM planner JSON parsing failed: bad json"),
                ):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        exit_code = cli.main(
                            [
                                "--prompt",
                                "Run RNA-seq differential expression.",
                                "--save-planner-prompt",
                                str(prompt_path),
                            ]
                        )

            self.assertEqual(exit_code, 1)
            self.assertEqual(prompt_path.read_text(encoding="utf-8"), "planner prompt")

    def test_cli_writes_wdl_output_from_recipe_plan_without_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "rnaseq_deg.wdl"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli.main(
                    [
                        "--input",
                        str(EXAMPLES_DIR / "rnaseq_deg_recipe_plan.json"),
                        "--output",
                        str(output_path),
                        "--print-ir",
                        "--no-check",
                    ]
                )

            self.assertEqual(exit_code, 0, stderr.getvalue())
            self.assertTrue(output_path.exists())
            self.assertIn("workflow RNASeqDEG", output_path.read_text(encoding="utf-8"))
            self.assertIn('"workflow"', stdout.getvalue())
            self.assertIn("WDL written to", stderr.getvalue())

    def test_cli_returns_failure_for_invalid_recipe_plan(self):
        plan = cli.load_workflow_input(EXAMPLES_DIR / "rnaseq_deg_recipe_plan.json")
        plan["workflow"]["inputs"].pop("sample_groups")

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "invalid_plan.json"
            input_path.write_text(json.dumps(plan), encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli.main(["--input", str(input_path), "--no-check"])

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("missing required workflow input 'sample_groups'", stderr.getvalue())

    def test_cli_stdout_is_pure_wdl_without_output_path(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli.main(
                [
                    "--input",
                    str(EXAMPLES_DIR / "rnaseq_workflow_ir.json"),
                    "--no-check",
                ]
            )

        self.assertEqual(exit_code, 0, stderr.getvalue())
        self.assertTrue(stdout.getvalue().startswith("version 1.0\n"))
        self.assertNotIn("IR normalizer node", stdout.getvalue())
        self.assertIn("WDL syntax validation skipped", stderr.getvalue())

    def test_cli_verbose_logs_stay_on_stderr(self):
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli.main(
                [
                    "--input",
                    str(EXAMPLES_DIR / "rnaseq_workflow_ir.json"),
                    "--no-check",
                    "--verbose",
                ]
            )

        self.assertEqual(exit_code, 0, stderr.getvalue())
        self.assertTrue(stdout.getvalue().startswith("version 1.0\n"))
        self.assertIn("IR normalizer node is normalizing Workflow IR.", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
