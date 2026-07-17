#!/usr/bin/env bash
set -euo pipefail

command -v python >/dev/null
test -x /usr/local/bin/run_gtf_tx2gene.py

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

cat >"$workdir/annotation.gtf" <<'GTF'
chr1	test	transcript	1	100	.	+	.	gene_id "gene_a"; transcript_id "tx_a1";
chr1	test	exon	1	50	.	+	.	gene_id "gene_a"; transcript_id "tx_a1";
chr1	test	transcript	200	300	.	+	.	gene_id "gene_b"; transcript_id "tx_b1";
GTF

run_gtf_tx2gene.py \
  --annotation-gtf "$workdir/annotation.gtf" \
  --output "$workdir/tx2gene.tsv"

grep -q '^TXNAME' "$workdir/tx2gene.tsv"
grep -q $'^tx_a1\tgene_a' "$workdir/tx2gene.tsv"
grep -q $'^tx_b1\tgene_b' "$workdir/tx2gene.tsv"
