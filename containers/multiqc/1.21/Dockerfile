FROM python:3.11-slim

RUN pip install --no-cache-dir multiqc==1.21

COPY run_multiqc.sh /usr/local/bin/run_multiqc.sh
RUN chmod +x /usr/local/bin/run_multiqc.sh

ENTRYPOINT []
