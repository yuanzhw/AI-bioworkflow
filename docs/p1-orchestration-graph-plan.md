# P1 Orchestration Graph 实施计划

本文档细化 P1 阶段的工程工作，用于把当前自然语言 Planner 和 Compiler Graph 的调用关系整理为明确的双层图结构。它补充 `DEVELOPMENT.md` 中的路线图摘要，作为后续 issue、分支、PR 和验收检查的依据。

## 背景与现状

当前工程方向是“Workflow IR 编译器 + LLM 辅助规划/修复”。自然语言请求必须先转换为 Recipe Tool Plan，再进入 Workflow IR 和 WDL 编译链路；LLM 不直接生成最终 WDL。

当前自然语言调用链路为：

```text
自然语言请求
  -> main.py / workflow_service
  -> src.nl_planner.create_natural_language_plan
  -> Recipe Tool Plan
  -> src.graph.compiler_graph
  -> Workflow IR / WDL / Diagnostics
```

当前结构化入口为：

```text
Recipe Tool Plan / Workflow IR / Legacy JSON
  -> workflow_service.compile_structured_workflow
  -> src.graph.compiler_graph 或 service 内手动 compiler loop
  -> Workflow IR / WDL / Diagnostics
```

主要现状：

- `src/graph.py` 承载结构化 Compiler Graph，并显式导出 `compiler_graph`；旧的 `agent` 导出保留为兼容别名。
- `src.nl_planner.py` 已能把自然语言请求转换为 Recipe Tool Plan，并通过 Recipe/Catalog/Analyzer 校验。
- `src.services.workflow_service` 已有 `compile_structured_workflow` 和 `plan_and_compile_workflow` 两类服务入口。
- `main.py` 已经区分自然语言入口和 `--input` 结构化入口，但自然语言编排仍是服务函数内的线性调用。
- API 和 run service 已开始记录 compiler 事件、artifacts 和 diagnostics，但 Planner 阶段还没有独立图节点边界。

## P1 目标

P1 的目标是把“图外 Planner + 编译图”整理为清晰的双层结构：

```text
Natural Language Request
  -> Orchestration Graph
       -> natural_language_planner
       -> Recipe Tool Plan
  -> Compiler Graph
       -> IR Normalizer
       -> Analyzer
       -> Repairer when deterministic repair is possible
       -> Renderer
       -> Checker
  -> Workflow IR / WDL / Diagnostic Report
```

完成后应满足：

- 代码中能够清楚区分 Orchestration Graph 与 Compiler Graph。
- 自然语言入口通过上层图运行 Planner，再将 Recipe Tool Plan 交给下层编译图。
- 结构化入口继续绕过上层图，直接进入 Compiler Graph。
- `--input`、测试和 `/api/compile` 在没有 `DEEPSEEK_API_KEY` 时仍可运行。
- Planner trace、Plan artifact、Compiler artifacts、修复记录和失败诊断能够被服务层或事件流稳定读取。
- P1 为 P2 以后接入 Reviewer LLM、Architect、Bioinfo Reviewer、Tool Retriever 和 Resource Agent 留出清晰边界。

## 非目标

P1 不承担以下工作：

- 不引入 Reviewer LLM 或 IR patch 修复闭环。
- 不实现 Architect、Bioinfo Reviewer、Tool Retriever 或 Resource Agent。
- 不做未知工具外部检索、Candidate ToolSpec、自动镜像构建或正式镜像晋升。
- 不改变 Workflow IR schema，除非实现过程中发现必须补充可审计字段，并先更新 `docs/workflow-ir.md`。
- 不改变 IR 到 WDL 的确定性 renderer。
- 不绕过 Analyzer、Repairer、Checker 或 Tool Catalog 校验边界。
- 不改变 Tool Catalog 的镜像来源准入规则。

## 目标架构

P1 后建议形成以下模块边界：

| 模块 | 责任 | 不负责 |
| --- | --- | --- |
| `src.graph` 或 `src.compiler_graph` | 结构化输入到 Workflow IR/WDL 的确定性编译图 | 自然语言理解、自由工具选择 |
| `src.orchestration.state` | 上层自然语言编排状态 | Workflow IR 内部校验细节 |
| `src.orchestration.nodes.planner` | 调用现有 Planner，产出 Recipe Tool Plan 和 trace | 渲染 WDL、修改 Catalog |
| `src.orchestration.graph` | 组合 Planner node 和 Compiler Graph | 引入 P2+ Agent 能力 |
| `src.services.workflow_service` | 对 CLI/API 暴露稳定服务入口 | 复制节点内部实现 |
| `src.api` / `main.py` | 按请求类型路由到自然语言或结构化入口 | shell 调用 `main.py` 或绕过 service |

推荐最终调用关系：

```text
CLI --prompt / API POST /api/runs
  -> plan_and_compile_workflow
  -> orchestration_graph.invoke
  -> compiler_graph.invoke

CLI --input / API POST /api/compile / tests
  -> compile_structured_workflow
  -> compiler_graph.invoke
```

## 实现拆分

### P1.1 Compiler Graph 命名明确化

目标：让当前编译图在代码命名上反映真实职责。

已完成工作：

- 在 `src/graph.py` 中显式导出 `compiler_graph = builder.compile()`。
- 保留 `agent = compiler_graph` 作为临时兼容别名，避免一次性破坏现有测试和调用方。
- 更新 service 层优先导入 `compiler_graph`。
- 将测试中的核心断言逐步改为使用 `compiler_graph`。
- 在文档中把 `src.graph.agent` 的旧称标记为兼容别名。

验收：

- 结构化 Recipe Tool Plan、Workflow IR 和 Legacy JSON 仍能编译。
- 现有 `agent` 导入不立刻失效。
- 新测试或更新后的测试直接覆盖 `compiler_graph`。

### P1.2 Orchestration State 初版

目标：建立上层图状态，避免自然语言编排字段污染 `WorkflowState`。

已落地字段（`src/orchestration/state.py`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `request` | `str` | 原始自然语言请求 |
| `planner_model` | `str` | Planner 使用的模型名 |
| `check` | `bool` | 是否执行 WDL syntax validation |
| `plan` | `dict[str, Any] \| None` | Planner 产出的 Recipe Tool Plan |
| `planner_prompt` | `str \| None` | 实际发送给 Planner 的 prompt |
| `planner_raw_response` | `str \| None` | Planner 原始响应文本 |
| `compiler_result` | `WorkflowCompilationResult \| None` | 下层编译结果 |
| `errors` | `list[str]` | 上层编排错误 |
| `events` | `list[dict[str, Any]]` | 可选的图内事件记录，具体持久化仍由 service/run layer 管理 |

已落地辅助函数：

- `build_initial_orchestration_state(...)`：为自然语言编排 run 创建初始状态。
- `orchestration_succeeded(...)`：只有上层没有错误且下层 compiler result 成功时返回 `True`。
- `orchestration_failure_stage(...)`：区分失败发生在上层 orchestration 还是下层 compiler。

验收：

- 自然语言 Planner 的 trace 信息有稳定字段承载。
- `WorkflowState` 继续只描述 Compiler Graph 内部状态。
- 上层失败和下层失败可以在 service result 中区分。

### P1.3 Planner Node

目标：把现有 `create_natural_language_plan` 包装为上层图节点。

已落地行为（`src/orchestration/nodes/planner.py`）：

- 输入 `request`、`planner_model`、可选测试注入的 `llm` / catalog 对象。
- 输出 `plan`、`planner_prompt`、`planner_raw_response`。
- 保留现有错误分类：JSON 解析失败、plan schema 失败、recipe/catalog 校验失败。
- Planner 成功后必须得到 Recipe Tool Plan，不能直接产出 Workflow IR 或 WDL。

事件建议：

| 事件类型 | node | 说明 |
| --- | --- | --- |
| `node.started` | `planner` | Planner 开始 |
| `node.completed` | `planner` | Planner 成功产出 plan |
| `node.failed` | `planner` | Planner 失败，payload 只包含安全诊断 |
| `artifact.updated` | `planner` | Plan artifact 更新 |

验收：

- fake LLM 测试可以稳定覆盖成功和失败路径。
- Planner 失败不进入 Compiler Graph。
- 事件中不记录 API key、鉴权 header、本地 credential path 或其他秘密。

### P1.4 Orchestration Graph 外壳

目标：第一版上层图只负责编排 Planner 与 Compiler Graph。

建议节点：

```text
START
  -> natural_language_planner
  -> compiler_graph
  -> END
```

失败路由：

- Planner 失败时结束，并返回自然语言规划诊断。
- Compiler Graph 失败时保留下层 diagnostics，不由上层图直接修复。
- `check=False` 时仍允许跳过 WDL syntax validation，但 Analyzer 和 Renderer 边界不变。

验收：

- 自然语言入口实际调用 Orchestration Graph。
- 下层 Compiler Graph 仍可独立测试和调用。
- 不引入 P2+ 的 Reviewer 或其他 Agent 占位逻辑。

### P1.5 Service 层入口

目标：让 CLI 和 API 只依赖稳定 service，而不是重复编排图节点。

建议入口：

| 函数 | 行为 |
| --- | --- |
| `compile_structured_workflow` | 结构化输入直接调用 Compiler Graph |
| `plan_and_compile_workflow` | 自然语言输入调用 Orchestration Graph |
| `compile_workflow` | 兼容旧调用，必要时保留为结构化入口别名 |

建议结果：

- 继续使用或扩展 `WorkflowCompilationResult`。
- 自然语言结果应保留 `planner_prompt` 和 `planner_raw_response`。
- Planner 失败应映射为明确异常或失败 result，API 层再转换为 run diagnostics。

验收：

- `plan_and_compile_workflow` 内不再手写 Planner 到 Compiler 的线性编排。
- `compile_structured_workflow` 不需要 `DEEPSEEK_API_KEY`。
- event callback 能覆盖 Planner 和 Compiler 阶段，或由 run service 统一桥接两层事件。

### P1.6 CLI 与 API 路由

目标：入口行为对用户和测试保持稳定，但内部路由完成分层。

CLI 路由：

| 输入 | 路径 | API key |
| --- | --- | --- |
| `--prompt` / `--prompt-file` | Orchestration Graph | 需要 `DEEPSEEK_API_KEY`，除非测试注入 fake LLM |
| `--input` | Compiler Graph | 不需要 |

API 路由：

| Endpoint | 路径 | API key |
| --- | --- | --- |
| `POST /api/runs` | Orchestration Graph | 需要自然语言 Planner 配置 |
| `POST /api/compile` | Compiler Graph | 不需要 |

验收：

- CLI stdout 继续只输出 WDL/JSON artifacts。
- 日志、diagnostics、validation message 继续写 stderr。
- `/api/compile` 不触发 Planner。
- `/api/runs` 的历史快照可以看到 Planner plan 和 Compiler artifacts。

### P1.7 事件与 artifacts

目标：让前端和历史详情能够展示自然语言到编译结果的完整链路。

建议 artifacts：

| artifact | 来源 | 说明 |
| --- | --- | --- |
| `plan` | Planner node | Recipe Tool Plan |
| `workflow_ir` | IR normalizer / repairer | 标准 Workflow IR |
| `wdl` | Renderer | 渲染后的 WDL |
| `diagnostics` | Planner / Analyzer / Checker | 错误、警告、修复、校验结果 |

事件顺序建议：

```text
run.created
node.started planner
node.completed planner
artifact.updated plan
node.started ir_normalizer
node.completed ir_normalizer
artifact.updated workflow_ir
node.started analyzer
node.completed analyzer
node.started renderer
node.completed renderer
artifact.updated wdl
node.started checker
validation.completed
run.completed
```

验收：

- 成功 run 和失败 run 都能回放关键阶段。
- 修复发生时，`workflow_ir` artifact 更新先于 `repair.applied` 事件。
- 事件 payload 使用结构化字段，不依赖前端拼装业务语义。

### P1.8 测试与文档

目标：P1 的边界必须由测试固定下来。

建议测试范围：

- `tests/test_graph.py`：覆盖 `compiler_graph` 兼容行为。
- `tests/test_workflow_service.py`：覆盖自然语言入口走 Orchestration Graph，结构化入口走 Compiler Graph。
- `tests/test_nl_planner.py`：保留 Planner JSON/schema/catalog 错误分类。
- `tests/test_cli.py`：覆盖 `--input` 不触发 Planner，`--prompt` 保持 stdout/stderr 契约。
- `tests/api/test_routes.py` 或 `tests/api/test_server.py`：覆盖 `/api/runs` 与 `/api/compile` 路由差异。
- `docs/test-cases.md`：当测试输入、期望输出或覆盖意图变化时同步更新。

推荐验证命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

如果变更影响生成 WDL、renderer 或 validation path，还应生成代表性 WDL 并运行项目配置的 WDL syntax validation。

## 关键契约

### 自然语言入口契约

输入：

```json
{
  "request": "Run bulk RNA-seq differential expression.",
  "planner_model": "deepseek-v4-pro",
  "check": true
}
```

输出应包含：

- `plan`
- `workflow_ir`
- `wdl`
- `analysis_errors`
- `analysis_warnings`
- `repair_actions`
- `validation_message`
- `is_valid`
- `succeeded`
- `planner_prompt`
- `planner_raw_response`

失败语义：

- 空请求或 request schema 错误由 CLI/API 入口拒绝。
- Planner JSON/schema/catalog 错误不进入 Compiler Graph。
- Compiler Graph 错误保留 Analyzer/Checker diagnostics。

### 结构化入口契约

输入：

```json
{
  "payload": {},
  "check": true
}
```

约束：

- `payload` 可以是 Recipe Tool Plan、Workflow IR 或 Legacy JSON。
- 不调用 Planner。
- 不要求 `DEEPSEEK_API_KEY`。
- 成功时返回 Workflow IR、WDL 和 diagnostics。
- 失败时返回结构化 diagnostics，不产生不可信 WDL。

### 安全与隐私契约

- 不记录 API key、authorization header、`.env` 内容或本地 credential path。
- Planner prompt 可以作为调试 artifact 保存，但必须只包含 catalog/recipe 上下文和用户请求。
- 事件 payload 不保存原始模型鉴权信息。
- CLI stdout 保持机器可消费，非 artifact 输出写 stderr。

## 建议 PR 切分

1. **PR 1：Compiler Graph 命名**
   暴露 `compiler_graph`，保留 `agent` 别名，更新 service 层导入和基础测试。

2. **PR 2：Orchestration State 与 Planner node**
   新增上层 state 和 planner node，使用 fake LLM 覆盖成功与失败路径。

3. **PR 3：Orchestration Graph 与 service 路由**
   新增上层 graph，让 `plan_and_compile_workflow` 调用 Orchestration Graph，保留结构化入口直达 Compiler Graph。

4. **PR 4：CLI/API 事件与 artifacts**
   将 Planner 阶段事件和 plan artifact 接入 run service / API history，补齐路由差异测试。

5. **PR 5：文档与回归整理**
   更新 `DEVELOPMENT.md`、`docs/test-cases.md` 和示例说明，运行完整单测与代表性编译验证。

## 验收清单

- [x] `compiler_graph` 成为结构化编译图的明确导出名。
- [x] `agent` 兼容别名仍可用于旧调用，或有明确迁移说明。
- [x] Orchestration State 不污染 `WorkflowState`。
- [x] Planner node 只产出 Recipe Tool Plan 和 trace，不产出最终 WDL。
- [ ] Orchestration Graph 实现 `natural_language_planner -> compiler_graph`。
- [ ] 自然语言入口调用 Orchestration Graph。
- [ ] `--input`、测试入口和 `/api/compile` 直接调用 Compiler Graph。
- [ ] 结构化入口在没有 `DEEPSEEK_API_KEY` 时可运行。
- [ ] Planner 失败不会进入 Compiler Graph。
- [ ] Compiler Graph 失败保留 Analyzer/Checker diagnostics。
- [ ] Planner 事件和 plan artifact 可被 run history 或 SSE 回放。
- [ ] CLI stdout/stderr 契约保持不变。
- [ ] API route tests 覆盖 `/api/runs` 和 `/api/compile` 的分层差异。
- [ ] `docs/test-cases.md` 在测试覆盖意图变化时已同步更新。
- [ ] 相关单元测试通过。

## 后续衔接

P1 完成后，后续阶段应在此边界上演进：

- P2 将 Reviewer LLM 作为受控 IR 修复分支接入 Compiler Graph。
- P3 将 Architect 与 Bioinfo Reviewer 接入 Orchestration Graph。
- P4 在 Planner 前增加 Approved Catalog Tool Retriever。
- P5 增加 Resource Agent，但只允许它修改或建议资源字段。
- P6 以后再处理未知工具、候选定义、实验性镜像和正式镜像晋升。
