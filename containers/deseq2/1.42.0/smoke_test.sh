#!/usr/bin/env bash
set -euo pipefail

command -v Rscript >/dev/null
test -x /usr/local/bin/run_deseq2.R
Rscript -e 'library(DESeq2); library(readr)'
