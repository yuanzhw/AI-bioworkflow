FROM bioconductor/bioconductor_docker:RELEASE_3_18

RUN Rscript -e 'BiocManager::install(c("DESeq2", "readr"), ask = FALSE, update = FALSE)'

COPY run_deseq2.R /usr/local/bin/run_deseq2.R
RUN chmod +x /usr/local/bin/run_deseq2.R

ENTRYPOINT []
