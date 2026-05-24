# Tiny RNA-seq DEG fixture

`tests/test_tiny_run.py` runs only when the local machine has `miniwdl`, a
Docker/Podman runtime, all required container images, and an input JSON at:

```text
examples/tiny/rnaseq_deg.inputs.json
```

The input JSON should point to a tiny Salmon index, four paired FASTQ files,
a `tx2gene` table, and a sample metadata table with at least two groups. Keep
large binary fixtures out of git; generate or download them locally before
running the optional end-to-end test.
