# Serving image for the iatromante web app.
# Contains code + serve-only deps + the embedding model. NO corpus data — that is
# mounted as a volume at /app/data (see docker-stack.yml). The expensive
# vectors.sqlite must be present in the volume; the cheap FTS index is rebuilt on
# start from corpus.jsonl if missing.

FROM python:3.13-slim

# uv for fast, locked installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV HOME=/app \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app

# 1) deps (cached layer): base deps only — no 'analysis' extra (umap/hdbscan/sklearn)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) app code + install the project
COPY feed/ feed/
COPY webapp/ webapp/
COPY config/ config/
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN uv sync --frozen --no-dev && chmod +x /usr/local/bin/entrypoint.sh

# 3) pre-cache the embedding model so first query is instant and offline
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

EXPOSE 8077
VOLUME ["/app/data"]
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
