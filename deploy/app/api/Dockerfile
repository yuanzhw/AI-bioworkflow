# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS runtime

ENTRYPOINT []

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./

# miniwdl is included for Linux container-local WDL syntax checks.
RUN uv sync --frozen --no-cache --all-extras --no-dev --no-install-project

COPY main.py ./
COPY src ./src
COPY examples ./examples

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/ai-bioworkflow \
    && chown -R appuser:appuser /app /data/ai-bioworkflow

USER appuser

ENV PATH="/app/.venv/bin:${PATH}" \
    AI_BIOWORKFLOW_DB_PATH=/data/ai-bioworkflow/ai-bioworkflow.sqlite3 \
    AI_BIOWORKFLOW_RUN_BACKEND=disabled \
    WDL_VALIDATOR=miniwdl

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/health', timeout=3).read()"

CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8010"]
