#!/usr/bin/env bash
set -euo pipefail

manifest="$1"
output="$2"

mkdir -p multiqc_inputs
while IFS= read -r source_file; do
  [ -n "$source_file" ] || continue
  cp "$source_file" "multiqc_inputs/$(basename "$source_file")"
done < "$manifest"

multiqc multiqc_inputs --filename "$output" --force
