# Tiny RNA-seq DEG fixture

This directory contains the reproducible source for the tiny RNA-seq DEG e2e
fixture. The final `rnaseq_deg.inputs.json` is environment-bound and should be
generated on the Cromwell runner side, not committed with absolute paths.

Generate fixture data and a Cromwell-visible inputs JSON with:

```bash
python examples/tiny/prepare_tiny_data.py \
  --fixture-root /data/ai-bioworkflow-tiny \
  --write-inputs /data/ai-bioworkflow-tiny/rnaseq_deg.inputs.json
```

The script uses Docker or Podman to build `salmon_index/` from the Salmon image
declared in the Tool Catalog (`src/catalog/tools/salmon/1.9.0.yaml`). The
runner environment does not need a host-level Salmon installation.

The script writes:

- `data/transcripts.fa`
- `data/tx2gene.tsv`
- `data/sample_groups.tsv`
- `data/reads/*_R1.fastq.gz`
- `data/reads/*_R2.fastq.gz`
- `salmon_index/`
- `rnaseq_deg.inputs.json` when `--write-inputs` is provided

The inputs JSON uses paths under `--cromwell-root` if supplied; otherwise it
uses `--fixture-root`. Those paths must be visible to Cromwell, even if they are
not the same paths seen by a Windows client.

When Cromwell is running inside WSL but the test is launched from Windows, keep
the inputs JSON on a Windows-readable path and render its contents with WSL
paths:

```powershell
.\scripts\run_cromwell_tiny_e2e.ps1 `
  -WindowsFixtureRoot C:\data\ai-bioworkflow-tiny `
  -CromwellFixtureRoot /data/ai-bioworkflow-runner/tiny
```

The helper prepares the fixture on Windows, copies it into the running
Cromwell container's runner mount, sets the Cromwell e2e environment variables,
and runs `tests.e2e.test_tiny_run`.

By default the helper syncs through Docker:

```powershell
.\scripts\run_cromwell_tiny_e2e.ps1 `
  -WindowsFixtureRoot C:\data\ai-bioworkflow-tiny `
  -CromwellFixtureRoot /data/ai-bioworkflow-runner/tiny `
  -SyncMode docker `
  -CromwellContainerName cromwell-cromwell-1
```

Use `-SyncMode wsl` if the Cromwell runner path should be populated through
`wsl.exe` instead.

If both Docker and Podman are installed, Docker is used by default. Override the
runtime with:

```bash
python examples/tiny/prepare_tiny_data.py \
  --fixture-root /data/ai-bioworkflow-tiny \
  --write-inputs /data/ai-bioworkflow-tiny/rnaseq_deg.inputs.json \
  --container-runtime podman
```

After preparing the fixture, run the real e2e only with explicit opt-in:

```bash
AI_BIOWORKFLOW_RUN_E2E=1 \
AI_BIOWORKFLOW_RUN_BACKEND=cromwell \
CROMWELL_URL=http://localhost:8000 \
AI_BIOWORKFLOW_TINY_INPUTS=/data/ai-bioworkflow-tiny/rnaseq_deg.inputs.json \
uv run python -m unittest tests.e2e.test_tiny_run -v
```
