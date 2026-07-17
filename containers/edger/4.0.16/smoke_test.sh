#!/usr/bin/env bash
set -euo pipefail

command -v Rscript >/dev/null
test -x /usr/local/bin/run_edger.R
Rscript -e 'library(edgeR); library(readr)'
Rscript -e 'stopifnot(as.character(packageVersion("edgeR")) == "4.0.16")'

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

cat >"$workdir/counts.tsv" <<'TSV'
gene_id	ctrl_1	ctrl_2	treat_1	treat_2
gene_a	100	110	20	25
gene_b	90	95	18	20
gene_c	20	18	100	105
gene_d	22	20	95	100
gene_e	40	42	41	39
gene_f	35	37	36	34
TSV

cat >"$workdir/sample_groups.tsv" <<'TSV'
sample_id	condition
ctrl_1	control
ctrl_2	control
treat_1	treated
treat_2	treated
TSV

run_edger.R \
  --counts "$workdir/counts.tsv" \
  --sample-groups "$workdir/sample_groups.tsv" \
  --contrast condition \
  --min-count 1 \
  --fdr 0.05 \
  --output "$workdir/differential_expression.tsv"

grep -q '^gene_id' "$workdir/differential_expression.tsv"
grep -q '^gene_a' "$workdir/differential_expression.tsv"
