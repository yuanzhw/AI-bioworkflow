#!/usr/bin/env bash
set -euo pipefail

command -v multiqc >/dev/null
test -x /usr/local/bin/run_multiqc.sh
python -c 'import multiqc; assert multiqc.__version__ == "1.21", multiqc.__version__'
