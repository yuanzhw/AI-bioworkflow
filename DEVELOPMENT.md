# AI-bioworkflow 开发与架构指南

本文档用于记录基于 LangGraph 的 WDL 工作流生成系统目录结构与核心设计理念，以供后续开发参考。

当前工程方向是“Workflow IR 编译器 + LLM 辅助规划/修复”，而不是让大模型直接手写最终 WDL。标准 IR 到 WDL 的过程必须保持确定性、可测试。

## 📁 核心目录结构

```text
AI-bioworkflow/
├── .env                  # 环境变量配置（DEEPSEEK_API_KEY等，勿提交至Git）
├── pyproject.toml        # uv 依赖配置文件
├── README.md             # 项目基础说明
├── DEVELOPMENT.md        # 本开发指南
├── docs/
│   └── workflow-ir.md    # Workflow IR 结构、表达式规则与后端映射规范
│
├── src/                  # 核心源代码目录
│   ├── __init__.py
│   │
│   ├── state.py          # 1. 状态定义：定义 Agent 的全局状态 (WorkflowState)
│   │
│   ├── schema.py         # 2. Workflow IR 的 Pydantic Schema 与兼容转换
│   │
│   ├── analyzer.py       # 3. IR 静态分析：引用、类型、DAG 顺序等检查
│   ├── repairer.py       # 4. IR 保守修复：call 顺序、输出字面量等确定性问题
│   ├── nl_planner.py     # 5. 自然语言需求 -> Recipe Tool Plan
│   │
│   ├── catalog/          # 6. 生信工具目录：工具 schema、YAML 定义与 plan resolver
│   │
│   ├── recipes/          # 7. 分析配方目录：配方 schema 与步骤定义
│   │
│   ├── prompts.py        # 8. 提示词管理：存放自然语言 Planner Prompt 模板
│   │
│   ├── renderers/        # 9. 确定性代码生成器
│   │   ├── wdl.py        # IR -> WDL
│   │   └── templates/
│   │       └── workflow.wdl.j2
│   │
│   ├── tools/            # 10. 工具箱：存放外部工具封装
│   │   ├── __init__.py
│   │   └── validator.py  # WDL validator wrapper
│   │
│   ├── nodes/            # 11. 工作节点：LangGraph 的具体执行工位
│   │   ├── __init__.py
│   │   ├── ir_normalizer.py # 将标准 IR、Legacy JSON 或 Recipe Tool Plan 标准化为 Workflow IR
│   │   ├── analyzer.py   # 调用 IR 静态分析
│   │   ├── repairer.py   # 调用 IR repairer 并记录修复动作
│   │   ├── renderer.py   # 调用 WDL renderer
│   │   └── checker.py    # 调用 WDL validator
│   │
│   └── graph.py          # 12. 核心图纸：组装 nodes 和 tools 的 StateGraph
│
├── tests/                # 单元与集成测试
│   ├── test_tools.py     
│   └── test_graph.py     
│
└── main.py               # 项目入口，负责接收用户输入并触发 workflow
```

## 🧠 核心模块设计理念

1. **状态管理 (`state.py`)**：必须保持强类型。除了 LangGraph 原生的 `messages` 列表，还需要定义好接收前端传入的 `parsed_json`、标准化后的 `workflow_ir`、流转中的 `current_wdl`、`analysis_errors` 和 `validation_message`。
2. **提示词隔离 (`prompts.py`)**：绝对不要将长篇大论的 System Prompt 硬编码在业务逻辑文件中。
3. **IR 优先 (`schema.py`)**：workflow 的调用关系与 task 的定义必须分离。`workflow.steps` 表达 call/scatter DAG，`workflow.calls` 作为旧输入兼容，`tasks` 表达可复用 task 模板。
4. **自然语言只到 Plan (`nl_planner.py`)**：LLM 的职责是把用户需求转成 Recipe Tool Plan，不直接生成 WDL。Planner 失败需要区分 JSON 解析、plan schema、recipe/catalog 校验三类错误，便于调试真实模型输出。
5. **Catalog 先于自由生成 (`catalog/`, `recipes/`)**：常见生信工具、版本、参数、runtime 与配方步骤应沉淀为结构化目录，Planner 可以把 Recipe Tool Plan 解析成标准 IR。
6. **静态分析先于渲染 (`analyzer.py`)**：在生成 WDL 前先检查 task 是否存在、输入是否齐全、上游输出引用是否有效、基础类型是否匹配。
7. **保守修复 (`repairer.py`)**：自动修复只处理可以由 IR 本身确定的问题，例如 call 拓扑顺序和明显漏引号的 File/String 输出字面量；无法确定的错误应保留给人工或后续 LLM repairer。
8. **确定性渲染 (`renderers/`)**：标准 IR 到 WDL 必须由模板或普通代码生成，不应依赖 LLM 的自由文本输出。
9. **工具封装 (`tools/`)**：所有与底层操作系统或第三方生信软件的交互（如调用 `java -jar womtool.jar validate`）都必须封装为独立 Tool，确保生成代码闭环验证。
10. **Catalog 镜像权威来源 (`catalog/`)**：每个 Tool Catalog 条目必须显式声明 `runtime.docker`。编译链路不搜索、不猜测、不联网补全镜像；新增或升级工具时由维护者明确选择镜像并写入 catalog。
11. **辅助脚本镜像化 (`containers/`)**：tximport、DESeq2、MultiQC 等辅助脚本随项目镜像构建进入容器，不作为 WDL 输入，也不内联到 command 中。
12. **渐进式重构**：先保证 Natural Language -> Recipe Tool Plan -> IR -> WDL -> WDL syntax validation 的主链路稳定，再逐步扩展 recipe/tool catalog、可解释错误报告与 LLM repairer。

## Workflow IR 规范

Workflow IR 是本项目的核心编译契约。字段结构、表达式系统、scatter 类型提升、Recipe Tool Plan 到 IR 的转换，以及 IR 到 WDL 1.0 的映射规则，统一维护在：

👉 **[Workflow IR 规范与后端映射](./docs/workflow-ir.md)**

后续新增 IR 数据结构、表达式形式、renderer backend 或 Nextflow 支持时，应先更新该规范，再实现代码与测试。

## 项目展示定位与 Web 产品化目标（规划中）

本项目同时承担求职作品集项目的职责：展示开发者能够将生物信息学领域知识转化为可解释、可测试、可交付的 AI Agent 工程系统。因此 Web 层不是简单的结果展示壳，而是用于呈现 Agent 决策过程、结构化中间产物、验证闭环和领域可信边界的产品入口。

Web 产品化遵循以下目标：

1. **突出 Agent 工程能力**：页面应能够展示从自然语言需求、规划过程、Workflow IR、静态分析/修复到 WDL 校验结果的完整链路，而不是只提供一个返回代码的聊天框。
2. **突出领域建模能力**：通过 recipe、tool catalog、工作流 DAG、运行输出和科学性告警展示生物信息学问题如何被结构化。
3. **突出可解释与可审计性**：关键状态变化、修复动作、错误诊断、候选工具来源和镜像可信等级应能够被记录并在详情页回看。
4. **保留核心编译器独立性**：Web API、CLI 与测试复用相同的 Python 服务层；UI 不侵入 Workflow IR 到 WDL 的确定性编译路径。
5. **控制非核心投入**：第一版优先完成可演示的 Agent 工作台，不提前引入用户权限、计费、复杂微服务或大规模任务调度基础设施。

## 当前端到端调用链路与编译子图

当前自然语言 Planner 尚未注册为 LangGraph 节点。`main.py` 在图外先调用 `src/nl_planner.py` 将自然语言需求转换为 Recipe Tool Plan，再将结构化 plan 提交给 LangGraph。`src/graph.py` 当前注册的是面向结构化输入的 **Compiler Graph**，而不是完整的自然语言编排图。

### 当前端到端调用链路

```text
自然语言请求
  ↓
main.py -> nl_planner          # 图外 LLM 调用，生成 Recipe Tool Plan
  ↓
Recipe Tool Plan
  ↓
Compiler Graph

--input 开发/调试入口
  ↓
Recipe Tool Plan / Workflow IR / Legacy JSON
  ↓
Compiler Graph                 # 不需要 LLM 或 API Key
```

### 当前 Compiler Graph (`src/graph.py`)

```text
START
  ↓
ir_normalizer     # 标准 IR / Legacy JSON / Recipe Tool Plan -> Workflow IR steps
  ↓
analyzer_node    # IR 静态分析
  ↓
renderer_node    # Workflow IR steps/scatter -> WDL
  ↓
checker_node     # WDL syntax validation
  ↓
END

analyzer_node 或 checker_node 发现错误时，如果 repairer 还有重试预算，会进入：

repairer_node    # 可确定修复时更新 IR
  ↓
analyzer_node    # 修复后重新分析、渲染、校验
```

## 已完成的容器管理边界

- [x] **Catalog 镜像权威来源**：正式工具条目显式声明 `runtime.docker`，编译链路不搜索、不猜测、不联网补全镜像。
- [x] **自建工具镜像管理规范初版**：对于需要项目维护脚本的工具，在 `containers/<tool>/<version>/` 管理 Dockerfile、脚本和 smoke test；构建完成后将最终镜像引用写入 Tool Catalog。
- [x] **镜像修订版 tag**：项目维护镜像使用 `<software-version>-rN` tag，例如 `deseq2:1.42.1-r2`。目录版本和 Tool Catalog `version` 字段表示上游软件版本；`image_revision.txt` 表示项目镜像修订号。
- [x] **当前辅助工具镜像**：tximport、DESeq2 与 MultiQC 已具备项目内构建定义，作为 RNA-seq DEG 可执行流程的依赖。

## 已完成的 P0 执行验证边界

- [x] **Execution Backend 抽象**：默认 disabled 后端和 Cromwell REST backend 已落地，测试覆盖 availability、submit、polling、outputs、metadata 与失败语义。
- [x] **Cromwell runner 基线**：独立 Cromwell server 已运行，Docker 与相关执行 backend 已可用。
- [x] **e2e 镜像就绪**：RNA-seq DEG tiny e2e 所需镜像已拉取到 runner 本地。
- [x] **真实 tiny e2e 手动验证**：已通过显式 opt-in 的 Cromwell e2e 入口手动运行真实 RNA-seq tiny workflow。

P0 后续工作重点不再是证明 runner 能否运行，而是把已验证流程沉淀为便捷检查脚本、可复现验证摘要和更清晰的作品集展示材料。

## 当前开发操作入口

日常开发优先使用以下入口，避免绕过 service、Compiler Graph 或执行后端边界。

| 场景 | 命令 | 说明 |
| --- | --- | --- |
| P0 本地快速检查 | `powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1` | 运行单测、代表性 RNA-seq WDL 编译和语法校验；不触发真实 e2e。 |
| 结构化编译 | `uv run main.py --input examples/rnaseq_deg_recipe_plan.json --output outputs/rnaseq_deg.wdl` | 直接走确定性 Recipe Tool Plan / IR 编译路径，不需要 API key。 |
| 自然语言规划编译 | `uv run main.py --prompt-file examples/rnaseq_deg_request.txt --output outputs/rnaseq_deg.wdl` | 先生成 Recipe Tool Plan，再进入确定性编译链路；需要 `DEEPSEEK_API_KEY`。 |
| FastAPI 开发服务 | `.\.venv\Scripts\python.exe -m src.api.server` | 默认监听 `127.0.0.1:8010`，避开 Cromwell 的 `8000`。 |
| 真实 Cromwell tiny e2e | `powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1 -RunE2E -CromwellUrl http://localhost:8000 -WindowsFixtureRoot C:\data\ai-bioworkflow-tiny -CromwellFixtureRoot /data/ai-bioworkflow-runner/tiny` | 显式 opt-in；`check_p0.ps1` 委托 `run_cromwell_tiny_e2e.ps1` 准备 fixture、同步 runner 并运行真实 e2e。 |

## 未来架构原则（规划中）

后续智能化能力遵循以下总原则：

> LLM 可以扩展规划、审查、检索、诊断和环境准备能力；Workflow IR、正式 Catalog 准入、容器可信等级、确定性渲染和验证闭环必须保持结构化、可审计、可约束。

已确认的设计决策：

1. **Reviewer LLM 只能修改 IR**：Reviewer 可以读取当前 IR、分析错误、WOMtool stderr 和历史修复记录，并输出结构化 IR patch 或候选 IR；不能直接改写最终 WDL、绕过验证或引入未经准入的正式工具。
2. **Bioinfo Reviewer 只告警与建议**：科学性审查节点负责指出缺失步骤、方法学风险和推荐调整，但最终流程方案始终由 Architect Agent 决定。
3. **Resource Agent 只处理资源字段**：该节点仅建议或覆盖 `cpu`、`memory`、`disks` 等资源字段，记录修改理由；不负责镜像选择、工具选择或分析方法选择。
4. **Catalog 内检索优先**：Planner 不必永久读取全量正式工具库；未来由 Tool Retriever 从 approved Catalog 中高召回筛选候选工具，再由完整 Catalog 做最终校验。
5. **未知工具先形成 Candidate ToolSpec**：外部检索发现的新工具必须先生成带来源、版本依据、未确认字段和测试状态的候选定义，才能进入镜像构建环节。
6. **临时镜像可服务当前任务**：自动构建并通过最小验证的临时镜像允许在隔离环境内用于当前探索任务，前端必须以文字提示可信等级和风险。
7. **正式 Catalog 只引用已验证 digest**：可复用的正式工具镜像应固定为经过验证的 digest，而不是依赖可变 tag。
8. **GitHub Actions 只负责发布和晋升**：正式镜像推送、provenance / attestation 及 Catalog 准入可由 GitHub Actions 承担；未来的即时构建由专用隔离 builder 承担，避免阻塞用户任务。
9. **IR 到 WDL 保持确定性**：任何新增 Agent 都不替代 renderer，也不允许绕过 Analyzer 与 Checker。
10. **全程可追踪**：检索来源、Agent 建议、IR 修改、资源覆盖、镜像验证和回退结果均应进入任务审计记录。
11. **双层图边界**：上层 Orchestration Graph 承担自然语言与多 Agent 协作，下层 Compiler Graph 接受结构化输入并完成 IR 校验与 WDL 编译；结构化调试入口始终可以绕过上层图直达编译子图。

## 目标智能流程（规划中）

目标架构拆分为两个职责清晰的 LangGraph 图，而不是将所有 LLM 节点直接接到现有编译子图之前。

### Orchestration Graph

```text
用户自然语言 / 文献方法描述
  ↓
Intent Router              # 判断直接规划、文献解析或未知工具扩展路径
  ↓
Architect Agent            # 确定分析目标、步骤与预期输出
  ↓
Bioinfo Reviewer           # 仅给出科学性告警和建议，反馈给 Architect
  ↓
Catalog Tool Retriever     # 在 approved Catalog 内召回候选 recipe / tools
  ↓
Planner / Tool Resolver    # 生成 Recipe Tool Plan，完整 Catalog 最终校验
  ↓
Resource Agent             # 仅补充有来源记录的资源建议或 override
  ↓
Recipe Tool Plan
  ↓
Compiler Graph             # 调用稳定编译子图
```

### Compiler Graph

```text
Recipe Tool Plan / Workflow IR / Legacy JSON
  ↓
IR Normalizer -> Analyzer -> Renderer -> Checker
                   ↑              │
                   └─ Repairer <──┘  # analyzer/checker 失败时触发
  ↓
Validated Workflow IR / WDL / Diagnostic Report
```

编译子图仍保留以下直接入口：

```text
--input / 测试 / 集成调用 -> Compiler Graph
```

### 两层状态与入口边界

| 层级 | 负责的数据与行为 | 不负责的行为 |
| --- | --- | --- |
| Orchestration Graph | 自然语言请求、planner trace、审查告警、检索候选、资源建议、Recipe Tool Plan | 不渲染最终 WDL，不绕过正式 Catalog 校验 |
| Compiler Graph | 结构化输入、Workflow IR、静态分析、受控修复、WDL 渲染、语法验证 | 不负责理解自然语言或自由选择未知工具 |

落地后，CLI 和前端入口遵循以下路由：

- 自然语言输入调用 Orchestration Graph，再将产出的 Recipe Tool Plan 提交给 Compiler Graph。
- `--input`、测试和集成接口继续直接调用 Compiler Graph，保持无 LLM、无 API Key 的确定性编译模式。
- Reviewer LLM 未来可以作为 Compiler Graph 中的受控失败恢复分支接入，但只能修改 IR；IR 到 WDL 的 renderer 仍然保持确定性。

## Web 展示系统技术方案（规划中）

### 技术选型

Web 展示系统与 Agent 核心代码继续保留在同一仓库中，以便 Workflow IR、API 契约、前端可视化和集成测试能够在同一次变更中演进。前端和后端作为独立进程部署，通过 HTTP API 与事件流通信。

| 层级 | 选型 | 在本项目中的职责 |
| --- | --- | --- |
| Agent / Compiler Core | Python + LangGraph + Pydantic + Jinja2 + WOMtool | 维护结构化状态、规划/编译流程、确定性输出和验证闭环 |
| Backend API | FastAPI + Pydantic | 暴露 workflow 创建、查询、catalog 读取、历史详情和事件流接口 |
| 实时状态推送 | Server-Sent Events (SSE) | 将单次 Agent run 的节点状态、诊断与产物更新推送给工作台 |
| 数据持久化 | SQLite（展示版）/ PostgreSQL（部署升级） | 保存 run 摘要、状态事件、结构化产物和错误记录 |
| Frontend | Next.js + TypeScript | 承载介绍站、交互工作台、DAG 视图和历史详情页 |
| UI 与样式 | Tailwind CSS + shadcn/ui | 建立一致、可扩展的产品界面组件 |
| DAG 可视化 | React Flow | 展示 Workflow IR 中 steps/calls/scatter 的依赖图 |
| 结构化产物展示 | Monaco Editor 或轻量只读代码查看器 | 展示 JSON Plan、Workflow IR 和 WDL，并支持复制/对比 |

第一阶段使用 SSE 而不是 WebSocket：当前主要需求是后端向前端单向推送执行阶段与中间产物，SSE 的实现和调试成本更低。当后续引入运行中人工批准、交互式修订或双向协作时，再评估 WebSocket。

### 系统边界

```text
Next.js Web Application
  ├─ 项目介绍页 / 示例案例
  ├─ Workflow 生成工作台
  ├─ 工作流 DAG 可视化
  └─ Agent 执行历史详情
          │
          │ REST API + SSE
          ▼
FastAPI Application
  ├─ 请求/响应 Schema 与错误映射
  ├─ Run 管理、事件记录与结果查询
  ├─ Recipe / Tool Catalog 查询
  └─ Application Service Layer
          │
          ├─ 自然语言入口 -> Orchestration Graph -> Compiler Graph
          └─ 结构化入口 -------------------------> Compiler Graph
                                                       │
                                                       ▼
                              Workflow IR / WDL / Diagnostics / Artifacts
```

边界约束：

- Next.js 不实现 Agent 编排、Catalog 解析或 WDL 生成逻辑，也不以其 API Route 取代 Python 后端。
- FastAPI 不通过 shell 调用 `main.py`；应抽取可复用的 Python application service，供 CLI 与 API 共同调用。
- `src/schema.py` 与 Workflow IR 规范仍是编译契约权威来源；前端展示模型从公开 API schema 派生或显式同步。
- API 层可以管理 run、流式事件和持久化，但不能绕过 Analyzer、Renderer 与 Checker 直接产生最终 WDL。
- 页面显示的修复、告警、容器可信等级与执行状态必须来自可保存的结构化记录，不能仅依靠前端拼装文案。

### 目标仓库目录

以下目录是在现有核心代码基础上的产品化目标结构，按迭代逐步创建：

```text
AI-bioworkflow/
├── src/
│   ├── ...                         # 现有 Agent / Compiler 核心模块
│   ├── services/                   # CLI 与 FastAPI 共用的应用服务层
│   │   ├── workflow_service.py     # 创建/编译 workflow run
│   │   └── catalog_service.py      # recipe / tool 查询
│   └── api/
│       ├── app.py                  # FastAPI app factory 与中间件
│       ├── models/                 # 对外请求/响应 DTO
│       └── routes/                 # workflows、runs、catalog、events
├── web/                            # Next.js + TypeScript 前端
│   ├── app/
│   │   ├── page.tsx                # 项目介绍页
│   │   ├── workspace/              # Workflow 生成工作台
│   │   ├── workflows/[id]/graph/   # DAG 可视化页
│   │   └── runs/[id]/              # Agent 执行历史详情页
│   ├── components/
│   │   ├── workflow-graph/         # React Flow 图组件
│   │   ├── run-timeline/           # Agent 阶段与事件组件
│   │   └── code-viewer/            # Plan / IR / WDL 查看组件
│   └── lib/                        # API client、SSE client 与 TypeScript types
├── tests/
│   ├── ...                         # 现有核心测试
│   └── api/                        # FastAPI contract / integration tests
└── main.py                         # CLI，改为调用 services 层
```

### 页面范围与展示重点

| 页面 | 核心内容 | 招聘展示价值 | 第一版完成标准 |
| --- | --- | --- | --- |
| 项目介绍页 | 问题背景、Agent/Compiler 架构、RNA-seq DEG 示例、技术栈与项目边界 | 快速说明生信经验如何转化为 Agent 产品能力 | 可以从介绍跳转到预填充示例的工作台 |
| Workflow 生成工作台 | 自然语言输入、执行阶段流、Plan / IR / WDL 标签页、校验和修复信息 | 展示端到端 Agent 工程链路与可解释输出 | 提交一个示例请求后可实时看到状态与最终校验结果 |
| 工作流 DAG 可视化页 | calls、scatter、依赖边、输入输出以及节点状态 | 展示结构化建模、领域工作流理解和可视化能力 | 能从生成的 IR 渲染 RNA-seq 示例 DAG 并选中节点查看详情 |
| Agent 执行历史详情页 | 原始请求、事件时间线、模型/编译步骤、修复动作、产物与诊断 | 展示可观测性、审计能力和失败处理意识 | 刷新页面后仍可重看一次成功或失败 run 的关键产物 |

第一版工作台重点呈现的阶段为：

```text
需求输入
  -> Planner / Recipe Tool Plan
  -> IR Normalizer
  -> Analyzer
  -> Repairer（仅触发时显示）
  -> Renderer
  -> WOMtool Checker
  -> Validated WDL 或 Diagnostic Report
```

### 后端 API 与事件契约

API 第一版围绕“生成并查看一次可解释 workflow run”设计，不直接引入登录、多租户或正式执行集群。

当前 W2 已落地的是持久化 run API：API 层接收请求、创建展示级 run 记录，并通过后台任务调用 application service / Compiler Graph。FastAPI 只负责 HTTP 入口、状态查询和 SSE 输出，不实现 planner、catalog resolver、Analyzer、Renderer 或 Checker 逻辑。

本地开发端口约定：

| 服务 | 地址 |
| --- | --- |
| Cromwell server | `http://127.0.0.1:8000` |
| AI-bioworkflow FastAPI | `http://127.0.0.1:8010` |

FastAPI 开发服务通过以下命令启动：

```powershell
.\.venv\Scripts\python.exe -m src.api.server
```

`src.api.server` 默认使用 `127.0.0.1:8010`，避免与 Cromwell 的 `8000` 端口冲突。需要临时覆盖时可设置 `AI_BIOWORKFLOW_API_HOST` 或 `AI_BIOWORKFLOW_API_PORT`。

W2 当前接口：

| Endpoint | 用途 | 主要返回 |
| --- | --- | --- |
| `POST /api/runs` | 从自然语言需求创建一次 Agent run | `run_id`、初始状态、事件流 URL |
| `POST /api/compile` | 从 Recipe Tool Plan 或 Workflow IR 创建一次确定性编译 run | `run_id`、初始状态、事件流 URL |
| `GET /api/runs/{run_id}` | 查询详情页所需的 run 快照 | 请求、状态、Plan、IR、WDL、诊断、修复记录 |
| `GET /api/runs/{run_id}/events` | 订阅或回放当前 run 的 SSE 事件 | 节点开始/完成/失败、产物更新、最终结果 |
| `GET /api/recipes` | 查询支持的分析配方列表 | recipe 元数据、required inputs 与步骤 |
| `GET /api/recipes/{recipe_id}` | 查询单个分析配方 | recipe 元数据、required inputs 与步骤 |
| `GET /api/tools` | 查询批准的工具目录列表 | tool、版本、runtime、trust status |
| `GET /api/tools/{tool_id}` | 查询单个工具，可通过 `version` query 指定版本 | tool、版本、runtime、trust status |

#### W2 `POST /api/runs` 与 `POST /api/compile` 当前契约

`/api/runs` 是自然语言入口：先由 planner 生成 Recipe Tool Plan，再进入确定性编译链路。

`/api/runs` request body：

```json
{
  "request": "Run bulk RNA-seq differential expression.",
  "planner_model": "deepseek-v4-pro",
  "check": true
}
```

字段说明：

- `request`：必填自然语言需求，API 层会去除首尾空白；空字符串返回 422。
- `planner_model`：可选 planner 模型名；未提供时使用后端默认 planner model。
- `check`：是否执行 WDL syntax validation；默认为 `true`。

`/api/compile` 是结构化输入入口：跳过自然语言 planner，直接把 Recipe Tool Plan、Workflow IR 或 legacy workflow JSON 送入 Compiler Graph。

`/api/compile` request body：

```json
{
  "payload": {},
  "check": true
}
```

两个创建接口成功接收请求后都返回 HTTP 202，响应体使用 `RunAcceptedResponse`：

```json
{
  "run_id": "run_001",
  "status": "created",
  "events_url": "/api/runs/run_001/events"
}
```

请求体 schema 错误仍返回 HTTP 422。Planner、Catalog、Analyzer 或 Checker 阶段失败时，run 本身会进入 `failed` 状态，失败信息写入持久化 diagnostics 和事件流，便于历史页回放。

`GET /api/runs/{run_id}` 返回当前或历史快照：

```json
{
  "run_id": "run_001",
  "status": "succeeded",
  "request": "Run bulk RNA-seq differential expression.",
  "events_url": "/api/runs/run_001/events",
  "artifacts": {
    "plan": {},
    "workflow_ir": {},
    "wdl": "version 1.0\n..."
  },
  "diagnostics": {
    "analysis_errors": [],
    "analysis_warnings": [],
    "repair_actions": [],
    "validation_message": "WDL syntax validation skipped (--no-check).",
    "is_valid": false,
    "succeeded": true,
    "check_performed": false
  }
}
```

事件采用可持久化的统一 envelope，便于 SSE 实时显示和历史页回放使用同一份数据：

```json
{
  "event_id": "evt_001",
  "run_id": "run_001",
  "sequence": 1,
  "type": "node.completed",
  "node": "analyzer",
  "timestamp": "2026-05-28T12:00:00Z",
  "summary": "Workflow IR static analysis passed.",
  "payload": {}
}
```

第一版事件类型包含：`run.created`、`node.started`、`node.completed`、`node.failed`、`artifact.updated`、`repair.applied`、`validation.completed` 和 `run.completed`。事件中不保存 API key、原始模型鉴权信息或其他秘密环境变量。

### 持久化与部署边界

- 本地展示和开发第一版使用 SQLite，保存 run、event、artifact 与 diagnostic 等必要信息，减少环境安装成本。
- 公开部署并需要并发或长期保存历史记录时，迁移到 PostgreSQL；持久化 schema 不应绑定到 SQLite 特有行为。
- Agent 调用与 WDL 生成可以先作为 API 进程内任务运行；真正接入耗时 WDL 执行或容器构建后，再引入任务队列或专门 worker。
- 前端与 API 可以独立部署，但必须基于同一公开 API contract；仓库仍保留为 monorepo，保证演示迭代效率。

### Web 产品化实施里程碑

Web 展示轨道与后续 Multi-Agent 能力路线并行推进，优先让已经具备的核心编译能力形成可演示产品，不等待全部未来 Agent 完成。

| 阶段 | 建设内容 | 主要交付 | 依赖 |
| --- | --- | --- | --- |
| W0 | 抽取 application service 层 | CLI 调用可复用 service；自然语言与结构化编译均有稳定 Python 接口 | 当前 Compiler Graph |
| W1 | FastAPI API 基础 | `POST /api/runs`、`POST /api/compile`、catalog 查询与 API 测试 | W0 |
| W2 | Run 事件与展示级持久化 | SQLite 数据模型、SSE 事件流、成功/失败历史快照 | W1 |
| W3 | Next.js 产品外壳与项目介绍页 | TypeScript/Tailwind/shadcn UI 基础、介绍页、案例入口 | W1 |
| W4 | Workflow 生成工作台 | 输入面板、执行时间线、Plan/IR/WDL/诊断查看与 SSE 接入 | W2, W3 |
| W5 | DAG 与历史详情 | React Flow 工作流图、run 历史详情和失败/修复回放 | W4 |
| W6 | 部署与作品集打磨 | 在线 demo、示例数据、架构图、截图/录屏、API 文档与 README 导航 | W5 |

求职展示的最小可发布范围为 `W0` 至 `W5`：访问者能够使用一个预置 RNA-seq 示例触发 run，看到 Agent/Compiler 的阶段过程、Workflow IR、DAG、校验后的 WDL 与历史回放。`W6` 负责将能力包装成可在简历和项目主页直接访问、快速理解的作品。

## Agent 修复闭环与职责边界（规划中）

### 有界反思与自愈

当前确定性 `repairer` 仍作为第一层修复机制。只有在不存在安全、确定的修复动作时，才引入 Reviewer LLM：

```text
Analyzer / WOMtool failure
  ↓
Deterministic Repairer
  ├─ 有安全修复动作 -> 重新分析和验证
  └─ 无安全修复动作 -> Reviewer LLM
                         ↓
                    结构化 IR Patch
                         ↓
              Schema -> Analyzer -> Renderer -> Checker
                         ↓
              成功 / 有限次数重试 / 诊断失败报告
```

Reviewer 修复闭环要求：

- 输入包含当前 Workflow IR、错误分类、stderr、修复历史和可使用的正式 Catalog 上下文。
- 输出必须能以 schema 校验的结构化形式应用到 IR。
- 不得修改 Catalog 镜像来源或使用不存在于批准上下文中的工具。
- 修复轮数有硬上限；最终失败时返回可读的诊断报告，而不是无限循环。

### 分层 Agent 职责

| 组件 | 主要职责 | 明确边界 |
| --- | --- | --- |
| Architect Agent | 从需求确定分析方案、步骤与输出 | 对最终流程方案负责 |
| Bioinfo Reviewer | 审查生物信息学合理性，给出风险告警和建议 | 不直接修改 plan 或 IR |
| Catalog Tool Retriever | 从正式 Catalog 检索候选工具 | 不产生未知工具 |
| Tool Resolver / Planner | 将方案映射到候选 recipe 与 tool | 必须通过完整 Catalog 校验 |
| Resource Agent | 估算并记录资源建议或覆盖 | 不选工具、不选镜像 |
| Reviewer LLM | 处理确定性 repairer 无法解决的 IR 错误 | 只能提出受验证的 IR 修改 |

## Tool Retriever 与外部检索（规划中）

### Approved Catalog Tool Retriever

当正式 Catalog 扩大后，应在传递给 Planner 之前增加内部检索层。检索器只处理已批准工具，以减少 prompt 长度并提升工具选择质量。

推荐演进路径：

1. 定义 `retrieve_tools(query, role, top_k)` 接口和评测样本格式。
2. 先使用工具描述、aliases、recipe role 与现成 embedding 模型建立 baseline。
3. 对每个 Architect 识别的步骤角色分别召回候选工具，而不是只按整段需求查询一次。
4. 置信度不足时扩大候选集或回退完整 Catalog，优先避免漏召回。
5. 当 Catalog 和标注任务积累到足够规模后，再使用 PyTorch / bi-encoder 微调检索器，并按需增加 reranker。

Retriever 影响的是 Planner 的候选上下文，不影响最终准入判断：

```text
Architect roles -> Tool Retriever (approved tools only) -> Planner
                                                     ↓
                                      Full Catalog final validation
```

### External Retrieval 与 Candidate ToolSpec

当请求涉及正式 Catalog 中没有的工具时，外部检索只负责生成候选定义，不能直接写入正式目录。候选定义应基于可信来源，例如官方文档、官方仓库或 Bioconda metadata。

Candidate ToolSpec 至少记录：

- 工具名称、版本和用途。
- 输入、输出、参数与命令行依据。
- 来源 URL 与文档版本信息。
- 需要的镜像构建方式及验证状态。
- 尚未确认的字段、风险和适用范围。

```text
未知工具请求 -> External Retrieval -> Candidate ToolSpec
                                    -> 临时镜像验证 / 当前任务试用
                                    -> 正式准入评估
                                    -> Approved Catalog Tool
```

## 镜像生命周期与自动构建（规划中）

### 可信等级

| 等级 | 含义 | 允许使用范围 |
| --- | --- | --- |
| `catalog-approved` | 正式验证并录入 Catalog，固定 digest | 正式流程与共享复用 |
| `auto-validated` | 自动构建和基本测试通过 | 当前用户或限定复用 |
| `experimental` | 首次自动构建或验证覆盖有限 | 当前探索任务，需提示风险 |
| `rejected` | 构建、测试或策略检查失败 | 不可运行 |

正式 Catalog 中的镜像引用先使用经过 smoke test 的修订版 tag，例如：

```yaml
runtime:
  docker: ghcr.io/yuanzhw/ai-bioworkflow/deseq2:1.42.1-r2
```

当镜像完成发布后审计和 digest 固定，最终目标形式为：

```yaml
runtime:
  docker: ghcr.io/yuanzhw/ai-bioworkflow/deseq2@sha256:<validated-digest>
```

### 热路径与冷路径

正式工具执行使用热路径：

```text
用户任务 -> Approved Catalog Tool -> Validated Image Digest -> Workflow IR -> Execution
```

未知工具或特殊脚本可以使用冷路径完成当前探索性任务：

```text
Candidate ToolSpec
  -> Structured Build Request
  -> Policy Check
  -> Isolated Builder
  -> Smoke Test / Basic Security Check
  -> Temporary Image Digest
  -> Current Task Execution with Trust Notice
```

前端对临时镜像必须提供文字提示，例如：

```text
该步骤使用自动构建的实验性镜像，仅通过基础验证，
尚未进入正式工具目录。结果适合探索性分析，不建议直接用于正式报告。
```

### 构建系统边界

- LLM 只生成结构化 Build Request 或受限模板所需参数，不持有 registry 发布凭证。
- 即时构建未来由专用隔离 builder 完成，支持当前任务不经人工等待即可探索执行。
- GitHub Actions 与 GHCR 用于将具有复用价值的镜像正式发布和晋升，生成 digest 与必要的 provenance / attestation。
- 临时镜像不会自动进入正式 Catalog；晋升需要通过相应准入流程。

## 文献驱动工作流生成（规划中）

系统未来可从论文摘要、方法章节或 supplementary material 中提取分析思路，但不应直接将摘要推断当作可执行事实。建议流程为：

```text
论文内容
  -> Method Extraction Report
  -> Candidate Workflow Blueprint
  -> Bioinfo Reviewer warnings
  -> 缺失信息和置信度说明
  -> Architect 确定方案
  -> Recipe Tool Plan
  -> Workflow IR
```

候选蓝图必须区分文献明确描述的步骤与 AI 推断补充的步骤，并标注缺失的软件版本、参考资源、参数和工具映射依据。

## 两层图迁移步骤（规划中）

1. **明确现状与 API 边界**：将当前 `src/graph.py` 视为 Compiler Graph，保持它接收 Recipe Tool Plan、Workflow IR 和 Legacy JSON 的既有能力。
2. **显式命名编译子图**：后续代码中将编译图暴露为 `compiler_graph` 或等价清晰命名，并为结构化入口补齐回归测试；迁移期间可以保留旧导出别名以减少破坏性修改。
3. **定义 Orchestration State**：为自然语言请求、Planner 结果、Reviewer 告警、Retriever 候选、资源建议和审计记录建立独立状态 schema，避免污染编译状态。
4. **将现有 Natural Language Planner 纳入上层图**：第一版 Orchestration Graph 只需实现 `natural_language_planner -> compiler_graph`，同时保证 `--input` 路径不触发 LLM。
5. **统一 CLI / 前端路由**：自然语言入口改调 Orchestration Graph，结构化入口继续调 Compiler Graph，并移除 `main.py` 中重复的人工编排逻辑。
6. **逐步接入新增 Agent**：在上层图稳定后依次接入 Architect、Bioinfo Reviewer、Tool Retriever 和 Resource Agent；Reviewer LLM 作为编译失败恢复分支单独接入 Compiler Graph。

## Agent 能力分阶段开发路线图（规划中）

本路线描述智能编排、检索和运行环境能力的演进；可演示 Web 产品的建设顺序见上文 `W0` 至 `W6`，两条轨道可以并行推进。

| 阶段 | 建设内容 | 主要交付 |
| --- | --- | --- |
| P0 | 稳定现有 Recipe / Catalog / 执行测试 | 可靠的编译与执行评测基线 |
| P1 | Compiler Graph 明确化与 Orchestration Graph 外壳 | 自然语言和结构化入口分层，Planner 可在上层图运行 |
| P2 | 有界 Reviewer LLM 与 IR 修复闭环 | 结构化修复、诊断记录、失败报告 |
| P3 | Architect 与 Bioinfo Reviewer 分层 | 分析方案和科学性告警职责分离 |
| P4 | Approved Catalog Tool Retriever | 高召回候选工具筛选和 prompt 缩减 |
| P5 | Resource Agent | 可追踪的 CPU / memory / disk 建议与 override |
| P6 | External Retrieval 与 Candidate ToolSpec | 未知工具发现和候选定义 |
| P7 | On-demand Experimental Container Build | 临时镜像支持当前探索任务 |
| P8 | Validated Container Promotion | GHCR 正式发布及 Catalog digest 准入 |
| P9 | 文献驱动 Workflow Blueprint | 从文献方法提取候选流程 |
| P10 | 完整 Multi-Agent 编排与评测 | 在边界成熟后扩大协作自治程度 |

### P1 实施计划

P1 的目标是明确 Compiler Graph，并建立第一版 Orchestration Graph 外壳，使自然语言入口和结构化入口在代码、服务层、CLI/API 路由和测试中完成分层。P1 不引入完整 Multi-Agent 能力，也不改变 IR 到 WDL 的确定性编译边界。

详细工作拆解、关键契约、验收清单和建议 PR 切分维护在：

👉 **[P1 Orchestration Graph 实施计划](./docs/p1-orchestration-graph-plan.md)**

## 评测重点（规划中）

| 能力 | 首要指标 |
| --- | --- |
| Reviewer LLM | IR 修复成功率、错误修改率、平均修复轮数、诊断可读性 |
| Bioinfo Reviewer | 高风险缺失步骤召回率、误告警率 |
| Tool Retriever | `Recall@K`、步骤覆盖率、Planner 成功率、prompt token 降幅、回退比例 |
| Resource Agent | 执行成功率、OOM 率、资源浪费比例、override 可追踪率 |
| Candidate ToolSpec | 字段完整率、来源可追溯率、准入接受率 |
| 临时镜像构建 | 构建成功率、smoke test 通过率、任务首跑等待时间 |
| 文献方法提取 | 显式步骤提取准确率、推断标注准确率、缺失信息识别率 |
