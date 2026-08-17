import unittest

from src.catalog import ExecutionVerificationSpec, load_tool_catalog
from src.execution import UnverifiedToolExecutionError, ensure_tools_execution_eligible


class ToolExecutionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tool_catalog = load_tool_catalog()

    def test_blocks_unverified_tools_by_default(self):
        tool = self.tool_catalog.get("edger", "4.0.16")

        with self.assertRaisesRegex(
            UnverifiedToolExecutionError,
            "edger@4.0.16.*allow_unverified=True",
        ):
            ensure_tools_execution_eligible([tool])

    def test_allows_explicit_opt_in_for_unverified_tools(self):
        tool = self.tool_catalog.get("salmon_index", "1.9.0")

        ensure_tools_execution_eligible([tool], allow_unverified=True)

    def test_allows_smoke_tested_and_e2e_validated_tools(self):
        e2e_tool = self.tool_catalog.get("fastp", "1.3.3")
        smoke_tested_tool = self.tool_catalog.get("edger", "4.0.16").model_copy(
            update={
                "execution_verification": ExecutionVerificationSpec(
                    status="smoke-tested",
                    evidence=["containers/edger/4.0.16/smoke_test.sh"],
                )
            }
        )

        ensure_tools_execution_eligible([smoke_tested_tool, e2e_tool])


if __name__ == "__main__":
    unittest.main()
