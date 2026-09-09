import tempfile
import unittest
from pathlib import Path

from scripts.build_container import (
    IMAGE_REVISION_FILE,
    discover_specs,
    select_specs,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class ContainerBuildScriptTests(unittest.TestCase):
    def test_select_spec_uses_image_revision_in_tag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            containers_root = Path(tmpdir)
            context_dir = make_container_dir(containers_root, "deseq2", "1.42.1", revision="r2")

            specs = select_specs(
                containers_root=containers_root,
                all_containers=False,
                tool="deseq2",
                version="1.42.1",
            )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].context_dir, context_dir)
        self.assertEqual(specs[0].image_revision, "r2")
        self.assertEqual(specs[0].image_tag, "1.42.1-r2")
        self.assertEqual(
            specs[0].image("ghcr.io/example/project"),
            "ghcr.io/example/project/deseq2:1.42.1-r2",
        )

    def test_discover_specs_requires_image_revision_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            containers_root = Path(tmpdir)
            make_container_dir(containers_root, "tximport", "1.30.0", revision=None)

            with self.assertRaisesRegex(SystemExit, IMAGE_REVISION_FILE):
                discover_specs(containers_root)

    def test_discover_specs_rejects_invalid_image_revision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            containers_root = Path(tmpdir)
            make_container_dir(containers_root, "multiqc", "1.21", revision="latest")

            with self.assertRaisesRegex(SystemExit, "must contain a value like r1"):
                discover_specs(containers_root)

    def test_discover_specs_ignores_directories_without_dockerfile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            containers_root = Path(tmpdir)
            ignored_dir = containers_root / "notes" / "draft"
            ignored_dir.mkdir(parents=True)

            self.assertEqual(discover_specs(containers_root), [])

    def test_scanpy_wrapper_container_contract_is_discoverable(self):
        specs = discover_specs(REPO_ROOT / "containers")
        spec = next(spec for spec in specs if spec.tool == "scanpy_qc_clustering")

        self.assertEqual(spec.version, "1.12.3")
        self.assertEqual(spec.image_revision, "r1")
        self.assertEqual(spec.image_tag, "1.12.3-r1")
        self.assertTrue((spec.context_dir / "run_scanpy_qc_clustering.py").is_file())
        self.assertTrue(spec.smoke_test.is_file())

    def test_scanpy_wrapper_cell_qc_export_includes_sample_id(self):
        wrapper_path = (
            REPO_ROOT
            / "containers"
            / "scanpy_qc_clustering"
            / "1.12.3"
            / "run_scanpy_qc_clustering.py"
        )
        source = wrapper_path.read_text(encoding="utf-8")
        sample_assignment = source.index('adata.obs["sample_id"] = args.sample_id')
        qc_table = source.index("cell_qc = adata.obs[")
        qc_export = source.index("cell_qc.reset_index().to_csv")

        self.assertLess(sample_assignment, qc_table)
        self.assertIn('"sample_id"', source[qc_table:qc_export])


def make_container_dir(
    containers_root: Path,
    tool: str,
    version: str,
    *,
    revision: str | None,
) -> Path:
    context_dir = containers_root / tool / version
    context_dir.mkdir(parents=True)
    (context_dir / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (context_dir / "smoke_test.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    if revision is not None:
        (context_dir / IMAGE_REVISION_FILE).write_text(f"{revision}\n", encoding="utf-8")
    return context_dir


if __name__ == "__main__":
    unittest.main()
