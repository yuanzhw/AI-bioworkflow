# Tiny RNA-seq DEG fixture（测试数据集）

本目录保存 tiny RNA-seq DEG 端到端（e2e）测试数据集的可复现源文件。最终的 `rnaseq_deg.inputs.json` 与运行环境绑定，应该在 Cromwell runner 侧生成，不应把包含绝对路径的版本提交到仓库。

生成测试数据和 Cromwell 可见的 inputs JSON：

```bash
python examples/tiny/prepare_tiny_data.py \
  --fixture-root /data/ai-bioworkflow-tiny \
  --write-inputs /data/ai-bioworkflow-tiny/rnaseq_deg.inputs.json
```

脚本会使用 Docker 或 Podman，从 Tool Catalog 中声明的 Salmon 镜像（`src/catalog/tools/salmon/1.9.0.yaml`）构建 `salmon_index/`。runner 环境不需要在宿主机层面安装 Salmon。

脚本会写出：

- `data/transcripts.fa`
- `data/tx2gene.tsv`
- `data/sample_groups.tsv`
- `data/reads/*_R1.fastq.gz`
- `data/reads/*_R2.fastq.gz`
- `salmon_index/`
- 提供 `--write-inputs` 时写出 `rnaseq_deg.inputs.json`

如果提供了 `--cromwell-root`，inputs JSON 会使用该路径下的文件；否则使用 `--fixture-root`。这些路径必须对 Cromwell 可见，即使它们与 Windows client 看到的路径不同。

当 Cromwell 运行在 WSL 内，而测试从 Windows 启动时，inputs JSON 应保存在 Windows 可读路径中，同时把内容渲染为 WSL 路径：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_cromwell_tiny_e2e.ps1 `
  -WindowsFixtureRoot C:\data\ai-bioworkflow-tiny `
  -CromwellFixtureRoot /data/ai-bioworkflow-runner/tiny
```

该 helper 会在 Windows 侧准备测试数据，将其同步到正在运行的 Cromwell 容器 runner mount 中，设置 Cromwell e2e 所需环境变量，并运行 `tests.e2e.test_tiny_run`。

默认情况下，helper 通过 Docker 同步：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_cromwell_tiny_e2e.ps1 `
  -WindowsFixtureRoot C:\data\ai-bioworkflow-tiny `
  -CromwellFixtureRoot /data/ai-bioworkflow-runner/tiny `
  -SyncMode docker `
  -CromwellContainerName cromwell-cromwell-1
```

如果希望通过 `wsl.exe` 填充 Cromwell runner 路径，可以使用 `-SyncMode wsl`。

如果 Docker 和 Podman 都已安装，默认使用 Docker。可以通过以下方式指定 runtime：

```bash
python examples/tiny/prepare_tiny_data.py \
  --fixture-root /data/ai-bioworkflow-tiny \
  --write-inputs /data/ai-bioworkflow-tiny/rnaseq_deg.inputs.json \
  --container-runtime podman
```

测试数据准备完成后，只有显式 opt-in 时才运行真实 e2e：

```bash
AI_BIOWORKFLOW_RUN_E2E=1 \
AI_BIOWORKFLOW_RUN_BACKEND=cromwell \
CROMWELL_URL=http://localhost:8000 \
AI_BIOWORKFLOW_TINY_INPUTS=/data/ai-bioworkflow-tiny/rnaseq_deg.inputs.json \
uv run python -m unittest tests.e2e.test_tiny_run -v
```

在 Windows 上，P0 check wrapper 可以运行同一个 opt-in e2e。它会把测试数据准备、同步和真实 e2e 执行委托给 `scripts\run_cromwell_tiny_e2e.ps1`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1 `
  -RunE2E `
  -CromwellUrl http://localhost:8000 `
  -WindowsFixtureRoot C:\data\ai-bioworkflow-tiny `
  -CromwellFixtureRoot /data/ai-bioworkflow-runner/tiny
```
