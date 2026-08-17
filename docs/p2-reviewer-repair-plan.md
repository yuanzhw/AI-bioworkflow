# P2 Reviewer IR 修复闭环实施计划

本文档细化 P2 阶段的工程工作：把 Reviewer LLM 作为受控 IR 修复分支接入
Compiler Graph。它补充 `DEVELOPMENT.md` 中的路线图摘要，并承接 P1
Orchestration Graph 的分层边界。

## 背景与现状

P1 已建立双层图边界：

```text
自然语言请求
  -> Orchestration Graph
  -> Recipe Tool Plan
  -> Compiler Graph
  -> Workflow IR / WDL / Diagnostic Report

结构化输入
  -> Compiler Graph
  -> Workflow IR / WDL / Diagnostic Report
```

当前 Compiler Graph 负责确定性的结构化编译：

```text
Recipe Tool Plan / Workflow IR / Legacy JSON
  -> IR Normalizer
  -> Analyzer
  -> deterministic Repairer when a safe fix exists
  -> Renderer
  -> Checker
```

现有 deterministic repairer 仍然是第一层修复机制。P2 只在编译链路已经产生
diagnostics，且 deterministic repairer 没有安全修复动作时，引入 Reviewer LLM
提出受约束的 Workflow IR patch。

## P2 目标

P2 的目标是增加一个有界 IR 修复闭环，使 Analyzer 或 Checker 失败后，可以由
Reviewer 提出结构化 Workflow IR 修复建议。

完成后应满足：

- Analyzer 和 Checker 失败可以路由到 Reviewer repair 分支，但必须发生在
  deterministic repairer 已失败或明确放弃修复之后。
- Reviewer 输入是结构化请求，包含当前 Workflow IR、diagnostics、
  `validation_message`、修复历史和 approved Catalog 上下文。
- Reviewer 输出只能是 schema 可校验的 IR patch 或显式 no-op 结果。
- patch 应用范围限制在 Workflow IR 内，并且应用后必须重新经过 Analyzer、
  Renderer 和 Checker。
- 修复轮数有硬上限，最终失败时返回可读的 diagnostic report。
- run events 和 artifacts 能暴露 Reviewer 尝试、已接受 patch、已拒绝 patch 和最终
  diagnostics。

## 非目标

P2 不承担以下工作：

- 不允许任何 LLM 直接生成或修改最终 WDL。
- 不绕过 Analyzer、Renderer、Checker 或 Catalog validation。
- 不引入未知工具、外部工具发现、Candidate ToolSpec 或容器构建行为。
- 不修改 Tool Catalog 条目、command template、runtime image 来源或容器可信策略。
- 不实现 Architect Agent、Bioinfo Reviewer、Resource Agent 或完整 Multi-Agent
  planning。
- 不改变自然语言入口路由，除非是为了把已有 approved Catalog 上下文传给
  Reviewer 请求。
- 不要求结构化确定性编译路径依赖 `DEEPSEEK_API_KEY`。

## 目标 Compiler Flow

```text
Analyzer / Checker failure
  -> deterministic Repairer
       -> safe deterministic fix
            -> Analyzer / Renderer / Checker
       -> no safe deterministic fix
            -> Reviewer Repair Node
                 -> structured IR patch
                 -> patch schema validation
                 -> patch policy validation
                 -> apply patch
                 -> Analyzer / Renderer / Checker
            -> rejected / no-op / exhausted attempts
                 -> Diagnostic Report
```

Reviewer node 是 Compiler Graph 的失败恢复分支，不属于 Orchestration Graph 的
planner sequence。

## 契约草案

P2 应引入明确的 request、patch 和 result model，而不是在 compiler nodes 之间传递
自由 prompt 文本。

### ReviewerRepairRequest

建议字段：

| 字段 | 说明 |
| --- | --- |
| `workflow_ir` | 当前 Workflow IR candidate。 |
| `failure_stage` | `analyzer` 或 `checker`。 |
| `analysis_errors` | Analyzer diagnostics。 |
| `analysis_warnings` | Analyzer warnings。 |
| `validation_message` | Checker 或 WDL validator 输出。 |
| `repair_history` | 已尝试的 deterministic 和 Reviewer repair actions。 |
| `catalog_context` | 避免未知工具和越权工具选择所需的 approved recipe/tool context。 |
| `attempt_index` | 当前 Reviewer 尝试次数。 |
| `constraints` | allowed changes 的机器可读 policy 限制。 |

### ReviewerIRPatch

初始 patch model 应保持保守。建议结构：

| 字段 | 说明 |
| --- | --- |
| `summary` | 人类可读的修复意图。 |
| `actions` | 有序 patch action 列表。 |
| `diagnostic_references` | 触发 patch 的错误信息或 validator 行。 |
| `catalog_references` | 支撑 patch 的 approved tools 或 recipes。 |
| `confidence` | 粗粒度置信度，仅用于 diagnostics，不可用于绕过验证。 |

每个 patch action 应包含 operation、target path、可选 value 和 reason。path 语言必须
限制在 patch policy 明确允许的 Workflow IR 字段内。

### ReviewerRepairResult

建议状态：

- `patch_proposed`
- `no_action`
- `invalid_request`
- `policy_rejected`
- `model_error`

P2 初版不保存 raw Reviewer output；只持久化脱敏后的 parsed patch data、
`rejection_reason` 和必要 diagnostics。

## Patch Policy

P2 初版应采用窄 allowlist。Reviewer patch 只能更新 compiler repair 所需的
Workflow IR 字段，不能修改：

- final WDL text；
- Tool Catalog entries；
- task command templates；
- runtime Docker images；
- container trust fields；
- approved context 之外的 tool IDs 或 recipe IDs；
- 未来 Resource Agent 负责的 resource sizing fields。

初始允许的 patch 区域建议聚焦：

- deterministic rules 无法安全处理的 workflow step ordering；
- 使用已有 workflow inputs 或已有 call outputs 的 call input wiring；
- 引用已有作用域值的 workflow output expressions；
- Workflow IR expression rules 覆盖范围内的有限 expression literal 修复。

任何超出 allowlist 的 patch 都必须在修改 compiler state 之前被拒绝。

## Observability

P2 应复用现有 run artifact contract，避免继续增加固定 artifact 列。

建议事件：

- `node.started` / `node.completed`：`reviewer_repair`；
- `node.failed`：Reviewer provider 或 patch validation 失败；
- `repair.proposed`：产出结构化 patch；
- `repair.rejected`：schema 或 policy validation 拒绝 patch；
- `repair.applied`：patch 被接受并应用。

建议 artifacts：

- `reviewer_repair_request`：脱敏后的结构化 request。
- `reviewer_ir_patch`：已接受或已拒绝的结构化 patch。
- `workflow_ir`：patch 应用后、`repair.applied` 事件前更新。
- `diagnostics`：包含 Reviewer attempt count 的最终诊断报告。

现有 `repair_actions` list 可以继续作为兼容摘要，但结构化 patch 应进入 named
artifacts，避免前端和 API 消费方解析文本 summary。

## 实现拆分

### P2.1 Plan 与契约模型

交付：

- 本计划文档。
- Reviewer request、patch action、patch result 和 patch diagnostics 的 Pydantic
  models。
- 在执行 policy 的模块中用简短注释或 docstring 固定 patch policy。

测试：

- 合法 patch model 可解析。
- 非法 patch model 会失败。
- 尝试编辑 WDL、Catalog、runtime image 或 resource sizing 的 patch 会被拒绝。

### P2.2 Patch Application Layer

交付：

- 一个小型 patch application 模块，接收 Workflow IR 和已校验 patch，返回新的
  Workflow IR candidate。
- 对 forbidden paths 和 unsupported operations 给出清晰 policy error。
- patch 通过 schema 与 policy validation 前，不修改原始 IR object。

测试：

- 允许的 workflow wiring patch 可应用。
- 禁止的 runtime 或 command patch 被拒绝。
- patch 失败时原始 IR 保持不变。
- 应用后的 patch 在 graph re-entry 前仍通过 Workflow IR schema validation。

### P2.3 Reviewer Node 与 Provider Boundary

交付：

- `reviewer_repair` compiler node。
- 可在测试中 fake 的 provider interface。
- prompt construction 只包含结构化 request data 和 approved context。
- structured path 未显式启用 Reviewer 或没有 API key 时，不触发 model call。

测试：

- Reviewer 不可用时 node 返回 no-op，并记录 diagnostics。
- fake provider patch 可被 node 接受并返回 validated patch data。
- provider 输出非法时 node 拒绝 patch，且不应用。

### P2.4 Compiler Graph Routing

交付：

- Analyzer 和 Checker failure routing 先尝试 deterministic repair。
- 只有 deterministic repair 没有安全动作且 repair budget 仍可用时，才进入 Reviewer
  branch。
- 修复次数有硬上限，可共享现有 `repair_count`，也可显式拆分
  deterministic/reviewer counters。

测试：

- deterministic repair 路径行为不变。
- deterministic repair 成功时不调用 Reviewer。
- deterministic repair 放弃且 policy 允许时调用 Reviewer。
- 修复次数耗尽时返回 failed diagnostic report。

当前拆分：

- 第一部分只接入 Analyzer failure routing。deterministic repairer 有安全动作时不
  调用 Reviewer；无安全动作时才进入 Reviewer branch。
- Reviewer 使用独立 `reviewer_attempt_count`，默认最多调用 provider 一次。禁用、
  provider 不可用、拒绝、model error 或预算耗尽都终止该分支并保留 diagnostics。
- 已应用 patch 重新进入 Analyzer、Renderer 和 Checker。
- Checker failure routing 不在第一部分启用，继续使用现有 deterministic repair
  行为，后续独立 PR 再接入 Reviewer。

### P2.5 Run Service 与 API Observability

交付：

- Reviewer start、completion、rejection、application 和 failure 的 run events。
- 脱敏 request 与结构化 patch 的 named artifacts。
- diagnostic summary 或 artifact content 能展示 Reviewer attempt count 和最终状态。

测试：

- Reviewer 尝试后 run snapshot 包含 Reviewer artifacts。
- SSE/history replay 中 `workflow_ir` update 早于 `repair.applied`。
- Reviewer 失败时，run completion 前仍写入 diagnostics。

### P2.6 文档与验收

交付：

- P2 实现落地时更新 `DEVELOPMENT.md` 状态。
- 增加测试时同步更新 `docs/test-cases.md`。
- 只有 Workflow IR schema 或 expression rules 发生变化时，才更新
  `docs/workflow-ir.md`。

验证：

```bash
.venv/bin/python -m unittest discover -v
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

如果实现改动影响生成 WDL，还应生成代表性 WDL，并运行配置的 WDL validator。

## 建议 PR 拆分

1. **Reviewer repair contract models**
   - models、patch policy skeleton、unit tests。
2. **Patch application and validation**
   - policy-enforced patch application、schema revalidation、tests。
3. **Reviewer node and graph routing**
   - fakeable provider boundary、Compiler Graph routing、attempt limits。
4. **Run observability**
   - events、named artifacts、diagnostics、API/run snapshot tests。
5. **Documentation closeout**
   - 行为稳定后更新 roadmap status 和 test coverage docs。

实现 PR 应与前端展示工作分开，除非只需要很小的 UI 改动来确认 artifact contract。

## 验收清单

- [ ] Deterministic repairer 仍然是第一层修复机制。
- [ ] Reviewer 只在 Analyzer 或 Checker 失败，且没有安全 deterministic repair 时触发。
- [ ] Reviewer 输出先经过 schema validation，再经过 patch policy validation。
- [ ] Patch policy 会拒绝 WDL、Catalog、runtime image、command 和 resource sizing
  修改。
- [ ] 已接受 patch 只应用到 Workflow IR，并重新进入 Analyzer、Renderer 和 Checker。
- [ ] 修复次数有硬上限，不能无限循环。
- [ ] 未配置 Reviewer 时，结构化编译路径仍可在没有 API key 的情况下运行。
- [ ] Run history 通过 named artifacts 和 events 暴露 Reviewer 尝试。
- [ ] 最终 diagnostics 能说明成功、拒绝、次数耗尽或 model error。
- [ ] 测试覆盖成功、拒绝、no-op、次数耗尽和 Reviewer 不可用路径。

## 已确认的 P2.1 决策

- Contract 同时保留 `analyzer` 与 `checker` failure stage，便于后续扩展；实现路由
  先覆盖 Analyzer failure，Checker / WDL validation failure 在后续 PR 接入。
- Reviewer provider 结果只持久化脱敏后的 parsed patch、`rejection_reason` 和
  diagnostics；不默认保存 raw Reviewer output。
- `catalog_context` 只传当前 workflow 已使用的 approved recipe/tool metadata，
  不复用完整 Catalog Retriever payload，也不提供候选工具重选上下文。
- Reviewer 尝试次数后续实现宜拆成 deterministic 与 Reviewer 计数，便于 run
  diagnostics 和前端展示区分两类修复来源。

## 已确认的 P2.3 决策

- Reviewer provider 默认禁用；只有调用方显式启用后才允许创建 provider 或调用
  模型。显式启用但缺少 `DEEPSEEK_API_KEY` 时返回 no-op diagnostic，不把该情况
  计为一次模型尝试。
- Recipe Tool Plan 路径只向 Reviewer 传递当前 plan 实际使用并再次通过正式
  Catalog 校验的 recipe、step 和 tool metadata。直接 Workflow IR 没有正式
  Catalog provenance，因此使用空 `catalog_context`，不根据 task 名称、command
  或 runtime 猜测工具。
- Provider boundary 只返回经过 `ReviewerRepairResult` schema 校验的结果。raw
  provider response 不进入 Compiler state；schema error 只保留不含原始值的字段
  位置和校验消息。
- Reviewer node 使用独立 `reviewer_attempt_count` 和结构化 request、patch、
  rejection reason、diagnostics state。P2.3 不添加 Compiler Graph edge；
  Analyzer failure routing 和 Checker failure routing 按后续 PR 分别接入。
- Policy rejection 与 application failure 使用不同异常类别。前者表示越过 P2
  allowlist，后者表示 policy 允许的 patch 无法安全应用到当前 Workflow IR。

## 已确认的 P2.4 Analyzer Routing 决策

- `build_compiler_graph(...)` 通过显式注入 Reviewer node 启用模型路径；默认导出的
  `compiler_graph` 使用 disabled Reviewer，不依赖 API key。
- Analyzer failure 始终先尝试 deterministic repair。只有没有安全动作，或
  deterministic budget 已耗尽时，才进入 Analyzer Reviewer branch。
- Reviewer provider 默认最多调用一次，预算与 `repair_count` 分离。预算耗尽时不
  再创建或调用 provider，并保留已有 parsed patch、rejection reason 和 diagnostics。
- 只有 `reviewer_patch_applied=True` 才重新进入 Analyzer；其他 Reviewer 状态全部
  结束当前 Compiler Graph 分支。
- Checker failure 通过 `analysis_errors` 为空与 Analyzer branch 隔离，本 PR 不改变
  Checker routing。
