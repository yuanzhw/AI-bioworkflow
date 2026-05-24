FROM bioconductor/bioconductor_docker:RELEASE_3_18

RUN Rscript -e 'BiocManager::install(c("tximport", "readr"), ask = FALSE, update = FALSE)'

COPY run_tximport.R /usr/local/bin/run_tximport.R
RUN chmod +x /usr/local/bin/run_tximport.R

ENTRYPOINT []
