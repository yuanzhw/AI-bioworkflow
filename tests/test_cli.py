import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import main as cli


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

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "rnaseq_deg.wdl"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch("main.plan_from_natural_language", return_value=planned) as planner:
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
        self.assertNotIn("Planner node", stdout.getvalue())
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
        self.assertIn("Planner node is normalizing Workflow IR.", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
