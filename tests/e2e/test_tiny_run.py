import os
import tempfile
import unittest
from pathlib import Path

import main as cli
from src.execution import get_execution_backend


EXAMPLES_DIR = Path(__file__).parents[2] / "examples"
RUN_E2E_ENV_VAR = "AI_BIOWORKFLOW_RUN_E2E"
TINY_INPUTS_ENV_VAR = "AI_BIOWORKFLOW_TINY_INPUTS"
EXPECTED_OUTPUT_KEYS = {
    "RNASeqDEG.deg_table",
    "RNASeqDEG.multiqc_report",
}


class CromwellTinyRunTests(unittest.TestCase):
    def test_rnaseq_tiny_run_when_e2e_is_enabled(self):
        if os.environ.get(RUN_E2E_ENV_VAR) != "1":
            self.skipTest(f"set {RUN_E2E_ENV_VAR}=1 to run the real Cromwell tiny e2e test")

        backend = get_execution_backend()
        availability = backend.availability()
        if not availability.available:
            self.fail(f"execution backend is unavailable: {availability.reason}")

        tiny_inputs = _tiny_inputs_path()
        if tiny_inputs is None:
            self.fail(f"{TINY_INPUTS_ENV_VAR} must point to a Cromwell-visible inputs JSON file")
        if not tiny_inputs.exists():
            self.fail(f"tiny-run inputs JSON does not exist: {tiny_inputs}")

        plan = cli.load_workflow_input(EXAMPLES_DIR / "rnaseq_deg_recipe_plan.json")
        state = cli.compile_workflow(plan, check=True)
        self.assertTrue(state["is_valid"], state["validation_message"])

        with tempfile.TemporaryDirectory() as tmpdir:
            wdl_path = Path(tmpdir) / "rnaseq_deg.wdl"
            wdl_path.write_text(state["current_wdl"], encoding="utf-8")

            result = backend.run(wdl_path, tiny_inputs)

        self.assertTrue(result.succeeded, result.message)
        self.assertEqual(result.status, "Succeeded")
        self.assertTrue(
            EXPECTED_OUTPUT_KEYS.issubset(result.outputs),
            f"missing expected Cromwell output keys: {EXPECTED_OUTPUT_KEYS - set(result.outputs)}",
        )


def _tiny_inputs_path() -> Path | None:
    raw_path = os.environ.get(TINY_INPUTS_ENV_VAR)
    if raw_path is None or raw_path.strip() == "":
        return None
    return Path(raw_path)


if __name__ == "__main__":
    unittest.main()
