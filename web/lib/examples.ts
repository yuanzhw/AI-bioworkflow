import type { JsonObject } from "@/lib/types";

export const rnaseqDemoExampleSlug = "rnaseq-deg";
export const rnaseqDemoWorkspaceHref = `/workspace?example=${rnaseqDemoExampleSlug}`;

export const rnaseqExamplePrompt =
  "构建一个 bulk RNA-seq 差异表达分析工作流，输入多个样本的 paired-end FASTQ 文件。每个样本先运行 fastp 做读段质控，再用 Salmon 做转录本定量，随后通过 tximport 汇总到基因层面，用 DESeq2 完成差异表达分析，并返回 MultiQC 质控报告。";

export const rnaseqRecipeSteps = [
  "fastp 质控",
  "Salmon 定量",
  "tximport 汇总",
  "DESeq2 差异分析",
  "MultiQC 报告",
];

export const rnaseqRecipePlan: JsonObject = {
  workflow: {
    name: "RNASeqDEG",
    recipe: "rnaseq_differential_expression",
    inputs: {
      sample_ids: "Array[String]",
      raw_r1s: "Array[File]",
      raw_r2s: "Array[File]",
      transcriptome_index: "File",
      tx2gene: "File",
      sample_groups: "File",
    },
    tool_calls: [
      {
        id: "qc",
        step: "qc",
        tool: "fastp",
        version: "1.3.3",
        inputs: {
          r1: "raw_r1s",
          r2: "raw_r2s",
        },
        params: {
          thread: 4,
        },
      },
      {
        id: "quantify",
        step: "quantify",
        tool: "salmon",
        version: "1.9.0",
        inputs: {
          r1: "qc.clean_r1",
          r2: "qc.clean_r2",
          index: "transcriptome_index",
        },
        params: {
          thread: 8,
        },
      },
      {
        id: "summarize",
        step: "summarize_transcripts",
        tool: "tximport",
        version: "1.30.0",
        inputs: {
          quant_files: "quantify.quant_file",
          sample_ids: "sample_ids",
          tx2gene: "tx2gene",
        },
        params: {},
      },
      {
        id: "deg",
        step: "differential_expression",
        tool: "deseq2",
        version: "1.42.1",
        inputs: {
          counts: "summarize.gene_counts",
          sample_groups: "sample_groups",
        },
        params: {
          contrast: "condition",
        },
      },
      {
        id: "report",
        step: "qc_report",
        tool: "multiqc",
        version: "1.21",
        inputs: {
          report_files: ["qc.html_report", "qc.json_report", "quantify.log_file"],
        },
        params: {},
      },
    ],
    outputs: {
      deg_table: "deg.deg_table",
      multiqc_report: "report.multiqc_report",
    },
  },
};
