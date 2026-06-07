FROM bioconductor/bioconductor_docker:RELEASE_3_18

ARG BIOCONDUCTOR_RELEASE=3.18
ARG TOOL_NAME=deseq2
ARG TOOL_VERSION=1.42.0

LABEL org.opencontainers.image.source="https://github.com/yuanzhw/AI-bioworkflow" \
      org.opencontainers.image.title="AI-bioworkflow DESeq2 helper" \
      org.opencontainers.image.description="Project-maintained helper image for DESeq2 workflows" \
      org.opencontainers.image.ref.name="${TOOL_NAME}:${TOOL_VERSION}" \
      org.opencontainers.image.version="${TOOL_VERSION}"

RUN Rscript -e "repos <- BiocManager::repositories(version = '${BIOCONDUCTOR_RELEASE}'); \
    deps <- c('Depends', 'Imports', 'LinkingTo'); \
    BiocManager::install('readr', version = '${BIOCONDUCTOR_RELEASE}', dependencies = deps, ask = FALSE, update = FALSE); \
    install.packages('https://bioconductor.org/packages/${BIOCONDUCTOR_RELEASE}/bioc/src/contrib/DESeq2_${TOOL_VERSION}.tar.gz', repos = repos, dependencies = deps, type = 'source'); \
    stopifnot(as.character(packageVersion('DESeq2')) == '${TOOL_VERSION}')"

COPY run_deseq2.R /usr/local/bin/run_deseq2.R
RUN chmod +x /usr/local/bin/run_deseq2.R

ENTRYPOINT []
