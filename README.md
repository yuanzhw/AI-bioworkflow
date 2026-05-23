# AI-bioworkflow 🧬🤖

[![Python Version](https://img.shields.io/badge/Python-3.13+-blue.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Package Manager: uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=flat-square)](./LICENSE)
[![Framework](https://img.shields.io/badge/Agent-LangGraph-1C3C3C?style=flat-square)](https://github.com/langchain-ai/langgraph)
[![Model](https://img.shields.io/badge/Model-DeepSeek_V4_Pro-4D6BFE?style=flat-square)](https://www.deepseek.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](http://makeapullrequest.com)


AI-bioworkflow 是一个面向生物信息学工作流生成的 Agent / 编译器原型。
项目利用 **LangGraph** 构建状态流转架构，将用户提供的结构化 JSON 标准化为内部 **Workflow IR**，再通过确定性的 Renderer 编译为标准、合规的 **WDL (Workflow Description Language) 1.0** 代码，并使用 `miniwdl` 做本地语法校验。

LLM 在这个架构中更适合承担规划、补全、修复与解释任务；从标准 IR 到 WDL 的最终生成由普通代码完成，保证输出稳定、可测试、可维护。

## ✨ 核心特性

- **Workflow IR 驱动**：将 workflow 调用关系与 task 定义分离，支持多个 task、复用 task 和明确的数据依赖。
- **确定性 WDL 编译**：通过 Jinja2 Renderer 从 IR 生成 WDL，避免让 LLM 承担模板引擎职责。
- **静态分析**：在渲染前检查 task/call 引用、输入完整性、上游输出引用和基础类型匹配。
- **Recipe / Tool Catalog**：支持用预定义生信工具目录和分析配方生成 Workflow IR。
- **Agentic 架构**：基于 LangGraph 串联 Planner、Analyzer、Repairer、Renderer 与 Checker 节点，支持继续扩展 LLM planner / repairer。
- **模块化设计**：高度解耦的 State、Prompts、Nodes 与 Tools 设计，极佳的代码可维护性。

## 🛠️ 快速开始

### 1. 环境准备

确保你的本地开发环境已安装以下基础工具：
- Python 3.13+
- [uv](https://github.com/astral-sh/uv) (极速的 Python 包管理器)

### 2. 克隆与安装

```bash
# 克隆仓库
git clone [https://github.com/yourusername/AI-bioworkflow.git](https://github.com/yourusername/AI-bioworkflow.git)
cd AI-bioworkflow

# 使用 uv 同步依赖并创建虚拟环境
uv sync
```

### 3. 配置环境变量

自然语言规划入口需要 DeepSeek API Key。确定性的 `--input` 结构化编译模式不需要 API Key。
可在项目根目录下创建 `.env` 文件，并填入 DeepSeek API 密钥。**请务必不要将此文件提交到版本控制系统中！**

```env
# .env 文件内容
DEEPSEEK_API_KEY="sk-你的真实API密钥"
```

### 4. 编译工作流

无参数运行时会使用内置自然语言 demo，先规划成 Recipe Tool Plan，再编译并打印生成的 WDL：

```bash
uv run main.py
```

也可以直接传入自然语言需求：

```bash
uv run main.py --prompt "做一个 bulk RNA-seq 差异表达分析流程，输入双端 FASTQ、Salmon index 和样本分组表，先 fastp，再 salmon，最后 DESeq2。"
```

或者从文本文件读取需求并写出 WDL：

```bash
uv run main.py --prompt-file examples/rnaseq_deg_request.txt --output outputs/rnaseq_deg.wdl
```

结构化 JSON/YAML 输入仍然保留为开发/调试模式：

```bash
uv run main.py --input examples/rnaseq_deg_recipe_plan.json --output outputs/rnaseq_deg.wdl
```

常用选项：

- `--prompt`：读取自然语言 workflow 需求。
- `--prompt-file`：从文本文件读取自然语言 workflow 需求。
- `--input` / `-i`：开发模式，读取标准 Workflow IR 或 Recipe Tool Plan。
- `--output` / `-o`：写出生成的 WDL；不传则打印到终端。
- `--print-plan`：打印自然语言 Planner 生成的结构化 Recipe Tool Plan。
- `--save-plan`：将自然语言 Planner 生成的 Recipe Tool Plan 保存为 JSON 文件。
- `--save-planner-prompt`：保存完整 Planner prompt，方便调试模型输出。
- `--print-ir`：打印 Planner 标准化后的 Workflow IR。
- `--no-check`：跳过 `miniwdl` 语法校验，仅执行 IR 分析与 WDL 渲染。
- `--planner-model`：指定自然语言 Planner 使用的模型。
- `--verbose`：将节点进度日志输出到 stderr。

默认情况下，CLI 会把 WDL / JSON IR 等机器可消费内容写到 stdout，将状态、错误和校验信息写到 stderr，因此可以直接重定向生成 WDL：

```bash
uv run main.py --input examples/rnaseq_workflow_ir.json --no-check > workflow.wdl
```

调试自然语言规划时，可以保存模型看到的 prompt 和模型生成的 plan：

```bash
uv run main.py \
  --prompt-file examples/rnaseq_deg_request.txt \
  --save-planner-prompt debug/planner_prompt.txt \
  --save-plan debug/plan.json \
  --output outputs/rnaseq_deg.wdl
```

## 📥 支持的输入格式

面向用户的主要入口是自然语言。系统会先用 LLM Planner 将需求转成结构化 Recipe Tool Plan，然后交给确定性编译链路处理。

结构化输入用于开发、调试和集成测试，目前支持两类：

1. **标准 Workflow IR**：直接提供 `workflow.calls` 和 `tasks`，适合精确控制每个 task 的命令、输入、输出和 runtime。
2. **Recipe Tool Plan**：提供 `workflow.recipe` 和 `workflow.tool_calls`，由内置 recipe/tool catalog 自动解析为 Workflow IR。

Recipe Tool Plan 示例：

```json
{
  "workflow": {
    "name": "RNASeqDEG",
    "recipe": "rnaseq_differential_expression",
    "inputs": {
      "raw_r1": "File",
      "raw_r2": "File",
      "transcriptome_index": "File",
      "sample_groups": "File"
    },
    "tool_calls": [
      {
        "id": "qc",
        "step": "qc",
        "tool": "fastp",
        "version": "0.23.2",
        "inputs": {
          "r1": "raw_r1",
          "r2": "raw_r2"
        },
        "params": {
          "thread": 4
        }
      }
    ]
  }
}
```

## 🏗️ 架构与开发指南

对于希望了解本项目底层实现原理、LangGraph 状态图设计，或有志于参与二次开发的工程师，请务必阅读我们的开发文档：

👉 **[查看 DEVELOPMENT.md 开发指南](./DEVELOPMENT.md)**

## 📅 未来路线图 (Roadmap)

- [x] 搭建基础 LangGraph 状态机。
- [x] 实现从结构化 JSON 到 WDL 的单向代码生成。
- [x] 引入 `miniwdl` / `womtool` 作为 Tool 节点，实现生成的 WDL 自动化本地校验。
- [x] 引入 Workflow IR、静态分析器与确定性 WDL Renderer。
- [x] 接入 Recipe / Tool Catalog 输入到 LangGraph Planner。
- [x] 闭环修复机制初版：当分析器或校验器发现可确定修复的问题时，优先修复 IR 并重新编译 WDL。
- [x] Tool Catalog 强制显式声明 `runtime.docker`，作为镜像来源的唯一权威。
- [ ] 扩展更多常用生信 recipe 与 tool catalog。

## 📄 许可证

[Apache License 2.0](./LICENSE)
