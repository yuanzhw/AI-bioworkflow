# R2 Retrieval Evaluation Roadmap

本文档记录 Approved Catalog Retriever 的评估与检索策略演进路线。它聚焦查询测试集、retrieval metrics、vector / hybrid retrieval 和 embedding fine-tuning 的优先级。

本文档是 RAG 开发序列的 R2。第一版内部 Catalog RAG 的实现边界、输入输出契约和已完成清单由 [R1 Internal Catalog RAG / Tool Retriever](./r1-internal-catalog-rag-plan.md) 维护。本文档不重复 MVP 实现细节，只规划评估和后续 retriever backend 演进。

## Current Retriever

当前 retriever 是 `Approved Catalog Retriever`：

```text
natural language request
  -> lexical retrieval over approved Recipe / Tool Catalog
  -> retrieved recipes and tools
  -> planner prompt context
  -> Recipe Tool Plan
  -> full Catalog validation
```

已具备能力：

- 只读取本地 approved Recipe / Tool Catalog。
- 使用确定性 lexical scoring。
- 输出 `score`、`matched_terms`、`matched_fields`、`reason`。
- Tool 结果包含 `trust_status`。
- recipe 或 tool 召回无匹配时触发 fallback，并在 artifact 中记录 `fallback_used` / `fallback_reason`。
- Retrieval artifact 会保存到 run snapshot，并可在前端展示。
- 完整 Catalog validation 仍使用全量 approved catalog。

## Why Evaluation Comes Before Vector Search

向量数据库和 embedding 检索适合进入后续路线，但应建立在评估集之后。否则无法判断检索策略是否真正改善了 planner context。

推荐顺序：

```text
retrieval query set
  -> lexical baseline
  -> vector retrieval
  -> hybrid retrieval
  -> reranker
  -> embedding fine-tuning
```

## Retrieval Query Set

查询测试集是一组人工标注的自然语言请求和期望召回结果。它不是生信原始数据，也不是 LLM 训练数据。

第一版样本结构：

```json
{
  "id": "rnaseq_deg_basic_en",
  "query": "Run bulk RNA-seq differential expression from paired-end FASTQ files.",
  "supported": true,
  "expected_recipe": "rnaseq_differential_expression",
  "expected_tools": ["fastp", "salmon", "tximport", "multiqc"],
  "expected_roles": {
    "read_quality_control": ["fastp"],
    "expression_quantification": ["salmon"],
    "transcript_to_gene_count_summary": ["tximport"],
    "differential_expression": ["deseq2", "edger", "limma_voom"],
    "quality_control_summary": ["multiqc"]
  },
  "notes": "Basic RNA-seq DEG request without explicit DE backend names."
}
```

`supported: false` 用于当前 approved Catalog 暂不支持的负例。负例不定义
`expected_recipe`、`expected_tools` 或 `expected_roles`，因此不会拉低当前
RNA-seq baseline recall；它们单独用于观察 fallback、误召回和未来 Catalog
扩展需求。

当前 query set 覆盖：

- 英文 RNA-seq DEG 请求。
- 中文 RNA-seq DEG 请求。
- 缩写表达，例如 DEG、RNAseq、bulk RNA。
- 明确工具名请求，例如 use Salmon and DESeq2。
- 只描述分析目标但不说工具名。
- RNA-seq reference preparation，例如 Salmon index 和 GTF -> tx2gene。
- edgeR 和 limma-voom 等 differential expression 替代后端。
- Catalog 暂不支持的负例，例如 ChIP-seq、scRNA-seq、variant calling。
- 模糊需求，例如 quality report、quantification、gene-level counts。
- 参数相关请求，例如 paired-end reads、contrast、threads。

建议文件：

```text
tests/fixtures/retrieval_queries.json
```

### R2a Current-Catalog Baseline Scope

R2 不要求先扩充工具数量。第一步先基于当前 approved Catalog 建立可重复
baseline：

- 12 条当前支持范围内的 RNA-seq DEG / QC / quantification / reporting 查询。
- 4 条 unsupported negative queries，覆盖 ChIP-seq、scRNA-seq、variant
  calling 和 metagenomics。
- 指标仅声明为 current-catalog baseline，不代表多 workflow family 检索能力。
- 后续增加更多 approved tools / recipes 后，再扩展到 20-40 条跨领域 query，
  并用同一 eval contract 比较 lexical、vector 和 hybrid backend。

当前 fixture：

```text
tests/fixtures/retrieval_queries.json
```

### R2b Expanded RNA-seq Catalog Baseline

在 Catalog 增加 `rnaseq_reference_preparation`、`salmon_index`、`gtf_tx2gene`、
`edger` 和 `limma_voom` 后，query set 扩展为：

- 20 条当前支持范围内的 RNA-seq DEG / reference prep / QC / quantification /
  reporting 查询。
- 4 条 unsupported negative queries，继续覆盖 ChIP-seq、scRNA-seq、variant
  calling 和 metagenomics。
- 泛化 differential expression query 不再硬性要求 `deseq2`；它们通过
  `expected_roles.differential_expression` 表达 `deseq2`、`edger` 或
  `limma_voom` 任一 approved backend 均可覆盖该 role。
- 显式指定 differential expression backend 的 query 仍将对应 tool 记录在
  `expected_tools` 中，并且只允许该 tool 覆盖
  `expected_roles.differential_expression`。

## Metrics

第一版 eval 应保持轻量、可解释、可在本地稳定运行。

| Metric | Definition | Purpose |
| --- | --- | --- |
| `Recipe Recall@K` | expected recipe 是否出现在 top-K recipes | 判断分析类型召回是否可靠 |
| `Tool Recall@K` | expected tools 中有多少出现在 top-K tools | 判断候选工具是否完整 |
| `MRR` | 第一个正确 recipe 或 tool 的 reciprocal rank | 判断排序质量 |
| `Role Coverage` | expected_roles 中每个 role 是否至少有一个正确 tool | 判断 workflow step 覆盖 |
| `Planner Context Tool Recall` | raw retrieved tools 加上 retrieved recipes 的 allowed tools 后覆盖多少 expected tools | 判断 Planner prompt 候选上下文是否完整 |
| `Planner Context Role Coverage` | Planner candidate context 是否覆盖每个 expected role | 区分 raw retriever miss 和 prompt context 可用性 |
| `Fallback Rate` | 触发 fallback 的 query 占比 | 判断 catalog 覆盖和检索置信度 |

初始目标不是追求高分，而是建立可重复 baseline：

```text
lexical_v1 Recipe Recall@3
lexical_v1 Tool Recall@8
lexical_v1 Role Coverage
lexical_v1 Planner Context Role Coverage
lexical_v1 Fallback Rate
```

## Eval Script

当前新增独立脚本与 unittest：

```text
scripts/evaluate_retrieval.py
tests/test_retrieval_evaluation.py
```

输出应包括：

- 每条 query 的 retrieved recipes/tools。
- missed expected recipe/tool。
- aggregate metrics。
- fallback queries。

输出格式建议同时支持人类可读 summary 和 JSON artifact，便于后续前端或文档展示。

当前命令：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py
```

当前 `lexical_v1` expanded RNA-seq catalog baseline：

| Metric | Value |
| --- | ---: |
| Query count | 24 |
| Supported queries | 20 |
| Unsupported queries | 4 |
| Recipe Recall@3 | 1.0000 |
| Recipe MRR | 0.9500 |
| Tool Recall@8 | 0.9708 |
| Tool MRR | 0.9600 |
| Role Coverage | 0.9733 |
| Planner Context Tool Recall | 1.0000 |
| Planner Context Role Coverage | 1.0000 |
| Fallback Rate | 0.0417 |
| Supported Fallback Rate | 0.0000 |
| Unsupported Fallback Rate | 0.2500 |

已知 baseline 观察：

- `rnaseq_deg_no_tool_names_en` 和 `rnaseq_params_threads_contrast_en` 的 raw
  tool retrieval 未直接召回 `tximport`，说明 query 只描述目标或参数时，
  lexical tool recall 仍会漏掉中间步骤。
- Planner Context Tool Recall 和 Planner Context Role Coverage 均为 1.0000，
  说明当 top recipe 召回正确时，Planner prompt 中通过 recipe allowed tools
  补齐的候选上下文仍覆盖所需工具和 role。
- `unsupported_chipseq_peak_calling_en`、`unsupported_scrnaseq_clustering_en`
  和 `unsupported_variant_calling_en` 产生 direct lexical match，说明当前
  lexical fallback 不是 unsupported intent detector；负例评估只用于暴露风险，
  不改变 full Catalog validation 边界。

## Vector / Hybrid Retriever

在 baseline 建立后，再引入可替换 retriever backend。

### Vector Retriever

职责：

- 将 recipe/tool metadata 构造成本地 catalog documents。
- 对 description、aliases、inputs、outputs、params、steps role 建立 embedding。
- 保留 metadata filtering，例如 tool id、version、`trust_status`、recipe id。

边界：

- 只检索 approved catalog。
- 不发现外部工具。
- 不改变 Catalog validation。
- 不替换 runtime image。

### Hybrid Retriever

职责：

- 融合 lexical score 和 vector similarity。
- 保留 `matched_terms` / `matched_fields`，用于解释。
- 输出与 lexical retriever 相同的 artifact contract。

验收：

- Hybrid retriever 在 query set 上优于或不低于 lexical baseline。
- 如果某些 query 变差，应在 eval output 中可见。
- Planner validation pass rate 不下降。

## Embedding Fine-Tuning Priority

Embedding model fine-tuning 暂不作为近期优先项。

原因：

- 当前 catalog 规模较小。
- 人工标注 query 和 validated plan 数据不足。
- 过早微调很难证明收益。
- Fine-tuning 应以 eval 指标提升为目标，而不是单独作为模型实验。

较合理的触发条件：

- Approved Catalog 扩展到几十到上百个工具。
- Query set 覆盖多个 workflow family。
- 已积累 validated plans、missed retrieval cases 和人工修正记录。
- Lexical / vector / hybrid baseline 已稳定。

届时可评估：

- local bi-encoder retriever。
- reranker for top-K candidates。
- domain-specific embedding fine-tuning。

## Relationship To Frontend And Agent Workflow

Retrieval eval 的结果可以被前端轻量展示，但前端不应重新计算指标。

后端 Agent workflow 使用 retriever 的规则保持不变：

- Retriever 提供 planner candidate context。
- Full Catalog validation 仍是准入边界。
- 结构化 compile path 不依赖 retriever。
- Retrieval miss 不应导致系统绕过 approved catalog。

## Deliverables

建议 PR 顺序：

1. **Retrieval query set**
   - 添加 `tests/fixtures/retrieval_queries.json`。
   - 覆盖中英文、缩写、工具名显式、工具名隐式、负例。

2. **Retrieval eval baseline**
   - 添加 eval 脚本或测试。
   - 输出 Recall@K、MRR、Role Coverage、Fallback Rate。
   - 文档记录 lexical baseline。

3. **Retriever interface**
   - 抽象 lexical backend。
   - 保持现有 artifact contract。

4. **Vector backend prototype**
   - 加入本地 vector index 或轻量 embedding backend。
   - 不影响结构化入口。

5. **Hybrid scoring**
   - 融合 lexical 和 vector。
   - 用 eval 证明效果。

## Verification

只修改评估文档时无需跑完整测试。

修改 retriever 或 eval 代码时运行：

Linux / macOS：

```bash
.venv/bin/python -m unittest discover -v
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

如果新增前端展示 retrieval metrics，还应运行：

```powershell
cd web
npm run lint
npm run test:catalog-retrieval
npm run build
```
