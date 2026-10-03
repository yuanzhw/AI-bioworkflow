# R3 Retrieval Backend Decision

本文档记录 64-query、four-family baseline 之后的检索后端决策。它只讨论
Approved Catalog Retriever，不扩展未知工具发现，也不改变 Recipe Tool Plan、
Workflow IR、Catalog validation 或确定性 WDL 编译边界。

## Decision

R3 采用 **hybrid-first experiment**：

- `lexical_v1` 继续作为生产默认和回归基线。
- 下一阶段先建立可替换 backend contract，再离线评估 vector 与 hybrid ranking。
- hybrid 是候选升级方向，原因是它可以保留显式工具名、aliases 和可解释 lexical
  命中，同时补充自然语言改写和 family intent 的语义信号。
- vector-only 不直接替换 lexical 默认后端。
- 当前不做 embedding fine-tuning，也不在本 PR 引入 embedding model、vector store
  或新的运行时依赖。

只有候选 hybrid backend 满足本文档的 promotion gates，才可以在后续独立 PR 中
讨论成为默认后端。在此之前，所有新增 backend 都必须显式选择或仅用于离线评估。

## Baseline Evidence

评估集包含 64 条 query：56 条 supported query 覆盖 bulk RNA-seq、ChIP-seq、
scRNA-seq 和 germline short variant calling，另有 8 条 unsupported 边界样本。

| Metric | lexical_v1 baseline |
| --- | ---: |
| Recipe Recall@1 | 0.8571 |
| Recipe Recall@3 | 0.9821 |
| Recipe MRR | 0.9137 |
| Tool Recall@3 | 0.7128 |
| Tool Recall@5 | 0.7973 |
| Tool Recall@8 | 0.9158 |
| Macro Recipe Recall@1 | 0.8812 |
| Macro Tool Recall@5 | 0.7902 |
| Recipe family top-1 agreement | 0.8750 (49/56) |
| Planner Context Tool Recall | 1.0000 |
| Planner Context Role Coverage | 1.0000 |
| Unsupported Direct-Match Rate | 0.8750 (7/8) |

Recipe family top-1 confusion matrix：

| Expected family | bulk_rnaseq | chipseq | scrnaseq | variant_calling |
| --- | ---: | ---: | ---: | ---: |
| bulk_rnaseq | 18 | 1 | 3 | 1 |
| chipseq | 0 | 6 | 0 | 1 |
| scrnaseq | 1 | 0 | 13 | 0 |
| variant_calling | 0 | 0 | 0 | 12 |

该矩阵只包含有 expected recipe 的 supported query。它衡量 top-ranked recipe 的
workflow family 是否正确，不替代 exact recipe Recall@1；例如
`rnaseq_multiqc_logs_en` 的 top recipe 虽然不是 expected recipe，但仍属于
`bulk_rnaseq`，因此是 exact recipe miss 而不是 family confusion。

## Miss Taxonomy

Evaluation artifact 的 miss categories 可以重叠。同一 query 可以同时是 recipe
ranking miss、raw tool miss 和由 recipe context 恢复的 miss。

| Category | Count | Interpretation |
| --- | ---: | --- |
| `recipe_top_1_miss` | 8 | expected recipe 未排在首位 |
| `recipe_top_k_miss` | 1 | expected recipe 未进入 top-3 |
| `recipe_no_match` | 0 | supported query 的 recipe ranker 无真实匹配；fallback candidates 不计为命中 |
| `recipe_family_confusion` | 7 | top recipe 属于另一个 workflow family |
| `raw_tool_miss` | 15 | raw top-8 未覆盖全部 expected tools |
| `raw_role_miss` | 16 | raw top-8 未覆盖全部 expected roles |
| `raw_tool_miss_recovered_by_recipe_context` | 15 | recipe allowed tools 补齐全部 raw tool miss |
| `raw_role_miss_recovered_by_recipe_context` | 16 | recipe allowed tools 补齐全部 raw role miss |
| `planner_context_tool_miss` | 0 | recipe expansion 后仍缺 expected tool |
| `planner_context_role_miss` | 0 | recipe expansion 后仍缺 expected role |
| `unsupported_direct_match` | 7 | unsupported query 产生 lexical direct match |

### Cross-family negation and comparison

4 条 top-1 miss 来自显式对比句：

- `cross_family_scrnaseq_not_bulk_en`
- `cross_family_rnaseq_not_chipseq_en`
- `cross_family_bulk_not_scrnaseq_en`
- `cross_family_chipseq_not_variant_en`

`lexical_v1` 会给目标侧和否定侧术语都加正向分数，不能理解 “not” 所表达的方向。
四条 query 的 expected recipe 仍在 top-3，因此问题主要是 family ranking，而不是
Catalog coverage。

### Shared intent and generic wording

3 条 family confusion 来自跨 family 共享词汇：

- `rnaseq_quality_report_en` 被 variant calling、ChIP-seq 和 scRNA-seq recipe 挤出
  top-3。它是唯一的 `recipe_top_k_miss`。
- `rnaseq_params_threads_contrast_en` 被 scRNA-seq recipe 排在首位。
- `rnaseq_gene_counts_cn_mixed` 被 scRNA-seq recipe 排在首位。

这些 query 依赖 reporting、threads、contrast、counts 等通用词或隐式目标；继续增加
aliases 可能改善单个样本，但难以稳定表达完整 workflow intent。

### Same-family recipe competition

`rnaseq_multiqc_logs_en` 将 `rnaseq_reference_preparation` 排在
`rnaseq_differential_expression` 之前。它属于 exact recipe top-1 miss，但不属于
family confusion，说明 R3 不能只优化 family classification，还要保留 recipe-level
排序评估。

### Raw tool crowding and implicit steps

raw tool/role miss 主要集中在 `fastp`、`tximport`、`samtools`、`multiqc` 和
`deseq2` 等共享工具或隐式中间步骤。全部 miss 都被 top recipe 的 allowed tools
恢复，因此当前 Planner context 没有缺口。R3 可以改善 raw ranking，但不能以删除
recipe expansion 换取更好看的 raw metrics。

### Unsupported direct matches

8 条 unsupported query 中有 7 条命中 Catalog；只有 metagenomics query 触发
fallback。Retriever 的 direct match 表示词汇相关，不表示产品支持该 intent。
完整 Catalog validation 仍会阻止未知 recipe/tool 越过正式能力边界，但它本身不证明
自然语言 intent 已受支持。显式 intent routing/capability rejection 是独立的后续问题，
不能假设 vector 或 hybrid retrieval 会自动解决。

## Options Considered

### Continue lexical only

不选为 R3 的唯一方向。Lexical retrieval 稳定、确定、便于解释，并且显式工具名
表现良好，但 four-family fixture 已经复现否定侧干扰、共享 role crowding 和 generic
intent ambiguity。继续手工补 aliases 容易对当前 fixture 过拟合。

### Replace lexical with vector retrieval

不选。当前 Catalog 和标注集仍较小，vector-only 可能削弱 exact tool/version/alias
匹配，也会降低现有 `matched_terms` / `matched_fields` 的可解释性。它适合作为离线
对照 backend，而不是直接替换默认实现。

### Hybrid retrieval

选为实验方向。Lexical 分支保留精确命中和解释字段，vector 分支补充语义相似度，
fusion 层再统一排序。第一版优先评估 reciprocal-rank fusion，避免直接混合量纲不同的
lexical score 和 vector similarity；只有离线证据支持时才考虑权重调优或 reranker。

### Embedding fine-tuning

暂缓。64 条 query 足以做受控回归，不足以支撑有说服力的训练/验证拆分。Fine-tuning
应等待更多 family、真实改写和 validated plan feedback，并以独立 held-out set 衡量。

## Promotion Gates

候选 backend 必须输出同一 query set 的完整对比 artifact，并满足以下条件：

1. Recipe family top-1 agreement 高于 `0.8750`，或 overall Recipe Recall@1 高于
   `0.8571`；至少一个主要 recipe-ranking 指标必须有实际改善。
2. Macro Recipe Recall@1 不低于 `0.8812`，Macro Tool Recall@5 不低于 `0.7902`。
3. Planner Context Tool Recall 和 Planner Context Role Coverage 均保持 `1.0000`。
4. 显式指定 recipe/tool 的 query 不得从正确 top-1 或可用 top-K 退化为 miss。
5. 每个 workflow family、confusion cell 和 per-query regression 都必须可见；不能只用
   overall 平均分掩盖小 family 退化。
6. Retrieval artifact 必须保留 recipe/tool identity、rank、score/reason、recipe/tool
   component fallback provenance、trust status 和 execution verification；hybrid 还应
   记录各分支 rank/score 与 fusion 依据。
7. 所有结果仍只来自 approved Catalog，完整 Catalog validation 继续执行；结构化
   `--input` 编译路径不得依赖 embedding 服务。

`Unsupported Direct-Match Rate` 必须继续报告，但不作为 hybrid promotion 指标。它是
intent routing/capability rejection 的风险信号，而不是相关性 ranking 的准确率。

## Implementation Sequence

### R3A: Retriever Backend Contract

- 抽取 recipe/tool retrieval backend interface 和 backend selection config。
- 将 `lexical_v1` 接入该 interface，保持默认行为和 artifact 向后兼容。
- 为 backend-specific evidence 预留结构化字段，不在公共路径中引入 embedding 依赖。
- 让 evaluation runner 可以对同一 fixture 指定 backend 并生成可比较结果。

### R3B: Vector Prototype And Offline Evaluation

- 从 approved recipe/tool metadata 构造可版本化 documents。
- 选择可本地复现的 embedding model，并记录 model id、revision、document schema 和
  index fingerprint。
- 只通过显式配置运行 vector prototype；不得静默下载模型或影响默认 Planner。
- 输出与 lexical 相同的 metrics、family confusion 和 miss categories。

### R3C: Hybrid Fusion And Promotion Review

- 实现 lexical/vector rank fusion，第一版优先 reciprocal-rank fusion。
- 保留 lexical explanation，并增加 vector/fusion provenance。
- 用本文档 promotion gates 比较 lexical、vector 和 hybrid。
- 只有通过 gates 后，另开 PR 决定是否切换默认 backend；否则保留实验实现或记录
  rejection decision。

Reranker、embedding fine-tuning 和 unsupported intent classifier 不进入 R3A-R3C。

## R3A Outcome

R3A 已完成以下基础设施，同时保持 `lexical_v1` scoring 与 64-query baseline 不变：

- `CatalogRetrievalBackend` Protocol、`LexicalCatalogRetrievalBackend` 和只接受显式名称的
  backend factory；未知 backend 会列出当前支持值并立即失败。
- active backend output 统一校验 normalized query、strategy、完整 recipe/tool candidate
  shape、精确 approved Catalog 成员、Catalog-owned tool trust/verification metadata、
  component fallback provenance、aggregate fallback、请求 top-k 上限、versioned
  `backend_evidence` 和递归 JSON compatibility。
- 原 `retrieve_catalog_context(...)` 继续作为 lexical compatibility API；Planner 与
  evaluation 的默认运行路径改由 backend contract 驱动。
- Natural Language Planner、Orchestration Planner node 与 evaluation runner 均支持
  backend dependency injection。
- `scripts/evaluate_retrieval.py` 增加 `--backend`；当前唯一允许值和默认值均为
  `lexical_v1`。
- Evaluation per-query artifact 同时保留 candidate IDs、完整 candidate objects 和
  backend evidence，为 R3B/R3C 的 model/index/fusion provenance 留出稳定位置。
- 前端读取接受新 evidence，同时继续兼容缺少 evidence 或 component fallback flags 的
  legacy run snapshots。

下一步是 R3B：引入可本地复现、只能显式选择的 vector prototype，记录 model revision、
document schema 和 index fingerprint，并用相同 64-query fixture 离线评估。R3B 不改变
生产默认 backend。

## Contract Boundaries

- LLM 不直接生成 WDL。
- Retriever 只缩小 Planner candidate context，不决定最终 Catalog 合法性。
- Recipe expansion 继续参与 Planner context；raw retrieval metrics 不能替代最终候选
  context metrics。
- Backend 不搜索、推断或替换 container image。
- 新 backend 不改变 ToolSpec execution verification 状态。
- 外部工具发现继续属于 P6 Candidate ToolSpec 流程。

## PR 6 Outcome

PR 6 为 evaluation artifact 增加：

- 每条 query 的 `top_recipe_id`、`top_recipe_family` 和 `miss_categories`。
- aggregate `recipe_family_confusion`。
- aggregate `miss_categories`，包含稳定的零计数类别和对应 query ids。
- CLI summary 中的 family confusion matrix 与 populated miss categories。
- component-level recipe/tool fallback provenance；fallback candidates 保留在 Planner
  context，但从 ranked metrics 中排除。
- evaluation backend 在 aggregate fallback 为 `true` 时必须提供两个 component flags，
  且 aggregate 必须等于 component flags 的逻辑或；不允许从 aggregate 状态猜测来源。
- 保留全部 expected family confusion columns，并以 `no_match` / `unmapped` 表达额外
  prediction states。

这些字段建立了后续 backend A/B comparison 的可审计基线；PR 6 本身不改变
`lexical_v1` scoring、默认 retrieval path 或 Catalog 内容。
