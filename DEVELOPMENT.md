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
│   │
│   ├── catalog/          # 4. 生信工具目录：工具 schema、YAML 定义与 plan resolver
│   │
│   ├── recipes/          # 5. 分析配方目录：配方 schema 与步骤定义
│   │
│   ├── prompts.py        # 6. 提示词管理：存放所有 System Prompts 和 Few-shot 示例
│   │
│   ├── renderers/        # 7. 确定性代码生成器
│   │   ├── wdl.py        # IR -> WDL
│   │   └── templates/
│   │       └── workflow.wdl.j2
│   │
│   ├── tools/            # 8. 工具箱：存放外部工具封装
│   │   ├── __init__.py
│   │   └── validator.py  # 生信特定工具（如 miniwdl 语法校验）
│   │
│   ├── nodes/            # 9. 工作节点：LangGraph 的具体执行工位
│   │   ├── __init__.py
│   │   ├── planner.py    # 将标准 IR 或 Recipe Tool Plan 标准化为 Workflow IR
│   │   ├── analyzer.py   # 调用 IR 静态分析
│   │   ├── renderer.py   # 调用 WDL renderer
│   │   ├── checker.py    # 调用 miniwdl validator
│   │   └── coder.py      # 旧版 LLM 直出 WDL 节点，保留作对照/实验
│   │
│   └── graph.py          # 10. 核心图纸：组装 nodes 和 tools 的 StateGraph
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
4. **Catalog 先于自由生成 (`catalog/`, `recipes/`)**：常见生信工具、版本、参数、runtime 与配方步骤应沉淀为结构化目录，Planner 可以把 Recipe Tool Plan 解析成标准 IR。
5. **静态分析先于渲染 (`analyzer.py`)**：在生成 WDL 前先检查 task 是否存在、输入是否齐全、上游输出引用是否有效、基础类型是否匹配。
6. **确定性渲染 (`renderers/`)**：标准 IR 到 WDL 必须由模板或普通代码生成，不应依赖 LLM 的自由文本输出。
7. **工具封装 (`tools/`)**：所有与底层操作系统或第三方生信软件的交互（如调用 `miniwdl check`）都必须封装为独立 Tool，确保生成代码闭环验证。
8. **渐进式重构**：先保证 IR -> WDL -> miniwdl check 的主链路稳定，再逐步引入 LLM planner、LLM repairer、Biocontainers 镜像查询节点。

## 当前 LangGraph 流程

```text
START
  ↓
planner_node     # 标准 IR / Legacy JSON / Recipe Tool Plan -> Workflow IR
  ↓
analyzer_node    # IR 静态分析
  ↓
renderer_node    # Workflow IR -> WDL
  ↓
checker_node     # miniwdl check
  ↓
END
```
