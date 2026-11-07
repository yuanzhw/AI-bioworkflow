# R3B-2 Vector Backend Prototype

## Status

R3B-2 建立了显式选择的本地 `vector_v1` prototype。它消费 R3B-1 的 canonical
Catalog documents，通过固定模型身份和精确 cosine index 产生与 `lexical_v1` 相同形状
的 retrieval artifact。

`lexical_v1` 继续是默认 backend。R3B-2 不实现 hybrid fusion，不改变 Planner 默认
路径，也不让结构化 `--input` 编译依赖 embedding runtime。

## Selected Model

Prototype 固定以下模型身份：

- model id：[`intfloat/multilingual-e5-small`](https://huggingface.co/intfloat/multilingual-e5-small)
- revision：
  [`fd1525a9fd15316a2d503bf26ab031a61d056e98`](https://huggingface.co/intfloat/multilingual-e5-small/commit/fd1525a9fd15316a2d503bf26ab031a61d056e98)
- embedding dimension：`384`
- query prefix：`query: `
- document prefix：`passage: `
- runtime extra：`sentence-transformers==5.5.1`

该模型覆盖中英文等多语言输入，且模型卡明确要求 retrieval query/document 使用不同
prefix。固定 revision、dimension 和 prefix 可以避免同名模型或调用方式变化后继续复用
旧 index。

## Runtime Boundary

模型下载与 retrieval runtime 严格分离：

1. `scripts/prepare_embedding_model.py` 是唯一允许下载模型文件的项目入口；必须由用户
   显式执行。
2. prepare 命令只请求固定 model id/revision 和运行所需文件，并在模型目录写入
   schema `1.1` 的 `ai-bioworkflow-embedding-model.json`；manifest 按稳定路径顺序记录
   权重、tokenizer、模型配置和 pooling 配置的 SHA-256。
3. `SentenceTransformerEmbeddingProvider` 要求显式本地目录，先验证 manifest identity、
   固定文件清单和每个文件的 SHA-256，再以 `local_files_only=True`、
   `trust_remote_code=False` 加载；准备和加载都会拒绝不属于固定 snapshot 的
   `config_sentence_transformers.json`。
4. 模型路径、模型文件、index 和 evaluation artifact 均位于已忽略的 `.cache/`，不进入
   Git、retrieval artifact 或 corpus fingerprint。
5. 未安装 `vector` extra、缺少本地模型、manifest 不匹配、运行时文件缺失或摘要不匹配、
   模型维度不匹配时，`vector_v1` 快速失败；不会回退到网络下载或另一个模型。

Manifest 不记录 Hugging Face 的 `.cache` 下载元数据，也不记录 manifest 自身。文件摘要在
prepare 完成固定 revision 下载后生成，并在导入和实例化 Sentence Transformer 之前重新
计算，因此准备完成后的权重、tokenizer 或配置漂移不能继续沿用批准的 revision identity。
固定 revision 不包含 `config_sentence_transformers.json`；显式拒绝该文件可以防止其
`prompts` 或 `default_prompt_name` 在摘要校验之外改变 query/document 编码输入。

## Exact Index Contract

`CatalogVectorIndex` 使用 schema `1.0`：

- 输入必须是 `CatalogRetrievalCorpus` 的全部 canonical `text`；
- recipe 与 tool 共享 index artifact，但查询时按 `kind` 分开排名；
- document vectors 与 query vector 均做 L2 normalization；
- normalized component 固定到 8 位小数，以减少相同锁定环境中的无意义浮点差异；
- similarity 使用纯 Python exact cosine，不引入 approximate index 或 vector database；
- score 相同时按 `document_id` 排序；
- index fingerprint 覆盖 model id/revision、dimension、prefix、document schema、corpus
  fingerprint 和全部 quantized vectors；
- backend 构造后若当前 Catalog 生成的 corpus fingerprint 发生变化，查询会失败，不会
  继续使用旧 index。

21-document corpus 很小，exact search 更易审计，也为 R3C 比较 lexical/vector rank
提供稳定基线。近似索引和外部 vector database 不属于当前阶段。

## Artifact Evidence

每个 `vector_v1` retrieval artifact 的顶层 `backend_evidence` 包含：

```json
{
  "schema_version": "1.0",
  "backend": "vector_v1",
  "model_id": "intfloat/multilingual-e5-small",
  "model_revision": "fd1525a9fd15316a2d503bf26ab031a61d056e98",
  "embedding_dimension": 384,
  "query_prefix": "query: ",
  "document_prefix": "passage: ",
  "document_schema_version": "1.0",
  "corpus_fingerprint": "sha256:<digest>",
  "index_schema_version": "1.0",
  "index_fingerprint": "sha256:<digest>",
  "similarity": "cosine"
}
```

每个 candidate 另外记录 `document_id`、`rank` 和 `cosine_similarity`。Tool candidate 的
trust status 与 execution verification 仍从当前 Tool Catalog 读取，并继续通过 R3A
公共 contract 校验。

## Commands

安装可选依赖并显式准备模型：

```bash
uv sync --extra vector
uv run python scripts/prepare_embedding_model.py
```

运行相同的 64-query fixture 并保存完整 artifact：

```bash
uv run python scripts/evaluate_retrieval.py \
  --backend vector_v1 \
  --embedding-model-path .cache/models/multilingual-e5-small \
  --json-output .cache/retrieval-vector-v1.json
```

`prepare_embedding_model.py` 将带文件摘要的 manifest JSON 写到 stdout；evaluation 的
`--json` 输出保持 machine-consumable，默认 summary 为人类可读文本，错误写入 stderr。

## Evaluation Outcome

Mandatory unit tests 使用注入的 deterministic fake provider 验证完整 21-document index、
R3A backend contract 和共享 64-query evaluation path，因此 CI 不下载模型，也不依赖
Hugging Face 可用性。

固定 revision 的真实模型已通过 local-only provider 加载，并使用同一 64-query fixture
完成离线评估。Artifact 保存在忽略目录 `.cache/retrieval-vector-v1.json`；该运行的 index
fingerprint 为：

```text
sha256:740acf494be2862c6851cab51ae89b53506efdc67937eedf9fc273a9da69ec46
```

| Metric | `lexical_v1` | `vector_v1` | Delta |
| --- | ---: | ---: | ---: |
| Recipe Recall@1 | 0.8571 | 0.9643 | +0.1072 |
| Recipe Recall@3 | 0.9821 | 1.0000 | +0.0179 |
| Recipe MRR | 0.9137 | 0.9821 | +0.0684 |
| Tool Recall@3 | 0.7128 | 0.7155 | +0.0027 |
| Tool Recall@5 | 0.7973 | 0.8506 | +0.0533 |
| Tool Recall@8 | 0.9158 | 0.9060 | -0.0098 |
| Tool MRR | 0.8549 | 0.9256 | +0.0707 |
| Role Coverage | 0.9134 | 0.9101 | -0.0033 |
| Macro Recipe Recall@1 | 0.8812 | 0.9683 | +0.0871 |
| Macro Tool Recall@5 | 0.7902 | 0.8288 | +0.0386 |
| Recipe family top-1 agreement | 0.8750 | 0.9643 | +0.0893 |
| Planner Context Tool Recall | 1.0000 | 1.0000 | 0.0000 |
| Planner Context Role Coverage | 1.0000 | 1.0000 | 0.0000 |
| Unsupported Direct-Match Rate | 0.8750 | 1.0000 | +0.1250 |

`vector_v1` 将 recipe top-1 miss 从 8 条降到 2 条，并修复大部分 lexical cross-family
confusion。它也显示出互补但不能忽略的退化：variant-calling Recipe Recall@1 从
`1.0000` 降到 `0.9167`，ChIP-seq Tool Recall@5 从 `0.6690` 降到 `0.6405`，且所有
unsupported query 都产生 direct match。

显式工具 query 也不满足保守的 no-regression gate：
`germline_variant_calling_explicit_tools_en` 的 Tool Recall@8 从 `0.8333` 降到
`0.6667`；`chipseq_peak_calling_explicit_tools_en` 虽保持 `0.6000`，但原先进入 top-8
的 `samtools` 被挤出。因此 vector-only 不作为默认 backend 候选，`lexical_v1` 保持
默认。

## Next Step

进入 R3C reciprocal-rank fusion：保留 lexical 的 exact tool/alias signal，并利用 vector
改善 recipe/family intent ranking。Hybrid 必须重新运行相同 artifact comparison，尤其
验证显式工具 query、variant-calling、ChIP-seq 和 unsupported risk；只有满足 promotion
gates 后，才可在独立 PR 中讨论默认 backend 切换。
