FROM bioconductor/bioconductor_docker:RELEASE_3_18

ARG BIOCONDUCTOR_RELEASE=3.18
ARG TOOL_NAME=edger
ARG TOOL_VERSION=4.0.16

LABEL org.opencontainers.image.source="https://github.com/yuanzhw/AI-bioworkflow" \
      org.opencontainers.image.title="AI-bioworkflow edgeR helper" \
      org.opencontainers.image.description="Project-maintained helper image for edgeR differential expression workflows" \
      org.opencontainers.image.ref.name="${TOOL_NAME}:${TOOL_VERSION}" \
      org.opencontainers.image.version="${TOOL_VERSION}"

RUN Rscript -e "deps <- c('Depends', 'Imports', 'LinkingTo'); \
    BiocManager::install(c('readr', 'edgeR'), version = '${BIOCONDUCTOR_RELEASE}', dependencies = deps, ask = FALSE, update = FALSE); \
    stopifnot(as.character(packageVersion('edgeR')) == '${TOOL_VERSION}')"

COPY run_edger.R /usr/local/bin/run_edger.R
RUN sed -i 's/\r$//' /usr/local/bin/run_edger.R \
    && chmod +x /usr/local/bin/run_edger.R

ENTRYPOINT []
