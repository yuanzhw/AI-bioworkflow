import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import main as cli
from src.catalog import load_tool_catalog
from src.execution import ensure_tools_execution_eligible
from src.tools.validator import miniwdl_available


EXAMPLES_DIR = Path(__file__).parents[1] / "examples"
REQUIRED_IMAGES = [
    "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0",
    "quay.io/biocontainers/salmon:1.9.0--h7e5ed60_0",
    "ghcr.io/yuanzhw/ai-bioworkflow/tximport:1.30.0-r1",
    "ghcr.io/yuanzhw/ai-bioworkflow/deseq2:1.42.1-r2",
    "ghcr.io/yuanzhw/ai-bioworkflow/multiqc:1.21-r1",
]


class OptionalTinyRunTests(unittest.TestCase):
    def test_rnaseq_tiny_run_when_local_runtime_is_ready(self):
        if not miniwdl_available():
            self.skipTest("miniwdl is not installed")

        container_runtime = shutil.which("docker") or shutil.which("podman")
        if container_runtime is None:
            self.skipTest("Docker or Podman is not installed")

        missing_images = [
            image
            for image in REQUIRED_IMAGES
            if not _container_image_available(container_runtime, image)
        ]
        if missing_images:
            self.skipTest(f"required tiny-run images are not available locally: {missing_images}")

        tiny_inputs = EXAMPLES_DIR / "tiny" / "rnaseq_deg.inputs.json"
        if not tiny_inputs.exists():
            self.skipTest(f"tiny run inputs are not available: {tiny_inputs}")

        plan = cli.load_workflow_input(EXAMPLES_DIR / "rnaseq_deg_recipe_plan.json")
        tool_catalog = load_tool_catalog()
        selected_tools = [
            tool_catalog.get(tool_call["tool"], tool_call["version"])
            for tool_call in plan["workflow"]["tool_calls"]
        ]
        ensure_tools_execution_eligible(selected_tools)

        state = cli.compile_workflow(plan, check=True)
        self.assertTrue(state["is_valid"], state["validation_message"])

        with tempfile.TemporaryDirectory() as tmpdir:
            wdl_path = Path(tmpdir) / "rnaseq_deg.wdl"
            wdl_path.write_text(state["current_wdl"], encoding="utf-8")

            result = subprocess.run(
                [
                    _miniwdl_command(),
                    "run",
                    str(wdl_path),
                    "-i",
                    str(tiny_inputs),
                    "--dir",
                    str(Path(tmpdir) / "run"),
                ],
                cwd=Path(__file__).parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        run_outputs = _last_json_object(result.stdout)
        self.assertIn("RNASeqDEG.deg_table", run_outputs)
        self.assertIn("RNASeqDEG.multiqc_report", run_outputs)


def _container_image_available(runtime: str, image: str) -> bool:
    result = subprocess.run(
        [runtime, "image", "inspect", image],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _miniwdl_command() -> str:
    executable = shutil.which("miniwdl")
    if executable:
        return executable
    return str(Path(sys.executable).with_name("miniwdl"))


def _last_json_object(text: str) -> dict:
    start = text.rfind("{")
    if start == -1:
        return {}
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return {}


if __name__ == "__main__":
    unittest.main()
