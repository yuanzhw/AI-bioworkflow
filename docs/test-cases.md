# 测试用例说明

本文档梳理当前 `tests/` 目录中的单元测试、集成测试和可选运行测试，说明每个用例的输入、执行路径和期望输出。当前测试集中大量用例围绕同一条主链路展开：

```text
Recipe Tool Plan / Workflow IR / Legacy JSON
  -> IR normalizer / catalog resolver
  -> Analyzer
  -> Renderer
  -> WDL validator 或跳过校验
```

## 运行方式

仓库约定的测试命令为：

```bash
.venv/bin/python -m unittest discover -v
```

在 Windows PowerShell 中通常使用：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

P0 快速检查脚本会运行完整单测、代表性 RNA-seq WDL 编译和语法校验：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1
```

真实 Cromwell tiny e2e 需要显式 opt-in：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1 `
  -RunE2E `
  -WindowsFixtureRoot C:\data\ai-bioworkflow-tiny `
  -CromwellFixtureRoot /data/ai-bioworkflow-runner/tiny
```

该 opt-in 路径会委托 `scripts/run_cromwell_tiny_e2e.ps1` 执行真实 e2e，
因此 fixture 生成和同步逻辑只有一个维护入口。

部分测试会按本地环境自动跳过：

- `tests/test_tools.py`：没有 WOMtool 或 miniwdl 时跳过 WDL validator 测试。
- `tests/test_tiny_run.py`：没有 miniwdl、Docker/Podman、本地镜像或 tiny 输入文件时跳过真实 tiny run。
- `tests/test_container_build.py`：纯单元测试，不调用 Docker；只验证容器构建脚本的 tag contract。

当前 P1.7 事件与 artifacts 收口后的最近一次完整验证结果：

```text
.\.venv\Scripts\python.exe -m unittest discover -v
Ran 186 tests
OK (skipped=2)
```

跳过项为显式 opt-in 的真实 Cromwell tiny e2e，以及本地未安装 miniwdl
时跳过的可选 miniwdl tiny run。

真实 Cromwell tiny e2e 已在独立 runner 环境中手动运行过；默认单测仍保留
显式 opt-in 机制，避免普通 Windows/Codex 开发环境误触发真实 workflow 执行。

## 公共测试输入

### RNA-seq Recipe Tool Plan

多个测试文件都构造了等价的 `sample_rnaseq_tool_plan()`，结构与 `examples/rnaseq_deg_recipe_plan.json` 一致。

输入内容：

- workflow 名称：`RNASeqDEG`
- recipe：`rnaseq_differential_expression`
- workflow inputs：
  - `sample_ids: Array[String]`
  - `raw_r1s: Array[File]`
  - `raw_r2s: Array[File]`
  - `transcriptome_index: File`
  - `tx2gene: File`
  - `sample_groups: File`
- tool calls：
  - `qc`: recipe step `qc`, tool `fastp` `1.3.3`, 输入 `raw_r1s/raw_r2s`, 参数 `thread=4`
  - `quantify`: recipe step `quantify`, tool `salmon` `1.9.0`, 输入来自 `qc.clean_r1/qc.clean_r2` 和 `transcriptome_index`, 参数 `thread=8`、`lib_type="A"`
  - `summarize`: recipe step `summarize_transcripts`, tool `tximport` `1.30.0`
  - `deg`: recipe step `differential_expression`, tool `deseq2` `1.42.1`, 参数 `contrast="condition"`
  - `report`: recipe step `qc_report`, tool `multiqc` `1.21`
- workflow outputs：
  - `deg_table = deg.deg_table`
  - `multiqc_report = report.multiqc_report`

期望转换后的核心输出：

- `qc` 和 `quantify` 进入同一个 `scatter (i in range(length(sample_ids)))`。
- `raw_r1s/raw_r2s` 在 scatter 内自动变为 `raw_r1s[i]/raw_r2s[i]`。
- Catalog 生成 task 定义、命令、outputs 和 runtime。
- MultiQC 的 `report_files` 渲染为 `flatten([qc.html_report, qc.json_report, quantify.log_file])`。

### 多任务 Workflow IR

`tests/test_graph.py` 中的 `sample_multi_task_ir()` 用于测试基础 IR 分析、渲染和修复。

输入内容：

- workflow 名称：`RNASeqPipeline`
- workflow inputs：`raw_r1: File`、`raw_r2: File`、`reference: File`
- calls：
  - `qc` 调用 task `fastp`
  - `align` 调用 task `bwa_mem`，输入引用 `qc.clean_r1/qc.clean_r2`
- outputs：`bam = align.bam`
- tasks：
  - `fastp` 输出 `clean_r1/clean_r2`
  - `bwa_mem` 输出 `bam`

期望输出：

- Analyzer 认为 call 顺序正确时 IR 有效。
- Renderer 生成 `workflow RNASeqPipeline`、`call fastp as qc`、`call bwa_mem as align` 和 `File bam = align.bam`。
- 当 calls 反转时，Analyzer 能发现前向引用；Agent repairer 能在安全情况下重排。

## `tests/api/test_models.py`

该文件验证 FastAPI DTO。DTO 只定义 API 输入输出形状，不实现业务逻辑；业务逻辑仍由 service 层和编译链路承担。

### `test_compile_workflow_request_accepts_structured_payload`

输入：

- `examples/rnaseq_deg_recipe_plan.json`

执行：

- 构造 `CompileWorkflowRequest(payload=plan)`。

期望输出：

- `payload` 等于输入 plan。
- 默认 `check == True`。

覆盖点：

- `/api/compile` 可以接收 Recipe Tool Plan / Workflow IR / legacy JSON 这类结构化 payload。

### `test_compile_workflow_request_rejects_empty_payload`

输入：

- 空 dict：`{}`

执行：

- 构造 `CompileWorkflowRequest(payload={})`。

期望输出：

- 抛出 `ValidationError`。
- 错误消息包含 `payload must not be empty`。

覆盖点：

- API 层在进入 service 前拒绝空结构化输入。

### `test_natural_language_request_strips_and_validates_text`

输入：

- 请求文本：`"  Run RNA-seq DEG.  "`
- 空白请求：`"  "`

执行：

- 构造 `NaturalLanguageRunRequest(...)`。

期望输出：

- 非空请求会被 strip 为 `Run RNA-seq DEG.`。
- 空白请求抛出 `ValidationError`，错误消息包含 `request must not be empty`。

覆盖点：

- `/api/runs` 的自然语言入口不会把空请求交给 planner service。

### `test_compilation_result_response_maps_successful_service_result`

输入：

- `examples/rnaseq_deg_recipe_plan.json`
- `compile_structured_workflow(..., check=False)` 返回的成功 service result。

执行：

- 调用 `CompilationResultResponse.from_service_result(result)`。

期望输出：

- `status == "succeeded"`。
- diagnostics 中 `succeeded == True`。
- diagnostics 中 `check_performed == False`。
- analysis errors 为空。
- artifacts 中 workflow 名称为 `RNASeqDEG`。
- artifacts 中 WDL 包含 `workflow RNASeqDEG`。

覆盖点：

- API response DTO 能稳定包装 W0 workflow service 的成功结果。

### `test_compilation_result_response_maps_failed_service_result`

输入：

- 复制 `examples/rnaseq_deg_recipe_plan.json`。
- 删除 required input `sample_groups`。
- `compile_structured_workflow(..., check=False)` 返回的失败 service result。

执行：

- 调用 `CompilationResultResponse.from_service_result(result)`。

期望输出：

- `status == "failed"`。
- diagnostics 中 `succeeded == False`。
- artifacts 中 `wdl == ""`。
- analysis errors 包含 `sample_groups`。

覆盖点：

- API response DTO 能保留 service 诊断，不把无效 plan 包装成成功响应。

### `test_run_snapshot_response_defaults_to_empty_artifacts_and_diagnostics`

输入：

- 只包含 run id、运行状态、请求内容和事件 URL 的 `WorkflowRunSnapshotResponse`。

执行：

- 直接构造 `WorkflowRunSnapshotResponse(...)`。

期望输出：

- artifacts 默认为空 Workflow IR 与空 WDL。
- `catalog_retrieval` 默认为 `None`，结构化或尚未检索的 run 不伪造 retrieval artifact。
- diagnostics 默认不是 succeeded。
- `kind`、`created_at`、`updated_at` 和 `completed_at` 默认为 `None`。

覆盖点：

- run 详情页依赖的 snapshot metadata 默认契约保持显式、稳定。

### `test_workflow_artifacts_expose_manifest_and_extra_artifacts`

输入：

- `WorkflowArtifacts`，包含：
  - `extras.catalog_retrieval.strategy == "lexical_v1"`
  - 一条 `WorkflowArtifactSummary(name="catalog_retrieval", content_type="application/json")`

执行：

- 直接构造 `WorkflowArtifacts(...)`。

期望输出：

- `extras` 保留额外 artifact 的 JSON-ready 内容。
- `manifest` 保留 artifact 名称、content type 和更新时间。

覆盖点：

- Run snapshot 可以在固定 `plan` / `workflow_ir` / `wdl` 字段之外，暴露后续 orchestration 阶段新增的命名 artifact。
- 前端和历史详情可以通过 manifest 判断哪些 artifact 已经持久化，而不依赖固定列枚举。

### `test_run_list_response_accepts_history_summaries`

输入：

- 一条 `RunSummary`：
  - `run_id == "run_001"`
  - `status == "succeeded"`
  - `kind == "structured_compile"`
  - `request_summary == "rnaseq_differential_expression"`
  - diagnostic summary 中 warning count 为 `1`

执行：

- 构造 `RunListResponse(...)`。

期望输出：

- response 保留 run id。
- diagnostic summary 保留 warning count。
- `is_valid == True`。

覆盖点：

- W5 run history 列表 DTO 只暴露轻量摘要，不返回完整 artifacts。

### `test_recipe_list_response_accepts_catalog_service_records`

输入：

- `list_recipes()` 返回的 JSON-ready recipe records。

执行：

- 调用 `RecipeListResponse.model_validate({"recipes": list_recipes()})`。

期望输出：

- 至少包含一个 recipe。
- 第一个 recipe id 为 `rnaseq_differential_expression`。
- `sample_ids` required input 类型为 `Array[String]`。
- 第一个 step 的 allowed tools 为 `["fastp"]`。

覆盖点：

- Catalog service 的 recipe records 与 API DTO 兼容。

### `test_tool_list_response_accepts_catalog_service_records`

输入：

- `list_tools()` 返回的 JSON-ready tool records。

执行：

- 调用 `ToolListResponse.model_validate({"tools": list_tools()})`。

期望输出：

- `fastp` tool version 为 `0.23.2`。
- `trust_status == "catalog-approved"`。
- runtime docker 为 `quay.io/biocontainers/fastp:0.23.2`。
- outputs 包含 `clean_r1`。

覆盖点：

- Catalog service 的 tool records 与 API DTO 兼容。
- Tool runtime 与 trust status 可以直接暴露给前端。

### `test_run_event_defines_persistable_event_envelope`

输入：

- event id：`evt_001`
- run id：`run_001`
- sequence：`1`
- type：`run.created`
- timestamp：`2026-06-06T00:00:00Z`

执行：

- 构造 `RunEvent(...)`。

期望输出：

- event type 为 `RunEventType.RUN_CREATED`。
- 默认 `payload == {}`。

覆盖点：

- W2 SSE / history 使用的 event envelope 形状已提前固定。

### `test_run_event_requires_positive_sequence`

输入：

- sequence：`0`

执行：

- 构造 `RunEvent(...)`。

期望输出：

- 抛出 `ValidationError`。
- 错误消息包含 `greater than or equal to 1`。

覆盖点：

- 事件序号必须从正整数开始，便于后续持久化和回放排序。

## `tests/api/test_routes.py`

该文件验证 W2 FastAPI endpoint contract。测试通过 `TestClient(create_app())` 打 HTTP 层，并通过 patch 断言 API routes 复用 service 层，而不是复制 catalog resolver、planner、compiler 或 run lifecycle 逻辑。

`POST /api/runs` 当前契约为 W2 异步 run 创建入口：请求体包含自然语言 `request`、可选 `planner_model` 和 `check`；响应返回 HTTP 202 与 `RunAcceptedResponse`，包括 `run_id`、初始 `created` 状态和 `events_url`。`POST /api/compile` 同样创建 run，但输入是 Recipe Tool Plan / Workflow IR JSON，跳过自然语言 planner。

`GET /api/runs` 返回分页 run 摘要列表，用于 W5 历史页首屏；`GET /api/runs/{run_id}` 返回持久化 run 快照；`GET /api/runs/{run_id}/events` 返回 SSE 事件流，用于实时展示和历史回放。

### `test_list_recipes`

输入：

- mock `catalog_service.list_recipes()` 返回当前 recipe records。
- HTTP 请求：`GET /api/recipes`

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `200`。
- `catalog_service.list_recipes()` 被调用一次。
- 响应中至少有一个 recipe。
- 第一个 recipe id 为 `rnaseq_differential_expression`。

覆盖点：

- Recipe 列表 endpoint 复用 W0 catalog service。

### `test_get_recipe_uses_catalog_service`

输入：

- mock `catalog_service.get_recipe("rnaseq_differential_expression")`。
- HTTP 请求：`GET /api/recipes/rnaseq_differential_expression`

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `200`。
- service 调用参数为 `rnaseq_differential_expression`。
- 响应 id 为 `rnaseq_differential_expression`。

覆盖点：

- 单个 recipe endpoint 复用 W0 catalog service。

### `test_get_recipe_not_found`

输入：

- mock `catalog_service.get_recipe(...)` 抛出 `KeyError("unknown recipe: missing_recipe")`。
- HTTP 请求：`GET /api/recipes/missing_recipe`

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `404`。
- service 调用参数为 `missing_recipe`。
- response detail 包含 `unknown recipe`。

覆盖点：

- 未知 recipe 被 API 层稳定映射为 404。

### `test_list_tools`

输入：

- mock `catalog_service.list_tools()` 返回当前 tool records。
- HTTP 请求：`GET /api/tools`

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `200`。
- `catalog_service.list_tools()` 被调用一次。
- `fastp` 记录中 `version == "0.23.2"`。
- `fastp` 记录中 `trust_status == "catalog-approved"`。

覆盖点：

- Tool 列表 endpoint 复用 W0 catalog service。

### `test_get_tool_with_version`

输入：

- mock `catalog_service.get_tool("salmon", "1.10.2")`。
- HTTP 请求：`GET /api/tools/salmon?version=1.10.2`

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `200`。
- service 调用参数为 `("salmon", "1.10.2")`。
- 响应 id 为 `salmon`。
- 响应 version 为 `1.10.2`。

覆盖点：

- 单个 tool endpoint 支持通过 query string 指定版本，并复用 W0 catalog service。

### `test_get_tool_not_found`

输入：

- mock `catalog_service.get_tool(...)` 抛出 `KeyError("unknown tool: missing_tool")`。
- HTTP 请求：`GET /api/tools/missing_tool`

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `404`。
- service 调用参数为 `("missing_tool", None)`。
- response detail 包含 `unknown tool`。

覆盖点：

- 未知 tool 被 API 层稳定映射为 404。

### `test_compile_recipe_plan`

输入：

- `examples/rnaseq_deg_recipe_plan.json`
- mock `run_service.create_structured_compile_run(...)` 返回 `RunAcceptedResponse`。
- mock `run_service.execute_structured_compile_run(...)` 作为后台任务。
- mock 自然语言 run service 方法，验证不会被调用。
- HTTP 请求：`POST /api/compile`

执行：

- 调用 FastAPI TestClient，请求体包含 `payload` 和 `check=False`。

期望输出：

- HTTP status 为 `202`。
- response 包含 `run_id`、`status == "created"` 和 `events_url`。
- route 调用 run 创建 service，并安排结构化编译后台执行。
- 自然语言 run service 没有被调用。

覆盖点：

- 结构化编译 endpoint 复用 run service。
- API 层不直接调用 Analyzer / Renderer / Checker。
- `/api/compile` 保持结构化入口边界，不触发自然语言 Planner 路径。

### `test_compile_rejects_empty_payload`

输入：

- HTTP 请求：`POST /api/compile`
- 请求体：`{"payload": {}, "check": false}`

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `422`。

覆盖点：

- DTO 校验会在进入 W0 service 前拒绝空 payload。

### `test_create_run_uses_natural_language_service`

输入：

- mock `run_service.create_natural_language_run(...)` 返回 `RunAcceptedResponse`。
- mock `run_service.execute_natural_language_run(...)` 作为后台任务。
- mock 结构化 compile run service 方法，验证不会被调用。
- HTTP 请求：`POST /api/runs`
- 请求体：`{"request": "Run RNA-seq DEG.", "check": false}`

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `202`。
- response 包含 `run_id`、`status == "created"` 和 `events_url`。
- route 调用 run 创建 service，并安排自然语言 run 后台执行。
- 结构化 compile run service 没有被调用。

覆盖点：

- 自然语言 run endpoint 复用 run service。
- FastAPI route 只负责 HTTP 输入输出和后台任务调度。
- W2 `/api/runs` 是异步 run 创建接口，不直接返回编译结果。
- `/api/runs` 保持自然语言 Orchestration Graph 入口边界。

### `test_create_run_passes_requested_planner_model`

输入：

- mock `run_service.create_natural_language_run(...)` 返回 `RunAcceptedResponse`。
- HTTP 请求：`POST /api/runs`
- 请求体包含 `planner_model: "custom-planner"`。

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `202`。
- 传给 run service 的 request DTO 中 `planner_model == "custom-planner"`。

覆盖点：

- API 支持调用方显式指定 planner model。
- `planner_model` 不在 API 层解释，原样传递给 run service。

### `test_list_runs_uses_run_service_with_filters`

输入：

- mock `run_service.list_runs(...)` 返回 `RunListResponse`。
- HTTP 请求：`GET /api/runs?limit=5&offset=10&status=succeeded`

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `200`。
- route 调用 `run_service.list_runs(limit=5, offset=10, status=RunStatus.SUCCEEDED)`。
- response 中 `runs[0].run_id == "run_123"`。
- response 中 `total == 42`。

覆盖点：

- W5 run history 列表 endpoint 只做分页/filter 参数解析和响应序列化。
- API 层不直接查询 SQLite 或展开 artifacts。

### `test_get_run_returns_snapshot`

输入：

- mock `run_service.get_snapshot(...)` 返回 `WorkflowRunSnapshotResponse`。
- snapshot 包含自然语言 run 的 catalog retrieval、plan、Workflow IR、WDL 和 diagnostics。
- HTTP 请求：`GET /api/runs/run_123`

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `200`。
- response `run_id == "run_123"`。
- response 保留 `kind == "natural_language"`。
- response artifacts 包含 Catalog retrieval、Planner plan、Compiler Workflow IR 和 WDL。
- response diagnostics 保留 `succeeded` 与 `check_performed`。

覆盖点：

- run snapshot endpoint 从 run service 读取持久化快照。
- 自然语言 run history 可通过 API route 暴露 Catalog retrieval、Planner plan 和 Compiler artifacts。

### `test_stream_run_events`

输入：

- mock `run_service.iter_sse_events(...)` 返回 SSE 字符串迭代器。
- HTTP 请求：`GET /api/runs/run_123/events`

执行：

- 调用 FastAPI TestClient。

期望输出：

- HTTP status 为 `200`。
- response text 包含 `event: run.created`。

覆盖点：

- SSE endpoint 复用 run service 的事件流，不在 API 层查询 SQLite。

## `tests/test_run_repository.py`

该文件验证 SQLite-backed run repository。Repository 负责持久化 run、event、artifact 和 diagnostic 数据，并提供面向 service 层的查询能力；它不调用 planner、compiler 或 FastAPI route。

新增 catalog retrieval artifact 覆盖：

- 完整 `save_artifacts(...)` 会保存并读回 `catalog_retrieval`。
- `save_catalog_retrieval_artifact(...)` 可先保存 retrieval artifact，后续 plan、Workflow IR、WDL 增量更新不会覆盖该字段。
- 既有 SQLite `run_artifacts` 表会通过 schema migration 补齐 `catalog_retrieval_json` 列。

### `test_repository_persists_run_events_artifacts_and_diagnostics`

输入：

- 一个 structured compile run。
- 两个 run events：`run.created` 与 `node.started`。
- `WorkflowArtifacts`，包含 plan、Workflow IR 和 WDL。
- `DiagnosticReport`，表示跳过 WDL syntax validation 且 run 成功。

执行：

- 调用 repository 创建 run、追加 events、保存 artifacts、保存 diagnostics、更新 terminal status。
- 读取 snapshot、events 和 named artifact records。

期望输出：

- snapshot run status 为 `succeeded`。
- snapshot artifacts 保留 Workflow IR、WDL 和 manifest。
- manifest 中包含 `plan`、`workflow_ir`、`wdl` 和 `diagnostics`。
- named artifact records 中 `wdl` content type 为 `text/plain`，其余核心 JSON artifact 为 `application/json`。

覆盖点：

- 固定 artifact 列与通用 `run_artifact_records` manifest 会同步写入。
- diagnostics 既保留在专用 diagnostic 表中，也作为命名 artifact 进入 manifest，方便后续统一 artifact 展示。

### `test_list_runs_returns_paginated_summaries_with_status_filter`

输入：

- 一个 failed run：
  - `run_id == "run_failed"`
  - diagnostics 含 1 条 analysis error、1 条 warning 和 1 条 repair action
- 一个 succeeded run：
  - `run_id == "run_succeeded"`
  - diagnostics 中 `is_valid == True`

执行：

- 调用 `repository.list_runs(limit=1)`。
- 调用 `repository.list_runs(limit=1, offset=1)`。
- 调用 `repository.list_runs(status=RunStatus.FAILED)`。

期望输出：

- 未过滤列表 total 为 `2`。
- 第一页返回较新的 `run_succeeded`。
- 第二页返回 `run_failed`。
- failed filter total 为 `1`。
- failed run 的 diagnostic summary 计数分别为 `1`。

覆盖点：

- W5 历史列表的 repository 查询支持分页、状态过滤和稳定排序。
- 列表查询只返回 diagnostic counters，不读取完整 artifact。

### `test_named_extra_artifacts_are_exposed_in_snapshot`

输入：

- 一个 natural-language run。
- 额外命名 JSON artifact：`catalog_retrieval`。

执行：

- 调用 `repository.save_json_artifact("run_001", "catalog_retrieval", ...)`。
- 读取 run snapshot。
- 尝试保存非法名称 `Bad-Name`。

期望输出：

- `snapshot.artifacts.extras.catalog_retrieval` 等于保存的检索结果。
- manifest 中包含 `catalog_retrieval`，content type 为 `application/json`。
- 非法 artifact 名称抛出 `ValueError`。

覆盖点：

- 后续 Catalog Retriever、planner trace 摘要和 execution result 可以作为命名 artifact 保存，不需要为每类产物新增 SQLite 固定列。
- Artifact 名称有稳定约束，避免 UI 和 API 消费方收到不可预测的 key。

### `test_named_records_override_legacy_fixed_columns_in_snapshot`

输入：

- 一个 natural-language run。
- 旧固定 artifact 列中已有 `catalog_retrieval`、`plan`、`workflow_ir` 和 `wdl`。
- 同名 named artifact records 中写入更新后的内容，其中 `workflow_ir == {}` 且 `wdl == ""`。

执行：

- 先调用 `repository.save_artifacts(...)` 写入 legacy fixed columns 和初始 records。
- 再通过 `save_json_artifact(...)` / `save_text_artifact(...)` 只更新同名 named artifact records。
- 读取 run snapshot。

期望输出：

- snapshot 顶层 `catalog_retrieval`、`plan`、`workflow_ir` 和 `wdl` 均来自 named artifact records。
- `extras.catalog_retrieval` 与顶层 `catalog_retrieval` 保持一致。
- 空 dict 和空字符串 record 不会被当作缺失值而回退到旧固定列。

覆盖点：

- `run_artifact_records` 是 snapshot 的优先读取来源。
- `run_artifacts` 固定列只作为兼容旧数据库或缺失 records 时的 fallback。

### `test_snapshot_reads_artifact_records_without_public_list_helper`

输入：

- 一个 natural-language run。
- 额外命名 JSON artifact：`catalog_retrieval`。

执行：

- patch 当前 repository 实例的 `list_artifact_records(...)`，使其一旦被调用就抛错。
- 调用 `repository.get_snapshot(...)`。

期望输出：

- snapshot 仍然成功返回。
- `snapshot.artifacts.extras.catalog_retrieval.strategy == "lexical_v1"`。

覆盖点：

- `get_snapshot()` 在同一个 DB connection 内读取 run、固定 artifact、named artifact records 和 diagnostics。
- snapshot 不再通过 `list_artifact_records()` 打开第二个连接，避免同一次 snapshot 内部读取到不同时间点的数据。

### `test_schema_backfills_named_artifacts_from_legacy_fixed_columns`

输入：

- 手工创建的旧版 SQLite schema，只包含 `runs`、`run_events`、`run_artifacts` 和 `run_diagnostics`。
- 旧表中已有 plan、Workflow IR、WDL 和 diagnostics。

执行：

- 用 `RunRepository(db_path)` 打开旧数据库，触发 `ensure_schema()`。
- 查询 `run_artifact_records` 和 snapshot。

期望输出：

- 新表 `run_artifact_records` 被创建。
- 旧固定列被回填为 `plan`、`workflow_ir`、`wdl` 和 `diagnostics` 四条 named artifact records。
- snapshot artifacts 仍可读取旧的 Workflow IR 和 manifest。
- 回填完成后再次初始化 repository 不再触发全量 backfill。

覆盖点：

- 本地 `.cache` 中已有展示数据库可以随 schema 演进自动补齐 manifest，不需要手动删除旧 DB。
- 新增通用 artifact 存储保持向后兼容。
- Backfill 只在缺失 legacy artifact records 时运行，避免每次 repository 初始化都扫描旧 artifact 表。

## `tests/test_run_service.py`

该文件验证 persistent run lifecycle service。Service 层连接 API DTO、RunRepository 和 workflow service；FastAPI routes 只调用 service 方法。自然语言 run 通过 `workflow_service.plan_and_compile_workflow` 进入 Orchestration Graph，不在 run service 内重复调用 planner 或结构化 compiler。

### `test_structured_compile_run_succeeds_and_records_events`

输入：

- `examples/rnaseq_deg_recipe_plan.json`
- `check=False`

执行：

- 通过 `RunService.create_structured_compile_run(...)` 创建 run。
- 调用 `RunService.execute_structured_compile_run(...)`。
- 读取 snapshot 与 events。

期望输出：

- snapshot `status == "succeeded"`。
- snapshot `kind == "structured_compile"`。
- snapshot 包含 `created_at`、`updated_at` 和 `completed_at`。
- structured compile snapshot 中 `catalog_retrieval == None`。
- Workflow IR 名称为 `RNASeqDEG`。
- WDL 包含 `workflow RNASeqDEG`。
- events 包含 `run.created`、`artifact.updated`，最后一条为 `run.completed`。
- 倒数第二条事件为 `artifact.updated` diagnostics，并包含 `artifact == "diagnostics"` 与 `succeeded == true`。
- `run.created` payload 包含 `stage == "run"`、`status == "created"` 和 run kind。
- diagnostics artifact payload 包含 `stage == "diagnostics"`、`status == "updated"`、`artifact_name == "diagnostics"` 和 `artifact_content_type == "application/json"`。
- `run.completed` payload 包含 terminal run status。

覆盖点：

- 结构化编译 run 会持久化详情页所需元数据、产物、诊断和事件回放记录。
- diagnostics 保存后会通过结构化 artifact 事件通知历史/SSE 消费方刷新。
- 事件 payload 提供稳定 observability 字段，前端不需要解析 summary 文案判断阶段、状态或 artifact 类型。

### `test_structured_compile_run_replays_repair_artifact_before_repair_event`

输入：

- 从 `examples/rnaseq_workflow_ir.json` 读取 Workflow IR，并反转 calls 形成 forward reference。
- `check=False`

执行：

- 创建并执行结构化 compile run。
- 读取 snapshot 与 events。

期望输出：

- snapshot `status == "succeeded"`。
- diagnostics 包含 repair actions。
- snapshot Workflow IR calls 被修复为 `["qc", "align"]`。
- `artifact.updated` workflow_ir 事件在 `repair.applied` 事件前出现。
- `repair.applied` payload 包含结构化 `repair_actions`。

覆盖点：

- 修复发生时，历史事件先通知 Workflow IR artifact 更新，再记录 repair action。
- 前端和 SSE 消费方不需要根据 summary 文案推断 repair 后的 artifact 类型。

### `test_natural_language_run_succeeds_after_planning`

输入：

- 自然语言请求：`Run RNA-seq DEG.`
- mock `workflow_service.plan_and_compile_workflow(...)` 返回成功的 `WorkflowCompilationResult`

执行：

- 通过 `RunService.create_natural_language_run(...)` 创建 run。
- 调用 `RunService.execute_natural_language_run(...)`。
- 读取 run snapshot。

期望输出：

- `plan_and_compile_workflow` 被调用一次。
- 调用参数包含自然语言 request、`check=False` 和 `event_callback`。
- snapshot `status == "succeeded"`。
- snapshot artifacts 包含 catalog retrieval、Recipe Tool Plan 和 WDL。

覆盖点：

- 自然语言 run service 入口只依赖稳定 workflow service，不再手写 Planner 到 Compiler 的线性编排。
- API run 层通过 callback 接收 service 事件。

### `test_natural_language_run_replays_key_events_and_artifacts`

输入：

- 自然语言请求：`Run RNA-seq DEG.`
- mock `plan_and_compile_workflow(...)` 通过 `event_callback` 发出 catalog retriever、planner、compiler delegate、Compiler Graph、artifact 和 validation 事件，并返回成功结果。

执行：

- 创建并执行自然语言 run。
- 读取 run snapshot 与 events。

期望输出：

- snapshot artifacts 包含 Catalog retrieval、Planner plan、Workflow IR 和 WDL。
- snapshot diagnostics 表示 run 成功。
- event history 以 `run.created` 开始，并依次包含 catalog_retriever started/completed、catalog_retrieval artifact、planner started/completed、plan artifact、compiler_graph started、Compiler Graph 节点事件、WDL artifact、validation completed。
- 倒数第二条为 diagnostics artifact 更新，最后一条为 `run.completed`。
- artifact 顺序为 `catalog_retrieval`、`plan`、`workflow_ir`、`wdl`、`diagnostics`。
- diagnostics artifact payload 包含错误数、修复数、`check_performed` 和 `succeeded` 等结构化字段。
- planner event payload 标记 `stage == "planning"`。
- compiler delegate event payload 标记 `stage == "orchestration"`。
- artifact event payload 同时保留旧字段 `artifact` 和新字段 `artifact_name` / `artifact_content_type`。

覆盖点：

- 成功自然语言 run 可以被前端和历史详情按关键阶段回放。
- artifact 事件 payload 使用结构化字段，不依赖前端解析 summary 文案。

### `test_extra_text_artifact_event_matches_persisted_content_type`

输入：

- 一个已创建的 natural-language run。
- 额外命名 artifact：`planner_trace`，state 中内容为字符串。

执行：

- 通过 workflow event callback 发出 `artifact.updated` 事件。
- 读取事件历史和 run snapshot。

期望输出：

- 事件 payload 中 `artifact_name == "planner_trace"`。
- 事件 payload 中 `artifact_content_type == "text/plain"`。
- snapshot `extras.planner_trace` 保留文本内容。
- manifest 中 `planner_trace` 的 content type 同样为 `text/plain`。

覆盖点：

- 未预注册的 text artifact 会按实际 state 内容推断 content type。
- 事件 payload 与 repository 持久化记录保持一致，不会出现事件声称 JSON、DB 保存 text 的契约分叉。

### `test_natural_language_run_preserves_empty_planner_observability_fields`

输入：

- 自然语言请求：`Run RNA-seq DEG.`
- mock `plan_and_compile_workflow(...)` 返回 `planner_prompt == ""` 和 `planner_raw_response == ""`

执行：

- 创建并执行自然语言 run。
- 直接读取 SQLite `run_artifacts` 表。

期望输出：

- `planner_prompt` 保存为空字符串。
- `planner_raw_response` 保存为空字符串。

覆盖点：

- 空字符串 trace 与 `None` 语义区分保留，便于后续调试真实 planner 行为。

### `test_natural_language_compile_exception_preserves_partial_artifacts`

输入：

- 自然语言请求：`Run RNA-seq DEG.`
- mock `plan_and_compile_workflow(...)` 先通过 `event_callback` 发出 catalog retrieval、plan 和 Workflow IR artifact 更新，再抛出 `RuntimeError("compiler exploded")`

执行：

- 创建并执行自然语言 run。
- 读取 snapshot 与 events。

期望输出：

- snapshot `status == "failed"`。
- snapshot artifacts 仍保留 retriever 产出的 catalog retrieval、planner 产出的 plan 和 compiler 已产出的 Workflow IR。
- snapshot WDL 仍为空字符串。
- diagnostics validation message 包含 `compiler exploded`。
- events 包含 compiler failure，并以 `run.completed` 结束。
- artifact 顺序为 `catalog_retrieval`、`plan`、`workflow_ir`、`diagnostics`。

覆盖点：

- 即使自然语言 run 在 compiler 阶段失败，已产生的 partial artifacts 仍可被历史详情和 SSE 回放读取。
- 失败 run 也会在完成前发出 diagnostics artifact 更新事件。

### `test_natural_language_planner_error_is_persisted_as_failed_run`

输入：

- 自然语言请求：`Run RNA-seq DEG.`
- mock `plan_and_compile_workflow(...)` 抛出 `NaturalLanguagePlanningError`

执行：

- 创建并执行自然语言 run。
- 读取 snapshot 与 events。

期望输出：

- snapshot `status == "failed"`。
- snapshot 不包含 plan、Workflow IR 或 WDL artifact。
- diagnostics validation message 包含 planner 错误。
- events 包含 `node.failed`。
- artifact 顺序只包含 `diagnostics`。

覆盖点：

- Planner 错误由 workflow service 分类并传递给 run service，run service 只负责持久化失败状态与诊断。
- Planner 失败不会误写 Compiler artifacts。

### `test_list_runs_returns_api_summaries`

输入：

- 通过 `RunService.create_structured_compile_run(...)` 创建一条 RNA-seq Recipe Tool Plan run。
- repository 中保存 succeeded diagnostics 并完成 run。

执行：

- 调用 `service.list_runs(status=RunStatus.SUCCEEDED)`。

期望输出：

- response total 为 `1`。
- run id 与创建时返回的 id 一致。
- `status == "succeeded"`。
- `kind == "structured_compile"`。
- `request_summary == "rnaseq_differential_expression"`。
- diagnostic summary 中 `check_performed == False`。
- `completed_at` 不为空。

覆盖点：

- Service 层把 repository records 转成 API-facing `RunListResponse`。
- 结构化 Recipe Tool Plan 的历史摘要优先使用 recipe id。

## `tests/api/test_server.py`

该文件验证 FastAPI 开发服务器的本地端口约定。Cromwell server 保留 `8000` 端口，本项目 API 默认使用 `8010`。

### `test_default_api_port_avoids_cromwell_default_port`

输入：

- `DEFAULT_API_HOST`
- `DEFAULT_API_PORT`

执行：

- 读取 `src.api.server` 中的默认 host 和 port。

期望输出：

- 默认 host 为 `127.0.0.1`。
- 默认 API port 为 `8010`。
- 默认 API port 不等于 Cromwell 常用端口 `8000`。

覆盖点：

- FastAPI 开发服务默认避开 Cromwell server 端口。

### `test_api_port_can_be_overridden_by_environment`

输入：

- 环境变量 `AI_BIOWORKFLOW_API_PORT=8020`。

执行：

- 调用 `get_api_port()`。

期望输出：

- 返回 `8020`。

覆盖点：

- 本地开发时可以临时覆盖 API 端口。

### `test_api_port_rejects_invalid_environment_value`

输入：

- 环境变量 `AI_BIOWORKFLOW_API_PORT=not-a-port`。
- 环境变量 `AI_BIOWORKFLOW_API_PORT=70000`。

执行：

- 调用 `get_api_port()`。

期望输出：

- 非整数端口抛出 `ValueError`，错误消息包含 `must be an integer`。
- 越界端口抛出 `ValueError`，错误消息包含 `between 1 and 65535`。

覆盖点：

- 开发服务不会接受无效端口配置。

### `test_api_host_can_be_overridden_by_environment`

输入：

- 环境变量 `AI_BIOWORKFLOW_API_HOST=0.0.0.0`。

执行：

- 调用 `get_api_host()`。

期望输出：

- 返回 `0.0.0.0`。

覆盖点：

- 本地或容器开发场景可以临时覆盖 API host。

### `test_default_cors_origins_cover_next_development_server`

输入：

- `DEFAULT_CORS_ORIGINS`

执行：

- 读取 `src.api.app` 中的默认 CORS origins。

期望输出：

- 默认允许 `http://127.0.0.1:3000`。
- 默认允许 `http://localhost:3000`。

覆盖点：

- 本地 Next.js 默认开发服务可以直接访问 FastAPI。

### `test_cors_origins_can_be_overridden_by_environment`

输入：

- 环境变量 `AI_BIOWORKFLOW_CORS_ORIGINS=http://127.0.0.1:3001/, http://localhost:3001`。

执行：

- 调用 `get_cors_origins()`。

期望输出：

- 返回 `["http://127.0.0.1:3001", "http://localhost:3001"]`。
- 末尾 `/` 会被规范化移除。

覆盖点：

- 前端开发服务使用非默认端口时，可以显式配置 allowed origins。
- 常见的 trailing slash 写法不会导致 CORS origin 匹配失败。

### `test_next_development_origin_can_preflight_api_requests`

输入：

- `TestClient(create_app())`
- `OPTIONS /api/compile`
- 请求头：
  - `Origin: http://127.0.0.1:3000`
  - `Access-Control-Request-Method: POST`
  - `Access-Control-Request-Headers: content-type`

执行：

- 调用 FastAPI TestClient 发起浏览器预检请求。

期望输出：

- HTTP 状态码为 `200`。
- `access-control-allow-origin` 响应头为 `http://127.0.0.1:3000`。

覆盖点：

- W4 工作台从 Next.js 开发服务点击“运行示例”时，浏览器可以通过 CORS preflight 调用 `POST /api/compile`。

### `test_root_and_health_endpoints_are_available`

输入：

- `TestClient(create_app())`
- `GET /`
- `GET /health`

执行：

- 调用 FastAPI TestClient 请求根路径和健康检查路径。

期望输出：

- 根路径 HTTP 状态码为 `200`，响应 JSON 中 `status == "ok"`。
- `/health` HTTP 状态码为 `200`，响应 JSON 为 `{"status": "ok"}`。

覆盖点：

- 本地开发服务和部署探针都有轻量健康检查入口。

### `test_favicon_request_does_not_log_404`

输入：

- `TestClient(create_app())`
- `GET /favicon.ico`

执行：

- 调用 FastAPI TestClient 请求浏览器常见 favicon 路径。

期望输出：

- HTTP 状态码为 `204`。

覆盖点：

- 浏览器访问 API docs 或 health 页面时不会因为 favicon 请求产生无意义的 404 噪声。

## `tests/test_catalog.py`

该文件验证 Recipe / Tool Catalog resolver 的结构化校验、IR 生成和 WDL 渲染。

### `test_catalog_plan_resolves_to_valid_renderable_ir`

输入：

- `sample_rnaseq_tool_plan()`
- 当前正式 Tool Catalog
- 当前正式 Recipe Catalog

执行：

1. 调用 `resolve_tool_plan(...)` 将 Recipe Tool Plan 转为 Workflow IR。
2. 调用 `analyze_workflow_ir(...)` 做静态分析。
3. 调用 `render_wdl(...)` 生成 WDL。

期望输出：

- Analyzer 返回 `is_valid=True`。
- Workflow 名称为 `RNASeqDEG`。
- IR 中包含 task：`fastp_qc`、`salmon_quantify`、`tximport_summarize`、`deseq2_deg`、`multiqc_report`。
- `workflow.steps[0].kind == "scatter"`。
- WDL 中包含：
  - `scatter (i in range(length(sample_ids)))`
  - `call fastp_qc as qc`
  - `call salmon_quantify as quantify`
  - `r1 = raw_r1s[i]`
  - `r2 = raw_r2s[i]`
  - `call tximport_summarize as summarize`
  - `call deseq2_deg as deg`
  - `call multiqc_report as report`
  - `report_files = flatten([qc.html_report, qc.json_report, quantify.log_file])`
  - `File deg_table = deg.deg_table`
  - `File multiqc_report = report.multiqc_report`
  - `quant_files = quantify.quant_file`
  - Salmon 默认 library type 渲染为 `lib_type = "A"` 和 `-l ~{lib_type}`
  - `--contrast ~{contrast}`
  - `contrast = "condition"`
  - fastp paired-end 参数片段以 shell 续行形式渲染，例如 `-I ~{r2} \`
    和 `-O clean_R2.fq.gz \`
  - DESeq2 wrapper 直接以 PATH 命令 `run_deseq2.R` 渲染，不依赖工作目录中存在脚本文件

覆盖点：

- Recipe Tool Plan 到 IR 的主路径。
- Catalog task 定义注入。
- scatter 自动索引。
- params 字面量格式化。
- scatter 输出数组汇总到 MultiQC。

### `test_tool_spec_requires_runtime_docker`

输入：

- 直接构造一个 `ToolSpec`：
  - tool id/version 为 `fastp/1.3.3`
  - 有 input、output 和 command template
  - runtime 只提供 `cpu` 和 `memory`，缺少 `docker`

执行：

- 调用 `ToolSpec.model_validate(...)`。

期望输出：

- 抛出 `ValueError`。
- 错误消息包含 `must define runtime.docker`。

覆盖点：

- Tool Catalog 条目必须显式声明容器镜像。
- 编译链路不能猜测或补全 runtime docker。

### `test_resolver_rejects_tool_not_allowed_for_recipe_step`

输入：

- 复制 `sample_rnaseq_tool_plan()`。
- 将第一个 tool call 的 `qc` 步骤工具从 `fastp` 改为 `salmon`，版本改为 `1.9.0`。

执行：

- 调用 `resolve_tool_plan(...)`。

期望输出：

- 抛出 `ValueError`。
- 错误消息包含 `not allowed for recipe step 'qc'`。

覆盖点：

- Resolver 必须检查 recipe step 的 `allowed_tools`。

### `test_resolver_rejects_unknown_recipe_step`

输入：

- 复制 `sample_rnaseq_tool_plan()`。
- 将第一个 tool call 的 `step` 改为不存在的 `magic`。

执行：

- 调用 `resolve_tool_plan(...)`。

期望输出：

- 抛出 `ValueError`。
- 错误消息包含 `references unknown recipe step 'magic'`。

覆盖点：

- Resolver 拒绝 plan 引用 recipe 未定义步骤。

### `test_resolver_rejects_missing_required_recipe_step`

输入：

- 复制 `sample_rnaseq_tool_plan()`。
- 删除 `step == "differential_expression"` 的 tool call。

执行：

- 调用 `resolve_tool_plan(...)`。

期望输出：

- 抛出 `ValueError`。
- 错误消息包含 `missing required recipe step(s): differential_expression`。

覆盖点：

- Recipe 中非 optional step 必须出现在 plan 中。

### `test_resolver_rejects_duplicate_recipe_step`

输入：

- 复制 `sample_rnaseq_tool_plan()`。
- 复制第一个 `qc` tool call，改 call id 为 `qc_again` 后追加到 `tool_calls`。

执行：

- 调用 `resolve_tool_plan(...)`。

期望输出：

- 抛出 `ValueError`。
- 错误消息包含 `duplicate tool calls for recipe step(s): qc`。

覆盖点：

- 当前 resolver 不允许同一个 recipe step 出现多个 tool call。

### `test_resolver_rejects_missing_required_workflow_input`

输入：

- 复制 `sample_rnaseq_tool_plan()`。
- 删除 workflow input `sample_groups`。

执行：

- 调用 `resolve_tool_plan(...)`。

期望输出：

- 抛出 `ValueError`。
- 错误消息包含 `missing required workflow input 'sample_groups'`。

覆盖点：

- Plan 必须提供 recipe 声明的 required input。

### `test_resolver_rejects_required_workflow_input_type_mismatch`

输入：

- 复制 `sample_rnaseq_tool_plan()`。
- 将 workflow input `sample_groups` 类型从 `File` 改为 `String`。

执行：

- 调用 `resolve_tool_plan(...)`。

期望输出：

- 抛出 `ValueError`。
- 错误消息包含 `workflow input 'sample_groups' expects File but received String`。

覆盖点：

- Required input 类型必须与 recipe 定义兼容。

### `test_resolver_rejects_unknown_param`

输入：

- 复制 `sample_rnaseq_tool_plan()`。
- 在第一个 `qc` tool call 的 `params` 中添加 `magic: 1`。

执行：

- 调用 `resolve_tool_plan(...)`。

期望输出：

- 抛出 `ValueError`。
- 错误消息包含 `unknown param 'magic'`。

覆盖点：

- Tool call params 必须来自 Tool Catalog 声明。

### `test_multiqc_report_files_can_be_auto_collected_from_output_tags`

输入：

- 复制 `sample_rnaseq_tool_plan()`。
- 将最后一个 `report` tool call 的 `inputs` 改为空字典。

执行：

1. 调用 `resolve_tool_plan(...)`。
2. 调用 `analyze_workflow_ir(...)`。
3. 调用 `render_wdl(...)`。

期望输出：

- Analyzer 返回 `is_valid=True`。
- 最后一个 workflow call 的 `report_files` 自动填为：

```json
["qc.html_report", "qc.json_report", "quantify.log_file"]
```

- WDL 中包含：

```wdl
report_files = flatten([qc.html_report, qc.json_report, quantify.log_file])
```

覆盖点：

- Catalog output tags 可以驱动 MultiQC 输入自动收集。

## `tests/test_catalog_retriever.py`

该文件验证第一版 Approved Catalog Retriever。Retriever 只在本地已批准
Recipe / Tool Catalog 中做确定性词法召回，不访问网络、不引入 embedding
服务，也不承担正式 Catalog 准入职责。

### `test_retrieves_rnaseq_recipe_and_key_tools`

输入：

- 自然语言 query：包含 bulk RNA-seq differential expression、FASTQ QC、
  adapter trimming、transcript quantification、Salmon aggregation、
  transcript-to-gene counts、DESeq2 DEG 和 workflow summary report。
- 当前正式 Recipe Catalog。
- 当前正式 Tool Catalog。

执行：

- 调用 `retrieve_catalog_context(..., top_k_recipes=3, top_k_tools=8)`。

期望输出：

- `strategy == "lexical_v1"`。
- `fallback_used == False`。
- top recipe 为 `rnaseq_differential_expression`。
- tool 召回结果包含 `fastp`、`salmon`、`tximport`、`deseq2` 和 `multiqc`。
- recipe/tool 结果包含非零 `score`、`matched_terms`、`matched_fields` 和 `reason`。
- tool 结果包含 `trust_status == "catalog-approved"`。

覆盖点：

- R1 retriever 可以从正式 catalog 中召回 RNA-seq DEG 所需 recipe 和关键工具。
- 输出契约使用稳定 JSON key，便于后续 Planner、API、SSE 和前端复用。

### `test_tokenizer_supports_rnaseq_variants_and_cjk_ngrams`

输入：

- 文本：`做差异表达 RNAseq`。

执行：

- 调用 `tokenize_for_retrieval(...)`。

期望输出：

- token 包含 `rna`、`seq` 和 `rnaseq`。
- CJK token 包含单字 token 和重叠 2-gram，例如 `差`、`差异` 和 `表达`。

覆盖点：

- tokenization 在零新增依赖前提下支持常见 RNA-seq 写法和中文 query。

### `test_no_match_fallback_records_reason_and_approved_tools`

输入：

- 无匹配 query：`zzzz qqqq`。
- 当前正式 Recipe Catalog。
- 当前正式 Tool Catalog。

执行：

- 调用 `retrieve_catalog_context(..., top_k_recipes=2, top_k_tools=3)`。

期望输出：

- `fallback_used == True`。
- `fallback_reason` 说明 recipe 和 tool recall 均无匹配。
- fallback recipe/tool 结果的 `score == 0.0`，`matched_terms == []`。
- fallback tool 仍包含 `trust_status == "catalog-approved"`。

覆盖点：

- 低置信度召回不会静默返回空结果，会记录可审计 fallback 原因。
- fallback 结果仍限定在 approved local catalog 内。

### `test_rejects_empty_query`

输入：

- 空白 query：`"  "`。

执行：

- 调用 `retrieve_catalog_context(...)`。

期望输出：

- 抛出 `ValueError`。
- 错误消息包含 `query must not be empty`。

覆盖点：

- Retriever 在进入 scoring 前拒绝不可分析的空 query。

## `tests/test_catalog_service.py`

该文件验证 W0 catalog 查询服务。服务层返回 JSON-ready 的 recipe/tool 记录，供 FastAPI 的 catalog 查询端点复用。

### `test_list_recipes_returns_json_ready_recipe_records`

输入：

- 当前正式 Recipe Catalog。
- 当前正式 Tool Catalog。

执行：

- 调用 `list_recipes()`。

期望输出：

- 返回至少一个 recipe。
- 第一个 recipe 的 `id` 为 `rnaseq_differential_expression`。
- 记录包含 `required_inputs` 和 `steps`。
- 第一个 step 的 `id` 为 `qc`。
- 第一个 step 的 `allowed_tools` 包含 `fastp`。

覆盖点：

- Catalog service 能返回 API 友好的 recipe 列表。
- Recipe step 与 allowed tools 信息可直接供前端或 API 响应使用。

### `test_get_recipe_returns_named_recipe`

输入：

- recipe id：`rnaseq_differential_expression`。

执行：

- 调用 `get_recipe("rnaseq_differential_expression")`。

期望输出：

- recipe `name` 为 `RNA-seq differential expression`。
- `required_inputs["sample_ids"]["type"] == "Array[String]"`。
- 第一个 step 的 scatter metadata 中 `id == "per_sample"`。

覆盖点：

- Catalog service 能查询单个 recipe。
- scatter metadata 被保留为 JSON-ready dict，便于后续 DAG/API 展示。

### `test_list_tools_returns_json_ready_tool_records`

输入：

- 当前正式 Tool Catalog。

执行：

- 调用 `list_tools()`。

期望输出：

- 返回至少 5 个 tool 记录。
- `fastp` 记录中：
  - `version == "1.3.3"`
  - `runtime["docker"] == "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0"`
  - `trust_status == "catalog-approved"`
  - `outputs` 包含 `clean_r1`

覆盖点：

- Tool runtime docker 从 Catalog 权威来源读取。
- API-facing tool 记录包含 container trust status。

### `test_get_tool_returns_explicit_version`

输入：

- tool id：`salmon`
- version：`1.9.0`

执行：

- 调用 `get_tool("salmon", "1.9.0")`。

期望输出：

- 返回 tool `id == "salmon"`。
- 返回 tool `version == "1.9.0"`。
- `inputs["r1"]["type"] == "File"`。
- `versions` 包含 `1.9.0`。

覆盖点：

- Catalog service 支持按 tool id 和 version 精确查询。

### `test_get_tool_defaults_to_highest_catalog_version`

输入：

- tool id：`multiqc`
- 不指定 version。

执行：

- 调用 `get_tool("multiqc")`。

期望输出：

- 返回 tool `id == "multiqc"`。
- 返回 tool `version == "1.21"`。

覆盖点：

- 未指定版本时，Catalog service 选择当前 catalog 中最高版本。

### `test_unknown_recipe_and_tool_raise_key_error`

输入：

- recipe id：`missing_recipe`
- tool id：`missing_tool`

执行：

1. 调用 `get_recipe("missing_recipe")`。
2. 调用 `get_tool("missing_tool")`。

期望输出：

- 未知 recipe 抛出 `KeyError`，错误消息包含 `unknown recipe`。
- 未知 tool 抛出 `KeyError`，错误消息包含 `unknown tool`。

覆盖点：

- API 层后续可以将未知 catalog 资源稳定映射为 404。

## `tests/test_reviewer_repair.py`

该文件验证 P2 Reviewer IR 修复闭环的第一批契约模型和 patch policy skeleton。
它不调用真实 LLM provider，也不接入 Compiler Graph 路由；只固定 request、patch、
result 和 policy 边界。

### `test_reviewer_repair_request_accepts_workflow_ir_and_minimal_catalog_context`

输入：

- 一个最小 Workflow IR。
- failure stage：`analyzer`。
- Analyzer diagnostic：`call 'qc' is missing input 'r2'`。
- 当前 workflow 已使用的 approved recipe/tool metadata。

执行：

- 构造 `ReviewerRepairRequest`。

期望输出：

- request 保留 `failure_stage == analyzer`。
- `workflow_ir` 被校验为 Workflow IR model。
- catalog context 只包含当前 workflow 的 approved tool metadata。
- constraints 默认包含允许的 patch operation。

覆盖点：

- Reviewer 请求使用结构化数据，而不是在节点之间传递自由 prompt 文本。
- P2 初版只向 Reviewer 暴露当前 workflow 已使用的 approved catalog metadata。

### `test_reviewer_patch_model_rejects_invalid_shape`

输入：

- operation 为 `rewrite`。
- path 不是绝对 JSON pointer。
- confidence 为 `1.5`。

执行：

- 构造 `ReviewerIRPatch`。

期望输出：

- 抛出 `ValidationError`。

覆盖点：

- Reviewer patch 必须先通过 schema validation。

### `test_policy_accepts_allowed_workflow_ir_patch`

输入：

- 一个给 `/workflow/steps/0/inputs/r2` 增加 wiring 的 patch。
- catalog reference：`fastp:1.3.3`。
- 当前 workflow approved catalog context。

执行：

- 调用 `validate_reviewer_patch_policy(...)`。

期望输出：

- policy validation 返回原 patch。

覆盖点：

- P2 policy 允许 Reviewer 在 Workflow IR 内修复 call input wiring。
- catalog reference 必须来自当前 workflow approved context。

### `test_policy_rejects_wdl_catalog_runtime_and_resource_edits`

输入：

- 分别尝试 patch：
  - `/current_wdl`
  - `/catalog/tools/fastp`
  - `/workflow/steps`
  - `/workflow/calls`
  - `/workflow/steps/0/task`
  - `/tasks/fastp/command`
  - `/tasks/fastp/runtime/docker`
  - `/tasks/fastp/runtime/cpu`

执行：

- 调用 `validate_reviewer_patch_policy(...)`。

期望输出：

- 每个 patch 都抛出 `ReviewerPatchPolicyError`。

覆盖点：

- Reviewer 不能修改最终 WDL、Catalog、command template、runtime image 或 resource
  sizing fields。
- Reviewer 不能替换整个 workflow step/call 集合，也不能修改 call 的 task 选择。

### `test_policy_rejects_catalog_references_outside_current_workflow_context`

输入：

- patch 本身只改 `/workflow/outputs/clean_r1`。
- `catalog_references` 包含当前 workflow context 外的 `star:2.7.11b`。

执行：

- 调用 `validate_reviewer_patch_policy(...)`。

期望输出：

- 抛出 `ReviewerPatchPolicyError`。

覆盖点：

- Reviewer 不能借由 catalog references 引入未传入的候选工具上下文。

### `test_policy_rejects_catalog_references_without_context`

输入：

- 一个合法的 call input wiring patch。
- `catalog_references` 包含 `fastp:1.3.3`。
- 不传 `catalog_context`。

执行：

- 调用 `validate_reviewer_patch_policy(...)`。

期望输出：

- 抛出 `ReviewerPatchPolicyError`。

覆盖点：

- patch 引用 catalog metadata 时必须同时提供当前 workflow 的 approved context；
  不能因为调用方漏传 context 而跳过 membership 校验。

### `test_policy_allows_move_only_for_workflow_step_or_call_items`

输入：

- 一个 `move` patch：
  - `from_path = /workflow/steps/1`
  - `path = /workflow/steps/0`

执行：

- 调用 `validate_reviewer_patch_policy(...)`。

期望输出：

- policy validation 返回原 patch。

覆盖点：

- P2 policy 允许 Reviewer 通过 list-item pointer 调整 step/call ordering。
- 该权限不扩展到整体替换 `workflow.steps` 或修改 step 内部 task 选择。

### `test_policy_rejects_move_outside_workflow_step_or_call_items`

输入：

- 分别尝试 `move`：
  - `/workflow/outputs/clean_r1`
  - `/workflow/steps/0/inputs/r2`
  - `/tasks/fastp/outputs/clean_r1/value`

执行：

- 调用 `validate_reviewer_patch_policy(...)`。

期望输出：

- 每个 patch 都抛出 `ReviewerPatchPolicyError`。

覆盖点：

- `move` 只服务于 `/workflow/steps/<index>` 或 `/workflow/calls/<index>` 的排序修复。
- Reviewer 不能用 `move` 修改 workflow output、call input wiring 或 task output literal。

### `test_repair_result_requires_parsed_patch_or_rejection_reason`

输入：

- `patch_proposed` result。
- 缺失 patch 的 `patch_proposed` result。
- 缺失 `rejection_reason` 的 `policy_rejected` result。

执行：

- 构造 `ReviewerRepairResult`。

期望输出：

- 合法 `patch_proposed` 保留 parsed patch。
- 缺失 patch 或 rejection reason 的结果抛出 `ValidationError`。

覆盖点：

- P2 只持久化 parsed patch 与 rejection reason，不把 raw Reviewer output 作为默认
  artifact。

## `tests/test_graph.py`

该文件验证 Compiler Graph、Analyzer、Renderer 和 deterministic repairer 的交互。

### `test_multi_task_ir_analyzes_and_renders`

输入：

- `sample_multi_task_ir()`。

执行：

1. 调用 `coerce_workflow_ir(...)` 将 dict 转为标准 Workflow IR。
2. 调用 `analyze_workflow_ir(...)`。
3. 调用 `render_wdl(...)`。

期望输出：

- Analyzer 返回 `is_valid=True`。
- WDL 中包含：
  - `workflow RNASeqPipeline`
  - `call fastp as qc`
  - `call bwa_mem as align`
  - `r1 = qc.clean_r1`
  - `File bam = align.bam`
  - `task fastp`
  - `task bwa_mem`

覆盖点：

- 基础多 call IR 可以通过分析并渲染为 WDL。

### `test_analyzer_rejects_forward_output_reference`

输入：

- `sample_multi_task_ir()`。
- 将 `workflow.calls` 顺序反转，使 `align` 在 `qc` 之前出现。

执行：

- 调用 `coerce_workflow_ir(...)` 和 `analyze_workflow_ir(...)`。

期望输出：

- Analyzer 返回 `is_valid=False`。
- errors 中包含 `references unavailable output 'qc.clean_r1'`。

覆盖点：

- Analyzer 拒绝前向引用。

### `test_agent_alias_points_to_compiler_graph`

输入：

- 从 `src.graph` 导入 `agent` 和 `compiler_graph`。

执行：

- 比较两个导出对象是否为同一个 compiled graph。

期望输出：

- `agent is compiler_graph`。

覆盖点：

- `compiler_graph` 是结构化编译图的明确导出名。
- 旧的 `agent` 导出仍作为兼容别名可用。

### `test_compiler_graph_repairs_forward_output_reference_order`

输入：

- `sample_multi_task_ir()`。
- 将 `workflow.calls` 顺序反转。
- 通过 `initial_state(...)` 构造 LangGraph state。

执行：

- 调用 `compiler_graph.invoke(...)`。

期望输出：

- final state 中 `is_valid=True`。
- 修复后的 `workflow_ir.workflow.calls` 顺序为 `["qc", "align"]`。
- `repair_actions` 非空。

覆盖点：

- Deterministic repairer 能修复可由依赖关系确定的 call 顺序问题。

### `test_analyzer_allows_omitted_optional_call_inputs`

输入：

- `sample_multi_task_ir()`。
- 将 task `fastp` 的 input `r2` 类型改为 `File?`。
- 删除 call `qc` 中的 input `r2`。

执行：

- 调用 `coerce_workflow_ir(...)` 和 `analyze_workflow_ir(...)`。

期望输出：

- Analyzer 返回 `is_valid=True`。

覆盖点：

- Optional task input 可以在 call 中省略。

### `test_explicit_scatter_steps_analyze_and_render`

输入：

- 直接构造 Workflow IR：
  - workflow 名称：`ScatterQC`
  - input：`raw_fastqs: Array[File]`
  - steps：一个 `scatter`，item 为 `i`，over 为 `range(length(raw_fastqs))`
  - scatter body 中 call `qc` 调用 task `fastp_single`，输入 `fastq = raw_fastqs[i]`
  - workflow output：`clean_fastqs = qc.clean_fastq`
  - task `fastp_single` 输出 `clean_fastq: File`

执行：

1. 调用 `coerce_workflow_ir(...)`。
2. 调用 `analyze_workflow_ir(...)`。
3. 调用 `render_wdl(...)`。

期望输出：

- Analyzer 返回 `is_valid=True`。
- WDL 中包含：
  - `scatter (i in range(length(raw_fastqs)))`
  - `fastq = raw_fastqs[i]`
  - `Array[File] clean_fastqs = qc.clean_fastq`

覆盖点：

- Analyzer 和 Renderer 支持显式 `workflow.steps` scatter。
- scatter 内部 File output 在外部提升为 `Array[File]`。

### `test_array_call_inputs_can_collect_scatter_outputs`

输入：

- 直接构造 Workflow IR：
  - workflow 名称：`ScatterReport`
  - inputs：`raw_fastqs: Array[File]`、`extra_report: File`
  - 第一步 scatter 调用 `qc_task`，产生 `qc.html_report` 和 `qc.json_report`
  - 第二步普通 call `report` 调用 `report_task`
  - `report.files` 输入为数组：`["qc.html_report", "qc.json_report", "extra_report"]`

执行：

1. 调用 `coerce_workflow_ir(...)`。
2. 调用 `analyze_workflow_ir(...)`。
3. 调用 `render_wdl(...)`。

期望输出：

- Analyzer 返回 `is_valid=True`。
- WDL 中包含：

```wdl
files = flatten([qc.html_report, qc.json_report, [extra_report]])
```

覆盖点：

- Renderer 能将 scatter 产生的 `Array[File]` 与普通 `File` 混合收集为 `Array[File]`。

### `test_legacy_json_is_normalized_to_ir`

输入：

- Legacy JSON：
  - `workflow_name: SimpleQC`
  - `inputs.raw_fastq: File`
  - `tasks` 列表中一个 task `fastp_qc`
  - task runtime docker 为 `quay.io/biocontainers/fastp:1.3.3--h43da1c4_0`

执行：

- 调用 `coerce_workflow_ir(...)`。

期望输出：

- 标准 IR workflow 名称为 `SimpleQC`。
- `workflow.calls[0].id == "fastp_qc"`。
- `workflow_ir.tasks["fastp_qc"].runtime.docker == "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0"`。

覆盖点：

- 旧格式 JSON 可以兼容转换为 Workflow IR。

### `test_compiler_graph_repairs_bare_file_output_literals`

输入：

- `sample_multi_task_ir()`。
- 将 `fastp` task outputs 中 `clean_r1/clean_r2` 的 value 从带引号的 WDL 字面量改成裸字符串：
  - `clean_R1.fq.gz`
  - `clean_R2.fq.gz`

执行：

- 调用 `compiler_graph.invoke(...)`。

期望输出：

- final state 中 `is_valid=True`。
- `current_wdl` 中包含：
  - `File clean_r1 = "clean_R1.fq.gz"`
  - `File clean_r2 = "clean_R2.fq.gz"`
- `repair_actions` 非空。

覆盖点：

- Deterministic repairer 能修复 File/String output 字面量缺少引号的问题。

### `test_compiler_graph_stops_when_repairer_has_no_safe_action`

输入：

- `sample_multi_task_ir()`。
- 将第一个 call `qc` 的 input `r1` 改为未知表达式 `missing_input`。

执行：

- 调用 `compiler_graph.invoke(...)`。

期望输出：

- final state 中 `is_valid=False`。
- `analysis_errors` 包含 `references unknown value 'missing_input'`。
- `repair_actions == []`。

覆盖点：

- Repairer 对无法安全推断的问题不做自由修复。

### `test_compiler_graph_compiles_recipe_tool_plan`

输入：

- `sample_rnaseq_tool_plan()`。

执行：

- 调用 `compiler_graph.invoke(...)`。

期望输出：

- final state 中 `is_valid=True`。
- `analysis_errors == []`。
- `workflow_ir.workflow.steps[0].kind == "scatter"`。
- `current_wdl` 中包含：
  - `scatter (i in range(length(sample_ids)))`
  - `call fastp_qc as qc`
  - `call salmon_quantify as quantify`
  - `call tximport_summarize as summarize`
  - `call deseq2_deg as deg`
  - `call multiqc_report as report`
  - `Array[File] quant_files`
  - `report_files = flatten([qc.html_report, qc.json_report, quantify.log_file])`
  - `File deg_table = deg.deg_table`
  - `File multiqc_report = report.multiqc_report`

覆盖点：

- Compiler Graph 可以直接接收 Recipe Tool Plan 并完成 normalizer -> analyzer -> renderer -> checker 流程。

## `tests/test_orchestration_state.py`

该文件验证 P1 Orchestration State 初版。该状态用于后续自然语言上层图，
与下层 Compiler Graph 的 `WorkflowState` 分离。

### `test_initial_orchestration_state_records_request_and_planner_options`

输入：

- 自然语言请求：`Run bulk RNA-seq differential expression.`
- `planner_model = DEFAULT_PLANNER_MODEL`
- `check=False`

执行：

- 调用 `build_initial_orchestration_state(...)`。

期望输出：

- state 保存原始 `request`、`planner_model` 和 `check`。
- `plan`、`planner_prompt`、`planner_raw_response`、`compiler_result` 初始为 `None`。
- `errors` 和 `events` 初始为空列表。

覆盖点：

- 自然语言 Planner trace 和下层 compiler result 有独立承载字段。

### `test_initial_orchestration_state_uses_independent_mutable_lists`

输入：

- 分别构造两个 Orchestration State。

执行：

- 向第一个 state 的 `errors` 和 `events` 追加内容。

期望输出：

- 第二个 state 的 `errors` 和 `events` 仍为空。

覆盖点：

- 初始状态不会共享可变列表。

### `test_orchestration_state_does_not_pollute_compiler_workflow_state`

输入：

- 调用 `build_initial_state({})` 构造 Compiler Graph 的 `WorkflowState`。

执行：

- 检查 orchestration-only 字段是否存在于 `WorkflowState`。

期望输出：

- `request`、`planner_model`、`plan`、`planner_prompt`、`compiler_result` 等上层字段均不在 `WorkflowState` 中。

覆盖点：

- Orchestration State 与 Compiler Graph `WorkflowState` 保持分层。

### `test_orchestration_failure_stage_distinguishes_top_level_errors`

输入：

- 初始 Orchestration State。
- 向 `errors` 添加 Planner JSON 解析失败信息。

执行：

- 调用 `orchestration_succeeded(...)`。
- 调用 `orchestration_failure_stage(...)`。

期望输出：

- `orchestration_succeeded(...) == False`。
- `orchestration_failure_stage(...) == "orchestration"`。

覆盖点：

- 上层 Planner / orchestration 错误可与下层 compiler 错误区分。

### `test_orchestration_failure_stage_treats_missing_compiler_result_as_orchestration`

输入：

- 初始 Orchestration State。
- 不设置 `compiler_result`。

执行：

- 调用 `orchestration_succeeded(...)`。
- 调用 `orchestration_failure_stage(...)`。

期望输出：

- `orchestration_succeeded(...) == False`。
- `orchestration_failure_stage(...) == "orchestration"`。

覆盖点：

- 未委派到 Compiler Graph 或缺失 compiler result 的终态不会被误判为成功。
- `orchestration_failure_stage(...)` 只在成功时返回 `None`。

### `test_orchestration_failure_stage_distinguishes_compiler_failure`

输入：

- 初始 Orchestration State。
- 设置 `compiler_result` 为 `succeeded=False` 的 `WorkflowCompilationResult`。

执行：

- 调用 `orchestration_succeeded(...)`。
- 调用 `orchestration_failure_stage(...)`。

期望输出：

- `orchestration_succeeded(...) == False`。
- `orchestration_failure_stage(...) == "compiler"`。

覆盖点：

- 下层 Compiler Graph 失败保留为 compiler failure，而不是混入上层错误。

### `test_orchestration_succeeded_requires_successful_compiler_result`

输入：

- 初始 Orchestration State。
- 设置 `compiler_result` 为 `succeeded=True` 的 `WorkflowCompilationResult`。

执行：

- 调用 `orchestration_succeeded(...)`。
- 调用 `orchestration_failure_stage(...)`。

期望输出：

- `orchestration_succeeded(...) == True`。
- `orchestration_failure_stage(...) is None`。

覆盖点：

- P1 上层 run 的成功语义要求 orchestration 和 delegated compiler 都成功。

## `tests/test_orchestration_planner_node.py`

该文件验证 P1 Planner Node 初版。Planner Node 负责把自然语言请求转换为
Recipe Tool Plan，并记录 planner prompt / raw response 等 trace；它不运行
Compiler Graph，也不产出 Workflow IR 或 WDL。

### `test_planner_node_returns_plan_trace_and_events`

输入：

- 自然语言请求：`Run RNA-seq differential expression.`
- `FakePlannerLlm` 返回有效 RNA-seq Recipe Tool Plan JSON。

执行：

- 调用 `make_natural_language_planner_node(llm=fake_llm)(state)`。

期望输出：

- update 中包含 Recipe Tool Plan。
- `planner_prompt` 包含 `Catalog:`。
- `planner_raw_response` 包含 `RNASeqDEG`。
- `errors == []`。
- update 不包含 `compiler_result`、`workflow_ir` 或 `wdl`。
- events 顺序为 `node.started`、`node.completed`、`artifact.updated`。
- artifact event payload 为 `{"artifact": "plan"}`。

覆盖点：

- Planner Node 只产出 Recipe Tool Plan 和 planner trace。
- Planner Node 成功事件可被后续 run history 或 SSE 层复用。

### `test_default_planner_node_uses_same_node_contract`

输入：

- 默认 `natural_language_planner_node`。

执行：

- 检查该对象是否可调用。

期望输出：

- 默认 Planner Node 是可注册到 LangGraph 的 callable。

覆盖点：

- 后续 Orchestration Graph 可以直接注册默认 planner node。

### `test_planner_node_records_json_failure_without_secret_payloads`

输入：

- `FakePlannerLlm` 返回非 JSON 文本。

执行：

- 调用 Planner Node。

期望输出：

- `errors` 包含 JSON 解析失败信息。
- `plan`、`planner_prompt`、`planner_raw_response` 均为 `None`。
- events 顺序为 `node.started`、`node.failed`。
- failure payload 的 `error_type == "PlannerJsonError"`。
- failure payload 不包含 `api_key` 或 `authorization`。

覆盖点：

- Planner JSON 失败保留结构化错误分类。
- 失败事件不记录鉴权敏感信息。

### `test_planner_node_records_unexpected_failure`

输入：

- 注入的 Planner LLM 抛出 `RuntimeError("planner transport unavailable")`。

执行：

- 调用 Planner Node。

期望输出：

- `errors` 包含原始异常消息。
- `plan`、`planner_prompt`、`planner_raw_response` 均为 `None`。
- events 顺序为 `node.started`、`node.failed`。
- failure payload 的 `error_type == "RuntimeError"`。

覆盖点：

- 非 `NaturalLanguagePlanningError` 的意外异常也会被 Planner Node 转换为结构化失败。
- 上层 Orchestration Graph 可以继续聚合 `errors` / `events`，不会被异常直接打断。

### `test_planner_node_preserves_schema_error_classification`

输入：

- `FakePlannerLlm` 返回缺少 `tool_calls` 的 plan JSON。

执行：

- 调用 Planner Node。

期望输出：

- `errors` 包含 `plan schema validation failed`。
- failure event payload 的 `error_type == "PlannerSchemaError"`。

覆盖点：

- Planner schema 错误不会被吞成泛化错误。

### `test_planner_node_preserves_catalog_error_classification`

输入：

- `FakePlannerLlm` 返回缺少 differential expression step 的 RNA-seq plan。

执行：

- 调用 Planner Node。

期望输出：

- `errors` 包含 `recipe/catalog validation failed`。
- failure event payload 的 `error_type == "PlannerCatalogError"`。

覆盖点：

- Planner catalog/resolver 错误可被上层 graph 识别为 planner-stage 失败。

## `tests/test_orchestration_graph.py`

该文件验证 P1 Orchestration Graph 外壳。该图只负责编排 Planner Node
和下层 Compiler Graph delegate，不引入 Reviewer、Retriever 或其他 P2+
Agent 占位逻辑。

### `test_default_orchestration_graph_is_invokable`

输入：

- 默认 `orchestration_graph`。

执行：

- 检查默认图是否暴露 `invoke` callable。

期望输出：

- 默认 Orchestration Graph 可被 LangGraph 运行。

覆盖点：

- P1.4 默认图已完成编译，可作为自然语言入口的上层图外壳。

### `test_orchestration_graph_runs_planner_then_compiler`

输入：

- fake planner node 返回 Recipe Tool Plan 和 planner trace。
- 注入的 compiler delegate 返回成功 `WorkflowCompilationResult`。
- `check=False`。

执行：

- 调用注入节点后的 Orchestration Graph。

期望输出：

- compiler delegate 只被调用一次。
- delegate 收到 planner 产出的 plan 和 `check=False`。
- final state 保留 `plan`、`planner_prompt` 和 `compiler_result`。
- `orchestration_succeeded(...) == True`。
- events 顺序为 Planner started/completed/artifact.updated，随后 Compiler Graph started/completed。

覆盖点：

- 上层图按 `natural_language_planner -> compiler_graph` 顺序运行。
- `check` 开关能从 Orchestration State 传给下层 Compiler Graph。

### `test_orchestration_graph_stops_after_planner_failure`

输入：

- fake planner node 返回 planner 错误和 `node.failed` event。
- compiler node 若被调用会抛出断言错误。

执行：

- 调用注入节点后的 Orchestration Graph。

期望输出：

- `compiler_result is None`。
- `errors` 保留 planner 错误。
- `orchestration_failure_stage(...) == "orchestration"`。
- events 中只有 planner 事件。

覆盖点：

- Planner 失败时条件路由直接结束，不进入 Compiler Graph。

### `test_orchestration_graph_preserves_compiler_failure_diagnostics`

输入：

- fake planner node 返回 Recipe Tool Plan。
- 注入的 compiler delegate 返回 `succeeded=False` 和 Analyzer 诊断。

执行：

- 调用注入节点后的 Orchestration Graph。

期望输出：

- 上层 `errors == []`。
- `orchestration_failure_stage(...) == "compiler"`。
- `compiler_result.analysis_errors` 保留下层诊断。
- 最后一个 event 是 `compiler_graph` 的 `node.failed`。

覆盖点：

- Compiler Graph 失败不由上层图修复，也不混入 Planner/orchestration 错误。
- 下层 Analyzer/Checker diagnostics 仍通过 `WorkflowCompilationResult` 返回。

## `tests/test_workflow_service.py`

该文件验证 W0 workflow application service。服务层用于让 CLI 和未来 FastAPI 复用同一套编译入口，避免 API 层复制 `main.py` 中的业务逻辑。

### `test_compile_structured_workflow_compiles_recipe_plan_without_check`

输入：

- `examples/rnaseq_deg_recipe_plan.json`
- `check=False`

执行：

- 调用 `compile_structured_workflow(plan, check=False)`。

期望输出：

- `result.succeeded == True`。
- `result.plan is plan`。
- `result.workflow_ir["workflow"]["name"] == "RNASeqDEG"`。
- `result.wdl` 包含 `workflow RNASeqDEG`。
- `result.validation_message == "WDL syntax validation skipped (--no-check)."`。
- `result.check_performed == False`。

覆盖点：

- 结构化 Recipe Tool Plan 可以通过 service 入口完成 IR 标准化、分析和 WDL 渲染。
- 跳过 checker 时仍返回稳定的成功状态和 validation message。

### `test_compile_structured_workflow_compiles_workflow_ir_without_plan`

输入：

- `examples/rnaseq_workflow_ir.json`
- `check=False`

执行：

- 调用 `compile_structured_workflow(workflow_ir, check=False)`。

期望输出：

- `result.succeeded == True`。
- `result.plan is None`。
- `result.workflow_ir["workflow"]["name"] == "RNASeqPipeline"`。
- `result.wdl` 包含 `workflow RNASeqPipeline`。

覆盖点：

- 结构化 Workflow IR 入口不会触发自然语言 planner。
- service 能区分 Recipe Tool Plan 与标准 Workflow IR。

### `test_compile_structured_workflow_without_check_does_not_invoke_graph`

输入：

- `examples/rnaseq_deg_recipe_plan.json`
- `check=False`
- mock `src.services.workflow_service.compiler_graph.invoke`，如果被调用则抛出错误。

执行：

- 调用 `compile_structured_workflow(plan, check=False)`。

期望输出：

- `result.succeeded == True`。
- `result.check_performed == False`。
- compiled graph 的 `compiler_graph.invoke` 未被调用。

覆盖点：

- `check=False` 路径走手动 deterministic compiler nodes。
- 跳过 checker 时不会进入包含 checker 的 compiled graph。

### `test_compile_structured_workflow_returns_diagnostics_for_invalid_plan`

输入：

- 复制 `examples/rnaseq_deg_recipe_plan.json`。
- 删除 workflow input `sample_groups`。
- `check=False`

执行：

- 调用 `compile_structured_workflow(plan, check=False)`。

期望输出：

- `result.succeeded == False`。
- `result.wdl == ""`。
- `result.analysis_errors` 包含 `missing required workflow input 'sample_groups'`。

覆盖点：

- service 不吞掉 resolver/catalog 诊断。
- 无效 plan 不会产生 WDL。

### `test_plan_and_compile_workflow_plans_then_compiles`

输入：

- 用户请求：`Run bulk RNA-seq differential expression.`
- `FakePlannerLlm` 返回 RNA-seq Recipe Tool Plan JSON。
- `check=False`

执行：

- 调用 `plan_and_compile_workflow(..., llm=fake_llm, check=False)`。

期望输出：

- `result.succeeded == True`。
- `result.plan` 等于 mock LLM 返回的 plan。
- `result.catalog_retrieval.strategy == "lexical_v1"`。
- `result.planner_prompt` 包含 `Catalog:`。
- `result.planner_raw_response` 包含 `RNASeqDEG`。
- `result.wdl` 包含 `workflow RNASeqDEG`。
- fake LLM 只被调用一次。

覆盖点：

- 自然语言入口通过 Orchestration Graph 先生成 Recipe Tool Plan，再进入确定性编译链路。
- LLM 仍不直接生成最终 WDL。
- planner observability 信息和 raw catalog retrieval artifact 被 service 结果保留。

### `test_plan_and_compile_workflow_event_callback_covers_planner_and_compiler`

输入：

- 用户请求：`Run bulk RNA-seq differential expression.`
- `FakePlannerLlm` 返回 RNA-seq Recipe Tool Plan JSON。
- `check=False`
- 注入 `event_callback` 收集 service 事件。

执行：

- 调用 `plan_and_compile_workflow(..., event_callback=event_callback)`。

期望输出：

- `result.succeeded == True`。
- 事件以 catalog_retriever started/completed/catalog_retrieval artifact 开始，然后进入 planner started/completed/plan artifact。
- 随后进入上层 `compiler_graph` delegate。
- 事件中包含下层 Compiler Graph 的 `ir_normalizer`、`workflow_ir` artifact、`wdl` artifact 和最终 compiler delegate 完成事件。
- catalog retrieval artifact 事件的 state 中包含 `catalog_retrieval`。
- plan artifact 事件的 state 中包含 planner 生成的 Recipe Tool Plan。

覆盖点：

- 自然语言 service 入口的 event callback 覆盖 Planner、Orchestration Graph delegate 和 Compiler Graph 阶段。
- run service/API 可以不重复编排节点，只通过 workflow service 事件桥接 run history / SSE。

### `test_plan_and_compile_workflow_preserves_planner_error_classification`

输入：

- 用户请求：`Run bulk RNA-seq differential expression.`
- `FakePlannerLlm` 返回非 JSON 文本。
- `check=False`

执行：

- 调用 `plan_and_compile_workflow(..., llm=fake_llm, check=False)`。

期望输出：

- 抛出 `PlannerJsonError`。
- 错误消息包含 `does not contain a JSON object`。

覆盖点：

- 自然语言 service 入口虽然改为通过 Orchestration Graph 执行，但仍保留既有 Planner 错误分类。
- CLI/API 上层不需要为 P1.4 改动适配新的异常类型。

### `test_result_to_dict_exposes_json_ready_service_fields`

输入：

- `examples/rnaseq_deg_recipe_plan.json`
- `check=False`

执行：

1. 调用 `compile_structured_workflow(plan, check=False)`。
2. 调用 `result.to_dict()`。

期望输出：

- dict 中 `plan` 等于输入 plan。
- dict 中 `workflow_ir` 包含 `workflow`。
- dict 中 `wdl` 包含 `workflow RNASeqDEG`。
- dict 中 `analysis_errors == []`。
- dict 中 `succeeded == True`。

覆盖点：

- `WorkflowCompilationResult` 可以转换为 API 友好的 dict。
- API 层后续可以稳定读取 plan、IR、WDL、diagnostics 和状态字段。

## `tests/test_nl_planner.py`

该文件验证自然语言 planner 的 prompt 构建、LLM 响应解析、schema 校验和 catalog 校验。测试使用 `FakePlannerLlm`，不会真实调用外部模型。

### `test_parse_json_object_accepts_fenced_json`

输入：

````text
```json
{"workflow": {"name": "Demo"}}
```
````

执行：

- 调用 `parse_json_object(...)`。

期望输出：

- 返回 dict。
- `parsed["workflow"]["name"] == "Demo"`。

覆盖点：

- Planner 可以解析 Markdown fenced JSON。

### `test_parse_json_object_rejects_non_json`

输入：

```text
I would run fastp first.
```

执行：

- 调用 `parse_json_object(...)`。

期望输出：

- 抛出 `PlannerJsonError`。
- 错误消息包含 `does not contain a JSON object`。

覆盖点：

- Planner 拒绝没有 JSON object 的自然语言响应。

### `test_build_planner_prompt_includes_catalog_and_request`

输入：

- 用户请求：`Run RNA-seq differential expression.`
- 当前 Tool Catalog
- 当前 Recipe Catalog

执行：

- 调用 `build_planner_prompt(...)`。

期望输出：

- prompt 文本包含：
  - `rnaseq_differential_expression`
  - `fastp`
  - `per_sample`
  - `tximport`
  - `Retrieved approved catalog context`
  - `primary recipe/tool candidates`
  - `validation_boundary`
  - `matched_terms`
  - `trust_status`
  - 用户原始请求
- prompt 文本不包含旧的 `Use only tools and versions listed in the retrieved` 硬门禁措辞。

覆盖点：

- Planner prompt 会包含 retriever 筛选后的 approved recipe/tool context、检索解释字段、完整 Catalog 校验边界说明和用户请求。
- Planner prompt 仍保留生成合法 Recipe Tool Plan 所需的 recipe steps、scatter metadata 和 tool schema。
- Retriever 结果作为 Planner 的首选候选上下文，不被表述为最终准入门禁。

### `test_plan_from_natural_language_validates_llm_plan`

输入：

- 用户请求：`Run RNA-seq differential expression.`
- `FakePlannerLlm` 返回合法 RNA-seq Recipe Tool Plan JSON。

执行：

- 调用 `plan_from_natural_language(...)`。

期望输出：

- 返回 plan 的 `workflow.recipe == "rnaseq_differential_expression"`。
- fake LLM 收到的 prompt 中包含用户请求。

覆盖点：

- 自然语言 planner 成功路径会解析 LLM JSON、校验 schema、校验 catalog，并返回 plan。

### `test_create_natural_language_plan_returns_observability_details`

输入：

- 用户请求：`Run RNA-seq differential expression.`
- `FakePlannerLlm` 返回合法 RNA-seq Recipe Tool Plan JSON。

执行：

- 调用 `create_natural_language_plan(...)`。

期望输出：

- `result.plan.workflow.recipe == "rnaseq_differential_expression"`。
- `result.planner_prompt` 包含 `Catalog:`。
- `result.catalog_retrieval.strategy == "lexical_v1"`。
- `result.catalog_retrieval.recipes[0].id == "rnaseq_differential_expression"`。
- `result.catalog_retrieval.tools` 包含 `deseq2`。
- `result.raw_response` 包含 `RNASeqDEG`。

覆盖点：

- Planner 返回可观测性信息：结构化 plan、实际 prompt、原始模型响应和 catalog retrieval artifact。
- 自然语言 planner 成功路径会先通过 Approved Catalog Retriever 缩小 prompt context。

### `test_plan_validation_uses_complete_catalog_after_retrieval`

输入：

- 用户请求：`Run RNA-seq differential expression.`
- mock `retrieve_catalog_context(...)` 返回稀疏结果：只包含 RNA-seq recipe 和 `fastp` tool。
- `FakePlannerLlm` 返回完整合法 RNA-seq Recipe Tool Plan JSON，包含 `salmon`、`tximport`、`deseq2` 和 `multiqc`。

执行：

- 调用 `create_natural_language_plan(...)`。

期望输出：

- `result.catalog_retrieval` 等于 mock 的稀疏 retrieval artifact。
- 返回 plan 的 `workflow.recipe == "rnaseq_differential_expression"`。
- `result.planner_prompt` 包含 `validation_boundary`。
- `result.planner_prompt` 包含 `context_source: retriever_match`。
- `result.planner_prompt` 包含 `context_source: retrieved_recipe_allowed_tool`。
- `result.planner_prompt` 包含从 retrieved recipe allowed tools 补齐的 `deseq2` 和 `multiqc` schema。

覆盖点：

- Retriever 缩小的是 Planner prompt context，不是最终准入边界。
- Prompt tool context 会补齐 retrieved recipes 的 allowed tools，避免 Planner 因缺少版本或 schema 被迫猜测。
- `catalog_retrieval` artifact 保留原始 retriever 输出，不混入 prompt-only 补齐工具。
- LLM 输出的 Recipe Tool Plan 仍然使用完整 Recipe / Tool Catalog 做 schema、resolver 和 Analyzer 校验。

### `test_plan_from_natural_language_reports_schema_error`

输入：

- 用户请求：`Run RNA-seq differential expression.`
- `FakePlannerLlm` 返回缺字段 JSON：`{"workflow": {"name": "RNASeqDEG"}}`。

执行：

- 调用 `plan_from_natural_language(...)`。

期望输出：

- 抛出 `PlannerSchemaError`。
- 错误消息包含 `plan schema validation failed`。

覆盖点：

- LLM JSON 能解析但不符合 Recipe Tool Plan schema 时，错误类型明确归类为 schema error。

### `test_plan_from_natural_language_reports_catalog_error`

输入：

- 合法格式的 RNA-seq plan，但删除 required step `differential_expression`。
- `FakePlannerLlm` 返回该 plan JSON。

执行：

- 调用 `plan_from_natural_language(...)`。

期望输出：

- 抛出 `PlannerCatalogError`。
- 错误消息包含 `recipe/catalog validation failed`。

覆盖点：

- LLM plan 通过 JSON/schema 后，还必须通过 recipe/catalog 校验。

### `test_plan_from_natural_language_rejects_unanalyzable_array_concatenation`

输入：

- 复制合法 RNA-seq plan。
- 将 MultiQC `report_files` 从 JSON array 改为字符串表达式：

```text
qc.html_report + qc.json_report
```

- `FakePlannerLlm` 返回该 plan JSON。

执行：

- 调用 `plan_from_natural_language(...)`。

期望输出：

- 抛出 `PlannerCatalogError`。
- 错误消息包含 `references unavailable output`。

覆盖点：

- Planner 不允许 LLM 把不受支持的 WDL/字符串拼接表达式塞进 IR。
- 数组收集必须使用 JSON array。

### `test_build_default_planner_prompt_loads_catalog`

输入：

- 用户请求：`Run RNA-seq differential expression.`

执行：

- 调用 `build_default_planner_prompt(...)`。

期望输出：

- prompt 包含 `rnaseq_differential_expression`。
- prompt 包含用户请求。

覆盖点：

- 默认 prompt builder 能自行加载 Tool Catalog 和 Recipe Catalog。

## `tests/test_cli.py`

该文件验证 `main.py` CLI 层，包括文件读取、自然语言入口、结构化输入入口、stdout/stderr 隔离和失败处理。自然语言相关测试 mock workflow service，不真实调用外部 LLM。

### `test_load_workflow_input_reads_recipe_plan_example`

输入：

- 文件：`examples/rnaseq_deg_recipe_plan.json`

执行：

- 调用 `cli.load_workflow_input(...)`。

期望输出：

- 返回 dict。
- `workflow.name == "RNASeqDEG"`。
- `workflow.recipe == "rnaseq_differential_expression"`。

覆盖点：

- CLI 可以读取示例 Recipe Tool Plan。

### `test_load_prompt_reads_prompt_file`

输入：

- 文件：`examples/rnaseq_deg_request.txt`

执行：

- 调用 `cli.load_prompt(prompt_file=...)`。

期望输出：

- 返回 prompt 文本。
- 文本包含 `bulk RNA-seq differential expression`。

覆盖点：

- CLI 可以从文件读取自然语言请求。

### `test_cli_compiles_natural_language_prompt_with_mock_planner`

输入：

- CLI args：

```text
--prompt "Run bulk RNA-seq differential expression."
--output <tmp>/rnaseq_deg.wdl
--print-plan
--no-check
```

- mock `main.plan_and_compile_workflow` 返回合法 RNA-seq plan 的编译结果。

执行：

- 调用 `cli.main(...)`。

期望输出：

- exit code 为 `0`。
- mock workflow service 被调用一次。
- stdout 包含 plan JSON 片段 `"recipe": "rnaseq_differential_expression"`。
- 输出文件 `<tmp>/rnaseq_deg.wdl` 包含 `workflow RNASeqDEG`。

覆盖点：

- 自然语言 CLI 入口通过 workflow service 进入规划和编译链路。
- `--print-plan` 将 plan 输出到 stdout。
- `--output` 将 WDL 写入文件。
- `--no-check` 跳过 WDL checker。

### `test_cli_prompt_file_uses_natural_language_service`

输入：

- CLI args：

```text
--prompt-file examples/rnaseq_deg_request.txt
--output <tmp>/rnaseq_deg.wdl
--no-check
```

- mock `main.plan_and_compile_workflow` 返回合法 RNA-seq plan 的编译结果。

执行：

- 调用 `cli.main(...)`。

期望输出：

- exit code 为 `0`。
- `plan_and_compile_workflow` 被调用一次，参数为 prompt 文件内容、默认 planner model 和 `check=False`。
- stdout 为空，因为 WDL 写入了 `--output` 指定文件，且没有请求打印 plan 或 IR。
- 输出文件 `<tmp>/rnaseq_deg.wdl` 包含 `workflow RNASeqDEG`。

覆盖点：

- `--prompt-file` 和 `--prompt` 一样走自然语言 workflow service。
- prompt 文件路径不会被误当作结构化 `--input`。
- 指定 `--output` 时，CLI 不向 stdout 写入非请求 artifact。

### `test_cli_structured_input_uses_structured_service_without_planner`

输入：

- CLI args：

```text
--input examples/rnaseq_deg_recipe_plan.json
--no-check
```

- mock `main.compile_structured_workflow` 返回合法 RNA-seq plan 的编译结果。
- mock `main.plan_and_compile_workflow`。

执行：

- 调用 `cli.main(...)`。

期望输出：

- exit code 为 `0`。
- `compile_structured_workflow` 被调用一次，参数为读取到的 plan 和 `check=False`。
- `plan_and_compile_workflow` 不被调用。
- stdout 以 `version 1.0\n` 开头。

覆盖点：

- 结构化 CLI 入口直接调用 workflow service 的结构化编译接口。
- `--input` 路径不会触发自然语言规划服务。

### `test_cli_saves_natural_language_plan_and_planner_prompt`

输入：

- CLI args：

```text
--prompt "Run bulk RNA-seq differential expression."
--output <tmp>/rnaseq_deg.wdl
--save-plan <tmp>/plan.json
--save-planner-prompt <tmp>/planner_prompt.txt
--no-check
```

- mock `build_default_planner_prompt` 返回 `planner prompt`。
- mock `plan_and_compile_workflow` 返回合法 RNA-seq plan 的编译结果。

执行：

- 调用 `cli.main(...)`。

期望输出：

- exit code 为 `0`。
- `<tmp>/plan.json` 内容等于 mock planner 返回的 plan。
- `<tmp>/planner_prompt.txt` 内容为 `planner prompt`。
- stderr 包含：
  - `Planner plan written to`
  - `Planner prompt written to`

覆盖点：

- CLI 可以保存 planner 生成的结构化 plan。
- CLI 可以保存实际 planner prompt，便于调试模型行为。

### `test_cli_reports_natural_language_planning_failure`

输入：

- CLI args：

```text
--prompt "Run RNA-seq differential expression."
```

- mock `plan_and_compile_workflow` 抛出 `NaturalLanguagePlanningError("LLM planner JSON parsing failed: bad json")`。

执行：

- 调用 `cli.main(...)`。

期望输出：

- exit code 为 `1`。
- stdout 为空。
- stderr 包含：
  - `Natural language planning failed`
  - `JSON parsing failed`

覆盖点：

- 自然语言 workflow service 失败时 CLI 返回失败状态，并把错误写到 stderr。

### `test_cli_saves_planner_prompt_even_when_planning_fails`

输入：

- CLI args：

```text
--prompt "Run RNA-seq differential expression."
--save-planner-prompt <tmp>/planner_prompt.txt
```

- mock `build_default_planner_prompt` 返回 `planner prompt`。
- mock `plan_and_compile_workflow` 抛出 JSON parsing 失败。

执行：

- 调用 `cli.main(...)`。

期望输出：

- exit code 为 `1`。
- `<tmp>/planner_prompt.txt` 内容仍为 `planner prompt`。

覆盖点：

- 即使 planner 失败，也能保留 prompt 供调试。

### `test_cli_writes_wdl_output_from_recipe_plan_without_check`

输入：

- CLI args：

```text
--input examples/rnaseq_deg_recipe_plan.json
--output <tmp>/rnaseq_deg.wdl
--print-ir
--no-check
```

执行：

- 调用 `cli.main(...)`。

期望输出：

- exit code 为 `0`。
- 输出 WDL 文件存在。
- 输出文件包含 `workflow RNASeqDEG`。
- stdout 包含 IR JSON 片段 `"workflow"`。
- stderr 包含 `WDL written to`。

覆盖点：

- 结构化 Recipe Tool Plan 输入可以直接编译。
- `--print-ir` 输出标准化后的 Workflow IR。

### `test_cli_returns_failure_for_invalid_recipe_plan`

输入：

- 从 `examples/rnaseq_deg_recipe_plan.json` 读取 plan。
- 删除 `workflow.inputs.sample_groups`。
- 写入临时 `invalid_plan.json`。
- CLI args：

```text
--input <tmp>/invalid_plan.json
--no-check
```

执行：

- 调用 `cli.main(...)`。

期望输出：

- exit code 为 `1`。
- stdout 为空。
- stderr 包含 `missing required workflow input 'sample_groups'`。

覆盖点：

- CLI 将 resolver/catalog 校验错误作为失败返回。

### `test_cli_stdout_is_pure_wdl_without_output_path`

输入：

- CLI args：

```text
--input examples/rnaseq_workflow_ir.json
--no-check
```

执行：

- 调用 `cli.main(...)`。

期望输出：

- exit code 为 `0`。
- stdout 以 `version 1.0\n` 开头。
- stdout 不包含日志文本 `IR normalizer node`。
- stderr 包含 `WDL syntax validation skipped`。

覆盖点：

- 不指定 `--output` 时，stdout 只输出机器可消费的 WDL。
- 状态/诊断信息保留在 stderr。

### `test_cli_verbose_logs_stay_on_stderr`

输入：

- CLI args：

```text
--input examples/rnaseq_workflow_ir.json
--no-check
--verbose
```

执行：

- 调用 `cli.main(...)`。

期望输出：

- exit code 为 `0`。
- stdout 以 `version 1.0\n` 开头。
- stderr 包含 verbose 日志 `IR normalizer node is normalizing Workflow IR.`。

覆盖点：

- verbose 日志不会污染 stdout WDL 输出。

## `tests/test_execution_backend.py`

该文件验证执行后端协议、默认禁用行为和 factory 环境变量路由。

覆盖点：

- `ExecutionResult` 的 outputs 与 metadata 默认 dict 互不共享。
- 未配置后端时返回 disabled backend。
- `AI_BIOWORKFLOW_RUN_BACKEND=cromwell` 时 factory 返回 `CromwellBackend`，并读取 Cromwell URL、poll interval 和 timeout 配置。
- `local-miniwdl` 后端仍保持未实现。

## `tests/test_cromwell_backend.py`

该文件验证 Cromwell server mode REST client 的 contract，不依赖真实 Cromwell、Docker 或生信输入文件。

覆盖点：

- `availability()` 调用 `/engine/v1/status`，并把连接失败、非 2xx 和无效 JSON 转成不可用原因。
- `run()` 在 Cromwell 不可用时不提交 workflow。
- workflow submit 使用 `/api/workflows/v1` 和 Cromwell 约定的 multipart 字段。
- polling 能处理 `Submitted -> Running -> Succeeded`，并解析 outputs 与 metadata。
- 刚提交后短暂出现 `Unrecognized workflow ID` 时继续轮询。
- `Succeeded` 但 outputs 收集失败时返回失败结果并保留 metadata。
- `Succeeded` 且 outputs 正常但 metadata 收集失败时保留成功结果，并在 message 中暴露 metadata 收集问题。
- `Failed` / `Aborted` 返回失败结果；当 outputs 收集失败时，message 仍保留 metadata 中的 workflow failure 摘要，并追加收集阶段问题。
- timeout 返回失败结果和清晰 message。

## `tests/test_tools.py`

该文件验证 WDL validator wrapper。两个用例只有在 `wdl_validator_available()` 返回 true 时运行。

### `test_validator_accepts_valid_wdl`

输入：

- `VALID_WDL` 字符串：
  - `workflow SimpleWorkflow`
  - input `raw_fastq: File`
  - call `fastp_qc`
  - output `clean_fastq`
  - task `fastp_qc`
  - runtime docker `ubuntu:22.04`

执行：

- 调用 `wdl_validator.invoke({"wdl_code": VALID_WDL})`。

期望输出：

- 返回 dict 中 `is_valid=True`。
- 如果失败，断言会显示 validator message。

覆盖点：

- 本地 WOMtool 或 miniwdl 能接受合法 WDL。

### `test_validator_rejects_invalid_wdl`

输入：

```wdl
workflow Bad {
```

执行：

- 调用 `wdl_validator.invoke({"wdl_code": "workflow Bad {"})`。

期望输出：

- 返回 dict 中 `is_valid=False`。
- `message` 包含 `WDL 语法校验失败`。

覆盖点：

- Validator wrapper 能把 WDL 语法错误转成结构化失败结果。

## `tests/test_tiny_run.py`

该文件是可选端到端执行测试，不是普通纯单元测试。它会在本地环境不完整时调用 `skipTest(...)`。

### `test_rnaseq_tiny_run_when_local_runtime_is_ready`

前置条件：

- `miniwdl_available()` 为 true。
- 本机存在 `docker` 或 `podman`。
- 下列镜像已经存在于本地：
  - `quay.io/biocontainers/fastp:1.3.3--h43da1c4_0`
  - `quay.io/biocontainers/salmon:1.9.0--h7e5ed60_0`
  - `ghcr.io/yuanzhw/ai-bioworkflow/tximport:1.30.0-r1`
  - `ghcr.io/yuanzhw/ai-bioworkflow/deseq2:1.42.1-r2`
  - `ghcr.io/yuanzhw/ai-bioworkflow/multiqc:1.21-r1`
- `examples/tiny/rnaseq_deg.inputs.json` 存在。

输入：

- `examples/rnaseq_deg_recipe_plan.json`
- `examples/tiny/rnaseq_deg.inputs.json`

执行：

1. 调用 `cli.load_workflow_input(...)` 读取 RNA-seq plan。
2. 调用 `cli.compile_workflow(plan, check=True)` 编译并校验 WDL。
3. 将 `state["current_wdl"]` 写入临时 `rnaseq_deg.wdl`。
4. 执行：

```text
miniwdl run <tmp>/rnaseq_deg.wdl -i examples/tiny/rnaseq_deg.inputs.json --dir <tmp>/run
```

期望输出：

- 编译 state 中 `is_valid=True`。
- miniwdl run 的 return code 为 `0`。
- miniwdl stdout 最后的 JSON output 中包含：
  - `RNASeqDEG.deg_table`
  - `RNASeqDEG.multiqc_report`

覆盖点：

- 从 Recipe Tool Plan 到实际 miniwdl 执行的完整路径。
- 依赖真实本地容器镜像和 tiny 数据，因此默认开发环境中可能跳过。

## `tests/test_container_build.py`

该文件验证项目维护容器的构建脚本 contract，不实际调用 Docker。

### `test_select_spec_uses_image_revision_in_tag`

输入：

- 临时 `containers/deseq2/1.42.1/` 目录。
- `Dockerfile`
- `smoke_test.sh`
- `image_revision.txt` 内容为 `r2`。

执行：

- 调用 `select_specs(...)` 读取单个 container spec。
- 调用 `spec.image("ghcr.io/example/project")`。

期望输出：

- `spec.image_revision == "r2"`。
- `spec.image_tag == "1.42.1-r2"`。
- 镜像名为 `ghcr.io/example/project/deseq2:1.42.1-r2`。

覆盖点：

- 上游软件版本与项目镜像修订版分离。
- 构建脚本生成 `<software-version>-<image-revision>` tag。

### `test_discover_specs_requires_image_revision_file`

输入：

- 临时 container 目录包含 `Dockerfile` 和 `smoke_test.sh`，但缺少 `image_revision.txt`。

执行：

- 调用 `discover_specs(...)`。

期望输出：

- 抛出 `SystemExit`，错误信息包含 `image_revision.txt`。

覆盖点：

- 每个项目维护容器必须显式声明镜像修订号。

### `test_discover_specs_rejects_invalid_image_revision`

输入：

- 临时 container 目录的 `image_revision.txt` 内容为 `latest`。

执行：

- 调用 `discover_specs(...)`。

期望输出：

- 抛出 `SystemExit`。
- 错误信息说明修订号必须类似 `r1`。

覆盖点：

- 禁止使用 `latest` 或其他不可审计的修订号格式。

### `test_discover_specs_ignores_directories_without_dockerfile`

输入：

- 临时目录 `containers/notes/draft/`，其中没有 `Dockerfile`。

执行：

- 调用 `discover_specs(...)`。

期望输出：

- 返回空列表。

覆盖点：

- `--all` 只发现实际容器目录，非容器草稿目录不会被强制要求声明镜像修订号。

## `web/tests/workflow-graph.test.mjs`

该文件验证 W5 DAG 可视化前置的数据模型转换层。测试通过 `tsx --test`
调用 Node 内置 test runner，并直接加载 `web/lib/workflow-graph.ts`，不启动
Next.js。

运行方式：

```powershell
cd web
npm run test:graph
```

### `builds call dependency and workflow output graph from legacy calls`

输入：

- legacy Workflow IR，使用 `workflow.calls`：
  - workflow inputs：`raw_r1`、`raw_r2`、`reference`
  - calls：`qc` 调用 `fastp`，`align` 调用 `bwa_mem`
  - `align` 的输入引用 `qc.clean_r1/qc.clean_r2`
  - workflow output：`bam = align.bam`
- task metadata 包含 outputs 和 runtime docker。

期望输出：

- 生成 workflow input、call 和 workflow output 节点。
- 生成 `qc -> align` 的 dependency edges。
- 生成 `align -> bam output` 的 output edge。
- call node metadata 保留 task、outputs 和 runtime。

覆盖点：

- 图模型兼容旧 `workflow.calls` 输入，但不修改 IR。
- W5 DAG 模型能从 task metadata 暴露节点详情需要的核心字段。

### `builds scatter group and nested call dependencies from workflow steps`

输入：

- canonical Workflow IR，使用 `workflow.steps`：
  - workflow inputs：`sample_ids`、`raw_r1s`、`raw_r2s`、`transcriptome_index`
  - scatter step：`per_sample`，`over = range(length(sample_ids))`
  - scatter body 内含 `qc` 和 `quantify`
  - scatter 后有 `summarize`，输入引用 `quantify.quant_file`
  - workflow output：`counts = summarize.gene_counts`

期望输出：

- 生成 scatter group node。
- scatter body 内的 call nodes 记录 `parentId = scatter:per_sample`。
- 生成 `sample_ids -> scatter` 的 input edge。
- 生成 `qc -> quantify`、`quantify -> summarize` 的 dependency edges。
- 生成 `summarize -> counts output` 的 output edge。

覆盖点：

- 图模型优先读取 `workflow.steps`。
- scatter body 会递归转成节点和边，但不做 Analyzer 的类型提升或修复工作。

### `records unresolved references without guessing unsupported expressions`

输入：

- Workflow IR 中 `report` call 的输入包含：
  - `missing.result`：未知 call。
  - `qc.missing_report`：已知 call 上未知 output。
  - `qc.html_report + qc.json_report`：不支持的字符串拼接表达式。
  - `qc.html_report-qc.json_report` 和 `qc.html_report*qc.json_report`：不支持的无空格运算表达式。

期望输出：

- `graph.unresolvedReferences` 按原因记录：
  - `unknown-call`
  - `unknown-output`
  - `unsupported-expression`
- 对不支持表达式不生成猜测性的 dependency edge。
- 对已解析的 `report.multiqc_report` workflow output 仍生成 output edge。

覆盖点：

- 前端图模型只做可解释的引用提取。
- 无法解析或无法确认的表达式保留在节点详情中，供后续 UI 展示和审计。

### `normalizes object expression fallbacks with stable key order`

输入：

- 两份语义相同但 object key 插入顺序不同的 call input：
  - `{b: 2, a: 1, nested: {z: true, y: false}}`
  - `{nested: {y: false, z: true}, a: 1, b: 2}`

期望输出：

- 两份 graph 中 `metadata.call.inputs.config` 的 fallback JSON 字符串完全一致。
- 嵌套 object key 也按稳定顺序输出。

覆盖点：

- graph metadata 中无法直接转成表达式文本的 object fallback 保持 deterministic。
- 该行为只影响节点详情/审计字符串，不改变 Workflow IR，也不参与 Analyzer 或 Renderer。

## `web/tests/catalog-retrieval.test.mjs`

该文件验证前端 Catalog Retrieval 展示所依赖的纯数据 helper。测试通过
`tsx --test` 调用 Node 内置 test runner，不启动 Next.js，也不访问后端 API。

运行方式：

```powershell
cd web
npm run test:catalog-retrieval
```

### `detects non-empty catalog retrieval artifacts`

输入：

- `null` retrieval。
- 空 query、空 recipes、空 tools 且未 fallback 的 retrieval。
- 包含 RNA-seq query、recipe 和 tool 候选的 retrieval。

期望输出：

- `null` 与空 retrieval 返回 `false`。
- 包含候选或 query 的 retrieval 返回 `true`。

覆盖点：

- 前端不会为结构化入口或未产生检索产物的 run 伪造 Catalog Retrieval 展示。

### `selects top catalog recipe and limited tools`

输入：

- RNA-seq retrieval artifact，包含 `rnaseq_differential_expression` recipe，以及 `deseq2`、`salmon` tools。

期望输出：

- top recipe 为 `rnaseq_differential_expression`。
- 限制 tool 数量为 1 时只返回 `deseq2:1.42.1`。
- limit 为 0 时返回空数组。

覆盖点：

- 工作台 run 卡片和详情页摘要使用稳定的 top recipe/tools 选择逻辑。

### `summarizes matched terms with overflow count`

输入：

- matched terms：`["rna", "seq", "deg"]`，limit 为 2。
- matched terms：`["rna", "seq"]`，limit 为 4。

期望输出：

- 第一组显示前两个 term，并记录 1 个隐藏 term。
- 第二组全部显示，隐藏数为 0。

覆盖点：

- `matched_terms` 在紧凑卡片中保持可扫读，同时不丢失溢出计数。

### `formats retrieval scores compactly`

输入：

- 整数 score、浮点 score 和 `NaN`。

期望输出：

- 整数不补小数。
- 浮点保留 1 位小数。
- 非法数字显示为 `0`。

覆盖点：

- 候选 recipe/tools 的 score 在前端展示中稳定、简洁。

## 当前测试覆盖边界

已有测试重点覆盖：

- Recipe Tool Plan schema 与 recipe/catalog 校验。
- Catalog runtime docker 必填约束。
- Recipe Tool Plan 到 Workflow IR 的 resolver 主路径。
- Catalog 查询服务的 recipe/tool JSON-ready 输出。
- Approved Catalog Retriever 的词法召回、CJK tokenization、fallback 原因和 JSON-ready 输出契约。
- 自然语言 run 对 catalog retrieval artifact 的持久化、snapshot 暴露和 SSE 事件回放顺序。
- 前端 Catalog Retrieval 摘要对 top recipe/tools、matched terms 和 score 格式的处理。
- Analyzer 对引用、optional input、scatter output 类型提升的处理。
- Renderer 对 call、scatter、array flatten、workflow output 和 task 的 WDL 渲染。
- Deterministic repairer 对 call 顺序和 output 字面量的安全修复。
- Reviewer repair request / patch / result 契约模型与 P2 patch policy skeleton。
- Workflow service 对结构化编译入口、自然语言规划后编译入口和 API 友好结果对象的封装。
- FastAPI DTO 对 workflow、catalog 和 event envelope 的输入输出契约。
- FastAPI endpoints 对 W0 workflow/catalog services 的复用、HTTP 状态映射和响应序列化。
- FastAPI 开发服务器默认端口 `8010`，避免与 Cromwell server 的 `8000` 冲突。
- CLI 的自然语言入口、结构化入口、文件输出、stdout/stderr 隔离和失败返回。
- Planner 的 JSON 解析、prompt 构建、schema 错误和 catalog 错误归类。
- Cromwell execution backend 的可用性检查、提交、轮询、结果收集错误语义和 factory 路由。
- WDL validator wrapper 和可选 miniwdl tiny run。
- W5 前端 workflow graph 数据模型对 call、scatter、workflow output 和 unresolved reference 的覆盖。

目前相对少覆盖或未覆盖的方向：

- 多 recipe、多工具候选和更复杂 tool selection。
- 参数范围错误以外的更多 Tool Catalog schema 边界。
- nested scatter、conditional step、subworkflow 等 roadmap feature。
- Reviewer provider、Compiler Graph 路由、Run observability、Resource Agent 和
  Bioinfo Reviewer 等规划中 Agent。
- Nextflow 或其他 backend。
- 真实自然语言模型调用的在线集成测试。
- Next.js 工作台、DAG 可视化和 run history 的浏览器级视觉回归测试。
