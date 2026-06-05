from pathlib import Path
import unittest

from src.execution import BackendAvailability, DisabledBackend, ExecutionBackend, ExecutionResult, get_execution_backend


class DisabledBackendTests(unittest.TestCase):
    def test_disabled_backend_reports_unavailable(self):
        backend = DisabledBackend()

        availability = backend.availability()

        self.assertFalse(availability.available)
        self.assertNotEqual(availability.reason, "")

    def test_disabled_backend_run_raises_without_touching_paths(self):
        backend = DisabledBackend()

        with self.assertRaisesRegex(RuntimeError, "WDL execution backend is disabled"):
            backend.run(
                Path("does-not-exist.wdl"),
                Path("does-not-exist.inputs.json"),
                options_path=Path("does-not-exist.options.json"),
                dependencies_path=Path("does-not-exist.zip"),
                labels_path=Path("does-not-exist.labels.json"),
            )


class ExecutionProtocolTests(unittest.TestCase):
    def test_execution_result_uses_independent_output_and_metadata_dicts(self):
        first = ExecutionResult(succeeded=True)
        second = ExecutionResult(succeeded=True)

        first.outputs["x"] = 1
        first.metadata["status"] = "Succeeded"

        self.assertEqual(second.outputs, {})
        self.assertEqual(second.metadata, {})

    def test_public_exports_are_importable(self):
        self.assertIs(BackendAvailability(available=True).available, True)
        self.assertTrue(hasattr(ExecutionBackend, "run"))


class ExecutionBackendFactoryTests(unittest.TestCase):
    def test_factory_defaults_to_disabled_when_env_is_unset(self):
        backend = get_execution_backend(env={})

        self.assertIsInstance(backend, DisabledBackend)

    def test_factory_reads_disabled_from_env(self):
        backend = get_execution_backend(env={"AI_BIOWORKFLOW_RUN_BACKEND": "disabled"})

        self.assertIsInstance(backend, DisabledBackend)

    def test_factory_normalizes_case_and_whitespace(self):
        backend = get_execution_backend(env={"AI_BIOWORKFLOW_RUN_BACKEND": " Disabled "})

        self.assertIsInstance(backend, DisabledBackend)

    def test_explicit_name_takes_precedence_over_env(self):
        backend = get_execution_backend(name="disabled", env={"AI_BIOWORKFLOW_RUN_BACKEND": "cromwell"})

        self.assertIsInstance(backend, DisabledBackend)

    def test_cromwell_backend_is_not_implemented_in_phase_2(self):
        with self.assertRaisesRegex(ValueError, "cromwell.*not implemented"):
            get_execution_backend(name="cromwell", env={})

    def test_local_miniwdl_backend_is_not_implemented_in_phase_2(self):
        with self.assertRaisesRegex(ValueError, "local-miniwdl.*not implemented"):
            get_execution_backend(name="local-miniwdl", env={})

    def test_unknown_backend_error_includes_name_and_supported_values(self):
        with self.assertRaisesRegex(ValueError, "unknown-backend.*disabled.*cromwell.*local-miniwdl"):
            get_execution_backend(name="unknown-backend", env={})


if __name__ == "__main__":
    unittest.main()
