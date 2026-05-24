#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(DESeq2)
  library(readr)
})

args <- commandArgs(trailingOnly = TRUE)

value_after <- function(flag) {
  pos <- match(flag, args)
  if (is.na(pos) || pos == length(args)) {
    stop(paste("missing argument", flag), call. = FALSE)
  }
  args[[pos + 1]]
}

counts_path <- value_after("--counts")
sample_groups_path <- value_after("--sample-groups")
contrast_column <- value_after("--contrast")
output_path <- value_after("--output")

counts_df <- read_tsv(counts_path, col_names = TRUE, show_col_types = FALSE)
sample_groups <- read_tsv(sample_groups_path, col_names = TRUE, show_col_types = FALSE)

if (!"gene_id" %in% names(counts_df)) {
  stop("counts table must contain a gene_id column", call. = FALSE)
}
if (!"sample_id" %in% names(sample_groups)) {
  stop("sample metadata must contain a sample_id column", call. = FALSE)
}
if (!contrast_column %in% names(sample_groups)) {
  stop(paste("sample metadata is missing contrast column", contrast_column), call. = FALSE)
}

count_matrix <- as.matrix(counts_df[, setdiff(names(counts_df), "gene_id")])
rownames(count_matrix) <- counts_df$gene_id
count_matrix <- round(count_matrix)

sample_groups <- as.data.frame(sample_groups)
rownames(sample_groups) <- sample_groups$sample_id
sample_groups <- sample_groups[colnames(count_matrix), , drop = FALSE]
sample_groups[[contrast_column]] <- factor(sample_groups[[contrast_column]])

if (length(levels(sample_groups[[contrast_column]])) < 2) {
  stop("contrast column must contain at least two groups", call. = FALSE)
}

dds <- DESeqDataSetFromMatrix(
  countData = count_matrix,
  colData = sample_groups,
  design = as.formula(paste("~", contrast_column))
)
dds <- DESeq(dds, quiet = TRUE)
groups <- levels(sample_groups[[contrast_column]])
res <- results(dds, contrast = c(contrast_column, groups[[2]], groups[[1]]))
res_df <- as.data.frame(res)
res_df <- cbind(gene_id = rownames(res_df), res_df)
write_tsv(res_df, output_path)
