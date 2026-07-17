FROM python:3.13-slim

ARG TOOL_NAME=gtf_tx2gene
ARG TOOL_VERSION=1.0.0

LABEL org.opencontainers.image.source="https://github.com/yuanzhw/AI-bioworkflow" \
      org.opencontainers.image.title="AI-bioworkflow gtf_tx2gene helper" \
      org.opencontainers.image.description="Project-maintained helper image for extracting tx2gene tables from GTF annotations" \
      org.opencontainers.image.ref.name="${TOOL_NAME}:${TOOL_VERSION}" \
      org.opencontainers.image.version="${TOOL_VERSION}"

COPY run_gtf_tx2gene.py /usr/local/bin/run_gtf_tx2gene.py
RUN chmod +x /usr/local/bin/run_gtf_tx2gene.py

ENTRYPOINT []
