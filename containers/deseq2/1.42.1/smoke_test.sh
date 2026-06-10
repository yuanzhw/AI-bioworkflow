#!/usr/bin/env bash
set -euo pipefail

command -v Rscript >/dev/null
test -x /usr/local/bin/run_deseq2.R
Rscript -e 'library(DESeq2); library(readr)'
Rscript -e 'stopifnot(as.character(packageVersion("DESeq2")) == "1.42.1")'

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

cat >"$workdir/counts.tsv" <<'TSV'
gene_id	ctrl_1	ctrl_2	treat_1	treat_2
gene_a	48	44	12	14
gene_b	12	14	48	44
TSV

cat >"$workdir/sample_groups.tsv" <<'TSV'
sample_id	condition
ctrl_1	control
ctrl_2	control
treat_1	treated
treat_2	treated
TSV

run_deseq2.R \
  --counts "$workdir/counts.tsv" \
  --sample-groups "$workdir/sample_groups.tsv" \
  --contrast condition \
  --output "$workdir/differential_expression.tsv"

grep -q '^gene_id' "$workdir/differential_expression.tsv"
grep -q '^gene_a' "$workdir/differential_expression.tsv"
