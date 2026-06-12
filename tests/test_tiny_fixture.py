import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "examples" / "tiny" / "prepare_tiny_data.py"


class TinyFixtureTests(unittest.TestCase):
    def test_prepare_tiny_data_writes_fixture_and_inputs_json(self):
        module = _load_prepare_tiny_data_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fixture_root = tmp_path / "fixture"
            inputs_path = tmp_path / "rnaseq_deg.inputs.json"
            salmon_image = module.load_salmon_image()
            commands = []

            def fake_run(command, check):
                commands.append(command)
                self.assertTrue(check)
                index_dir = fixture_root / "salmon_index"
                index_dir.mkdir(parents=True, exist_ok=True)
                (index_dir / "versionInfo.json").write_text("{}", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            with patch.object(module.subprocess, "run", side_effect=fake_run):
                paths = module.prepare_fixture(
                    fixture_root=fixture_root,
                    container_runtime="fake-runtime",
                    salmon_image=salmon_image,
                    kmer_length=7,
                )
                module.write_inputs_json(inputs_path, "/data/ai-bioworkflow-tiny")
                module.validate_paths([*paths, inputs_path])

            self.assertTrue((fixture_root / "data" / "transcripts.fa").exists())
            self.assertTrue((fixture_root / "data" / "tx2gene.tsv").exists())
            self.assertTrue((fixture_root / "data" / "sample_groups.tsv").exists())
            self.assertTrue((fixture_root / "data" / "reads" / "ctrl_1_R1.fastq.gz").exists())
            self.assertTrue((fixture_root / "salmon_index" / "versionInfo.json").exists())
            self.assertEqual(len(commands), 1)
            self.assertEqual(
                commands[0][:11],
                [
                    "fake-runtime",
                    "run",
                    "--rm",
                    "-e",
                    "LC_ALL=C",
                    "-e",
                    "LANG=C",
                    "-e",
                    "LANGUAGE=C",
                    "-v",
                    f"{fixture_root.as_posix()}:/fixture",
                ],
            )
            self.assertEqual(commands[0][11], salmon_image)
            self.assertEqual(commands[0][12:15], ["salmon", "index", "-t"])
            self.assertEqual(commands[0][15], "/fixture/data/transcripts.fa")
            self.assertEqual(commands[0][17], "/fixture/salmon_index")

            inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
            self.assertEqual(
                inputs["RNASeqDEG.transcriptome_index"],
                "/data/ai-bioworkflow-tiny/salmon_index",
            )
            self.assertEqual(len(inputs["RNASeqDEG.sample_ids"]), 4)
            self.assertTrue(inputs["RNASeqDEG.raw_r1s"][0].startswith("/data/ai-bioworkflow-tiny/"))
            self.assertNotIn("{{ fixture_root }}", inputs_path.read_text(encoding="utf-8"))

    def test_prepare_tiny_data_rebuilds_incomplete_salmon_index(self):
        module = _load_prepare_tiny_data_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_root = Path(tmpdir) / "fixture"
            partial_index = fixture_root / "salmon_index"
            partial_index.mkdir(parents=True)
            stale_file = partial_index / "ref_k7_fixed.fa"
            stale_file.write_text("partial", encoding="utf-8")

            def fake_run(command, check):
                self.assertTrue(check)
                self.assertFalse(stale_file.exists())
                partial_index.mkdir(parents=True, exist_ok=True)
                (partial_index / "versionInfo.json").write_text("{}", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            with patch.object(module.subprocess, "run", side_effect=fake_run):
                module.prepare_fixture(
                    fixture_root=fixture_root,
                    container_runtime="fake-runtime",
                    salmon_image=module.load_salmon_image(),
                    kmer_length=7,
                )

            self.assertTrue((partial_index / "versionInfo.json").exists())

    def test_resolve_container_runtime_prefers_docker_then_podman(self):
        module = _load_prepare_tiny_data_module()

        with patch.object(module.shutil, "which", side_effect=lambda name: "docker.exe" if name == "docker" else None):
            self.assertEqual(module.resolve_container_runtime("auto"), "docker.exe")

        with patch.object(module.shutil, "which", side_effect=lambda name: "podman.exe" if name == "podman" else None):
            self.assertEqual(module.resolve_container_runtime("auto"), "podman.exe")


def _load_prepare_tiny_data_module():
    spec = importlib.util.spec_from_file_location("prepare_tiny_data", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
