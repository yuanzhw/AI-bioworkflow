FROM python:3.12-slim-bookworm

ARG TOOL_NAME=scanpy_qc_clustering
ARG TOOL_VERSION=1.12.3

LABEL org.opencontainers.image.source="https://github.com/yuanzhw/AI-bioworkflow" \
      org.opencontainers.image.title="AI-bioworkflow Scanpy QC and clustering helper" \
      org.opencontainers.image.description="Project-maintained helper image for bounded scRNA-seq QC and clustering" \
      org.opencontainers.image.ref.name="${TOOL_NAME}:${TOOL_VERSION}" \
      org.opencontainers.image.version="${TOOL_VERSION}"

ENV MPLBACKEND=Agg \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN python -m pip install --no-cache-dir "scanpy[leiden]==${TOOL_VERSION}" \
    && python -c "from importlib.metadata import version; assert version('scanpy') == '${TOOL_VERSION}'"

COPY run_scanpy_qc_clustering.py /usr/local/bin/run_scanpy_qc_clustering.py
RUN chmod +x /usr/local/bin/run_scanpy_qc_clustering.py

ENTRYPOINT []
