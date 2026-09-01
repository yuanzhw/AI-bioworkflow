import os
import unittest
from pathlib import Path
from unittest.mock import patch

import src.tools.validator as validator_module
from src.tools.validator import ValidatorCommand, wdl_validator, wdl_validator_available

VALID_WDL = """
version 1.0

workflow SimpleWorkflow {
  input {
    File raw_fastq
  }

  call fastp_qc {
    input:
      raw_fastq = raw_fastq
  }

  output {
    File clean_fastq = fastp_qc.clean_fastq
  }
}

task fastp_qc {
  input {
    File raw_fastq
  }

  command <<<
    cp ~{raw_fastq} clean.fq
  >>>

  output {
    File clean_fastq = "clean.fq"
  }

  runtime {
    docker: "ubuntu:22.04"
  }
}
"""


class ValidatorTests(unittest.TestCase):
    @unittest.skipIf(not wdl_validator_available(), "WDL validator is not installed")
    def test_validator_accepts_valid_wdl(self):
        result = wdl_validator.invoke({"wdl_code": VALID_WDL})

        self.assertTrue(result["is_valid"], result["message"])

    @unittest.skipIf(not wdl_validator_available(), "WDL validator is not installed")
    def test_validator_rejects_invalid_wdl(self):
        result = wdl_validator.invoke({"wdl_code": "workflow Bad {"})

        self.assertFalse(result["is_valid"])
        self.assertIn("WDL 语法校验失败", result["message"])


class ValidatorSelectionTests(unittest.TestCase):
    def test_auto_prefers_womtool_without_probing_miniwdl(self):
        womtool = ValidatorCommand(
            name="womtool",
            label="WOMtool test",
            command=["java", "-jar", "womtool.jar", "validate"],
        )

        with (
            patch.dict(os.environ, {"WDL_VALIDATOR": "auto"}),
            patch.object(validator_module, "_womtool_command", return_value=womtool),
            patch.object(validator_module, "_miniwdl_command") as miniwdl_command,
        ):
            selected = validator_module._selected_validator()

        self.assertIs(selected, womtool)
        miniwdl_command.assert_not_called()

    def test_auto_falls_back_to_miniwdl_when_womtool_is_unavailable(self):
        miniwdl = ValidatorCommand(
            name="miniwdl",
            label="miniwdl",
            command=["miniwdl", "check"],
        )

        with (
            patch.dict(os.environ, {"WDL_VALIDATOR": "auto"}),
            patch.object(validator_module, "_womtool_command", return_value=None),
            patch.object(validator_module, "_miniwdl_command", return_value=miniwdl),
        ):
            selected = validator_module._selected_validator()

        self.assertIs(selected, miniwdl)

    def test_explicit_womtool_does_not_fall_back_to_miniwdl(self):
        with (
            patch.dict(os.environ, {"WDL_VALIDATOR": "womtool"}),
            patch.object(validator_module, "_womtool_command", return_value=None),
            patch.object(validator_module, "_miniwdl_command") as miniwdl_command,
        ):
            selected = validator_module._selected_validator()

        self.assertIsNone(selected)
        miniwdl_command.assert_not_called()

    def test_womtool_rejects_java_older_than_17(self):
        java = Path("java")

        with (
            patch.object(validator_module, "_womtool_jar", return_value=Path("womtool.jar")),
            patch.object(validator_module, "_java_candidates", return_value=[java]),
            patch.object(validator_module, "_java_major_version", return_value=16),
        ):
            selected = validator_module._womtool_command()

        self.assertIsNone(selected)


if __name__ == "__main__":
    unittest.main()
