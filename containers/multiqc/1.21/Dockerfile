FROM python:3.11-slim

ARG TOOL_NAME=multiqc
ARG TOOL_VERSION=1.21

LABEL org.opencontainers.image.source="https://github.com/yuanzhw/AI-bioworkflow" \
      org.opencontainers.image.title="AI-bioworkflow MultiQC helper" \
      org.opencontainers.image.description="Project-maintained helper image for MultiQC workflows" \
      org.opencontainers.image.ref.name="${TOOL_NAME}:${TOOL_VERSION}" \
      org.opencontainers.image.version="${TOOL_VERSION}"

RUN pip install --no-cache-dir "multiqc==${TOOL_VERSION}" \
    && python -c "import multiqc; assert multiqc.__version__ == '${TOOL_VERSION}', multiqc.__version__"

COPY run_multiqc.sh /usr/local/bin/run_multiqc.sh
RUN chmod +x /usr/local/bin/run_multiqc.sh

ENTRYPOINT []
