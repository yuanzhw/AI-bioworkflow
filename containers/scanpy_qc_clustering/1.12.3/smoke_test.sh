#!/usr/bin/env bash
set -euo pipefail

command -v python >/dev/null
test -x /usr/local/bin/run_scanpy_qc_clustering.py
python -c 'from importlib.metadata import version; assert version("scanpy") == "1.12.3"'
python -c 'import h5py, igraph, leidenalg, scanpy'
run_scanpy_qc_clustering.py --help >/dev/null
