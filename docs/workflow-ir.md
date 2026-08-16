# Workflow IR 规范与后端映射

本文档定义 AI-bioworkflow 的 Workflow IR 结构、表达式规则，以及当前 WDL 后端的转换约定。它面向项目开发者和 catalog / recipe 维护者，而不是终端用户。

Workflow IR 的目标不是把 WDL 用 JSON 重写一遍，而是在自然语言 Planner、Recipe / Tool Catalog、静态分析器、修复器和 workflow 后端之间建立一个稳定的语义契约。WDL 是当前第一个后端；未来支持 Nextflow 或其他 workflow engine 时，应优先扩展 IR 的语义层，而不是把某个后端的语法直接渗入 IR。

## 设计原则

1. **IR 是 canonical model**：进入 LangGraph 编译链路后，标准 Workflow IR 是后续 Analyzer、Repairer、Renderer 的共同输入。
2. **确定性优先**：IR 到后端代码的转换由普通代码完成，不依赖 LLM 自由生成最终 WDL。
3. **语义先于语法**：IR 表达的是调用、依赖、并行映射、输入输出和 runtime 约束，不直接保存 WDL AST。
4. **小表达式语言**：IR 只支持项目定义的有限表达式集合。任意 WDL / shell / Python 表达式不能直接塞进 IR。
5. **后端可扩展**：新增 backend 可以把同一组 IR 语义映射到自己的语言；无法支持的 feature 应显式报错。

## 输入层级

项目目前存在三层输入/中间表示：

1. **自然语言需求**：由 `src/nl_planner.py` 调用 LLM 转成 Recipe Tool Plan。
2. **Recipe Tool Plan**：面向 catalog 的轻量结构，只声明 recipe、workflow 输入和每一步选用的 tool。
3. **Workflow IR**：编译器内部 canonical model，包含 workflow DAG、task 定义、表达式和 runtime。

LangGraph 中的 `ir_normalizer` 节点只处理结构化输入到 Workflow IR 的转换。自然语言到 Recipe Tool Plan 的 LLM 调用发生在 CLI 入口、进入 graph 之前。

## 顶层结构

标准 Workflow IR 的顶层结构如下：

```json
{
  "version": "1.0",
  "workflow": {
    "name": "RNASeqDEG",
    "inputs": {
      "sample_ids": "Array[String]",
      "raw_r1s": "Array[File]",
      "raw_r2s": "Array[File]"
    },
    "steps": [],
    "calls": [],
    "outputs": {
      "deg_table": "deg.deg_table"
    }
  },
  "tasks": {}
}
```

`version` 标识 IR schema 版本。当前实现默认为 `"1.0"`。后续如果引入不兼容语义，应提升版本，而不是悄悄改变旧字段含义。

`workflow` 描述 workflow 级别的输入、步骤和输出。

`tasks` 是 task 模板字典。workflow step 通过 task 名引用这里的定义。task 定义与 workflow 调用关系必须分离，以便同一个 task 模板被不同 call 复用。

## WorkflowSpec

`workflow` 字段对应 `WorkflowSpec`。

```json
{
  "name": "RNASeqDEG",
  "inputs": {
    "sample_ids": "Array[String]",
    "raw_r1s": "Array[File]"
  },
  "steps": [
    {
      "kind": "scatter",
      "id": "per_sample",
      "item": "i",
      "over": "range(length(sample_ids))",
      "body": []
    }
  ],
  "calls": [],
  "outputs": {
    "multiqc_report": "report.multiqc_report"
  }
}
```

### `workflow.name`

Workflow 名称，必须是合法标识符：

```text
[A-Za-z_][A-Za-z0-9_]*
```

当前 WDL 后端会直接把它渲染为：

```wdl
workflow RNASeqDEG {
}
```

### `workflow.inputs`

Workflow 级输入字典：

```json
{
  "raw_r1s": "Array[File]",
  "sample_groups": "File"
}
```

key 是输入名，value 是 IR 类型字符串。当前支持的基础类型来自 WDL 常用类型：

```text
Boolean
File
Float
Int
String
Array[T]
T?
```

当前类型兼容判断是保守的：去掉 optional 标记 `?` 后必须完全相等。`Array[File]` 不会隐式兼容 `File`，除非表达式规则明确进行索引或聚合。

### `workflow.steps`

`steps` 是新的 canonical workflow DAG 表达，支持普通 call 和 scatter。

```json
[
  {
    "kind": "call",
    "id": "summarize",
    "task": "tximport_summarize",
    "inputs": {
      "quant_files": "quantify.quant_file"
    }
  }
]
```

```json
[
  {
    "kind": "scatter",
    "id": "per_sample",
    "item": "i",
    "over": "range(length(sample_ids))",
    "body": [
      {
        "kind": "call",
        "id": "qc",
        "task": "fastp_qc",
        "inputs": {
          "r1": "raw_r1s[i]"
        }
      }
    ]
  }
]
```

Analyzer、Repairer、Reviewer 和 Renderer 都只以 `workflow.steps` 为 DAG 数据源。

### `workflow.calls`

`calls` 是旧输入和序列化输出的兼容字段，不是第二份 DAG。旧 IR 只提供
`workflow.calls` 时，normalizer 会把每个 call 转成 `steps` 中的
`kind: "call"`。新输入应只提供 `workflow.steps`；schema 会从 canonical steps
递归生成一个扁平、深拷贝的 `calls` 快照。

如果输入同时提供 `steps` 和 `calls`，两者的 call 顺序、ID、task 和 inputs 必须
完全一致，否则 schema 会拒绝该 IR。内部逻辑修改 `steps` 后必须通过共享 schema
helper 单向刷新 `calls`，不得读取或单独 patch `calls`。由于扁平视图不保留 scatter
边界，新功能不得依赖它表达 DAG 语义。

### `workflow.outputs`

Workflow 输出字典：

```json
{
  "deg_table": "deg.deg_table",
  "multiqc_report": "report.multiqc_report"
}
```

key 是 workflow output 名称，value 是 IR 表达式。Renderer 会调用 Analyzer 推断表达式类型，再渲染为 WDL output：

```wdl
output {
  File deg_table = deg.deg_table
}
```

## TaskSpec

`tasks` 中每个条目对应一个 `TaskSpec`。

```json
{
  "fastp_qc": {
    "inputs": {
      "r1": "File",
      "r2": "File?",
      "thread": "Int"
    },
    "command": "fastp -i ~{r1} -I ~{r2} -o clean_R1.fq.gz",
    "outputs": {
      "clean_r1": {
        "type": "File",
        "value": "\"clean_R1.fq.gz\""
      }
    },
    "runtime": {
      "docker": "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0",
      "cpu": 4,
      "memory": "8G"
    }
  }
}
```

### `task.inputs`

Task 输入名到类型的映射。Call step 的 `inputs` 必须覆盖所有非 optional task inputs。

Optional 输入使用 `T?` 表示。例如：

```json
{
  "r2": "File?"
}
```

### `task.command`

Task 命令模板当前按 WDL command 语义保存，变量插值使用 `~{name}`：

```text
salmon quant \
-l ~{lib_type} \
-i ~{index} \
-1 ~{r1} \
-2 ~{r2} \
-o salmon_quant
```

Analyzer 会检查 command 中出现的 `~{identifier}` 是否在 `task.inputs` 中声明。当前 command 字符串仍偏 WDL；未来如果支持 Nextflow，建议引入 backend-neutral command model 或明确把 command 作为 shell script body，由各后端负责包装。

当 Recipe Tool Plan 通过 Catalog resolver 生成 IR 时，Catalog `command_template`
中非空的多行命令会被规范化为 shell 续行形式，确保类似 `fastp`、`salmon`
和 R wrapper 的分行参数在 WDL/Cromwell 中作为同一个 shell 命令执行。

### `task.outputs`

Task 输出名到 `OutputSpec` 的映射：

```json
{
  "html_report": {
    "type": "File",
    "value": "\"fastp.html\"",
    "tags": ["multiqc_input"]
  }
}
```

`type` 是输出类型。

`value` 是输出表达式。对于 `File` / `String` 字面量，应使用带引号的表达式，例如 `"\"fastp.html\""` 在 JSON 中表示 WDL 的 `"fastp.html"`。

`tags` 是可选语义标签，不影响 WDL task output 本身，但可被 resolver 或后续 backend 用于自动连线。例如 `multiqc_input` 表示该输出适合被 MultiQC 汇总。

### `task.runtime`

Runtime 定义当前包含：

```json
{
  "docker": "ghcr.io/yuanzhw/ai-bioworkflow/deseq2:1.42.1-r2",
  "cpu": 4,
  "memory": "16G",
  "disks": "local-disk 50 HDD"
}
```

Catalog tool 必须显式声明 `runtime.docker`。编译链路不搜索、不猜测、不联网补齐镜像。

WDL 后端会渲染为：

```wdl
runtime {
  cpu: 4
  docker: "ghcr.io/yuanzhw/ai-bioworkflow/deseq2:1.42.1-r2"
  memory: "16G"
}
```

未来 Nextflow 后端可把 `docker` 映射为 `container`，把 `cpu` / `memory` 映射为 process directive。

## CallSpec

普通 call step 结构：

```json
{
  "kind": "call",
  "id": "deg",
  "task": "deseq2_deg",
  "inputs": {
    "counts": "summarize.gene_counts",
    "sample_groups": "sample_groups",
    "contrast": "\"condition\""
  }
}
```

`id` 是 call 实例名。它决定后续表达式中的引用前缀，例如 `deg.deg_table`。

`task` 必须引用 `tasks` 中存在的 task 名。

`inputs` 是 task input 名到 `ExpressionValue` 的映射。当前 `ExpressionValue` 支持：

```text
string expression
list[string expression]
```

也就是说，单个输入可以来自一个表达式，也可以来自表达式数组。

## ScatterSpec

Scatter step 表示对集合输入的并行映射语义。

```json
{
  "kind": "scatter",
  "id": "per_sample",
  "item": "i",
  "over": "range(length(sample_ids))",
  "body": [
    {
      "kind": "call",
      "id": "qc",
      "task": "fastp_qc",
      "inputs": {
        "r1": "raw_r1s[i]",
        "r2": "raw_r2s[i]"
      }
    }
  ]
}
```

`id` 是 scatter block 名称，用于调试和未来 backend metadata。

`item` 是 scatter body 内的循环变量名。当前常用 `i`。

`over` 必须解析为 `Array[...]` 类型。RNA-seq recipe 当前使用：

```text
range(length(sample_ids))
```

`body` 是嵌套 workflow steps。当前 Analyzer 和 Renderer 递归处理 scatter body。

Scatter 的关键类型规则是：scatter body 内产生的 call output，在 scatter 外部被提升为数组。

如果 `qc.html_report` 在 scatter 内部类型是：

```text
File
```

那么在 scatter 外部引用 `qc.html_report` 时类型是：

```text
Array[File]
```

这条规则是 MultiQC 汇总、tximport 汇总等多样本工作流的基础。

## 表达式系统

IR 表达式是项目自定义的小表达式语言。表达式的职责是描述数据依赖和简单集合操作，而不是承载完整后端语言能力。

### Workflow 输入引用

```text
sample_groups
raw_r1s
```

如果表达式正好匹配 `workflow.inputs` 中的输入名，类型就是该 workflow input 的类型。

### Call 输出引用

```text
qc.clean_r1
summarize.gene_counts
deg.deg_table
```

格式：

```text
call_id.output_name
```

Analyzer 要求被引用的 call 已经在当前作用域中可用。默认不允许前向引用；Repairer 可以在某些简单情况下重排 step 顺序。

### 索引表达式

```text
raw_r1s[i]
```

如果 `raw_r1s` 是 `Array[File]`，且 `i` 是 `Int`，则 `raw_r1s[i]` 类型为 `File`。

Recipe resolver 在 scatter step 中会自动把匹配的 workflow array input 索引成单样本输入。例如 tool 需要 `File r1`，plan 写的是：

```json
{
  "r1": "raw_r1s"
}
```

如果 recipe step 带有 `scatter.item: "i"`，resolver 会生成：

```json
{
  "r1": "raw_r1s[i]"
}
```

### 函数表达式

当前支持两个函数：

```text
length(x)
range(x)
```

`length(Array[T]) -> Int`

`length(String) -> Int`

`range(Int) -> Array[Int]`

典型 scatter 入口：

```text
range(length(sample_ids))
```

### 字面量

Analyzer 支持基础字面量类型推断：

```text
"condition" -> String
true / false -> Boolean
1 -> Int
1.5 -> Float
```

在 Recipe Tool Plan resolver 中，tool params 会被格式化为 WDL 字面量。例如 Python 字符串 `"condition"` 会进入 IR call input 为：

```text
"condition"
```

### 数组表达式

Call input 可以直接使用表达式数组：

```json
{
  "report_files": [
    "qc.html_report",
    "qc.json_report",
    "quantify.log_file"
  ]
}
```

Analyzer 会逐个推断元素类型。如果元素是 `T` 或 `Array[T]`，数组表达式整体可推断为 `Array[T]`。这使得 scatter 外部的多个 `Array[File]` 可以组合成一个 `Array[File]` 输入。

当前数组表达式为空时无法推断类型。需要空数组语义时，应先扩展 IR 表达式系统，为空数组携带显式元素类型。

### 不支持的表达式

当前不支持：

```text
qc.html_report + qc.json_report
a || b
if (...) then ... else ...
select_first(...)
glob(...)
任意 WDL 表达式透传
任意 shell 字符串拼接
```

尤其要注意，数组收集必须写成 JSON array：

```json
{
  "report_files": ["qc.html_report", "qc.json_report"]
}
```

不要写成：

```json
{
  "report_files": "qc.html_report + qc.json_report"
}
```

后者既不是当前 IR 表达式，也不是 backend-neutral 语义。

## 作用域与依赖规则

Analyzer 按 `workflow.steps` 顺序递归分析。

普通 call 完成分析后，其 outputs 进入后续作用域。

Scatter body 分析时会创建内部作用域，并加入 scatter item：

```text
i: Int
```

Scatter body 中新增的 call outputs 在离开 scatter 后进入外部作用域，但类型提升一层 `Array[...]`。

例如：

```text
inside scatter:
  qc.html_report: File

outside scatter:
  qc.html_report: Array[File]
```

这也意味着 scatter 外部对内部 call output 的引用是合法的，但类型通常已经变为数组。

## Recipe Tool Plan 到 IR 的转换

Recipe Tool Plan 是更接近 LLM 和 catalog 的输入格式：

```json
{
  "workflow": {
    "name": "RNASeqDEG",
    "recipe": "rnaseq_differential_expression",
    "inputs": {
      "sample_ids": "Array[String]",
      "raw_r1s": "Array[File]"
    },
    "tool_calls": [
      {
        "id": "qc",
        "step": "qc",
        "tool": "fastp",
        "version": "1.3.3",
        "inputs": {
          "r1": "raw_r1s"
        },
        "params": {
          "thread": 4
        }
      }
    ]
  }
}
```

Resolver 的主要职责：

1. 校验 `workflow.recipe` 是否存在。
2. 校验每个 `tool_call.step` 是否属于 recipe。
3. 校验选用 tool 是否在该 recipe step 的 `allowed_tools` 中。
4. 根据 Tool Catalog 生成 task inputs、command、outputs、runtime。
5. 把 tool params 转成 task inputs 和 WDL 字面量。
6. 根据 recipe scatter metadata 生成 `workflow.steps` 中的 scatter block。
7. 在 scatter 中自动把 workflow array input 索引为单元素输入。
8. 从 canonical steps 生成扁平化 `workflow.calls` 兼容快照。
9. 收集 catalog output tags，用于自动连接某些通用汇总工具。

### MultiQC 自动收集

Tool Catalog output 可以标记：

```yaml
outputs:
  html_report:
    type: File
    value: '"fastp.html"'
    tags:
      - multiqc_input
```

当 MultiQC tool call 没有显式提供 `report_files` 时，resolver 会自动收集前序 call 中带 `multiqc_input` tag 的输出：

```json
{
  "report_files": [
    "qc.html_report",
    "qc.json_report",
    "quantify.log_file"
  ]
}
```

这保持了 MultiQC 的通用性：它接收的是 `Array[File]`，而不是某个 fastp 专用字段。

## IR 到 WDL 1.0 的映射

当前唯一实现的后端是 WDL 1.0，入口在 `src/renderers/wdl.py`。

### Workflow 输入

IR:

```json
{
  "inputs": {
    "sample_ids": "Array[String]",
    "sample_groups": "File"
  }
}
```

WDL:

```wdl
input {
  Array[String] sample_ids
  File sample_groups
}
```

### 普通 call

IR:

```json
{
  "kind": "call",
  "id": "deg",
  "task": "deseq2_deg",
  "inputs": {
    "counts": "summarize.gene_counts"
  }
}
```

WDL:

```wdl
call deseq2_deg as deg {
  input:
    counts = summarize.gene_counts
}
```

如果 `id` 与 `task` 相同，可以省略 alias。

### Scatter

IR:

```json
{
  "kind": "scatter",
  "id": "per_sample",
  "item": "i",
  "over": "range(length(sample_ids))",
  "body": []
}
```

WDL:

```wdl
scatter (i in range(length(sample_ids))) {
}
```

### 数组输入

IR:

```json
{
  "report_files": [
    "qc.html_report",
    "qc.json_report"
  ]
}
```

如果所有元素都是标量 `File`，WDL 渲染为：

```wdl
report_files = [qc.html_report, qc.json_report]
```

如果任一元素是 `Array[File]`，WDL 渲染为 `flatten(...)`。例如 scatter 外部：

```json
{
  "report_files": [
    "qc.html_report",
    "qc.json_report",
    "extra_report"
  ]
}
```

其中 `qc.html_report` 和 `qc.json_report` 是 `Array[File]`，`extra_report` 是 `File`，WDL 渲染为：

```wdl
report_files = flatten([qc.html_report, qc.json_report, [extra_report]])
```

如果所有元素都是 scatter 输出数组，则渲染为：

```wdl
report_files = flatten([qc.html_report, qc.json_report, quantify.log_file])
```

### Workflow 输出

IR:

```json
{
  "outputs": {
    "multiqc_report": "report.multiqc_report"
  }
}
```

WDL:

```wdl
output {
  File multiqc_report = report.multiqc_report
}
```

输出类型由 Analyzer 根据表达式推断。

### Task

IR task 渲染为 WDL task：

```wdl
task multiqc_report {
  input {
    Array[File] report_files
  }

  command <<<
    run_multiqc.sh \
    ~{write_lines(report_files)} \
    multiqc_report.html
  >>>

  output {
    File multiqc_report = "multiqc_report.html"
  }

  runtime {
    cpu: 2
    docker: "ghcr.io/yuanzhw/ai-bioworkflow/multiqc:1.21-r1"
    memory: "4G"
  }
}
```

Renderer 只负责确定性渲染。生成后由 `miniwdl check` 做 WDL 语法校验。

## 后端中立约束

为了给 Nextflow 等后续后端留下空间，新增 IR 字段时应遵守以下约束：

1. 不要把字段命名为 WDL 专有概念，除非该字段只属于 WDL backend options。
2. 不要把任意 WDL 表达式作为 IR 表达式透传。
3. 新表达式必须先定义语义、类型规则和作用域规则，再实现 WDL 渲染。
4. 后端不支持某个 IR feature 时，应在 backend capability 检查中明确报错。
5. Catalog 里描述 tool 的生物信息学语义和 runtime，不描述某个后端的 DAG 语法。

## Nextflow 后端展望

Nextflow 支持时，不建议把 IR 改造成 Nextflow channel DSL 的 JSON 版本。推荐映射方向：

```text
Workflow IR workflow.inputs -> Nextflow params / input channel bootstrap
TaskSpec -> process
CallSpec -> process invocation / channel wiring
ScatterSpec -> channel fan-out / per-item process execution
Scatter output Array[T] -> collected channel or value channel
RuntimeSpec.docker -> process container
RuntimeSpec.cpu/memory -> process cpus / memory
ExpressionValue list -> channel mix / collect / flatten strategy
```

这部分目前只是扩展方向，不是已实现行为。正式实现前应补充 backend capability model，例如：

```text
supports_scatter
supports_nested_scatter
supports_optional_inputs
supports_array_file_inputs
supports_runtime_docker
supports_resource_hints
```

## 扩展 checklist

新增或修改 IR 结构时，应同步检查：

1. `src/schema.py`：Pydantic model 与兼容 normalizer。
2. `src/analyzer.py`：类型推断、作用域、错误信息。
3. `src/repairer.py`：是否需要递归处理新结构。
4. `src/renderers/wdl.py`：WDL 后端映射。
5. `src/catalog/resolver.py`：Recipe Tool Plan 是否需要生成新结构。
6. `src/prompts.py`：LLM Planner 是否需要知道新表达式规则。
7. `tests/`：schema、analyzer、renderer、catalog resolver、graph 编译链路测试。
8. `docs/workflow-ir.md`：更新本规范。

新增 backend 时，应先定义：

1. backend 支持哪些 IR feature。
2. 不支持 feature 的错误信息。
3. IR 类型到 backend 类型/通道的映射。
4. task command 和 runtime 的包装策略。
5. backend 生成代码的本地校验工具。

## 当前保留扩展点

以下能力尚未实现，但 IR 设计应为它们保留空间：

1. Conditional step：条件执行。
2. Nested scatter：多层并行映射。
3. Subworkflow：workflow 复用。
4. Backend capabilities：不同后端的能力声明与报错。
5. Rich metadata：样本表、数据集、tool provenance、container digest。
6. Resource hints：更完整的 cpu、memory、disk、preemptible、gpu 等资源语义。
7. Script packaging：辅助脚本与容器镜像的显式绑定。
8. More expression forms：条件表达式、可选值处理、typed empty arrays。

这些扩展进入实现前，应先补充本文档中的语义定义，再改代码。
