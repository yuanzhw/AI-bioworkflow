# W5 DAG 与历史详情工作拆解

本文档记录 Web 产品化路线中 `W5` 阶段的实施范围、任务拆分和验收口径，便于后续开发按同一边界推进。

## 阶段定位

`W5` 的目标是把 `W4` 工作台产生的一次 workflow run，从“可实时生成”推进到“可结构化理解、可回放、可审计”。

完成后，访问者应能从工作台创建 RNA-seq 示例 run，在历史列表中再次找到它，进入详情页回放事件、产物和诊断信息，并通过 DAG 图理解 Workflow IR 中的 calls、scatter、依赖边、输入输出和节点状态。

`W5` 是 run 历史与 Workflow IR 可视化阶段，不改变 Compiler Graph 的职责，不让前端生成或修复 Plan、IR、WDL，也不引入新的 Agent 节点或真实 WDL 执行后端。

## 进入条件

- `W4` 的 SSE 时间线已能基于真实 `RunEvent` envelope 展示节点进度。
- `W4` 的 Plan / IR / WDL / Diagnostics tabs 已接入真实 run snapshot。
- `/workspace?example=rnaseq-deg` 可以稳定创建结构化 RNA-seq 示例 run。
- 失败 run 保留已产生的 events、artifacts 和 diagnostics，供历史详情页回放。

如果进入 `W5` 时上述能力尚未全部完成，应先收尾 `W4`，避免历史详情页和工作台重复实现同一套事件、产物和失败态展示逻辑。

## 当前基础

- 后端已有单个 run 查询接口：
  - `GET /api/runs/{run_id}`：返回 run snapshot、artifacts 和 diagnostics。
  - `GET /api/runs/{run_id}/events`：通过 SSE 推送或回放 run events。
- SQLite repository 已保存：
  - `runs`
  - `run_events`
  - `run_artifacts`
  - `run_diagnostics`
- 前端已有：
  - `/workspace` 示例 run launcher。
  - `/runs` 静态历史列表预览。
  - `RunEvent`、`WorkflowArtifacts`、`DiagnosticReport` 和 `WorkflowRunSnapshotResponse` 类型。
- Workflow IR 已以 `workflow.steps` 作为 canonical DAG 表示，`workflow.calls` 仅用于兼容旧输入和调试输出。

## 产品行为

第一版 `W5` 建议围绕同一个 `run_id` 组织三层视图：

1. **历史列表**：展示最近 run 的状态、请求摘要、创建/更新时间、诊断摘要和详情入口。
2. **历史详情**：回放同一次 run 的 request、timeline、Plan、IR、WDL 和 Diagnostics。
3. **DAG 视图**：从详情页中的 Workflow IR 派生图结构，展示 workflow inputs、call nodes、scatter group、workflow outputs 和依赖边。

历史详情页和工作台应复用同一批展示组件，例如 timeline、artifact tabs、diagnostics summary 和 code viewer。工作台关注“当前运行中”，历史详情页关注“刷新后仍可审计”。

## 任务拆分

### 1. 后端 run 历史列表契约

新增 `GET /api/runs`，用于分页读取持久化 run 摘要。

建议第一版 query 参数：

- `limit`：默认 20，设置合理上限。
- `offset`：默认 0。
- `status`：可选，过滤 `created` / `running` / `succeeded` / `failed`。

建议响应 DTO：

```json
{
  "runs": [
    {
      "run_id": "run_001",
      "status": "succeeded",
      "kind": "structured_compile",
      "request_summary": "rnaseq_differential_expression",
      "events_url": "/api/runs/run_001/events",
      "created_at": "2026-06-16T00:00:00Z",
      "updated_at": "2026-06-16T00:00:02Z",
      "completed_at": "2026-06-16T00:00:02Z",
      "diagnostic_summary": {
        "analysis_error_count": 0,
        "analysis_warning_count": 0,
        "repair_action_count": 0,
        "check_performed": true,
        "is_valid": true
      }
    }
  ],
  "limit": 20,
  "offset": 0,
  "total": 1
}
```

Repository 层应按 `created_at DESC` 或 `updated_at DESC` 稳定排序，并补充 service 与 API route 测试。列表响应不返回完整 WDL 或大块 JSON artifact，避免历史页首屏过重。

### 2. 前端 API client 与类型

在 `web/lib/types.ts` 和 `web/lib/api.ts` 中补齐：

- `RunSummary`
- `RunDiagnosticSummary`
- `RunListResponse`
- `listRuns(params?)`
- `getRunEvents(runId, afterSequence?)` 或继续复用 SSE URL helper，由详情页选择是否一次性回放事件。

类型应与 Pydantic DTO 显式同步，页面组件不直接拼装松散的 `any`。

### 3. `/runs` 真实历史列表页

替换当前静态预览：

- 首屏展示最近 run。
- 状态 badge 使用 created / running / succeeded / failed。
- 每条 run 展示请求摘要、运行类型、更新时间、诊断计数和详情入口。
- 空状态引导用户前往 `/workspace?example=rnaseq-deg` 创建示例 run。
- API 不可达或返回错误时显示明确错误状态。

列表页不展示完整 Plan、IR 或 WDL，只作为审计入口。

### 4. `/runs/[runId]` 历史详情页

新增 run 详情页，读取 `GET /api/runs/{run_id}` 和事件回放数据。

详情页需要展示：

- run id、状态、运行类型、创建/完成时间。
- 原始 request 或结构化 payload 摘要。
- 事件 timeline，保留 sequence、timestamp、node、type 和 summary。
- Plan / IR / WDL / Diagnostics tabs。
- 失败阶段、分析错误、checker 信息和 repair actions。

成功 run 和失败 run 都必须可刷新回放。自然语言 planner 失败时，详情页应显示 planner 失败事件和 diagnostics；结构化编译失败时，应保留已经产生的 artifact。

### 5. Workflow graph 数据模型

在前端新增纯函数，把 `WorkflowArtifacts.workflow_ir` 转成图模型。

建议图模型包含：

- workflow input nodes。
- call nodes。
- scatter group nodes。
- workflow output nodes。
- dependency edges。
- node metadata：task、inputs、outputs、runtime、source step id。

图生成规则：

- 优先读取 `workflow.steps`。
- `kind: "call"` 生成 call node。
- `kind: "scatter"` 生成 group node，并递归处理 `body`。
- call input 表达式中引用上游 call output 时生成依赖边。
- workflow outputs 引用 call output 时生成 output edge。
- 无法解析的表达式不静默猜测，只保留为节点详情中的 unresolved reference。

该层不应改变 Workflow IR，不做 Analyzer 工作，也不尝试补全依赖。

### 6. React Flow DAG 可视化

引入 React Flow 作为 W5 的前端展示依赖，用于交互式 DAG 布局、节点选择和边关系展示。新增依赖时需要在 PR 描述中说明用途。

建议组件目录：

```text
web/components/workflow-graph/
  workflow-graph.tsx
  workflow-node.tsx
  node-detail-panel.tsx
  graph-empty-state.tsx
```

第一版图交互：

- 节点状态映射 pending / running / completed / failed / unavailable。
- 点击节点展示 task、inputs、outputs、runtime docker 和相关事件摘要。
- scatter group 能体现 per-sample 并行语义。
- DAG 空状态说明当前 run 尚未产生 Workflow IR。
- 失败 run 中已产生 IR 时仍展示 DAG，并标出失败节点。

### 7. 导航、文案与文档更新

- 工作台成功后提供“查看历史详情”入口。
- `/runs` 列表提供“返回工作台”入口。
- 项目介绍页中 DAG 和 Timeline 的系统视图文案从预览状态更新为真实能力。
- README roadmap 链接到本文件。
- `DEVELOPMENT.md` 保留 W5 里程碑摘要，并链接本拆解文档。

公共文案保持项目维护者视角，强调工程、编译器、生信工作流建模和产品可观测性，不加入工具签名、自动生成说明或外部助手品牌化措辞。

## W5 不做

- 不改变 Recipe Tool Plan、Workflow IR、Analyzer、Repairer、Renderer 或 Checker 的职责边界。
- 不让前端生成、修复或补全 Plan、IR、WDL。
- 不实现 roadmap-only Reviewer LLM、自愈循环或 Tool Retriever。
- 不接入真实 Cromwell / miniwdl 执行后端；执行能力仍通过 `src.execution` 后端边界独立推进。
- 不把历史列表做成多用户、权限或长期审计系统；第一版只服务本地和作品集 demo。
- 不新增生信 tool catalog 或 recipe，除非 DAG 展示发现现有示例缺少必要元数据。

## 建议 PR 顺序

1. **W5 run history API**：新增 run summary DTO、repository 分页查询、service 方法、`GET /api/runs` 与 API 测试。
2. **W5 real runs list page**：替换 `/runs` 静态样例，接入真实列表和错误/空状态。
3. **W5 run detail replay**：新增 `/runs/[runId]`，复用 timeline、artifact tabs 和 diagnostics 展示。
4. **W5 workflow graph model**：实现 Workflow IR 到 graph nodes/edges 的纯函数和覆盖 scatter 的测试。
5. **W5 React Flow DAG view**：接入 React Flow、节点详情面板和状态映射。
6. **W5 navigation and docs polish**：更新工作台入口、README、DEVELOPMENT 和作品集文案。

## 验收标准

功能验收：

- 从 `/workspace?example=rnaseq-deg` 创建 run 后，刷新 `/runs` 仍能看到该记录。
- `/runs` 能展示 succeeded 和 failed run 的关键摘要，并能进入详情页。
- `/runs/[runId]` 能回放 events、artifacts 和 diagnostics。
- DAG 能正确展示 RNA-seq 示例中的 per-sample Salmon scatter、tximport、DESeq2 和 MultiQC 依赖关系。
- 点击 DAG 节点能看到对应 task、inputs、outputs 和 runtime docker。
- 失败 run 已有 Workflow IR 时仍能展示 DAG，并突出失败阶段或失败节点。

工程验收：

- 后端列表接口有 repository、service 和 route 测试。
- 前端 graph 数据模型有覆盖 call、scatter、workflow output 和 unresolved reference 的测试或等效验证。
- 新增前端依赖有明确用途说明。
- 不触碰 WDL 输出路径时，不需要额外生成 WDL 语法校验；如果实现过程中修改 renderer、recipe resolution 或 validation path，则必须生成代表性 WDL 并运行 `miniwdl check`。

## 验证建议

后端与共享逻辑：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

前端：

```powershell
cd web
npm run lint
npm run build
```

如果 W5 引入 React Flow 后首次运行前端构建，需要确认 `package.json` 与 lockfile 一起更新，并在 PR 中说明新增依赖只用于 workflow graph 可视化。
