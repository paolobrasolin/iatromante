#!/bin/sh
# Prepare the data volume, then serve.
set -e
cd /app
mkdir -p data

# Optionally fetch the data bundle on first boot (e.g. DATA_PULL_CMD="feed pull-data").
if [ ! -f data/vectors.sqlite ] && [ -n "$DATA_PULL_CMD" ]; then
  echo "[entrypoint] pulling data: $DATA_PULL_CMD"
  sh -c "$DATA_PULL_CMD"
fi

if [ ! -f data/vectors.sqlite ]; then
  echo "[entrypoint] ERROR: data/vectors.sqlite missing." >&2
  echo "  Populate the mounted volume with vectors.sqlite (+ corpus.jsonl)," >&2
  echo "  or set DATA_PULL_CMD to fetch it. See README 'Deploying'." >&2
  exit 1
fi

# The FTS index is cheap and derived — (re)build it if absent.
if [ ! -f data/index.sqlite ] && [ -f data/corpus.jsonl ]; then
  echo "[entrypoint] building search index from corpus ..."
  feed index
fi

exec uvicorn webapp.app:app --host 0.0.0.0 --port "${PORT:-8077}"
