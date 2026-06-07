import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
SCRIPT_PATH = REPO_ROOT / "examples" / "tiny" / "prepare_tiny_data.py"


class TinyFixtureTests(unittest.TestCase):
    def test_prepare_tiny_data_writes_fixture_and_inputs_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fake_salmon = tmp_path / "fake_salmon.py"
            fixture_root = tmp_path / "fixture"
            inputs_path = tmp_path / "rnaseq_deg.inputs.json"
            fake_salmon.write_text(
                "\n".join(
                    [
                        "import sys",
                        "from pathlib import Path",
                        "args = sys.argv[1:]",
                        "if args[0] != 'index':",
                        "    raise SystemExit(2)",
                        "index_dir = Path(args[args.index('-i') + 1])",
                        "index_dir.mkdir(parents=True, exist_ok=True)",
                        "(index_dir / 'versionInfo.json').write_text('{}', encoding='utf-8')",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--fixture-root",
                    str(fixture_root),
                    "--write-inputs",
                    str(inputs_path),
                    "--cromwell-root",
                    "/data/ai-bioworkflow-tiny",
                    "--salmon-command",
                    sys.executable,
                    str(fake_salmon),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((fixture_root / "data" / "transcripts.fa").exists())
            self.assertTrue((fixture_root / "data" / "tx2gene.tsv").exists())
            self.assertTrue((fixture_root / "data" / "sample_groups.tsv").exists())
            self.assertTrue((fixture_root / "data" / "reads" / "ctrl_1_R1.fastq.gz").exists())
            self.assertTrue((fixture_root / "salmon_index" / "versionInfo.json").exists())

            inputs = json.loads(inputs_path.read_text(encoding="utf-8"))
            self.assertEqual(
                inputs["RNASeqDEG.transcriptome_index"],
                "/data/ai-bioworkflow-tiny/salmon_index",
            )
            self.assertEqual(len(inputs["RNASeqDEG.sample_ids"]), 4)
            self.assertTrue(inputs["RNASeqDEG.raw_r1s"][0].startswith("/data/ai-bioworkflow-tiny/"))
            self.assertNotIn("{{ fixture_root }}", inputs_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
