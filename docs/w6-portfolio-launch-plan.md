# W6 部署与作品集打磨工作拆解

本文档记录 Web 产品化路线中 `W6` 阶段的实施范围、任务拆分和验收口径。`W6` 的目标不是继续扩展新的前端产品功能，而是把 W0-W5 已经完成的 workbench、run history、DAG 审阅和失败回放包装成可以公开访问、快速理解、适合求职展示的作品集 demo。

## 阶段定位

截至 `W5`，前端已经完成最小作品集演示闭环：

1. 从 `/workspace?example=rnaseq-deg` 创建一次结构化 RNA-seq compile run。
2. 在工作台查看 SSE timeline、run snapshot、Plan、Workflow IR、WDL、Diagnostics 和失败摘要。
3. 在 `/runs` 回看持久化 run history。
4. 在 `/runs/[runId]` 回放 events、artifacts、diagnostics 和 Workflow IR DAG。
5. 在 `/catalog` 查看已批准的 recipe / tool catalog 展示入口。

`W6` 负责把这些能力打磨成对外可展示的产品入口：访问者不需要阅读完整开发文档，也能在 1-2 分钟内理解项目价值、架构边界和演示路径。

完成 `W6` 后，前端主线进入 **feature freeze**：除 bugfix、响应式 polish、文案微调和后续 Agent 能力带来的小型展示增量外，不再继续规划独立的 W7/W8 前端功能阶段。

## 进入条件

- `W4` 工作台已接入真实 run 生命周期、SSE timeline、snapshot 轮询和 artifact tabs。
- `W5` 已完成真实 run history、详情页回放、Workflow IR DAG、失败 run 摘要和结构状态语义。
- README、DEVELOPMENT、`docs/w4-workbench-plan.md` 和 `docs/w5-dag-history-plan.md` 已把 W4/W5 标记为完成。
- 本地开发入口 `scripts\dev_local.ps1` 可以同时启动 FastAPI 和 Next.js。

## 产品目标

`W6` 的产品目标是让项目从“功能已经能跑”推进到“别人能快速看懂并愿意点开试用”。

首屏和文档叙事应强调：

- 这是一个 bioinformatics workflow compiler / workbench demo。
- LLM 只负责自然语言规划到 Recipe Tool Plan，不直接生成最终 WDL。
- Workflow IR、Analyzer、Repairer、Renderer 和 Checker 形成确定性编译闭环。
- Web 层展示可审计 run 过程、结构化 artifacts、Workflow IR DAG 和失败回放。
- 当前 demo 的稳定路径是 RNA-seq DEG 示例；自然语言入口依赖 planner 环境变量。

## 任务拆分

### 1. 作品集首页与导航打磨

目标：让首页成为清晰的 demo hub，而不是只承担项目介绍。

需要完成：

- 首屏直接说明项目名称、领域、核心能力和稳定 demo 入口。
- 将 `/workspace?example=rnaseq-deg`、`/runs`、`/catalog` 作为主要导航路径。
- 首页文案突出工程实现、编译器边界、生信建模和可观测性，不使用外部工具签名或自动生成口吻。
- 首页内容应让访问者知道 demo 能看到什么：run timeline、Plan / IR / WDL、DAG 和 failed replay。
- 保持页面信息密度适合工程作品集，避免做成营销式空泛 landing page。

### 2. Demo readiness 与示例路径固化

目标：保证公开演示时最短路径稳定、可解释、可恢复。

需要完成：

- 明确推荐演示路径：
  - `/workspace?example=rnaseq-deg` 创建结构化示例 run。
  - 运行成功后进入详情页查看 DAG。
  - `/runs` 回看历史记录。
  - `/catalog` 查看 recipe / tool catalog。
- 确认结构化 RNA-seq 示例不依赖 `DEEPSEEK_API_KEY`。
- 自然语言模式在 planner 环境不可用时展示清晰失败诊断。
- API 不可达、空历史、失败 run、无 Workflow IR 的 DAG 空状态都应可读。
- 示例按钮、空状态和详情页返回路径保持一致，不让用户卡在无入口页面。

### 3. 架构图与系统叙事

目标：用一张或少数几张图解释系统边界，降低读者理解成本。

建议展示：

```text
Natural Language / Structured Payload
  -> Recipe Tool Plan
  -> Workflow IR
  -> Analyzer / Repairer
  -> Deterministic WDL Renderer
  -> WDL Checker
  -> Run Events / Artifacts / DAG
```

需要完成：

- 在 README、首页或专门文档中加入系统流程图。
- 明确 Next.js 只展示 API 产物，不生成或修复 Plan、IR、WDL。
- 明确 FastAPI 复用 Python service，不通过 shell 调用 CLI。
- 明确 DAG 表达 Workflow IR 结构审阅，不表达真实 workflow call 执行状态。
- 图示和文案保持作品集视角，避免把 roadmap-only Agent 说成已完成能力。

### 4. 部署说明与环境变量收口

目标：让本地和公开部署的运行边界清晰可复现。

实施入口：[部署与运维手册](./deployment.md)。

需要完成：

- 更新或补充部署文档，覆盖 FastAPI、Next.js、SQLite 展示库和 CORS。
- 记录关键环境变量：
  - `NEXT_PUBLIC_API_BASE_URL`
  - `AI_BIOWORKFLOW_API_HOST`
  - `AI_BIOWORKFLOW_API_PORT`
  - `AI_BIOWORKFLOW_CORS_ORIGINS`
  - `DEEPSEEK_API_KEY`
  - `WDL_VALIDATOR`
- 说明结构化 compile demo 不需要 planner API key。
- 说明公开 demo 如需长期保存或并发访问，应评估 PostgreSQL 或重置策略。
- 避免提交 `.env`、API key、本地凭证路径或部署私有配置。

### 5. 截图、录屏与 README 导航

目标：沉淀可用于 GitHub、简历和作品集页面的展示资产。

建议准备：

- 工作台创建 RNA-seq 示例 run 的截图。
- 成功 run 的 Plan / IR / WDL / Diagnostics tabs 截图。
- DAG 详情面板截图，突出 scatter、runtime docker 和依赖边。
- 失败 run 摘要或 diagnostics 回放截图。
- 30-90 秒录屏，覆盖从运行示例到详情页 DAG 的主路径。

README 应提供：

- 最短本地启动路径。
- 主要 demo URL。
- W4/W5/W6 文档链接。
- 架构说明入口。
- 当前已完成能力和下一阶段 backend / Agent 方向的区别。

### 6. 最终前端 QA 与 feature freeze

目标：在 W6 完成后明确前端主线收口，不继续扩大独立产品范围。

需要检查：

- 桌面和移动视口下首页、工作台、历史页、详情页和 catalog 页无明显布局错位。
- 主要按钮文案和导航入口一致。
- 失败、空状态、loading、API 不可达状态都可理解。
- `npm run lint`、`npm run test:graph` 和 `npm run build` 通过。
- 如仅修改前端展示和文档，不需要额外生成 WDL；如触碰 renderer、recipe resolution 或 validation path，则补充代表性 WDL 语法校验。

完成后前端状态定义为：

- 独立前端功能开发基本结束。
- 保留 bugfix、响应式 polish、截图更新、文案微调。
- 后续 P2-P10 Agent 能力如果新增结构化 artifact 或事件类型，前端只做配套展示，不再重新设计 workbench / history / DAG 主框架。

## 建议 PR 顺序

1. **W6 portfolio landing polish**：首页、导航、demo 入口和作品集文案。
2. **W6 demo readiness**：示例路径、失败/空状态、API 不可达状态和按钮入口一致性。
3. **W6 architecture visuals**：架构图、README/首页系统叙事和 DAG 状态边界说明。
4. **W6 deployment docs**：部署说明、环境变量、CORS 和公开 demo 注意事项。
5. **W6 screenshots and final QA**：截图/录屏资产、README 导航和最终 lint/build/test。

当前实施进度：

| 阶段 | 状态 | 实施记录 |
| --- | --- | --- |
| W6 portfolio landing polish | 已完成 | 首页和导航已形成 demo hub，稳定入口覆盖 RNA-seq 示例、run history、Catalog 和 API 文档。 |
| W6 demo readiness | 已完成 | 工作台、历史、详情和 Catalog 已统一恢复入口，并补充 API 不可达等可读失败状态。 |
| W6 architecture visuals | 已完成 | README 已补充确定性编译链、Web/service 边界和 DAG 结构语义。 |
| W6 deployment docs | 已完成 | 部署手册已覆盖本地/公开拓扑、环境变量、CORS、SQLite 持久化、回滚和匿名 demo 安全边界。 |
| W6 screenshots and final QA | 已完成 | README 已加入 3 张固定视口截图与 [90 秒演示分镜](./portfolio-demo-script.md)，并完成桌面/移动响应式检查和前端 lint/test/build。 |

展示资产：

- [RNA-seq 工作台成功 run](./assets/workspace-rnaseq-run.png)
- [Workflow IR DAG 与节点详情](./assets/run-workflow-dag.png)
- [Recipe / Tool Catalog 边界](./assets/catalog-boundary.png)

如果某个 PR 只改文档，可以不运行前端 build，但应至少检查 Markdown 链接和文案一致性。涉及前端代码的 PR 应运行前端验证。

## W6 不做

- 不新增新的核心产品页面，除非是承载架构说明或 demo assets 的轻量文档页。
- 不实现用户权限、登录、计费、多租户或长期审计系统。
- 不接入真实 Cromwell / miniwdl 执行监控 UI；真实执行仍属于 execution backend 轨道。
- 不把 DAG 改成 call-level running / completed / failed 状态，除非后端未来提供 `step_id` / `call_id` 级事件。
- 不实现 Architect Agent、Bioinfo Reviewer、Resource Agent、External Retrieval 或容器构建 UI；P2 有界 Reviewer IR 修复已在后端独立完成。
- 不让前端生成、修复或补全 Plan、Workflow IR、WDL。

## 验收标准

功能验收：

- 首页能在首屏或紧邻首屏提供稳定 demo 入口。
- `/workspace?example=rnaseq-deg`、`/runs`、`/runs/[runId]` 和 `/catalog` 构成清晰演示路径。
- 成功 run 和失败 run 都能被解释：timeline、artifacts、diagnostics、DAG 的职责边界清楚。
- README 和 DEVELOPMENT 能引导读者找到 W4/W5/W6 文档、启动命令和 demo URL。
- 部署文档明确本地开发、公开 demo、环境变量和 secrets 边界。
- 至少准备一组可用于作品集展示的截图或录屏计划；如果实际资产尚未提交，应在 issue 或后续 PR 中明确路径。

工程验收：

- 只改文档时，确认链接和阶段状态一致。
- 修改前端代码时运行：

```powershell
cd web
npm run lint
npm run test:graph
npm run build
```

- 修改后端 API、service 或持久化契约时运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

- 修改 WDL 输出路径时按项目规则生成代表性 WDL 并运行语法校验。

## 收口判断

当 `W6` 验收标准全部满足后，前端可以正式标记为“作品集 demo 主线完成”。后续主要精力应转向：

- P3 Architect 与 Bioinfo Reviewer 的职责分层。
- 更丰富的 recipe / tool catalog 与检索评估。
- 新增后端/Agent 产物的配套结构化展示。
- 真实执行与容器生命周期能力。

前端只随着这些后端能力做必要展示，而不再独立扩展新的产品框架。
