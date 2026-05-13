# AI-bioworkflow 🧬🤖

[![Python Version](https://img.shields.io/badge/Python-3.10+-blue.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Package Manager: uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg?style=flat-square)](./LICENSE)
[![Framework](https://img.shields.io/badge/Agent-LangGraph-1C3C3C?style=flat-square)](https://github.com/langchain-ai/langgraph)
[![Model](https://img.shields.io/badge/Model-DeepSeek_V4_Pro-4D6BFE?style=flat-square)](https://www.deepseek.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](http://makeapullrequest.com)


AI-bioworkflow 是一个基于大语言模型（LLM）驱动的生物信息学工作流生成智能体（Agent）。
本项目利用 **LangGraph** 构建稳健的状态流转架构，并接入 **DeepSeek V4 Pro** 模型，能够将用户提供的结构化表单（JSON）自动翻译为标准、合规的 **WDL (Workflow Description Language) 1.0** 代码。

## ✨ 核心特性

- **结构化驱动**：摒弃纯自然语言的模糊性，通过结构化 JSON 保证上下游步骤变量传递的准确性。
- **Agentic 架构**：基于 LangGraph 构建的多节点智能体架构，支持灵活扩展（未来将支持自动化闭环语法校验与查错）。
- **DeepSeek 强力驱动**：使用 `deepseek-v4-pro`（已深度优化 Tool Calling 并关闭发散思考模式），提供卓越的代码生成质量。
- **模块化设计**：高度解耦的 State、Prompts、Nodes 与 Tools 设计，极佳的代码可维护性。

## 🛠️ 快速开始

### 1. 环境准备

确保你的本地开发环境已安装以下基础工具：
- Python 3.10+
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

在项目根目录下创建一个 `.env` 文件，并填入你的 DeepSeek API 密钥。**请务必不要将此文件提交到版本控制系统中！**

```env
# .env 文件内容
DEEPSEEK_API_KEY="sk-你的真实API密钥"
```

### 4. 运行 MVP 测试

执行主入口文件，验证 Agent 是否能正常根据预设的 JSON 生成 WDL 代码：

```bash
uv run main.py
```
*如果配置正确，终端将在几秒钟后输出一段完整的、包含 fastp 质控步骤的合规 WDL 代码。*

## 🏗️ 架构与开发指南

对于希望了解本项目底层实现原理、LangGraph 状态图设计，或有志于参与二次开发的工程师，请务必阅读我们的开发文档：

👉 **[查看 DEVELOPMENT.md 开发指南](./DEVELOPMENT.md)**

## 📅 未来路线图 (Roadmap)

- [x] 搭建基础 LangGraph 状态机与 DeepSeek 连通。
- [x] 实现从结构化 JSON 到 WDL 的单向代码生成。
- [x] 引入 `miniwdl` / `womtool` 作为 Tool 节点，实现生成的 WDL 自动化本地校验。
- [x] 闭环重试机制：当校验器报错时，将 Error Message 返回给大模型进行自我修复。
- [ ] 接入 Biocontainers 镜像搜索节点，实现 Docker 地址的自动补全。

## 📄 许可证

[Apache License 2.0](./LICENSE)