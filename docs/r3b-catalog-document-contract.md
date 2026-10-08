# R3B Catalog Retrieval Document Contract

本文档定义 R3B-1 的 Approved Catalog retrieval document 和 corpus contract。它将正式
Recipe Catalog 与 Tool Catalog 转换为可版本化、可审计、可稳定 fingerprint 的本地
documents，为后续 vector backend 提供唯一输入格式。

R3B-1 不引入 embedding model、vector index、vector database 或新的运行时依赖，也不
改变 `lexical_v1`、Planner 默认路径、Catalog validation 或确定性 WDL 编译边界。

## Corpus Artifact

`build_catalog_retrieval_corpus(...)` 返回以下 JSON-ready artifact：

```json
{
  "schema_version": "1.0",
  "document_schema_version": "1.0",
  "fingerprint_algorithm": "sha256",
  "fingerprint": "sha256:a0d1e6dde133936d808bf43a4262f5f1e6fc764a89732733298933aa97b490db",
  "documents": []
}
```

当前 5 个 recipe 和 16 个 tool version 共生成 21 个 documents。Corpus 不包含时间戳、
本地绝对路径或模型缓存位置，因此相同 Catalog 内容在不同机器上生成相同 fingerprint。

## Document Identity

每个 document 包含：

- `schema_version`：当前为 `1.0`。
- `document_id`：recipe 使用 `recipe:<recipe_id>`；tool 使用
  `tool:<tool_id>@<version>`。
- `kind`：`recipe` 或 `tool`。
- `catalog_id` / `catalog_version`：映射回正式 Catalog identity；recipe version 必须为
  `null`。
- `title`：供诊断和人工检查使用。
- `sections`：有序、具名的原始检索字段。
- `text`：由 `sections` 确定性渲染，后续 embedding backend 只能使用该值作为文档输入。
- `trust_status` / `execution_verification_*`：只对 tool document 存在，且必须保留
  Tool Catalog 的权威值。这些字段不进入 `text`，不能成为相似度信号。

Schema 会拒绝不一致的 identity、重复 section、空 section value、被修改的 `text`，以及
缺失或被篡改的 tool trust / execution verification metadata。

## Searchable Sections

Recipe documents 按固定顺序构造以下 sections：

```text
recipe_id -> name -> aliases -> description -> required_inputs -> steps
```

`steps` 保留 recipe 声明顺序，并记录 step id、role、optional、allowed tools 和 scatter id。

Tool documents 按固定顺序构造以下 sections：

```text
tool_id -> version -> aliases -> description -> inputs -> parameters -> outputs
```

Inputs、parameters 和 outputs 保留名称、类型、required/default/range/choices、描述与 output
tags 等检索相关信息。Command template、container image 和 runtime resources 不进入 embedding
文本，避免执行实现细节污染语义排序；它们仍由正式 Catalog 和后续完整 validation 管理。

## Canonicalization And Fingerprint

Canonicalization 规则如下：

1. Documents 按 `document_id` 排序且 identity 必须唯一。
2. Catalog mappings 按 key 排序；aliases 和 output tags 去重后按稳定的大小写无关顺序排序。
3. Recipe steps 保留声明顺序，因为它属于 workflow 语义。
4. 空 optional sections 不写入 document。
5. `text` 必须逐行渲染为 `<section_name>: <value> | <value>`，不能由 backend 自行拼接。
6. Fingerprint payload 包含 corpus schema version、document schema version 和完整 canonical
   documents；使用 UTF-8、JSON sorted keys、紧凑 separators 和 SHA-256。

当前 fingerprint 被回归测试固定。任何 searchable content、identity 或 Catalog-owned
metadata 变化都会要求显式更新该 checkpoint。

## JSON Export

Linux / macOS：

```bash
.venv/bin/python scripts/build_retrieval_corpus.py --output retrieval_corpus.json
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe scripts\build_retrieval_corpus.py --output retrieval_corpus.json
```

省略 `--output` 时，完整 JSON artifact 写入 stdout；该路径不输出日志或说明文字。

## Next Step

R3B-2 将在独立 PR 中：

- 选择并固定可本地复现的多语言 embedding model id 与 revision；
- 要求显式本地模型路径或已准备好的 cache，禁止静默下载；
- 对本 contract 的 `text` 建立小规模精确 cosine index；
- 将 model、revision、dimension、document schema 和 corpus/index fingerprint 写入
  `backend_evidence`；
- 仅通过显式 `vector_v1` 或离线 evaluation 运行，不改变 `lexical_v1` 默认行为。
