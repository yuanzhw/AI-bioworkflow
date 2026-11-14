# R3C-1 Hybrid Reciprocal-Rank Fusion Backend

本文档定义 `hybrid_v1` 的可复现 rank-fusion 契约。R3C-1 只交付 backend、证据结构、
共享 evaluation 入口和 deterministic tests；固定真实模型的三方指标比较与 promotion
结论属于 R3C-2。

## Scope

`hybrid_v1` 组合现有两个 Approved Catalog backend：

- `lexical_v1` 保留显式 recipe/tool/alias 命中及 `matched_terms`、`matched_fields`；
- `vector_v1` 使用固定本地 multilingual E5 模型与 exact cosine index 提供语义排序；
- fusion 只使用两个分支的 rank，不直接混合 lexical score 与 cosine similarity；
- 输出仍通过 R3A common backend contract，只包含当前 approved recipes 和 tool versions。

R3C-1 不包含：

- 默认 backend 切换；
- RRF 权重或 `k` 调优；
- reranker、embedding fine-tuning 或 unsupported intent classifier；
- 外部工具发现、Catalog 准入或 container image 变更。

`lexical_v1` 继续作为生产默认。`hybrid_v1` 必须显式选择，并与 `vector_v1` 一样要求
已经准备完成的 local model directory；运行时不会下载模型。

## Fusion Contract

### Candidate pool

对每条 query，hybrid backend 让 lexical 与 vector 分支分别对完整 approved Catalog 排名：

- recipe pool 为当前全部 approved recipes；
- tool pool 为当前全部 approved tool versions；
- fusion 完成后才按调用方的 `top_k_recipes` / `top_k_tools` 截断。

这避免某个候选分别处于两个分支的较低名次、但合并后本应进入 top-K 时，被 component
top-K 过早丢弃。当前 checkpoint 为 5 个 recipes 和 16 个 tool versions；pool size 从
实际 Catalog 读取，不写死在实现中。

### Reciprocal-rank fusion

`hybrid_v1` 固定使用无权重 RRF，`k = 60`：

```text
rrf(candidate) = sum(1 / (60 + rank_backend(candidate)))
```

只在分支 direct ranking 中出现的候选获得该分支 contribution。Lexical 与 vector 原始
score 只作为 evidence 保留，不参与 fusion 算术。相同 fusion score 按稳定 identity
排序：recipe 使用 `id`，tool 使用 `(id, version)`。

同一分支如果返回重复 identity，hybrid backend fail closed，避免重复 RRF credit。
`hybrid_v1` 的 backend identity 与固定 `k = 60` 绑定；如未来调整算法或参数，应使用新的
versioned backend identity，而不是在相同名称下静默改变排序。

### Explanation and Catalog metadata

若候选出现在 lexical 分支，最终候选保留其 `matched_terms` 与 `matched_fields`；仅由 vector
召回的候选使用空 lexical explanation。Tool 的 `version`、`trust_status` 和
`execution_verification` 继续来自经过 common contract 校验的 Approved Catalog 数据，
fusion 层不生成或覆盖这些声明。

## Fallback Semantics

Component fallback candidate 是为保证 Planner context 有界可用而产生的 Catalog fallback，
不是相关性命中，因此不获得 RRF contribution：

- 某一个分支 fallback、另一个分支有 direct candidates 时，只融合 direct candidates；
- recipe/tool 两个分支都没有 direct candidate 时，hybrid 对应分支才标记 fallback；
- hybrid fallback 优先保留 lexical component 的 deterministic fallback candidates；若其为空，
  才使用 vector component candidates；
- top-level `fallback_used` 仍等于 `recipe_fallback_used or tool_fallback_used`。

Top-level evidence 同时保留每个 component 的 recipe/tool/aggregate fallback flags 和 reason，
不能从 hybrid aggregate 状态反推 component provenance。

## Evidence Contract

每个 fused candidate 的 `backend_evidence` 固定记录：

```json
{
  "fusion": {
    "algorithm": "reciprocal_rank_fusion",
    "rrf_k": 60,
    "score": 0.032258064516,
    "fallback": false
  },
  "components": {
    "lexical_v1": {
      "rank": 2,
      "score": 14.0,
      "rrf_contribution": 0.016129032258,
      "candidate_evidence": null
    },
    "vector_v1": {
      "rank": 2,
      "score": 0.81234567,
      "rrf_contribution": 0.016129032258,
      "candidate_evidence": {
        "document_id": "recipe:rnaseq_differential_expression",
        "rank": 2,
        "cosine_similarity": 0.81234567
      }
    }
  }
}
```

缺席的 component 值为 `null`。Backend-level evidence 记录 schema/backend identity、固定
fusion algorithm、`rrf_k`、实际 recipe/tool pool size，以及 lexical/vector 两个完整
component backend evidence 和 fallback provenance。

## Evaluation Entry Point

准备模型的命令与 R3B-2 相同：

```powershell
uv sync --extra vector
uv run python scripts/prepare_embedding_model.py `
  --output .cache/models/multilingual-e5-small
```

显式运行 hybrid evaluator：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py `
  --backend hybrid_v1 `
  --embedding-model-path .cache/models/multilingual-e5-small `
  --json-output .cache/retrieval-hybrid-v1.json
```

R3C-1 mandatory tests 注入 deterministic fake provider，不访问模型仓库，也不把 fake
ranking 当作质量证据。R3C-2 将使用固定真实模型重新运行 64-query fixture，对照 lexical、
vector 和 hybrid 的 aggregate、family、confusion、显式工具 query 与全部 per-query
regressions，再依据 promotion gates 给出结论。

## Definition Of Done

- `hybrid_v1` 可由正式 backend factory 和 evaluation CLI 显式构造；
- RRF 使用固定 `k = 60`、完整 Catalog pool 和稳定 identity tie-break；
- lexical explanation、Catalog-owned tool metadata、component rank/score/contribution 和
  fallback provenance 均保留；
- 64-query shared evaluator 可生成严格 JSON artifact；
- `lexical_v1` 默认行为、结构化 compile path 和 Catalog validation 边界不变；
- promotion review、默认切换与真实模型指标不在 R3C-1 中提前完成。
