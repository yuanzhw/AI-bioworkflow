# W4 Workflow 生成工作台工作拆解

本文档记录 Web 产品化路线中 `W4` 阶段的实施范围、任务拆分和验收口径，便于后续开发按同一边界推进。

## 阶段定位

`W4` 的目标是把 `W3` 已搭好的静态工作台预览接入 `W2` 已落地的 run API、SQLite 持久化和 SSE 事件流，形成一个可演示的 Workflow 生成工作台。

完成后，访问者应能提交一个预置 RNA-seq 示例，实时看到 Agent / Compiler 的阶段事件，并查看同一次 run 产生的 Recipe Tool Plan、Workflow IR、WDL 和 diagnostics。

`W4` 是 Web 工作台与可观测性接入阶段，不改变 Compiler Graph 的职责，也不引入新的 Multi-Agent 能力。

## 当前基础

- 后端已有异步 run 创建接口：
  - `POST /api/runs`：自然语言请求入口，需要 planner 环境变量可用。
  - `POST /api/compile`：结构化 Recipe Tool Plan / Workflow IR 编译入口，不需要 API key。
- 后端已有 run 查询和事件接口：
  - `GET /api/runs/{run_id}`：返回 run snapshot、artifacts 和 diagnostics。
  - `GET /api/runs/{run_id}/events`：通过 SSE 推送或回放 run events。
- 事件 envelope 已覆盖第一版工作台所需事件类型：
  - `run.created`
  - `node.started`
  - `node.completed`
  - `node.failed`
  - `artifact.updated`
  - `repair.applied`
  - `validation.completed`
  - `run.completed`
- 前端已有 `/workspace` 真实工作台：
  - 结构化示例模式使用内置 RNA-seq Recipe Tool Plan 调用 `POST /api/compile`。
  - 自然语言模式调用 `POST /api/runs`，planner 失败时展示后端持久化的失败诊断。
  - 前端会轮询 `GET /api/runs/{run_id}`，展示 run 状态、WDL 摘要、校验信息和诊断计数。
  - 前端会订阅 `GET /api/runs/{run_id}/events` SSE 事件流，展示 run 时间线。
  - Catalog Retrieval / Plan / Workflow IR / WDL / Diagnostics tabs 来自真实 run snapshot。
  - 默认本地 API base URL 为 `http://127.0.0.1:8010`，可通过 `NEXT_PUBLIC_API_BASE_URL` 覆盖。

## 产品行为

第一版工作台建议支持两个运行路径：

1. **稳定示例运行**：默认使用 `examples/rnaseq_deg_recipe_plan.json` 作为 payload 调用 `POST /api/compile`。这条路径适合本地和公开 demo，因为它不依赖 `DEEPSEEK_API_KEY`，仍然完整经过 Compiler Graph。
2. **自然语言运行**：用户输入自然语言请求时调用 `POST /api/runs`。如果 planner 环境不可用，工作台应展示后端返回的失败诊断，而不是在前端自行模拟成功。

页面需要围绕同一个 `run_id` 组织所有视图：

- 输入面板展示请求文本、运行模式、`check` 开关和当前 run 状态。
- 执行时间线展示每个阶段的 pending / running / completed / failed 状态。
- 产物查看区展示 Catalog Retrieval、Plan、IR、WDL 和 Diagnostics。
- 失败状态保留已产生的事件和 diagnostics，体现可审计失败，而不是只显示通用错误提示。

## 任务拆分

### 1. 前端 API client 与类型

在 `web/lib/api.ts` 和 `web/lib/types.ts` 中补齐工作台所需的客户端能力：

- `createNaturalLanguageRun(request, check, plannerModel?)`
- `createStructuredCompileRun(payload, check)`
- `getRunSnapshot(runId)`
- `buildRunEventsUrl(eventsUrl, afterSequence?)`
- `RunEvent`
- `WorkflowArtifacts`
- `DiagnosticReport`
- `WorkflowRunSnapshotResponse`

类型应与后端 Pydantic DTO 显式同步，避免在页面组件中使用松散的 `any` 拼装 run 数据。

### 2. `/workspace` 页面交互化

将当前静态工作台拆成 server page + client workbench 组件，或直接将交互区域封装为 client component。

需要实现：

- RNA-seq 示例预填充。
- 可编辑自然语言输入。
- 运行模式选择：结构化示例编译 / 自然语言规划编译。
- `check` 开关。
- 运行按钮、运行中禁用状态和当前 run id。
- 空状态、运行中状态、成功状态和失败状态。

页面不应在前端构造 Workflow IR 或 WDL；前端只提交请求、订阅事件、读取 snapshot 并展示后端产物。

### 3. Run 提交与 SSE 状态机

提交成功后，前端从 `RunAcceptedResponse` 获取 `run_id` 和 `events_url`，立即建立 `EventSource` 订阅。

事件处理规则：

- 维护 `lastSequence`，用于断线重连时追加 `?after=<lastSequence>`。
- `node.started` 将对应节点置为 running。
- `node.completed` 将对应节点置为 completed。
- `node.failed` 将对应节点置为 failed，并将 run 状态转为 failed 候选状态。
- `repair.applied` 在 timeline 中保留 repairer 事件，并更新 diagnostics 提示。
- `validation.completed` 更新 checker 状态与 validation 摘要。
- `artifact.updated` 只说明有产物更新；前端应再请求 `GET /api/runs/{run_id}` 获取完整 artifact 内容。
- `run.completed` 是终态事件；收到后关闭 EventSource，并做一次最终 snapshot 拉取。

SSE 断开但 run 未终态时，页面应显示连接状态，并允许自动重连或手动重新连接。

### 4. 执行时间线

时间线应覆盖第一版工作台重点阶段：

- Planner / Recipe Tool Plan
- IR Normalizer
- Analyzer
- Repairer（仅有事件时显示）
- Renderer
- WOMtool Checker
- Run Completed

结构化编译模式不会出现 planner 事件，页面应自然跳过或显示为不适用，而不是标成失败。

### 5. 产物查看区

产物区从当前静态卡片改成真实 tabs：

- **Catalog**：展示自然语言 run 的 top recipe/tools、`score`、`matched_terms`、`matched_fields`、`trust_status` 和 fallback 原因；结构化入口为空状态。
- **Plan**：展示 Recipe Tool Plan JSON；结构化编译 payload 是 Recipe Tool Plan 时应可见。
- **IR**：展示 Workflow IR JSON，优先使用 pretty JSON。
- **WDL**：展示生成的 WDL 1.0 文本。
- **Diagnostics**：展示 `analysis_errors`、`analysis_warnings`、`repair_actions`、`validation_message`、`is_valid`、`succeeded` 和 `check_performed`。

每个 tab 都需要清晰的空状态。运行过程中 artifact 尚未生成时，应显示“等待对应阶段完成”，不要显示静态示例内容。

### 6. 错误与边界状态

至少覆盖以下用户可见状态：

- FastAPI 服务不可达。
- 请求体校验失败或 API 返回 422。
- 自然语言 planner 缺少 API key 或 planner 失败。
- Compiler Graph 阶段失败。
- WDL checker 失败。
- SSE 连接中断。
- Run 终态为 failed，但已有部分 artifact 可查看。

错误文案应说明失败发生在哪个阶段，并尽量复用后端 diagnostics 和 event summary。

### 7. 文案与导航更新

W4 已把工作台顶部、运行模式、时间线、artifact tabs 和失败态更新为真实 run 接入表述。

项目介绍页可以继续强调：

- 自然语言只到 Recipe Tool Plan。
- Workflow IR 是编译契约。
- WDL 由确定性 renderer 生成。
- Analyzer / Repairer / Checker 过程可追踪。

公共文案保持项目维护者视角，不加入工具签名、自动生成说明或外部助手品牌化措辞。

## W4 不做

- 不实现 React Flow DAG 可视化；该能力属于 `W5`。
- 不实现 run 历史详情页和失败/修复回放详情；该能力属于 `W5`。
- 不改变 Recipe Tool Plan、Workflow IR、Analyzer、Renderer 或 Checker 的架构边界。
- 不让前端生成或修复 Plan、IR、WDL。
- 不引入新的 Agent 节点、Reviewer LLM 或 Tool Retriever。
- 不接入真实 WDL 执行后端；执行能力仍通过 `src.execution` 后端边界独立推进。

## 建议 PR 顺序

1. **W4 API client and types**：补齐前端 run DTO、API client、SSE URL helper。已完成。
2. **W4 workbench structured run launcher**：实现结构化示例提交、run 状态和 snapshot 轮询。已完成。
3. **W4 SSE timeline**：实现 EventSource 订阅、断线恢复和时间线状态映射。已完成。
4. **W4 artifacts tabs**：实现 Plan / IR / WDL / Diagnostics tabs 和空状态。已完成。
5. **W4 failure states and polish**：补齐错误状态、占位文案替换、响应式细节和自然语言运行入口。已完成。
6. **W4 docs and verification**：持续更新 README / DEVELOPMENT 中的阶段状态说明，并记录验证结果。已完成。

## 验收标准

功能验收：

- 已落地：
  - 启动 FastAPI 与 Next.js 后，访问 `/workspace?example=rnaseq-deg` 可以提交一次结构化 RNA-seq 示例 run。
  - 页面能从 accepted run 轮询到 `created` / `running` / `succeeded` / `failed` snapshot。
  - 运行卡片展示 run id、状态、WDL 摘要、校验信息、analysis error 计数和 repair action 计数。
  - Timeline 能实时显示 Compiler Graph 节点进度。
  - Catalog Retrieval、Plan、Workflow IR、WDL 和 Diagnostics 来自真实 run snapshot tabs。
  - 自然语言模式在 planner 环境可用时能走 `POST /api/runs`；环境不可用时显示明确失败诊断。
  - 失败 run 仍保留已产生事件、artifact 和 diagnostics。

验证建议：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

```powershell
cd web
npm run lint
npm run build
```

如果 W4 只改前端展示和 API client，不改变 renderer、recipe resolution、validation path 或生成 WDL 的代码，一般不需要额外生成 WDL 并运行 `miniwdl check`。如果后续实现过程中触碰 WDL 输出路径，则需要按项目开发规则补充代表性 WDL 语法校验。
