FROM bioconductor/bioconductor_docker:RELEASE_3_18

ARG BIOCONDUCTOR_RELEASE=3.18
ARG TOOL_NAME=limma_voom
ARG TOOL_VERSION=3.58.1

LABEL org.opencontainers.image.source="https://github.com/yuanzhw/AI-bioworkflow" \
      org.opencontainers.image.title="AI-bioworkflow limma-voom helper" \
      org.opencontainers.image.description="Project-maintained helper image for limma-voom differential expression workflows" \
      org.opencontainers.image.ref.name="${TOOL_NAME}:${TOOL_VERSION}" \
      org.opencontainers.image.version="${TOOL_VERSION}"

RUN Rscript -e "deps <- c('Depends', 'Imports', 'LinkingTo'); \
    BiocManager::install(c('readr', 'edgeR', 'limma'), version = '${BIOCONDUCTOR_RELEASE}', dependencies = deps, ask = FALSE, update = FALSE); \
    stopifnot(as.character(packageVersion('limma')) == '${TOOL_VERSION}')"

COPY run_limma_voom.R /usr/local/bin/run_limma_voom.R
RUN sed -i 's/\r$//' /usr/local/bin/run_limma_voom.R \
    && chmod +x /usr/local/bin/run_limma_voom.R

ENTRYPOINT []
