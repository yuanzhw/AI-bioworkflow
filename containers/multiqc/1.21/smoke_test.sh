#!/usr/bin/env bash
set -euo pipefail

command -v multiqc >/dev/null
test -x /usr/local/bin/run_multiqc.sh
