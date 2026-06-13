# P0 Cromwell Tiny E2E 验证摘要

本文档记录一次真实的 P0 Cromwell e2e 验证运行，验证对象是 RNA-seq
差异表达分析工作流。它作为可复现的里程碑记录，不替代自动化测试本身。

## 摘要

| 字段 | 值 |
| --- | --- |
| 验证日期 | 2026-06-14 Asia/Shanghai |
| Workflow | `RNASeqDEG` |
| Cromwell workflow id | `1ea70de2-dee2-4da9-b7ab-e6ac25e1bdf8` |
| 最终状态 | `Succeeded` |
| Cromwell URL | `http://localhost:8000` |
| Windows fixture root | `C:\data\ai-bioworkflow-tiny` |
| Cromwell fixture root | `/data/ai-bioworkflow-runner/tiny` |
| 同步模式 | `docker` |
| Cromwell 容器 | `cromwell-cromwell-1` |

## 运行命令

本次运行通过 P0 检查入口触发，并只启用真实 e2e 路径：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_p0.ps1 `
  -SkipUnitTests `
  -SkipCompile `
  -RunE2E `
  -CromwellUrl http://localhost:8000 `
  -WindowsFixtureRoot C:\data\ai-bioworkflow-tiny `
  -CromwellFixtureRoot /data/ai-bioworkflow-runner/tiny
```

`check_p0.ps1 -RunE2E` 会将 fixture 准备、runner 同步、环境变量设置和
测试执行委托给 `scripts\run_cromwell_tiny_e2e.ps1`。

## 测试结果

```text
test_rnaseq_tiny_run_when_e2e_is_enabled (...) ... ok

Ran 1 test in 76.821s

OK
```

P0 wrapper 输出：

```text
OK: Cromwell tiny RNA-seq e2e (79.7s)
P0 check passed.
```

## Cromwell 记录

Cromwell query 返回的最新 `RNASeqDEG` workflow 记录如下：

```text
id:         1ea70de2-dee2-4da9-b7ab-e6ac25e1bdf8
name:       RNASeqDEG
status:     Succeeded
submission: 2026-06-13T16:45:51.073Z
start:      2026-06-13T16:45:58.663Z
end:        2026-06-13T16:47:05.179Z
```

换算为 Asia/Shanghai 时间，本次 workflow 约在 2026-06-14 00:45:58 到
2026-06-14 00:47:05 之间运行。

Metadata 中包含预期的 workflow calls：

```text
RNASeqDEG.qc
RNASeqDEG.quantify
RNASeqDEG.summarize
RNASeqDEG.deg
RNASeqDEG.report
```

## 输入

e2e helper 在 Windows 可读路径生成 inputs JSON：

```text
C:\data\ai-bioworkflow-tiny\rnaseq_deg.inputs.json
```

该 JSON 使用 Cromwell runner 可见路径：

```text
/data/ai-bioworkflow-runner/tiny
```

本次 workflow 输入包含 4 个 tiny samples：

```text
ctrl_1
ctrl_2
treat_1
treat_2
```

## 输出

Cromwell 返回了两个预期 workflow output keys：

```text
RNASeqDEG.deg_table
RNASeqDEG.multiqc_report
```

返回的 output paths：

```text
RNASeqDEG.deg_table:
/data/ai-bioworkflow-runner/executions/RNASeqDEG/1ea70de2-dee2-4da9-b7ab-e6ac25e1bdf8/call-deg/execution/differential_expression.tsv

RNASeqDEG.multiqc_report:
/data/ai-bioworkflow-runner/executions/RNASeqDEG/1ea70de2-dee2-4da9-b7ab-e6ac25e1bdf8/call-report/execution/multiqc_report.html
```

在 Cromwell runner 容器内确认两个输出文件均存在且非空：

```text
differential_expression.tsv  308 B
multiqc_report.html          4.4M
```

## 结论

P0 已具备 RNA-seq DEG 路径的真实执行基线：

- Recipe Tool Plan 可以编译为通过校验的 WDL。
- Cromwell 可以接受并运行生成的 WDL。
- 已配置的 Docker execution backend 可以完成整个 workflow。
- 预期 workflow outputs 已生成，并能通过 Cromwell 查询到。

以下后续工作不是证明 P0 可执行性的前置条件，但可以提高可重复性和发布质量：

- 评估后续 e2e 是否应在检查 Cromwell output keys 之外，同时断言输出文件存在且非空。
- 在镜像发布流程稳定后，将可复用容器引用从 mutable tags 推进到 validated digests。
