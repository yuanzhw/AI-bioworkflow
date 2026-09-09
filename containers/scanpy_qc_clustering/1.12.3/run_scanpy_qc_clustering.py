#!/usr/bin/env python
"""Run the bounded Scanpy workflow exposed by the Tool Catalog contract."""

from __future__ import annotations

import argparse
import json
from importlib.metadata import version
from pathlib import Path


MARKER_COLUMNS = ["group", "names", "scores", "logfoldchanges", "pvals", "pvals_adj"]


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def at_least_two_int(value: str) -> int:
    parsed = int(value)
    if parsed < 2:
        raise argparse.ArgumentTypeError("must be at least 2")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def percentage(value: str) -> float:
    parsed = float(value)
    if not 0 <= parsed <= 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be at least 0")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run cell/gene QC, normalization, highly variable gene selection, PCA, "
            "neighbors, Leiden clustering, UMAP, and marker ranking on a filtered 10x H5 matrix."
        )
    )
    parser.add_argument("--matrix-h5", type=Path, required=True)
    parser.add_argument("--cell-metadata", type=Path)
    parser.add_argument("--sample-id", required=True)
    parser.add_argument("--min-genes", type=non_negative_int, default=200)
    parser.add_argument("--min-cells", type=positive_int, default=3)
    parser.add_argument("--max-mito-pct", type=percentage, default=20.0)
    parser.add_argument("--target-sum", type=positive_float, default=10000.0)
    parser.add_argument("--n-top-genes", type=at_least_two_int, default=2000)
    parser.add_argument("--n-pcs", type=at_least_two_int, default=40)
    parser.add_argument("--n-neighbors", type=at_least_two_int, default=15)
    parser.add_argument("--leiden-resolution", type=non_negative_float, default=1.0)
    parser.add_argument("--random-seed", type=non_negative_int, default=0)
    parser.add_argument("--processed-h5ad", type=Path, required=True)
    parser.add_argument("--cell-qc-table", type=Path, required=True)
    parser.add_argument("--umap-coordinates", type=Path, required=True)
    parser.add_argument("--cluster-assignments", type=Path, required=True)
    parser.add_argument("--marker-genes", type=Path, required=True)
    parser.add_argument("--umap-plot", type=Path, required=True)
    parser.add_argument("--analysis-summary", type=Path, required=True)
    return parser.parse_args(argv)


def load_cell_metadata(path: Path, pandas_module):
    metadata = pandas_module.read_csv(path, sep=None, engine="python")
    if "barcode" not in metadata.columns:
        raise ValueError("cell metadata must contain a 'barcode' column")
    barcodes = metadata["barcode"].astype("string").str.strip()
    if barcodes.isna().any() or barcodes.eq("").any() or barcodes.duplicated().any():
        raise ValueError("cell metadata barcodes must be non-empty and unique")
    metadata["barcode"] = barcodes.astype(str)
    return metadata.set_index("barcode")


def run_analysis(args: argparse.Namespace) -> None:
    import matplotlib.pyplot as plt
    import pandas as pd
    import scanpy as sc

    sc.settings.verbosity = 2
    adata = sc.read_10x_h5(args.matrix_h5, gex_only=True)
    adata.var_names_make_unique()
    input_cells = int(adata.n_obs)
    input_genes = int(adata.n_vars)

    adata.var["mt"] = adata.var_names.str.upper().str.startswith("MT-")
    sc.pp.calculate_qc_metrics(
        adata,
        qc_vars=["mt"],
        percent_top=None,
        log1p=False,
        inplace=True,
    )
    passed_qc = (adata.obs["n_genes_by_counts"] >= args.min_genes) & (
        adata.obs["pct_counts_mt"] <= args.max_mito_pct
    )
    cell_qc = adata.obs[
        ["total_counts", "n_genes_by_counts", "pct_counts_mt"]
    ].copy()
    cell_qc["passed_qc"] = passed_qc
    cell_qc.index.name = "barcode"
    cell_qc.reset_index().to_csv(args.cell_qc_table, sep="\t", index=False)

    adata = adata[passed_qc].copy()
    sc.pp.filter_genes(adata, min_cells=args.min_cells)
    if adata.n_obs < 3 or adata.n_vars < 3:
        raise ValueError(
            "QC retained fewer than 3 cells or 3 genes; relax thresholds or inspect the input matrix"
        )

    adata.obs["sample_id"] = args.sample_id
    if args.cell_metadata is not None:
        metadata = load_cell_metadata(args.cell_metadata, pd)
        overlapping_columns = sorted(set(metadata.columns).intersection(adata.obs.columns))
        if overlapping_columns:
            joined = ", ".join(overlapping_columns)
            raise ValueError(f"cell metadata columns conflict with generated annotations: {joined}")
        adata.obs = adata.obs.join(metadata, how="left", validate="one_to_one")

    adata.layers["counts"] = adata.X.copy()
    sc.pp.normalize_total(adata, target_sum=args.target_sum)
    sc.pp.log1p(adata)
    adata.raw = adata

    effective_top_genes = min(args.n_top_genes, int(adata.n_vars))
    sc.pp.highly_variable_genes(
        adata,
        n_top_genes=effective_top_genes,
        flavor="seurat",
        inplace=True,
    )
    highly_variable_count = int(adata.var["highly_variable"].sum())
    if highly_variable_count < 3:
        raise ValueError("fewer than 3 highly variable genes were selected")

    retained_gene_count = int(adata.n_vars)
    adata = adata[:, adata.var["highly_variable"]].copy()
    sc.pp.scale(adata, max_value=10)
    effective_pcs = min(args.n_pcs, int(adata.n_obs) - 1, int(adata.n_vars) - 1)
    sc.tl.pca(
        adata,
        n_comps=effective_pcs,
        svd_solver="arpack",
        random_state=args.random_seed,
    )
    effective_neighbors = min(args.n_neighbors, int(adata.n_obs) - 1)
    sc.pp.neighbors(adata, n_neighbors=effective_neighbors, n_pcs=effective_pcs)
    sc.tl.leiden(
        adata,
        resolution=args.leiden_resolution,
        random_state=args.random_seed,
        flavor="igraph",
        n_iterations=2,
        directed=False,
        key_added="leiden",
    )
    sc.tl.umap(adata, random_state=args.random_seed)

    cluster_assignments = adata.obs[["sample_id", "leiden"]].copy()
    cluster_assignments.index.name = "barcode"
    cluster_assignments.reset_index().to_csv(
        args.cluster_assignments,
        sep="\t",
        index=False,
    )

    umap_coordinates = pd.DataFrame(
        adata.obsm["X_umap"],
        index=adata.obs_names,
        columns=["umap_1", "umap_2"],
    )
    umap_coordinates.insert(0, "sample_id", adata.obs["sample_id"].to_numpy())
    umap_coordinates["leiden"] = adata.obs["leiden"].to_numpy()
    umap_coordinates.index.name = "barcode"
    umap_coordinates.reset_index().to_csv(args.umap_coordinates, sep="\t", index=False)

    cluster_count = int(adata.obs["leiden"].nunique())
    if cluster_count > 1:
        sc.tl.rank_genes_groups(
            adata,
            groupby="leiden",
            method="wilcoxon",
            use_raw=True,
        )
        marker_genes = sc.get.rank_genes_groups_df(adata, group=None)
        marker_genes = marker_genes[MARKER_COLUMNS]
    else:
        marker_genes = pd.DataFrame(columns=MARKER_COLUMNS)
    marker_genes.to_csv(args.marker_genes, sep="\t", index=False)

    sc.pl.umap(adata, color="leiden", show=False, title=f"{args.sample_id} Leiden clusters")
    plt.savefig(args.umap_plot, dpi=150, bbox_inches="tight")
    plt.close("all")
    adata.write_h5ad(args.processed_h5ad, compression="gzip")

    summary = {
        "tool": "scanpy_qc_clustering",
        "scanpy_version": version("scanpy"),
        "sample_id": args.sample_id,
        "input_cells": input_cells,
        "input_genes": input_genes,
        "retained_cells": int(adata.n_obs),
        "retained_genes": retained_gene_count,
        "highly_variable_genes": highly_variable_count,
        "processed_h5ad_genes": int(adata.n_vars),
        "cluster_count": cluster_count,
        "effective_pcs": effective_pcs,
        "effective_neighbors": effective_neighbors,
        "parameters": {
            "min_genes": args.min_genes,
            "min_cells": args.min_cells,
            "max_mito_pct": args.max_mito_pct,
            "target_sum": args.target_sum,
            "n_top_genes": args.n_top_genes,
            "n_pcs": args.n_pcs,
            "n_neighbors": args.n_neighbors,
            "leiden_resolution": args.leiden_resolution,
            "random_seed": args.random_seed,
        },
    }
    args.analysis_summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_analysis(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
