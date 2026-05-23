import unittest
from collections.abc import Sequence

from src.catalog import (
    AmbiguousContainerImageError,
    ContainerImageCandidate,
    ContainerImageNotFoundError,
    StaticContainerImageProvider,
    ToolSpec,
    fill_missing_tool_container,
    parse_tool_version_key,
    resolve_tool_container,
    static_provider_from_image_map,
)


def make_tool(*, docker: str | None = None, aliases: list[str] | None = None) -> ToolSpec:
    data = {
        "id": "fastp",
        "version": "0.23.2",
        "aliases": aliases or ["fastq qc"],
        "description": "FASTQ quality control.",
        "inputs": {
            "r1": {
                "type": "File",
                "required": True,
            }
        },
        "params": {
            "thread": {
                "type": "Int",
                "default": 4,
                "min": 1,
            }
        },
        "outputs": {
            "clean_r1": {
                "type": "File",
                "value": '"clean_R1.fq.gz"',
            }
        },
        "command_template": "fastp -i ~{r1} --thread ~{thread}",
        "runtime": {
            "cpu": 4,
            "memory": "8G",
        },
    }
    if docker:
        data["runtime"]["docker"] = docker
    return ToolSpec.model_validate(data)


class FailingProvider:
    def search(
        self,
        tool_id: str,
        version: str,
        aliases: Sequence[str] = (),
    ) -> Sequence[ContainerImageCandidate]:
        raise AssertionError("provider should not be called")


class RecordingProvider:
    def __init__(self):
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def search(
        self,
        tool_id: str,
        version: str,
        aliases: Sequence[str] = (),
    ) -> Sequence[ContainerImageCandidate]:
        self.calls.append((tool_id, version, tuple(aliases)))
        return [ContainerImageCandidate("quay.io/biocontainers/fastp:0.23.2")]


class ContainerResolverTests(unittest.TestCase):
    def test_resolve_container_keeps_existing_docker_without_provider_lookup(self):
        tool = make_tool(docker="quay.io/biocontainers/fastp:0.23.2")

        self.assertEqual(
            resolve_tool_container(tool, FailingProvider()),
            "quay.io/biocontainers/fastp:0.23.2",
        )
        self.assertIs(fill_missing_tool_container(tool, FailingProvider()), tool)

    def test_static_provider_fills_missing_docker_and_preserves_runtime(self):
        tool = make_tool()
        provider = StaticContainerImageProvider(
            {
                ("fastp", "0.23.2"): [
                    "quay.io/biocontainers/fastp:0.23.2--h5f740d0_0",
                ]
            }
        )

        filled = fill_missing_tool_container(tool, provider)

        self.assertIsNone(tool.runtime.docker)
        self.assertEqual(filled.runtime.cpu, 4)
        self.assertEqual(filled.runtime.memory, "8G")
        self.assertEqual(
            filled.runtime.docker,
            "quay.io/biocontainers/fastp:0.23.2--h5f740d0_0",
        )

    def test_provider_receives_tool_identity_and_aliases(self):
        tool = make_tool(aliases=["fastq qc", "adapter trimming"])
        provider = RecordingProvider()

        self.assertEqual(
            resolve_tool_container(tool, provider),
            "quay.io/biocontainers/fastp:0.23.2",
        )
        self.assertEqual(
            provider.calls,
            [("fastp", "0.23.2", ("fastq qc", "adapter trimming"))],
        )

    def test_static_provider_from_image_map_parses_tool_version_keys(self):
        provider = static_provider_from_image_map(
            {
                "fastp@0.23.2": "quay.io/biocontainers/fastp:0.23.2",
            }
        )

        self.assertEqual(
            resolve_tool_container(make_tool(), provider),
            "quay.io/biocontainers/fastp:0.23.2",
        )

    def test_parse_tool_version_key_rejects_malformed_key(self):
        with self.assertRaisesRegex(ValueError, "<tool>@<version>"):
            parse_tool_version_key("fastp")

    def test_missing_image_reports_tool_version(self):
        tool = make_tool()
        provider = StaticContainerImageProvider({})

        with self.assertRaisesRegex(ContainerImageNotFoundError, "fastp@0.23.2"):
            resolve_tool_container(tool, provider)

    def test_ambiguous_image_requires_manual_selection(self):
        tool = make_tool()
        provider = StaticContainerImageProvider(
            {
                ("fastp", "0.23.2"): [
                    "quay.io/biocontainers/fastp:0.23.2--h5f740d0_0",
                    "quay.io/biocontainers/fastp:0.23.2--h79da9fb_1",
                ]
            }
        )

        with self.assertRaisesRegex(
            AmbiguousContainerImageError,
            "multiple container images found.*h5f740d0_0.*h79da9fb_1",
        ):
            resolve_tool_container(tool, provider)


if __name__ == "__main__":
    unittest.main()
