# Internal Catalog RAG / Tool Retriever 开发计划

本文档描述项目内第一版 RAG 能力的范围、边界和实施步骤。这里的
RAG 不指外部网页、论文或未知工具检索，而是指在项目已批准的
Recipe / Tool Catalog 内做可解释召回，为自然语言 Planner 提供受控上下文。

## 背景

AI-bioworkflow 的核心边界是：

```text
Natural Language Request
  -> Recipe Tool Plan
  -> Workflow IR
  -> Analyzer / Repairer
  -> Deterministic WDL Renderer
  -> Checker
```

当前 Planner 可以读取完整 recipe/tool catalog。随着 catalog 扩大，直接把
全量目录放入 prompt 会带来三个问题：

1. Prompt 变长，模型调用成本和失败面增加。
2. 工具选择缺少显式召回记录，前端难以展示“为什么选这些工具”。
3. 后续接入 Architect、Bioinfo Reviewer、Resource Agent 时缺少独立的工具候选层。

因此第一版内部 RAG 的目标不是扩大自治范围，而是在正式 Catalog 内加入一个
可审计的检索节点。

## 定位

推荐名称：

```text
Approved Catalog Retriever
```

它的职责是：

- 从项目已批准的 recipe/tool catalog 中召回候选 recipe 和 tools。
- 为每个候选项记录 `score`、`matched_terms`、`matched_fields` 和 `reason`。
- 将召回结果作为 Planner prompt 的候选上下文。
- 将召回结果保存为 run artifact，并通过事件流展示。

它不负责：

- 发现外部工具。
- 读取网页、论文或软件文档。
- 自动生成 Candidate ToolSpec。
- 自动选择或替换 container image。
- 修改正式 Catalog。
- 绕过完整 recipe/catalog validation。

关键原则：

```text
Retriever narrows planner context.
Full Catalog validation remains the admission boundary.
```

## 目标

第一版应满足以下目标：

1. **零网络依赖**：只读取本地 `src/recipes` 和 `src/catalog/tools`。
2. **零新增重依赖**：先使用确定性词法检索，不引入向量数据库或 embedding 服务。
3. **可解释**：每个结果包含命中词、命中字段和简短理由。
4. **可测试**：RNA-seq DEG 请求能够召回现有 recipe 和关键工具。
5. **可展示**：前端可以展示 Catalog Retrieval 阶段和候选工具列表。
6. **可替换**：后续可以将 scoring backend 换成 BM25、embedding 或 reranker，但外部契约不变。

## 非目标

第一版不做以下能力：

- 外部文档 RAG。
- 论文方法提取。
- 未知工具发现。
- Candidate ToolSpec 生成。
- 自动镜像构建。
- Catalog 正式准入流程。
- 向量数据库部署。
- embedding 模型微调。

这些能力属于后续 `External Retrieval`、`Candidate ToolSpec` 和镜像生命周期路线，不应混入内部 catalog retriever 的 MVP。

## 后期本地训练路线

第一版内部 RAG 不训练模型。当前 catalog 规模仍小，过早引入训练会增加
依赖、评测和维护成本，也不利于解释检索行为。MVP 的重点应是先实现稳定的
词法 baseline，并把后续训练所需的数据契约沉淀下来。

推荐演进顺序：

```text
lexical retriever
  -> retrieval evaluation set
  -> BM25 / lightweight embedding baseline
  -> local bi-encoder retriever
  -> reranker for top-K candidates
```

在项目正规化、Catalog 扩大后，可以基于本地数据训练可替换的检索器。可用数据包括：

- 用户自然语言请求。
- 最终通过验证的 Recipe Tool Plan。
- request 到 recipe / tool 的成功映射。
- Architect 或人工标注的 step roles。
- Retriever 召回候选与最终 Planner 选择之间的差异。
- 失败 run 中的漏召回、错召回和人工修正记录。
- Catalog metadata，例如 aliases、description、inputs、outputs 和 recipe steps。

训练前应优先建设评测集，而不是直接训练模型。评测样本建议显式记录：

```json
{
  "query": "bulk RNA-seq differential expression",
  "expected_recipe": "rnaseq_differential_expression",
  "expected_tools": ["fastp", "salmon", "tximport", "deseq2", "multiqc"],
  "expected_roles": {
    "read_quality_control": ["fastp"],
    "expression_quantification": ["salmon"],
    "transcript_to_gene_count_summary": ["tximport"],
    "differential_expression": ["deseq2"],
    "quality_control_summary": ["multiqc"]
  }
}
```

当工具数达到几十到上百、并且有足够 validated plans 与人工标注后，再考虑训练：

- **Bi-encoder retriever**：用于快速召回 top-K recipe / tools。
- **Reranker**：用于对 top-K 候选做精排，尤其区分功能相近工具。

训练后的实现必须保持与第一版 retriever 相同的外部契约：recipe 和 tool 结果
仍包含 `score`、`matched_terms`、`matched_fields` 和 `reason`，顶层结果仍包含
`fallback_used` 与 `fallback_reason`，tool 结果仍包含 `trust_status`。
完整 Catalog validation 仍然是准入边界，训练模型不能直接准入未知工具、
替换镜像或绕过 Analyzer / Renderer / Checker。

## 架构位置

目标链路：

```text
User request
  -> Catalog Retriever
       -> retrieved recipes
       -> retrieved tools
       -> retrieval trace
  -> Planner
       -> Recipe Tool Plan
  -> Full Catalog validation
  -> Compiler Graph
       -> Workflow IR
       -> WDL
       -> Diagnostics
```

自然语言入口使用该节点。结构化入口继续直接进入 Compiler Graph：

```text
--input / POST /api/compile
  -> Compiler Graph
```

结构化入口不需要 RAG，也不需要 API key。

## 检索数据源

### Recipe 字段

检索器可以索引：

- `recipe.id`
- `recipe.name`
- `recipe.aliases`
- `recipe.description`
- `recipe.required_inputs` 的字段名和 description
- `recipe.steps[].id`
- `recipe.steps[].role`
- `recipe.steps[].allowed_tools`

### Tool 字段

检索器可以索引：

- `tool.id`
- `tool.version`
- `tool.aliases`
- `tool.description`
- `tool.inputs` 的字段名、type、description
- `tool.params` 的字段名、type、description
- `tool.outputs` 的字段名、type、description、tags
- `tool.runtime.docker`

第一版默认所有已加载 Tool Catalog 条目均视为 `catalog-approved`。后续如果 catalog schema 增加 trust status 字段，retriever 应读取真实字段。

## 检索输入

第一版输入：

```json
{
  "query": "Run bulk RNA-seq differential expression.",
  "top_k_recipes": 3,
  "top_k_tools": 8
}
```

后续可扩展输入：

```json
{
  "query": "Run bulk RNA-seq differential expression.",
  "roles": ["quality control", "quantification", "differential expression"],
  "top_k_recipes": 3,
  "top_k_tools_per_role": 5
}
```

## 检索输出契约

推荐输出：

```json
{
  "query": "Run bulk RNA-seq differential expression.",
  "strategy": "lexical_v1",
  "recipes": [
    {
      "id": "rnaseq_differential_expression",
      "score": 12.5,
      "matched_terms": ["rna", "seq", "differential", "expression"],
      "matched_fields": ["id", "name", "description", "steps.role"],
      "reason": "Matched RNA-seq differential expression recipe metadata."
    }
  ],
  "tools": [
    {
      "id": "deseq2",
      "version": "1.42.1",
      "score": 8.0,
      "matched_terms": ["differential", "expression"],
      "matched_fields": ["id", "description"],
      "trust_status": "catalog-approved",
      "reason": "Matched differential expression role and tool description."
    }
  ],
  "fallback_used": false,
  "fallback_reason": null
}
```

输出应保持 JSON-ready，便于 API、SSE、历史详情和前端复用。

## 第一版 scoring 建议

先实现确定性词法检索。可以使用简单 tokenization：

- 小写化。
- 按非字母数字字符切分。
- 保留长度大于 1 的 token。
- 对连续 CJK（中文、日文、韩文）字符生成确定性的单字 token 和重叠 2-gram，
  例如 `差异表达` 生成 `差`、`异`、`表`、`达`、`差异`、`异表`、`表达`。
- 对常见变体做轻量规范化，例如 `rna-seq`、`rnaseq`、`rna seq`。

建议权重：

| 字段 | 权重 |
| --- | --- |
| id / alias exact token | 5 |
| name | 4 |
| step role | 4 |
| description | 3 |
| input / output / param name | 2 |
| input / output / param description | 1 |
| runtime docker | 0.5 |

排序规则：

1. score 降序。
2. id 升序，保证稳定输出。
3. tool version 使用 catalog 当前排序或显式 latest 规则。

低置信度策略：

- 如果 recipe 召回为空，回退完整 recipe catalog。
- 如果 tool 召回为空，回退 recipe allowed tools 或完整 tool catalog。
- fallback 必须记录 `fallback_used: true` 和 `fallback_reason`。

## Planner 集成

当前 Planner prompt 包含完整 catalog context。接入 retriever 后：

1. `create_natural_language_plan(...)` 加载完整 Tool Catalog 和 Recipe Catalog。
2. 调用 `retrieve_catalog_context(query, tool_catalog, recipe_catalog, top_k_recipes, top_k_tools)`。
3. Prompt 使用 retrieved context。
4. LLM 输出 Recipe Tool Plan。
5. 仍使用完整 recipe/tool catalog 执行 schema、resolver 和 analyzer 校验。

重要边界：

```text
Prompt context can be narrowed.
Validation catalog must remain complete.
```

这样即使 retriever 漏召回，只要 Planner 输出引用了合法工具，最终校验仍按完整 Catalog 判断。

## API 与事件展示

自然语言 run 建议新增事件：

```text
node.started     catalog_retriever
node.completed   catalog_retriever
artifact.updated catalog_retrieval
```

`GET /api/runs/{run_id}` 的 artifacts 建议扩展：

```json
{
  "artifacts": {
    "catalog_retrieval": {},
    "plan": {},
    "workflow_ir": {},
    "wdl": "version 1.0\n..."
  }
}
```

前端工作台展示重点：

- Query。
- Top recipe。
- Top tools。
- `matched_terms`。
- `trust_status`。
- fallback 是否发生。
- 提示该检索只来自 approved catalog。

## 推荐文件拆分

第一版实现可以按以下文件组织：

```text
src/catalog/retriever.py
tests/test_catalog_retriever.py
src/nl_planner.py
src/prompts.py
src/services/run_service.py
src/api/models/workflows.py
src/services/run_repository.py
web/lib/types.ts
web/app/workspace/...
docs/test-cases.md
```

其中 `src/catalog/retriever.py` 应尽量保持纯函数和无副作用，便于测试。

## 建议实现步骤

### R1. Catalog Retriever 核心

交付：

- `retrieve_catalog_context(query, tool_catalog, recipe_catalog, top_k_recipes, top_k_tools)`。
- JSON-ready result。
- 词法 scoring。
- fallback 记录。

测试：

- RNA-seq DEG 请求召回 `rnaseq_differential_expression`。
- RNA-seq DEG 请求召回 `fastp`、`salmon`、`tximport`、`deseq2`、`multiqc`。
- 输出包含 `matched_terms`、`matched_fields` 和 `strategy`。
- 空 query 返回清晰错误或 fallback 结果。

### R2. Planner Prompt 集成

交付：

- Planner 使用 retrieved catalog context。
- `NaturalLanguagePlanResult` 保留 retrieval artifact。
- 完整 catalog validation 不变。

测试：

- Fake LLM 收到的 prompt 包含检索后的 recipe/tool context。
- Planner 成功路径仍产出 Recipe Tool Plan。
- Planner schema/catalog 错误分类不变。
- `--input` 结构化路径不触发 retriever。

### R3. Run Artifact 与事件

交付：

- 自然语言 run 在 planner 前记录 `catalog_retriever` 事件。
- run snapshot 暴露 `catalog_retrieval` artifact。
- SSE 可以回放检索阶段。

测试：

- 自然语言 run 创建后事件顺序包含 retriever。
- snapshot artifacts 包含 retrieval result。
- 失败路径不泄露 API key 或本地 credential path。

### R4. 前端展示

交付：

- 工作台 timeline 增加 Catalog Retrieval 阶段。
- run 卡片展示 top recipe/tools 和 `matched_terms`。
- 文案明确“仅来自 approved catalog”。

测试：

- TypeScript 类型更新。
- 前端 build/lint 在依赖安装后通过。

### R5. 文档与验收

交付：

- 更新 `DEVELOPMENT.md` 中 Tool Retriever 的落地状态。
- 更新 `docs/test-cases.md` 中新增测试意图。
- README 或作品集页面可增加一段能力说明。

验证：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1
```

如果只修改文档，可不运行完整单测，但最终功能实现 PR 应运行上述验证。

## 验收清单

- [x] 检索范围只包含 approved local catalog。
- [x] 检索结果包含 `score`、`matched_terms`、`matched_fields` 和 `reason`。
- [x] Planner prompt 使用 retrieved context。
- [x] 完整 Catalog validation 仍然执行。
- [x] 结构化入口不依赖 retriever。
- [x] 自然语言 run 记录 retriever 事件。
- [x] Run snapshot 暴露 retrieval artifact。
- [ ] 前端能展示候选 recipe/tools 和 `trust_status`。
- [x] 单测覆盖成功、fallback 和错误边界。
- [ ] 文档说明内部 RAG 与外部工具发现的边界。

## 面试展示叙述

推荐讲法：

> I added a retrieval layer over the approved bioinformatics catalog. It narrows
> planner context and records why tools were retrieved, but it does not admit
> new tools or bypass validation. The final Recipe Tool Plan still goes through
> full Catalog validation, Workflow IR analysis, deterministic WDL rendering,
> and syntax checking.

中文版本：

> 我把 RAG 做在正式工具目录内部。它帮助 Planner 缩小候选上下文，并记录为什么召回这些工具，但它不负责准入未知工具，也不能绕过完整 Catalog 校验。最终仍然走 Recipe Tool Plan、Workflow IR、Analyzer、确定性 WDL Renderer 和 Checker。

这个定位能同时展示 RAG 能力、领域工具建模能力和工程边界意识。
