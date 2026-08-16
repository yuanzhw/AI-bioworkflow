# Catalog Expansion for RAG Development Plan

本文档记录 R2 retrieval evaluation baseline 之后的 Catalog 扩展计划。当前目标
不是立即引入 vector / hybrid backend，而是先通过更多 workflow family 扩大
Approved Catalog Retriever 的语义空间，再用跨 family 评测决定 R3 是否值得
投入。

本阶段以工程能力、领域建模、可解释检索和边界设计展示为优先，不要求每个新增
workflow 都完成真实生物数据 e2e。但正式 Catalog 仍必须保持结构化、可审计，
不能用缺失 command、虚构镜像或无法通过 schema validation 的占位条目冒充
approved tool。

## Decision Summary

Catalog 按以下顺序扩展：

```text
ChIP-seq peak calling
  -> scRNA-seq QC and clustering
  -> germline short variant calling
  -> cross-family retrieval baseline
  -> R3 lexical / vector / hybrid decision
```

选择该顺序的原因：

- ChIP-seq 规模适中，能够复用 `fastp` 和 `multiqc`，并新增 alignment、
  BAM processing、peak calling 等 role。
- scRNA-seq 与 bulk RNA-seq 词汇相近，适合测试近邻 workflow family 的语义
  消歧。
- Variant calling 与 RNA-seq 差异较大，适合测试跨领域 recipe/tool 召回。
- 三个 family 依次落地可以避免一个大 PR 同时引入过多 schema、container 和
  evaluation 变化。

ChIP-seq、scRNA-seq 和 variant calling 的工具内容允许适当简化。简化的是
workflow 科学范围、参数数量和执行验证深度，不是 ToolSpec 契约完整度。

## Current Baseline

当前 approved Catalog 包含：

- 2 个 recipe，均属于 bulk RNA-seq family：
  - `rnaseq_differential_expression`
  - `rnaseq_reference_preparation`
- 9 个 tool：
  - `fastp`
  - `salmon`
  - `salmon_index`
  - `tximport`
  - `gtf_tx2gene`
  - `deseq2`
  - `edger`
  - `limma_voom`
  - `multiqc`
- 24 条 retrieval query：
  - 20 条 supported RNA-seq query。
  - 4 条 unsupported negative query。

当前 `lexical_v1` baseline 的 Planner Context Tool Recall 和 Planner Context
Role Coverage 均为 `1.0000`。这说明当前 RNA-seq Catalog 内的 prompt context
覆盖稳定，但不能证明跨 workflow family 的检索能力。

现有 `Recipe Recall@3` 和 `Tool Recall@8` 在 Catalog 较小时区分度有限。扩展
Catalog 后应增加更严格的 top-K 和 family-level 指标。

## Goals

本计划的目标是：

1. 将 approved Catalog 从单一 bulk RNA-seq family 扩展到至少四类分析需求。
2. 建立 tool catalog admission、compilation readiness 和 execution
   verification 的清晰边界。
3. 让 Planner 在相似和不相似 family 间都能获得可解释候选上下文。
4. 建立可按 workflow family 分组的 retrieval evaluation。
5. 用真实 baseline 变化决定是否进入 R3 vector / hybrid prototype。
6. 保持 Recipe Tool Plan、Workflow IR、Analyzer、Renderer 和 Checker 边界不变。

## Non-Goals

本阶段不要求：

- 所有新增 workflow 完成真实 Cromwell e2e。
- 对生物学结果正确性做生产级验证。
- 完成性能、资源和大规模数据 benchmark。
- 支持所有 ChIP-seq、scRNA-seq 或 variant calling 方法。
- 自动搜索外部工具并写入正式 Catalog。
- 引入 vector database、embedding service、reranker 或模型微调。
- 允许 LLM 直接生成最终 WDL。
- 绕过完整 Catalog validation 或 execution backend policy。

## Tool Capability Levels

工具能力需要区分三个层级：

| Level | Required contract | Allowed usage |
| --- | --- | --- |
| Retrieval-only | id、aliases、description、roles 和必要检索字段 | 只用于 evaluation fixture，不进入默认 Planner、Resolver 或正式 Catalog |
| Compile-ready | 完整 inputs、outputs、params、command template 和明确 runtime | 可以进入 Planner 和确定性编译；执行状态必须显示为未验证 |
| Execution-verified | Compile-ready，加 smoke test 或小数据真实执行记录 | 可以声明已完成对应级别的执行验证 |

### Retrieval-only Policy

Retrieval-only 条目不得写入默认 `src/catalog/tools` 并被当作正式
`catalog-approved` 工具加载。建议将其保存在独立 fixture，例如：

```text
tests/fixtures/retrieval_catalog/
```

它们可以用于测试 ranking、family confusion 和 query coverage，但不能被
Recipe Tool Plan 选择，也不能进入 Workflow IR。

### Compile-ready Policy

正式 Catalog 中的新增工具至少必须达到 compile-ready：

- 明确 `id` 和 `version`。
- 定义 aliases 和用途说明。
- 定义完整 input、output 和 parameter schema。
- command template 只引用已声明变量。
- 明确 `runtime.docker`，不得使用虚构占位镜像。
- Tool Catalog loader 和 schema validation 通过。
- Recipe Resolver 可以验证对应 tool plan。
- Renderer 可以生成确定性 WDL。
- WDL 语法验证通过。

Compile-ready 不等于执行已验证。当前 ToolSpec 尚未记录该区别，第一项实现
工作应为 Tool Catalog 增加独立的 execution verification 状态。字段命名和
枚举在实现 PR 中确定，但至少应表达：

```text
unverified
smoke-tested
e2e-validated
```

Catalog admission、compilation readiness 和 execution verification 是不同
概念，不应继续通过单个硬编码 `catalog-approved` 文案隐含全部状态。

### Execution Policy

- 默认 disabled execution backend 不受影响。
- 真实 execution backend 应拒绝未验证工具，或要求显式 opt-in。
- API、run artifact 和前端应显示 execution verification 状态。
- 未验证工具可以用于 Planner 和 WDL 编译演示，但不得描述为已经真实运行。
- 项目维护的 R/Python/helper wrapper 仍需 Dockerfile、打包脚本和最小
  `smoke_test.sh`。如果当前阶段不准备满足该要求，应先保留为
  retrieval-only，而不是进入正式 Catalog。

## Family 1: ChIP-seq Peak Calling

### MVP Scope

建议新增 recipe：

```text
chipseq_peak_calling
```

最小步骤：

```text
paired-end ChIP-seq FASTQ
  -> fastp
  -> bowtie2
  -> samtools sort/index
  -> macs2 peak calling
  -> multiqc
```

复用现有工具：

- `fastp`
- `multiqc`

建议新增工具：

- `bowtie2`
- `samtools`
- `macs2`

为控制范围，`samtools` 可以先提供边界清晰的 sort/index command contract，
不必覆盖完整 samtools 子命令集合。

### Inputs And Outputs

建议输入：

- sample ids。
- paired-end ChIP FASTQ。
- paired-end input/control FASTQ，第一版可以定义为 optional。
- prebuilt genome index。
- peak calling genome size 参数。

建议输出：

- filtered FASTQ。
- aligned and sorted BAM。
- BAM index。
- peak table，例如 narrowPeak。
- workflow QC summary。

### Deferred Scope

第一版不做：

- deepTools coverage track。
- replicate IDR。
- broad/narrow peak 自动策略选择。
- blacklist filtering。
- motif enrichment。
- peak annotation。
- 真实 peak quality benchmark。

### Retrieval Coverage

ChIP-seq query 应覆盖：

- peak calling。
- transcription factor binding。
- histone modification enrichment。
- MACS2 显式请求。
- input/control 描述。
- 只描述 enriched genomic regions 而不写工具名。
- 与 RNA-seq 共享的 QC/reporting 模糊请求。

当前 ChIP-seq unsupported negative query 在该 family 落地后转为 supported。

## Family 2: scRNA-seq QC And Clustering

### MVP Scope

建议新增 recipe：

```text
scrnaseq_qc_clustering
```

最小步骤：

```text
10x filtered feature-barcode HDF5
  -> cell and gene QC
  -> normalization
  -> highly variable genes
  -> PCA and neighbors
  -> Leiden clustering
  -> UMAP
  -> marker table
```

为控制 Tool Catalog 数量，第一版可以使用一个边界明确的
`scanpy_qc_clustering` compile-ready tool，而不是立即拆成多个只调用一次的
Scanpy wrapper。后续如果需要展示 step-level alternatives，再拆分为独立工具。

### Inputs And Outputs

建议输入：

- 10x HDF5 count matrix。
- optional sample metadata。
- QC thresholds。
- clustering resolution。
- random seed。

建议输出：

- filtered `.h5ad`。
- cell QC table。
- UMAP coordinates 或 plot。
- cluster assignments。
- marker gene table。

### Deferred Scope

第一版不做：

- raw FASTQ 和 Cell Ranger。
- reference bundle 构建。
- doublet detection。
- batch integration。
- automatic cell type annotation。
- trajectory、RNA velocity、多组学和空间转录组。

如果 `scanpy_qc_clustering` 使用项目维护脚本，则必须满足 wrapper/container
规则；否则第一步只建立 retrieval-only metadata 和 query fixture。

### Retrieval Coverage

scRNA-seq query 应重点测试与 bulk RNA-seq 的近邻消歧：

- single-cell clustering。
- UMAP and Leiden。
- marker genes。
- cell-level QC。
- 10x matrix。
- bulk DEG 与 single-cell marker detection 的模糊表达。

当前 scRNA-seq unsupported negative query 在该 family 落地后转为 supported。

## Family 3: Germline Short Variant Calling

### MVP Scope

建议新增 recipe：

```text
germline_short_variant_calling
```

最小步骤：

```text
paired-end FASTQ
  -> fastp
  -> bwa_mem2
  -> samtools sort/index
  -> bcftools call
  -> bcftools filter
  -> multiqc
```

复用现有工具：

- `fastp`
- `multiqc`

建议新增工具：

- `bwa_mem2`
- `samtools`，与 ChIP-seq 共用。
- `bcftools`。

### Inputs And Outputs

建议输入：

- sample ids。
- paired-end FASTQ。
- reference FASTA。
- prebuilt BWA index 或显式 reference bundle。
- ploidy 和基础过滤参数。

建议输出：

- aligned and sorted BAM。
- BAM index。
- unfiltered VCF。
- filtered VCF。
- workflow QC summary。

### Deferred Scope

第一版不做：

- GATK BQSR 和 VQSR。
- joint genotyping。
- somatic calling。
- CNV 和 structural variants。
- long-read calling。
- cohort-scale reference resource management。

### Retrieval Coverage

Variant calling query 应覆盖：

- germline SNV/indel。
- BWA、samtools 和 bcftools 显式请求。
- FASTQ to VCF。
- alignment and variant filtering。
- 与 ChIP-seq 共享的 alignment/BAM 描述。
- 与 RNA-seq 共享的 paired-end FASTQ 和 QC 描述。

当前 variant calling unsupported negative query 在该 family 落地后转为
supported。

## Retrieval Evaluation Expansion

### Query Set Growth

建议分阶段扩展当前 24 条 fixture：

| Milestone | Supported queries | Unsupported queries | Focus |
| --- | ---: | ---: | --- |
| Current R2 | 20 | 4 | RNA-seq baseline |
| After ChIP-seq | 30-36 | 4-6 | First cross-family ranking |
| After scRNA-seq | 42-52 | 5-7 | Bulk/single-cell disambiguation |
| After variant calling | 55-70 | 6-10 | Multi-family retrieval |

新增 query 应包含：

- 每个 family 的明确 recipe intent。
- 明确工具名和不写工具名的表达。
- 中英文和常见缩写。
- 只描述输入、输出或目标的 query。
- 跨 family 共享 role，例如 QC、alignment、reporting。
- 容易混淆的近邻 query。
- 仍未支持的 ChIP annotation、metagenomics、long-read、CNV/SV 等负例。

Query fixture 应增加显式 `workflow_family` 标签，例如：

```text
bulk_rnaseq
rnaseq_reference
chipseq
scrnaseq
germline_variant
unsupported
```

该字段只用于 evaluation 分组，不替代 `expected_recipe`，也不进入 Planner
prompt。Unsupported query 继续通过 `supported: false` 表达准入边界。

### Metrics

保留现有历史指标：

- Recipe Recall@3。
- Recipe MRR。
- Tool Recall@8。
- Tool MRR。
- Raw Role Coverage。
- Planner Context Tool Recall。
- Planner Context Role Coverage。
- Fallback Rate。

新增更严格指标：

- Recipe Recall@1。
- Tool Recall@3。
- Tool Recall@5。
- 每个 workflow family 的独立指标。
- macro-averaged family metrics。
- recipe confusion matrix。
- unsupported direct-match rate。

Supported 和 unsupported query 继续分开统计。Unsupported negative queries 不参与
supported recall，但必须暴露 direct lexical match 和 fallback 风险。

### Baseline Interpretation

- Raw tool miss 不自动等于 Planner context failure。
- Retrieved recipe 的 allowed tools 可以补齐 Planner context，但不能掩盖
  recipe ranking 错误。
- 当 Catalog recipe 数量接近 `top_k_recipes` 时，Recipe Recall@3 不能作为
  主要判断依据，应优先看 Recall@1 和 MRR。
- Unsupported direct match 是 intent routing / confidence policy 问题，不应
  假设 vector retrieval 会自动解决。

## R3 Decision Gate

完成四个 workflow family 的 lexical baseline 后再决定 R3。

优先尝试 vector / hybrid 的信号包括：

- Recipe Recall@1 或 MRR 在自然语言改写下明显下降。
- bulk RNA-seq 与 scRNA-seq 出现稳定 family confusion。
- ChIP-seq 与 variant calling 的 alignment/BAM query 经常错排。
- Planner Context Role Coverage 出现 recipe expansion 也无法补齐的 miss。
- 增加 aliases 和 metadata 后 lexical miss 仍持续存在。

不应进入 vector / hybrid 的情况：

- 只有少量直接工具 miss，但 Planner context coverage 仍接近完整。
- 主要问题是 unsupported intent detection。
- Catalog 仍过小，top-K 几乎覆盖全部条目。
- Query set 规模不足，无法证明新 backend 优于 `lexical_v1`。

如果进入 R3，vector 或 hybrid backend 必须保持现有 retrieval artifact contract
和完整 Catalog validation 边界。

## Proposed PR Sequence

### PR 1: Tool Capability And Verification Contract

- 为 ToolSpec 设计 execution verification 状态。
- 区分 Catalog admission、compile readiness 和 execution verification。
- 更新 Retriever artifact、API 类型和前端状态文案。
- 为 execution backend 增加未验证工具 policy。

### PR 2: ChIP-seq Tool Catalog

- 加入 `bowtie2`、`samtools` 和 `macs2`。
- 复用 `fastp`、`multiqc`。
- 添加 schema/load/rendering tests。
- 标记真实 execution verification 状态。

### PR 3: ChIP-seq Recipe And Retrieval Baseline

- 加入 `chipseq_peak_calling`。
- 添加 example plan 和确定性 WDL validation。
- 将 ChIP-seq negative query 转为 supported。
- 增加 cross-family query 和 Recall@1/Tool Recall@3/5。

### PR 4: scRNA-seq Catalog And Recipe

- 加入 `scrnaseq_qc_clustering`。
- 根据 wrapper readiness 选择 retrieval-only 或 compile-ready 路径。
- 增加 bulk/scRNA confusion cases。

### PR 5: Variant Calling Catalog And Recipe

- 加入 `bwa_mem2`、`bcftools`，复用 `samtools`、`fastp` 和 `multiqc`。
- 加入 `germline_short_variant_calling`。
- 增加 FASTQ/BAM/VCF retrieval cases。

### PR 6: Cross-family Baseline And R3 Decision

- 汇总四个 family 的 metrics。
- 增加 family macro metrics 和 confusion matrix。
- 记录 lexical miss categories。
- 明确继续 lexical、尝试 vector，或实现 hybrid 的决策。

每个 PR 保持单一主题。工具 schema、recipe、evaluation 和 frontend contract
变化较大时继续拆分，避免在一个 PR 中同时修改过多架构边界。

## Verification Policy

只修改规划文档时无需运行完整测试。

新增或修改正式 Tool Catalog 时至少运行：

Linux / macOS：

```bash
.venv/bin/python -m unittest tests.test_catalog tests.test_catalog_retriever tests.test_retrieval_evaluation -v
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_catalog tests.test_catalog_retriever tests.test_retrieval_evaluation -v
```

实际测试模块名称应以仓库当时已有测试为准，不新增不存在的固定命令。影响
recipe resolution、Workflow IR 或 WDL 输出时，还应：

- 运行相关 resolver、renderer 和 graph tests。
- 生成代表性 WDL。
- 使用配置的 WOMtool 或 miniwdl 做语法验证。
- 更新 `docs/test-cases.md`。

项目维护 wrapper/container 必须增加：

- Dockerfile。
- helper script。
- `smoke_test.sh`。
- 最小 resolver/rendering 或 execution-path test。

真实生物数据 e2e 不是 compile-ready 的完成条件，但必须在文档、artifact 和
前端中明确显示 execution 尚未验证。

## Definition Of Done

单个 family 的 Catalog expansion 完成需要：

- Tool metadata 足以支持可解释 retrieval。
- 正式工具满足完整 ToolSpec；纯 metadata 条目只存在于 evaluation fixture。
- Recipe roles、allowed tools、required inputs 和 outputs 明确。
- Planner context 可以区分该 family 和已有 family。
- Full Catalog validation 仍然执行。
- Structured compile path 不依赖 Retriever。
- Retrieval query set 覆盖明确、隐式、缩写、中文和 confusion cases。
- Family-level baseline 已记录。
- Execution verification 状态真实、可见、不会误导。
- 文档和测试意图已同步。

## Immediate Next Step

本计划落地后的第一项代码工作是 Tool Capability And Verification Contract。
在该契约合并前，不向正式 Catalog 批量加入未执行验证的新工具。

契约稳定后，优先实现简化版 ChIP-seq tool metadata、recipe 和 retrieval
baseline，再按相同模式推进 scRNA-seq 与 variant calling。
