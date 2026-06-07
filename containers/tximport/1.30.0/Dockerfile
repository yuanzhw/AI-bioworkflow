FROM bioconductor/bioconductor_docker:RELEASE_3_18

ARG BIOCONDUCTOR_RELEASE=3.18
ARG TOOL_NAME=tximport
ARG TOOL_VERSION=1.30.0

LABEL org.opencontainers.image.source="https://github.com/yuanzhw/AI-bioworkflow" \
      org.opencontainers.image.title="AI-bioworkflow tximport helper" \
      org.opencontainers.image.description="Project-maintained helper image for tximport workflows" \
      org.opencontainers.image.ref.name="${TOOL_NAME}:${TOOL_VERSION}" \
      org.opencontainers.image.version="${TOOL_VERSION}"

RUN Rscript -e "repos <- BiocManager::repositories(version = '${BIOCONDUCTOR_RELEASE}'); \
    deps <- c('Depends', 'Imports', 'LinkingTo'); \
    BiocManager::install('readr', version = '${BIOCONDUCTOR_RELEASE}', dependencies = deps, ask = FALSE, update = FALSE); \
    install.packages('https://bioconductor.org/packages/${BIOCONDUCTOR_RELEASE}/bioc/src/contrib/tximport_${TOOL_VERSION}.tar.gz', repos = repos, dependencies = deps, type = 'source'); \
    stopifnot(as.character(packageVersion('tximport')) == '${TOOL_VERSION}')"

COPY run_tximport.R /usr/local/bin/run_tximport.R
RUN chmod +x /usr/local/bin/run_tximport.R

ENTRYPOINT []
