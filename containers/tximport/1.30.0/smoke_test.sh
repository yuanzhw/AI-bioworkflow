#!/usr/bin/env bash
set -euo pipefail

command -v Rscript >/dev/null
test -x /usr/local/bin/run_tximport.R
Rscript -e 'library(tximport); library(readr)'
Rscript -e 'stopifnot(as.character(packageVersion("tximport")) == "1.30.0")'
