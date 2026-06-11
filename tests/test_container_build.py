import tempfile
import unittest
from pathlib import Path

from scripts.build_container import (
    IMAGE_REVISION_FILE,
    discover_specs,
    select_specs,
)


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
