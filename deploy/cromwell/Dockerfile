FROM eclipse-temurin:17-jre-jammy

ARG CROMWELL_VERSION=92

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        docker.io \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/cromwell \
    && curl -fsSL \
        "https://github.com/broadinstitute/cromwell/releases/download/${CROMWELL_VERSION}/cromwell-${CROMWELL_VERSION}.jar" \
        -o /opt/cromwell/cromwell.jar

WORKDIR /opt/cromwell

EXPOSE 8000

ENTRYPOINT ["java", "-Dconfig.file=/opt/cromwell/application.conf", "-jar", "/opt/cromwell/cromwell.jar"]
CMD ["server"]
