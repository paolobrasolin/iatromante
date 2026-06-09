# iatromante

A **self-updating, in-repo corpus** of the biomedical literature on a fixed set of
pathologies — currently **endometriosis**, **lipedema** (incl. UK spelling
*lipoedema*), and **fibromyalgia**. Every run pulls new papers from several
sources, deduplicates them into one canonical record per paper, and writes them
to a git-tracked JSONL file so that an LLM (or any tool) can read and reason over
the whole dataset.

## Sources

| Source | Role | Notes |
|---|---|---|
| **PubMed / MEDLINE** (NCBI E-utilities) | Peer-reviewed core | abstracts + MeSH terms |
| **Europe PMC** | Unifies PubMed/PMC/preprints | open-access full-text links |
| **OpenAlex** | Widest net (replaces Google Scholar) | legitimate API, no scraping |
| **ClinicalTrials.gov** (API v2) | Trials, not just papers | incremental on last-update date |
| **bioRxiv / medRxiv** (direct) | Preprints | **opt-in** (`--source preprints`); date-scan + local filter |

> **Why not Google Scholar?** It has no public API and scraping it violates their
> terms and gets the IP banned. OpenAlex + Europe PMC + the preprint servers cover
> the same breadth legitimately.

## Quick start

```bash
# one-time: enter the dev shell (nix) or just use uv directly
uv sync

# set a contact email — joins OpenAlex's faster "polite pool" and is good API etiquette
export CONTACT_EMAIL=you@example.com
# optional: raises PubMed rate limit from 3 to 10 req/s
export NCBI_API_KEY=...

# fetch everything new since the last run (first run backfills from config.backfill_start)
uv run feed fetch

# build the search index and explore
uv run feed index
uv run feed stats
uv run feed search "deep infiltrating endometriosis MRI"
```

### Commands

- `feed fetch` — pull new papers into `data/corpus.jsonl`.
  - `--pathology endometriosis` (repeatable) — limit to one disease.
  - `--source pubmed` (repeatable) — limit to one source. Default: all except `preprints`.
  - `--since 2020-01-01` — override the start date (does **not** move the watermark).
  - `--all` — fetch full history, ignoring watermarks.
- `feed index` — (re)build `data/index.sqlite` (FTS5 full-text) from the corpus.
- `feed search "<query>"` — search the corpus (`--semantic` for deep/vector search).
- `feed stats` — counts by pathology / source / type, plus per-source watermarks.
- `feed embed` — compute local semantic embeddings → `data/vectors.sqlite` (deep search).
- `feed cluster [--k 60]` — topic-cluster + 2D-project the embeddings for the map.

## Web app (browse / search / map)

A self-hosted single-page UI lives in `webapp/` (FastAPI + vanilla JS, no build step).
It reads the derived artifacts (`data/index.sqlite`, `data/vectors.sqlite`) and serves
three tabs: **Ask** (plain-language → most-relevant papers), **Search** (semantic or
keyword, condition filters), and **Map** (the topic-cluster landscape).

```bash
# prerequisites (once the corpus exists): build the derived artifacts
uv run feed index      # keyword search + metadata/abstracts
uv run feed embed      # semantic search vectors (local, on-device)
uv run feed cluster    # topic clusters + 2D map coordinates

# run the server
uv run uvicorn webapp.app:app --host 0.0.0.0 --port 8077
```

The AI-answer summary is intentionally not wired yet: `/api/ask` returns the deep-search
results with `answer: null` — a generated, cited summary drops in there later without any
frontend change.

### Deploying to your own server

1. Clone the repo and `uv sync` on the server.
2. Build the artifacts there (`feed index && feed embed && feed cluster`) **or** copy the
   `data/*.sqlite` files over (the embedding model otherwise downloads ~130 MB on first run).
3. Run uvicorn behind your reverse proxy (nginx/Caddy) with TLS; restrict access as needed
   (this is health-adjacent reading — consider HTTP basic-auth or your usual gate).
4. **Keep it current** with a daily job:
   ```bash
   feed fetch          # new papers (incremental once watermarks are set)
   feed embed          # embed only the new ones (resumable)
   feed index          # rebuild keyword index
   feed cluster        # periodically (weekly) — re-cluster as the corpus grows
   ```

## How it works

1. **Fetch** — each source is queried per-pathology using the synonyms and MeSH
   terms in `config/pathologies.yaml`, restricted to a date window.
2. **Deduplicate** — records are merged on DOI → PMID → normalized title, so a
   paper seen by three sources becomes one record listing all three in `sources`.
   The richest field wins (e.g. the longest abstract, the most complete author list).
3. **Store** — the merged corpus is written to `data/corpus.jsonl`, one JSON object
   per line, **sorted by id** so git diffs stay small. This file is the source of truth.
4. **Index** — `data/index.sqlite` is a *derived, git-ignored* FTS5 index rebuilt
   on demand for fast search.

### Incremental updates

Each source stores a watermark (last fetch date) in `data/state.json`. Subsequent
runs only fetch from `watermark − lookback_days` (a re-scan buffer for
late-indexed records) to today. Re-fetched duplicates are harmlessly merged.

To extend the historical depth, run a one-off backfill that doesn't disturb
watermarks: `uv run feed fetch --since 2000-01-01`.

## Data schema

`data/corpus.jsonl` — one `Paper` per line:

```jsonc
{
  "id": "doi:10.1016/...",       // canonical: doi: | pmid: | title:<hash>
  "title": "...", "abstract": "...",
  "doi": "...", "pmid": "...", "pmcid": "...",
  "authors": ["..."], "venue": "...",
  "pub_date": "2026-04-12", "year": 2026,
  "type": "article",             // article | preprint | clinical_trial
  "url": "...", "full_text_url": "...", "is_oa": true,
  "mesh": ["..."], "keywords": ["..."],
  "pathologies": ["endometriosis"],   // which configured diseases matched
  "sources": ["pubmed", "openalex"],  // which providers supplied this record
  "source_ids": { "pubmed": "42104671" },
  "fetched_at": "2026-06-01T15:40:00"
}
```

## Keeping it fed (scheduling)

The pipeline is built; wiring up *automatic* recurrence is a separate, deliberate
choice. Three options:

**A. GitHub Actions cron** (recommended for an in-repo archive — runs in the cloud,
commits new papers itself, no machine need be on):

```yaml
# .github/workflows/feed.yml
name: feed
on:
  schedule: [{ cron: "0 6 * * *" }]   # daily at 06:00 UTC
  workflow_dispatch:
jobs:
  fetch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run feed fetch
        env:
          CONTACT_EMAIL: ${{ secrets.CONTACT_EMAIL }}
          NCBI_API_KEY:  ${{ secrets.NCBI_API_KEY }}
      - run: |
          git config user.name  "feed-bot"
          git config user.email "feed-bot@users.noreply.github.com"
          git add data/corpus.jsonl data/state.json
          git diff --cached --quiet || git commit -m "feed: $(date -u +%F)"
          git push
```

**B. Local cron** — `0 6 * * * cd /path/to/iatromante && uv run feed fetch`.

**C. Claude scheduled agent** — a Claude routine that runs `feed fetch` *and* writes
you a human-readable digest of what's new each run (set up via the `/schedule` skill).
