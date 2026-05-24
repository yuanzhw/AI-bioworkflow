#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(readr)
  library(tximport)
})

args <- commandArgs(trailingOnly = TRUE)

value_after <- function(flag) {
  pos <- match(flag, args)
  if (is.na(pos) || pos == length(args)) {
    stop(paste("missing argument", flag), call. = FALSE)
  }
  args[[pos + 1]]
}

quant_files_path <- value_after("--quant-files")
sample_ids_path <- value_after("--sample-ids")
tx2gene_path <- value_after("--tx2gene")
output_path <- value_after("--output")

quant_files <- readLines(quant_files_path, warn = FALSE)
sample_ids <- readLines(sample_ids_path, warn = FALSE)
tx2gene <- read_tsv(tx2gene_path, col_names = TRUE, show_col_types = FALSE)

if (length(quant_files) != length(sample_ids)) {
  stop("quant_files and sample_ids must have the same length", call. = FALSE)
}

names(quant_files) <- sample_ids
txi <- tximport(quant_files, type = "salmon", tx2gene = tx2gene)
counts <- as.data.frame(txi$counts)
counts <- cbind(gene_id = rownames(counts), counts)
write_tsv(counts, output_path)
