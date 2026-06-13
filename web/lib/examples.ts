export const rnaseqExamplePrompt =
  "构建一个 bulk RNA-seq 差异表达分析工作流，输入多个样本的 paired-end FASTQ 文件。每个样本先运行 fastp 做读段质控，再用 Salmon 做转录本定量，随后通过 tximport 汇总到基因层面，用 DESeq2 完成差异表达分析，并返回 MultiQC 质控报告。";

export const rnaseqRecipeSteps = [
  "fastp 质控",
  "Salmon 定量",
  "tximport 汇总",
  "DESeq2 差异分析",
  "MultiQC 报告",
];
