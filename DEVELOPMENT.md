# AI-bioworkflow 开发与架构指南

本文档用于记录基于 LangGraph 和 DeepSeek 搭建的 WDL 自动生成 Agent 的目录结构与核心设计理念，以供后续开发参考。

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
│   ├── prompts.py        # 2. 提示词管理：存放所有 System Prompts 和 Few-shot 示例
│   │
│   ├── tools/            # 3. 工具箱：存放供大模型调用的外部工具
│   │   ├── __init__.py
│   │   └── validator.py  # 生信特定工具（如 miniwdl 语法校验）
│   │
│   ├── nodes/            # 4. 工作节点：LangGraph 的具体执行工位
│   │   ├── __init__.py
│   │   ├── planner.py    # 将结构化表单转化为步骤图的逻辑
│   │   └── coder.py      # 负责输出具体 WDL 代码的逻辑
│   │
│   └── graph.py          # 5. 核心图纸：组装 nodes 和 tools 的 StateGraph
│
├── tests/                # 单元与集成测试
│   ├── test_tools.py     
│   └── test_graph.py     
│
└── main.py               # 项目入口，负责接收用户输入并触发 workflow
```

## 🧠 核心模块设计理念

1. **状态管理 (`state.py`)**：必须保持强类型。除了 LangGraph 原生的 `messages` 列表，还需要定义好接收前端传入的 `parsed_json`（结构化表单数据）和流转中的 `current_wdl` 代码。
2. **提示词隔离 (`prompts.py`)**：绝对不要将长篇大论的 System Prompt 硬编码在业务逻辑文件中。
3. **工具封装 (`tools/`)**：所有与底层操作系统或第三方生信软件的交互（如调用 `miniwdl check`）都必须封装为独立的 Tool 节点，确保大模型生成的代码闭环验证。
4. **渐进式重构**：初期 MVP 阶段确保数据流转清晰，后期再逐步引入更复杂的查库（如自动查询 biocontainers 镜像）节点。