# P0 Cromwell 执行后端计划

本文档记录 AI-bioworkflow 当前关于 P0 执行后端与测试框架的设计结论，用于把 Windows 开发环境和独立 Cromwell runner 之间的职责边界固定下来。

## 背景

`DEVELOPMENT.md` 中对 P0 的定义是：

```text
稳定现有 Recipe / Catalog / 执行测试，交付可靠的编译与执行评测基线。
```

项目目前迁移到 Windows 原生环境开发。由于 Codex desktop 沙箱和 Windows 本地权限限制，Windows/Codex 环境不适合作为真实 WDL 执行环境，尤其不应强依赖：

- `miniwdl run`
- Docker / Podman 工作流执行
- 真实 WDL workflow 执行
- tiny RNA-seq fixture e2e 测试

Windows 开发环境继续负责确定性编译、静态分析、WDL 渲染、WDL 语法校验和快速单元测试。真实 WDL 执行应交给独立 Cromwell 环境。

## 架构决策

引入 `ExecutionBackend` 执行后端抽象。

测试代码和未来 service 层不直接调用 `miniwdl`、Docker、Podman 或 Cromwell，而是调用由配置选择出来的执行后端：

```python
backend = get_execution_backend()
result = backend.run(wdl_path, inputs_path)
```

后端负责决定执行是否禁用、是否提交到 Cromwell，或未来是否使用其他运行时。

P0 主执行后端是：

```text
CromwellBackend
```

`miniwdl` 不再作为 P0 必需执行路径。后续可以保留为可选开发 fallback，但不应阻塞 P0 完成。

## P0 边界

Windows/Codex 开发环境负责：

- 运行 unit 和 compiler tests。
- 从 Recipe Tool Plan 或 Workflow IR 生成 WDL。
- 执行 Analyzer / Renderer / Checker 边界。
- 运行项目 WDL validator 做语法校验。
- 通过 mock 或 fake HTTP 层运行 Cromwell backend contract tests。
- 不要求 Docker、miniwdl、真实 Cromwell 或真实 tiny input 文件。

Cromwell runner 环境负责：

- 持有或能够访问 tiny fixture 文件。
- 运行 Cromwell server。
- 提供 Docker 或其他 Cromwell 支持的执行 backend。
- 准备 workflow 所需容器镜像。
- 生成与 runner 环境绑定的 inputs JSON。
- 运行真实 RNA-seq DEG tiny workflow e2e 测试。

## 当前状态：P0 执行闭环已手动验证

当前 Windows/Codex 侧已经落地 Execution Backend 抽象、默认 disabled 后端、
Cromwell REST client、mock contract tests、真实 e2e 测试入口、tiny fixture
生成脚本，以及独立 Cromwell server/runner 的 Docker Compose 部署包。

独立 Cromwell runner 环境也已完成手动验证：Cromwell server 已运行，
Docker 与相关 backend 已可用，RNA-seq DEG e2e 所需镜像已拉取到本地，
并已手动运行真实 e2e 测试。P0 后续重点是把这套验证沉淀成更便捷的
快速检查脚本和可复现的验证记录。

部署包位置：

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

部署包约定：

- Cromwell server 固定为 `92`。
- 使用 PostgreSQL 16 保存 Cromwell workflow metadata。
- 使用 Docker-outside-of-Docker，通过挂载宿主机 `/var/run/docker.sock` 启动 task 容器。
- 默认 backend 名称为 `LocalDocker`。
- 默认 runner 根目录为 `/data/ai-bioworkflow-runner`。
- Cromwell 容器内路径和宿主机路径必须保持一致，避免 task 容器挂载执行目录失败。
- inputs JSON 中的 `File` 路径必须是 Cromwell runner 可见的 Linux 路径，不能使用 Windows 绝对路径。

当前已人工确认的 runner 状态：

- Cromwell server 已启动并可用于真实 workflow 提交。
- Docker 与 Cromwell 配套执行 backend 已可用。
- RNA-seq DEG e2e 所需 workflow task 镜像已拉取到本地。
- 已使用显式 e2e 环境变量手动运行真实 RNA-seq tiny e2e。

当前验证记录：

- 真实 e2e 的 Cromwell workflow id、最终 status、output keys 和输出文件大小已记录在
  `docs/cromwell-tiny-e2e-verification.md`。
- Runner 快速检查步骤已收敛到 `scripts/check_p0.ps1`，真实 e2e 逻辑由
  `scripts/run_cromwell_tiny_e2e.ps1` 统一负责。

Windows/Codex 普通验证仍不要求 Docker、miniwdl、真实 Cromwell 或真实 tiny input 文件。

## 当前目录结构

```text
src/execution/
  __init__.py
  protocol.py
  disabled.py
  cromwell.py
  factory.py

tests/e2e/
  test_tiny_run.py

tests/
  test_cromwell_backend.py

examples/tiny/
  README.md
  prepare_tiny_data.py
  rnaseq_deg.inputs.template.json
  data/
    sample_groups.tsv
    tx2gene.tsv
    transcripts.fa
    reads/
```

真实 Cromwell e2e 已位于 `tests/e2e/test_tiny_run.py`，默认跳过，只有显式设置
`AI_BIOWORKFLOW_RUN_E2E=1` 时运行。`tests/test_tiny_run.py` 保留为可选
miniwdl tiny run 检查，不作为 P0 必需路径。

## ExecutionBackend 接口

初始接口应为 Cromwell workflow options 和 WDL dependencies 预留位置，即使 P0 第一版不一定全部使用。

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class BackendAvailability:
    available: bool
    reason: str = ""


@dataclass
class ExecutionResult:
    succeeded: bool
    workflow_id: str | None = None
    status: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    message: str = ""


class ExecutionBackend(Protocol):
    def availability(self) -> BackendAvailability:
        ...

    def run(
        self,
        wdl_path: Path,
        inputs_path: Path,
        *,
        options_path: Path | None = None,
        dependencies_path: Path | None = None,
        labels_path: Path | None = None,
    ) -> ExecutionResult:
        ...
```

设计理由：

- `availability()` 比单纯的布尔值更有用，因为测试可以解释执行环境为什么不可用。
- `options_path` 应从一开始保留，因为 Cromwell workflow options 是 output copy 和 backend 选择的自然位置。
- `dependencies_path` 应从一开始保留，因为 Cromwell 通过 workflow dependencies ZIP 支持 WDL imports。
- `labels_path` 对未来 run tracking 和 Web 产品化有用。

## 后端选择

环境变量：

```text
AI_BIOWORKFLOW_RUN_E2E=1
AI_BIOWORKFLOW_RUN_BACKEND=cromwell
CROMWELL_URL=http://localhost:8000
CROMWELL_POLL_INTERVAL_SECONDS=5
CROMWELL_TIMEOUT_SECONDS=1800
AI_BIOWORKFLOW_TINY_INPUTS=/data/ai-bioworkflow-tiny/rnaseq_deg.inputs.json
```

默认行为：

```text
AI_BIOWORKFLOW_RUN_BACKEND=disabled
```

推荐 factory 行为：

```text
unset / disabled -> DisabledBackend
cromwell         -> CromwellBackend
local-miniwdl    -> P0 不要求实现；可作为未来可选 backend
```

e2e 测试行为：

- 如果 `AI_BIOWORKFLOW_RUN_E2E != 1`，真实 e2e 测试应 skip。
- 如果 `AI_BIOWORKFLOW_RUN_E2E=1`，但所选 backend 不可用，测试应 fail，并输出 backend availability reason。
- 用户显式开启 e2e 后，不应再静默 skip，避免出现“假绿”。

## DisabledBackend

`DisabledBackend` 是 Windows/Codex 和普通单元测试的安全默认值。

预期行为：

- `availability()` 返回不可用，并给出清晰原因。
- `run()` 被调用时抛出显式错误。

这样可以防止普通开发过程中误触发真实 workflow 执行。

## CromwellBackend

Cromwell backend 使用 Cromwell server mode 的 REST API。

关键 API：

- 健康检查：`GET /engine/v1/status`
- 提交 workflow：`POST /api/workflows/v1`
- 轮询 workflow 状态：`GET /api/workflows/v1/{id}/status`
- 获取 outputs：`GET /api/workflows/v1/{id}/outputs`
- 获取 metadata：`GET /api/workflows/v1/{id}/metadata`

提交 endpoint 应使用 Cromwell 当前字段名：

```text
workflowSource
workflowInputs
workflowOptions
workflowDependencies
labels
```

不要使用旧示例中的 `wdlSource`；当前实现应使用 `workflowSource`。

P0 `CromwellBackend.run()` 流程：

```text
1. 检查 Cromwell 可用性。
2. 使用 multipart/form-data 提交 WDL 和 inputs。
3. 从提交响应中取出 workflow id。
4. 轮询状态直到 Succeeded、Failed、Aborted 或 timeout。
5. 获取 outputs 和 metadata。
6. 返回 ExecutionResult。
```

终止状态处理：

```text
Succeeded -> succeeded=True
Failed    -> succeeded=False
Aborted   -> succeeded=False
timeout   -> succeeded=False，message 说明超时
```

失败时应尽量保留 metadata 中有用的信息，尤其是失败 call 名、stderr 路径和 workflow 级失败原因。

## Contract Tests

Windows/Codex 应该能在没有真实 Cromwell server 的情况下测试 `CromwellBackend`。

新增测试应通过 mock HTTP 响应验证：

- availability check 调用 `/engine/v1/status`。
- submit 使用 multipart form 字段 `workflowSource` 和 `workflowInputs`。
- 提供 `workflowOptions`、`workflowDependencies`、`labels` 时会一起提交。
- polling 正确处理 `Submitted`、`Running` 和 `Succeeded`。
- `Failed` 返回失败的 `ExecutionResult`。
- timeout 返回失败的 `ExecutionResult`，并带有清晰 message。
- connection failure 通过 `BackendAvailability.reason` 暴露。
- outputs 和 metadata 会解析进 `ExecutionResult`。

这些测试用于稳定 API client 行为，同时避免 Windows/Codex 执行真实 e2e。

## Tiny Fixture 策略

不要提交带有环境绑定绝对路径的最终 `rnaseq_deg.inputs.json`。

仓库应提交可复现 fixture 来源和模板：

```text
examples/tiny/
  prepare_tiny_data.py
  rnaseq_deg.inputs.template.json
  data/
    sample_groups.tsv
    tx2gene.tsv
    transcripts.fa
    reads/
```

生成文件应留在未跟踪目录，例如：

```text
.cache/tiny/
/data/ai-bioworkflow-tiny/
```

最终 `rnaseq_deg.inputs.json` 应由 Cromwell runner 环境中的代码生成，因为其中的 `File` 路径必须指向 Cromwell 能访问的路径。

runner 侧示例命令：

```bash
python examples/tiny/prepare_tiny_data.py \
  --fixture-root /data/ai-bioworkflow-tiny \
  --write-inputs /data/ai-bioworkflow-tiny/rnaseq_deg.inputs.json
```

该脚本应负责：

- 创建 fixture root。
- 拷贝或生成 tiny FASTQ 文件。
- 写出 `sample_groups.tsv`。
- 写出 `tx2gene.tsv`。
- 写出或拷贝 `transcripts.fa`。
- 生成或准备 tiny Salmon index。
- 使用 Cromwell 可见路径写出 `rnaseq_deg.inputs.json`。
- 成功退出前检查所有生成路径确实存在。

路径规则：

```text
inputs JSON 中的路径必须是 Cromwell server 可见路径，而不一定是 Windows/Codex 可见路径。
```

例如，如果 Windows 看到的路径是：

```text
C:\Users\yuanz\Project\AI-bioworkflow\examples\tiny
```

而 Cromwell runner 看到同一份数据的路径是：

```text
/data/ai-bioworkflow-tiny
```

那么 `rnaseq_deg.inputs.json` 中必须写 `/data/ai-bioworkflow-tiny/...`。

## 真实 E2E 测试

`tests/e2e/test_tiny_run.py` 应执行：

1. 检查 `AI_BIOWORKFLOW_RUN_E2E`。
2. 通过 `get_execution_backend()` 选择 backend。
3. 如果 e2e 未开启，则 skip。
4. 如果 e2e 已开启但 backend 不可用，则 fail。
5. 读取 `examples/rnaseq_deg_recipe_plan.json`。
6. 开启校验编译 workflow。
7. 断言生成状态有效。
8. 将 WDL 写入本地临时路径，用于 API upload。
9. 读取 `AI_BIOWORKFLOW_TINY_INPUTS`。
10. 通过 `backend.run(...)` 提交 WDL 和 inputs。
11. 断言 `result.succeeded`。
12. 断言 outputs 包含：

```text
RNASeqDEG.deg_table
RNASeqDEG.multiqc_report
```

Windows client 不应默认假设自己可以读取 Cromwell 返回的 output 文件路径。P0 第一版应基于 Cromwell status 和 output keys 做断言。只有在共享输出目录或 output copy 策略明确后，才适合检查 output 文件存在且非空。

## P0 验证命令

P0 验证入口分为本地快速检查和真实 Cromwell e2e。默认入口不触发真实
workflow 执行，真实 e2e 必须显式 opt-in。

| 场景 | 命令 | 说明 |
| --- | --- | --- |
| 本地 P0 快速检查 | `powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1` | 运行单测、代表性 RNA-seq WDL 编译和语法校验。 |
| 真实 Cromwell tiny e2e | `powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1 -RunE2E -CromwellUrl http://localhost:8000 -WindowsFixtureRoot C:\data\ai-bioworkflow-tiny -CromwellFixtureRoot /data/ai-bioworkflow-runner/tiny` | 委托 `scripts/run_cromwell_tiny_e2e.ps1` 准备 fixture、同步 runner 并运行 e2e。 |

本地快速检查的多行写法：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1
```

真实 Cromwell e2e 的多行写法：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1 `
  -RunE2E `
  -CromwellUrl http://localhost:8000 `
  -WindowsFixtureRoot C:\data\ai-bioworkflow-tiny `
  -CromwellFixtureRoot /data/ai-bioworkflow-runner/tiny
```

`check_p0.ps1` 是 P0 总检查入口；真实 Cromwell e2e 的 fixture 准备、
runner 同步和测试执行仍由 `scripts/run_cromwell_tiny_e2e.ps1` 统一负责，
避免两份脚本维护重复的 e2e 逻辑。

## 实施计划

### 阶段 1：文档与测试边界

- [x] 更新 P0 文档，明确 miniwdl 是可选项。
- [x] 明确 Cromwell API execution 是 P0 runtime baseline。
- [x] 固定 Windows/Codex 与 Cromwell runner 的职责边界。
- [x] 将本文档作为独立计划文档。

### 阶段 2：Execution Backend 核心

- [x] 新增 `src/execution/protocol.py`。
- [x] 新增 `BackendAvailability`。
- [x] 新增 `ExecutionResult`。
- [x] 新增 `ExecutionBackend` protocol。
- [x] 新增 `src/execution/disabled.py`。
- [x] 新增 `src/execution/factory.py`。
- [x] 添加 backend selection 单元测试。

### 阶段 3：Cromwell Backend

- [x] 新增 `src/execution/cromwell.py`。
- [x] 通过 `/engine/v1/status` 实现 health check。
- [x] 通过 `/api/workflows/v1` 实现 submit。
- [x] 使用 `workflowSource`、`workflowInputs`、`workflowOptions`、`workflowDependencies` 和 `labels`。
- [x] 通过 `/api/workflows/v1/{id}/status` 实现 polling。
- [x] 实现 outputs 和 metadata 获取。
- [x] 实现 timeout 和 failed status 处理。
- [x] 添加 mock contract tests。

### 阶段 4：E2E 测试迁移

- [x] 创建 `tests/e2e/`。
- [x] 新增真实 Cromwell e2e 入口，并保留 miniwdl tiny run 为可选检查。
- [x] 保证默认 e2e 行为是 skip。
- [x] 保证显式开启 e2e 但 backend 不可用时 fail。
- [x] 断言 Cromwell status 和 output keys。
- [x] 不默认假设 Windows 能访问 Cromwell output 文件路径。

### 阶段 5：Tiny Fixture

- [x] 新增 `examples/tiny/prepare_tiny_data.py`。
- [x] 新增 `examples/tiny/rnaseq_deg.inputs.template.json`。
- [x] 由脚本生成小型 fixture 源数据。
- [x] 在 runner 环境生成 Salmon index。
- [x] 在 runner 环境生成最终 `rnaseq_deg.inputs.json`。
- [x] 写出成功前验证所有路径存在。

### 阶段 6：Cromwell Runner

- [x] 准备 Linux、WSL、devcontainer 或服务器侧 Cromwell 环境。
- [x] 使用 `deploy/cromwell/` 中的 Docker Compose 部署 Cromwell server mode。
- [x] 固定 Cromwell server 版本为 `92`。
- [x] 使用 PostgreSQL 16 作为 Cromwell metadata database。
- [x] 使用 Docker-outside-of-Docker 挂载宿主机 Docker socket，不使用 Docker-in-Docker。
- [x] 确保 Docker 或其他已配置 backend 可用。
- [x] 拉取或构建所需镜像：

```text
quay.io/biocontainers/fastp:1.3.3--h43da1c4_0
quay.io/biocontainers/salmon:1.9.0--h7e5ed60_0
ghcr.io/yuanzhw/ai-bioworkflow/tximport:1.30.0-r1
ghcr.io/yuanzhw/ai-bioworkflow/deseq2:1.42.1-r2
ghcr.io/yuanzhw/ai-bioworkflow/multiqc:1.21-r1
```

- [x] 手动确认 `GET /engine/v1/status` 可用。
- [x] 运行 tiny fixture 准备脚本。
- [x] 设置 Cromwell 相关环境变量并运行 e2e 测试。

### 阶段 7：P0 便捷检查

- [x] 新增 `scripts/check_p0.ps1`。
- [x] 默认只跑快速检查。
- [x] 真实 e2e 必须显式 opt-in。
- [x] 文档化所需环境变量。

## P0 Definition of Done

P0 完成需要满足：

- [x] Windows/Codex 普通 unit 和 compiler tests 通过。
- [x] 代表性生成 WDL 可以通过项目 WDL validator（WOMtool 或 miniwdl）校验。
- [x] `CromwellBackend` 有 submit、poll、outputs、metadata 和错误处理的 contract tests。
- [x] 真实 RNA-seq DEG tiny workflow 可以在 Cromwell runner 中运行到 `Succeeded`。
- [x] e2e 测试检查 Cromwell outputs 中包含 `RNASeqDEG.deg_table` 和 `RNASeqDEG.multiqc_report`。
- [x] 最终环境绑定的 inputs JSON 由 runner 侧 fixture 脚本生成，不作为固定绝对路径文件提交。
- [x] README 或开发文档说明如何运行快速检查和真实 e2e 检查。

## P0 非目标

- 完整 Web API run history。
- 完整 workflow output 文件下载能力。
- 跨平台自动 fixture 路径翻译。
- 从 Windows/Codex 进程启动 Cromwell。
- P0 强制依赖 `miniwdl`。
- 支持未知工具或 Candidate ToolSpec discovery。
- 生产级 Cromwell 部署加固。

## 待确认问题

- output 文件存在且非空检查是否等到共享输出目录标准化后再加入？
- 项目维护镜像是否要在 P0 前从 mutable tag 升级到 digest-pinned reference？
