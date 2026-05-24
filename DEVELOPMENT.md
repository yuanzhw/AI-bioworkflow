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
│   ├── prompts.py        # 8. 提示词管理：存放所有 System Prompts 和 Few-shot 示例
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
│   │   ├── checker.py    # 调用 miniwdl validator
│   │   └── coder.py      # 旧版 LLM 直出 WDL 节点，保留作对照/实验
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
3. **IR 优先 (`schema.py`)**：workflow 的调用关系与 task 的定义必须分离。`workflow.calls` 表达 DAG，`tasks` 表达可复用 task 模板。
4. **自然语言只到 Plan (`nl_planner.py`)**：LLM 的职责是把用户需求转成 Recipe Tool Plan，不直接生成 WDL。Planner 失败需要区分 JSON 解析、plan schema、recipe/catalog 校验三类错误，便于调试真实模型输出。
5. **Catalog 先于自由生成 (`catalog/`, `recipes/`)**：常见生信工具、版本、参数、runtime 与配方步骤应沉淀为结构化目录，Planner 可以把 Recipe Tool Plan 解析成标准 IR。
6. **静态分析先于渲染 (`analyzer.py`)**：在生成 WDL 前先检查 task 是否存在、输入是否齐全、上游输出引用是否有效、基础类型是否匹配。
7. **保守修复 (`repairer.py`)**：自动修复只处理可以由 IR 本身确定的问题，例如 call 拓扑顺序和明显漏引号的 File/String 输出字面量；无法确定的错误应保留给人工或后续 LLM repairer。
8. **确定性渲染 (`renderers/`)**：标准 IR 到 WDL 必须由模板或普通代码生成，不应依赖 LLM 的自由文本输出。
9. **工具封装 (`tools/`)**：所有与底层操作系统或第三方生信软件的交互（如调用 `miniwdl check`）都必须封装为独立 Tool，确保生成代码闭环验证。
10. **Catalog 镜像权威来源 (`catalog/`)**：每个 Tool Catalog 条目必须显式声明 `runtime.docker`。编译链路不搜索、不猜测、不联网补全镜像；新增或升级工具时由维护者明确选择镜像并写入 catalog。
11. **渐进式重构**：先保证 Natural Language -> Recipe Tool Plan -> IR -> WDL -> miniwdl check 的主链路稳定，再逐步扩展 recipe/tool catalog、可解释错误报告与 LLM repairer。

## 后续待办

- [ ] **低优先级：自建工具镜像管理规范**：当 Catalog 中某些工具没有合适公共镜像时，考虑在 `containers/<tool>/<version>/` 维护 Dockerfile、smoke test 与构建说明；镜像构建并推送到内部 registry 后，只把最终 tag 或 digest 显式写入 Tool Catalog。该工作不接入编译链路，也不恢复镜像搜索或自动补全。

## 当前 LangGraph 流程

```text
START
  ↓
nl_planner        # 自然语言需求 -> Recipe Tool Plan（CLI 自然语言入口）
  ↓
ir_normalizer    # 标准 IR / Legacy JSON / Recipe Tool Plan -> Workflow IR
  ↓
analyzer_node    # IR 静态分析
  ↓
renderer_node    # Workflow IR -> WDL
  ↓
checker_node     # miniwdl check
  ↓
END

analyzer_node 或 checker_node 发现错误时，如果 repairer 还有重试预算，会进入：

repairer_node    # 可确定修复时更新 IR
  ↓
analyzer_node    # 修复后重新分析、渲染、校验
```
