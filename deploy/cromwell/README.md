# Cromwell Compose Runner

本目录提供 AI-bioworkflow P0 阶段使用的 Cromwell server runner 部署包。它用于 Linux、WSL、devcontainer 或小型服务器环境，是一个独立的部署辅助目录。

它不包含项目后端 client 联调，也不会修改 `AI_BIOWORKFLOW_RUN_BACKEND` 的行为。

该 runner 使用：

- Cromwell server `92`
- PostgreSQL `16` 保存 workflow metadata
- 通过 `/var/run/docker.sock` 使用 Docker-outside-of-Docker
- 默认共享 Linux 路径 `/data/ai-bioworkflow-runner`

## 文件

```text
deploy/cromwell/
  Dockerfile
  docker-compose.yml
  application.conf
  options.example.json
  labels.example.json
  .env.example
  README.md
```

## 准备 Runner 主机

在运行 Cromwell 的 Linux、WSL、devcontainer 或服务器环境中执行：

```bash
sudo mkdir -p /data/ai-bioworkflow-runner/{executions,outputs,workflow-logs,call-logs,tiny}
sudo chown -R "$USER":"$USER" /data/ai-bioworkflow-runner
```

主机必须安装 Docker，因为 workflow task 容器会通过宿主机 Docker daemon 启动。Cromwell 容器会挂载 `/var/run/docker.sock`，不会运行 Docker-in-Docker。

宿主机和 Cromwell 容器内必须能以同一个绝对路径看到 runner 目录。因此 compose 文件会挂载：

```text
/data/ai-bioworkflow-runner:/data/ai-bioworkflow-runner
```

这可以避免 task 容器启动时找不到 Cromwell 执行目录。

## 配置

```bash
cd deploy/cromwell
cp .env.example .env
```

默认配置为：

```text
CROMWELL_VERSION=92
CROMWELL_PORT=8000
AI_BIOWORKFLOW_RUNNER_ROOT=/data/ai-bioworkflow-runner
POSTGRES_DB=cromwell
POSTGRES_USER=cromwell
POSTGRES_PASSWORD=cromwell
```

如果修改 `AI_BIOWORKFLOW_RUNNER_ROOT`，请保持它是 Linux 绝对路径，并确认宿主机 Docker daemon 也能看到同一个路径。还需要复制并修改 `options.example.json`，因为 workflow options 是普通 JSON，不会读取 `.env` 中的变量。

## 启动与停止

```bash
docker compose up -d --build
docker compose ps
```

检查 Cromwell server：

```bash
curl http://localhost:8000/engine/v1/status
```

查看日志：

```bash
docker compose logs cromwell
docker compose logs postgres
```

停止服务：

```bash
docker compose down
```

停止服务并删除 Postgres metadata volume：

```bash
docker compose down -v
```

## 准备 Workflow 镜像

编译器会从 Tool Catalog 读取容器镜像，并将其渲染到 WDL `runtime.docker`。Cromwell server 不负责推断或替换镜像。
该本地 P0 runner 使用 Docker local hash lookup，避免 Cromwell remote lookup 对 registry
支持范围的限制影响 GHCR 等镜像。请先在 runner 主机拉取所需镜像，或确保本地镜像具有
`RepoDigests`。

当前 RNA-seq DEG 示例需要在 runner 环境中拉取或构建以下镜像：

```bash
docker pull quay.io/biocontainers/fastp:1.3.3--h43da1c4_0
docker pull quay.io/biocontainers/salmon:1.9.0--h7e5ed60_0
docker pull ghcr.io/yuanzhw/ai-bioworkflow/tximport:1.30.0
docker pull ghcr.io/yuanzhw/ai-bioworkflow/deseq2:1.42.1
docker pull ghcr.io/yuanzhw/ai-bioworkflow/multiqc:1.21
```

## 输入路径规则

Cromwell inputs JSON 中每个 `File` 值都必须是 Cromwell runner 可见的 Linux 路径。不要在 inputs JSON 中写入 `C:\Users\...` 这类 Windows 路径。

例如，可以使用：

```text
/data/ai-bioworkflow-runner/tiny
```

也可以使用其他已挂载到 runner 环境中的 Linux 绝对路径。

## 手动提交 Workflow

在 runner 环境中生成 WDL 后，可以直接提交给 Cromwell：

```bash
curl -F workflowSource=@/path/to/rnaseq_deg.wdl \
  -F workflowInputs=@/data/ai-bioworkflow-runner/tiny/rnaseq_deg.inputs.json \
  -F workflowOptions=@options.example.json \
  -F labels=@labels.example.json \
  http://localhost:8000/api/workflows/v1
```

响应中会包含 workflow id。查询状态：

```bash
curl http://localhost:8000/api/workflows/v1/<workflow-id>/status
```

查询输出：

```bash
curl http://localhost:8000/api/workflows/v1/<workflow-id>/outputs
```

查询 metadata：

```bash
curl http://localhost:8000/api/workflows/v1/<workflow-id>/metadata
```

## 常见问题

- `Cannot connect to the Docker daemon`：确认宿主机 Docker 正在运行，并且 `/var/run/docker.sock` 存在。
- task 容器找不到文件：确认 inputs JSON 使用 runner 可见的 Linux 路径，并且 runner 根目录在 Cromwell 容器内外使用同一个绝对路径。
- Cromwell 启动后不健康：查看 `docker compose logs cromwell` 和 `docker compose logs postgres`；Cromwell 会等待 Postgres 可用后再启动。
- workflow 输出没有复制：使用 `options.example.json`，或提供等价的 workflow options 文件并设置 `final_workflow_outputs_dir`。

## 本部署包不包含的内容

- 实现 `src/execution/cromwell.py`
- 修改 `get_execution_backend()` 行为
- 运行真实 RNA-seq tiny e2e 测试
- 通过 AI-bioworkflow 后端 client 提交 workflow
