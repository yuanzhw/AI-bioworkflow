#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(edgeR)
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
min_count <- as.numeric(value_after("--min-count"))
fdr_threshold <- as.numeric(value_after("--fdr"))
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

sample_columns <- setdiff(names(counts_df), "gene_id")
count_matrix <- as.matrix(counts_df[, sample_columns, drop = FALSE])
storage.mode(count_matrix) <- "numeric"
count_matrix <- round(count_matrix)
rownames(count_matrix) <- counts_df$gene_id

sample_groups <- as.data.frame(sample_groups)
sample_groups <- sample_groups[match(colnames(count_matrix), sample_groups$sample_id), , drop = FALSE]
if (any(is.na(sample_groups$sample_id))) {
  stop("sample metadata must include every count matrix sample column", call. = FALSE)
}

group <- factor(sample_groups[[contrast_column]])
if (length(levels(group)) < 2) {
  stop("contrast column must contain at least two groups", call. = FALSE)
}

y <- DGEList(counts = count_matrix, group = group)
keep <- filterByExpr(y, group = group, min.count = min_count)
if (!any(keep)) {
  keep <- rowSums(y$counts) > 0
}
if (!any(keep)) {
  stop("no genes remain after expression filtering", call. = FALSE)
}

y <- y[keep, , keep.lib.sizes = FALSE]
y <- calcNormFactors(y)
design <- model.matrix(~ group)
y <- estimateDisp(y, design, robust = TRUE)
fit <- glmQLFit(y, design, robust = TRUE)
qlf <- glmQLFTest(fit, coef = 2)

res_df <- as.data.frame(topTags(qlf, n = Inf, sort.by = "none")$table)
res_df <- cbind(gene_id = rownames(res_df), res_df)
if ("FDR" %in% names(res_df)) {
  res_df$significant <- res_df$FDR <= fdr_threshold
  res_df <- res_df[order(res_df$FDR, res_df$PValue), , drop = FALSE]
}
write_tsv(res_df, output_path)
