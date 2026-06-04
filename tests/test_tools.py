import unittest

from src.tools.validator import wdl_validator, wdl_validator_available

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


if __name__ == "__main__":
    unittest.main()
