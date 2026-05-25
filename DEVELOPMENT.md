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
│   │   └── validator.py  # 生信特定工具（如 miniwdl 语法校验）
│   │
│   ├── nodes/            # 11. 工作节点：LangGraph 的具体执行工位
│   │   ├── __init__.py
│   │   ├── ir_normalizer.py # 将标准 IR、Legacy JSON 或 Recipe Tool Plan 标准化为 Workflow IR
│   │   ├── analyzer.py   # 调用 IR 静态分析
│   │   ├── repairer.py   # 调用 IR repairer 并记录修复动作
│   │   ├── renderer.py   # 调用 WDL renderer
│   │   └── checker.py    # 调用 miniwdl validator
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
9. **工具封装 (`tools/`)**：所有与底层操作系统或第三方生信软件的交互（如调用 `miniwdl check`）都必须封装为独立 Tool，确保生成代码闭环验证。
10. **Catalog 镜像权威来源 (`catalog/`)**：每个 Tool Catalog 条目必须显式声明 `runtime.docker`。编译链路不搜索、不猜测、不联网补全镜像；新增或升级工具时由维护者明确选择镜像并写入 catalog。
11. **辅助脚本镜像化 (`containers/`)**：tximport、DESeq2、MultiQC 等辅助脚本随项目镜像构建进入容器，不作为 WDL 输入，也不内联到 command 中。
12. **渐进式重构**：先保证 Natural Language -> Recipe Tool Plan -> IR -> WDL -> miniwdl check 的主链路稳定，再逐步扩展 recipe/tool catalog、可解释错误报告与 LLM repairer。

## Workflow IR 规范

Workflow IR 是本项目的核心编译契约。字段结构、表达式系统、scatter 类型提升、Recipe Tool Plan 到 IR 的转换，以及 IR 到 WDL 1.0 的映射规则，统一维护在：

👉 **[Workflow IR 规范与后端映射](./docs/workflow-ir.md)**

后续新增 IR 数据结构、表达式形式、renderer backend 或 Nextflow 支持时，应先更新该规范，再实现代码与测试。

## 当前 LangGraph 流程

```text
START
  ↓
nl_planner        # 自然语言需求 -> Recipe Tool Plan（CLI 自然语言入口）
  ↓
ir_normalizer    # 标准 IR / Legacy JSON / Recipe Tool Plan -> Workflow IR steps
  ↓
analyzer_node    # IR 静态分析
  ↓
renderer_node    # Workflow IR steps/scatter -> WDL
  ↓
checker_node     # miniwdl check
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
- [x] **当前辅助工具镜像**：tximport、DESeq2 与 MultiQC 已具备项目内构建定义，作为 RNA-seq DEG 可执行流程的依赖。

## 未来架构原则（规划中）

后续智能化能力遵循以下总原则：

> LLM 可以扩展规划、审查、检索、诊断和环境准备能力；Workflow IR、正式 Catalog 准入、容器可信等级、确定性渲染和验证闭环必须保持结构化、可审计、可约束。

已确认的设计决策：

1. **Reviewer LLM 只能修改 IR**：Reviewer 可以读取当前 IR、分析错误、`miniwdl` stderr 和历史修复记录，并输出结构化 IR patch 或候选 IR；不能直接改写最终 WDL、绕过验证或引入未经准入的正式工具。
2. **Bioinfo Reviewer 只告警与建议**：科学性审查节点负责指出缺失步骤、方法学风险和推荐调整，但最终流程方案始终由 Architect Agent 决定。
3. **Resource Agent 只处理资源字段**：该节点仅建议或覆盖 `cpu`、`memory`、`disks` 等资源字段，记录修改理由；不负责镜像选择、工具选择或分析方法选择。
4. **Catalog 内检索优先**：Planner 不必永久读取全量正式工具库；未来由 Tool Retriever 从 approved Catalog 中高召回筛选候选工具，再由完整 Catalog 做最终校验。
5. **未知工具先形成 Candidate ToolSpec**：外部检索发现的新工具必须先生成带来源、版本依据、未确认字段和测试状态的候选定义，才能进入镜像构建环节。
6. **临时镜像可服务当前任务**：自动构建并通过最小验证的临时镜像允许在隔离环境内用于当前探索任务，前端必须以文字提示可信等级和风险。
7. **正式 Catalog 只引用已验证 digest**：可复用的正式工具镜像应固定为经过验证的 digest，而不是依赖可变 tag。
8. **GitHub Actions 只负责发布和晋升**：正式镜像推送、provenance / attestation 及 Catalog 准入可由 GitHub Actions 承担；未来的即时构建由专用隔离 builder 承担，避免阻塞用户任务。
9. **IR 到 WDL 保持确定性**：任何新增 Agent 都不替代 renderer，也不允许绕过 Analyzer 与 Checker。
10. **全程可追踪**：检索来源、Agent 建议、IR 修改、资源覆盖、镜像验证和回退结果均应进入任务审计记录。

## 目标智能流程（规划中）

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
IR Normalizer -> Analyzer -> Renderer -> Checker -> Execution
```

### 有界反思与自愈

当前确定性 `repairer` 仍作为第一层修复机制。只有在不存在安全、确定的修复动作时，才引入 Reviewer LLM：

```text
Analyzer / miniwdl failure
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

正式 Catalog 中的镜像引用目标形式为：

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

## 分阶段开发路线图（规划中）

| 阶段 | 建设内容 | 主要交付 |
| --- | --- | --- |
| P0 | 稳定现有 Recipe / Catalog / 执行测试 | 可靠的编译与执行评测基线 |
| P1 | 有界 Reviewer LLM 与 IR 修复闭环 | 结构化修复、诊断记录、失败报告 |
| P2 | Architect 与 Bioinfo Reviewer 分层 | 分析方案和科学性告警职责分离 |
| P3 | Approved Catalog Tool Retriever | 高召回候选工具筛选和 prompt 缩减 |
| P4 | Resource Agent | 可追踪的 CPU / memory / disk 建议与 override |
| P5 | External Retrieval 与 Candidate ToolSpec | 未知工具发现和候选定义 |
| P6 | On-demand Experimental Container Build | 临时镜像支持当前探索任务 |
| P7 | Validated Container Promotion | GHCR 正式发布及 Catalog digest 准入 |
| P8 | 文献驱动 Workflow Blueprint | 从文献方法提取候选流程 |
| P9 | 完整 Multi-Agent 编排与评测 | 在边界成熟后扩大协作自治程度 |

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
