# Architecture

Pipeline shape: **acquire → enrich → understand → serve.** A Python package
`feed/` does the data work via a `feed` CLI; `webapp/` is a FastAPI app over the
derived artifacts. Stack: Python 3.13, `uv`, nix flake (provides `uv`).

## `feed` CLI commands

| Command | What it does | Writes |
|---|---|---|
| `feed fetch` | Pull new papers from sources, dedup, merge | `data/corpus.jsonl`, `data/state.json` |
| `feed fulltext` | Download PMC open-access full text (NCBI efetch) | `data/fulltext/*.txt` + manifest |
| `feed resolve-oa` | Find legal OA copies of paywalled DOIs (Unpaywall) | `data/openaccess/manifest.json` |
| `feed clean-dois` | Normalize/validate DOIs, null non-DOIs, reindex | rewrites `corpus.jsonl` |
| `feed embed` | Local semantic embeddings (fastembed) | `data/vectors.sqlite` |
| `feed cluster` | Hierarchical topics + 2D UMAP map | tables in `vectors.sqlite` |
| `feed index` | FTS5 keyword index + metadata/abstracts | `data/index.sqlite` |
| `feed search "q" [-s]` | Keyword (default) or `--semantic` vector search | — |
| `feed stats` | Corpus counts by pathology/source/type | — |

## Data files (`data/`, gitignored)

| File | Size | Role | Derived? |
|---|---|---|---|
| `corpus.jsonl` | 430 MB | Source of truth: one `Paper` JSON/line, sorted by id | no |
| `state.json` | tiny | Per-source watermarks (incremental fetch) | — |
| `vectors.sqlite` | 309 MB | Embeddings + map coords + cluster hierarchy | **precious** (hours to rebuild) |
| `index.sqlite` | 634 MB | FTS5 + metadata + abstracts | yes — rebuild via `feed index` |
| `fulltext/` | (sample) | Extracted OA full text + manifest | re-fetchable |
| `openaccess/manifest.json` | (sample) | Unpaywall OA locations | re-fetchable |

Rule of thumb: **ship `corpus.jsonl` + `vectors.sqlite`; rebuild `index.sqlite`.**

## Sources (`feed/sources/`)

- **PubMed/MEDLINE** (E-utilities esearch+efetch) — abstracts + MeSH. *Gotcha:* big
  query translations contain raw control chars → JSON parsed with `strict=False`.
- **Europe PMC** — unifies PubMed/PMC/preprints, OA full-text links. Covers MEDLINE,
  so a separate PubMed backfill is low-value (we never completed it; ~1.3k PubMed
  records vs 149k Europe PMC).
- **OpenAlex** — the wide net (replaces Google Scholar). Abstracts arrive as an
  inverted index we reconstruct. Polite pool via `CONTACT_EMAIL`.
- **ClinicalTrials.gov v2** — trials. *Gotcha:* Akamai 403s httpx's TLS fingerprint;
  we call it via stdlib `urllib` (see `sources/base.py:get_json_stdlib`).
- **bioRxiv/medRxiv** (`preprints.py`) — opt-in; date-scan + local keyword filter
  (the API has no search). Preprints mostly come via Europe PMC/OpenAlex anyway.

Dedup (`feed/store.py:Corpus`): merge on **DOI → PMID → normalized title**; one record
lists all sources that saw it; richest field wins (longest abstract, etc.).

## Data model

`Paper` (`feed/models.py`): `id` (canonical: `doi:` | `pmid:` | `title:<hash>`),
`title, abstract, doi, pmid, pmcid, authors[], venue, pub_date, year, type`
(`article|preprint|clinical_trial`), `url, full_text_url, is_oa, mesh[], keywords[],
pathologies[], sources[], source_ids{}, fetched_at`.

`vectors.sqlite` (sqlite-vec):
- `vec_papers(paper_id PK, embedding float[384], +title, +year, +type, +url, +pathologies)`
- `paper_map(paper_id PK, x, y, cluster, macro)` — `cluster` = leaf/sub id
- `clusters(cluster PK, label, size, pathology_mix, parent, level)` — level 1 = macro
  (parent NULL), level 2 = sub (parent = macro id). Sub ids start at 1000.

## Web app (`webapp/`, FastAPI + vanilla JS, no build step)

Two tabs: **Search / Map**.

Endpoints (`webapp/app.py`):
- `GET /api/meta` → totals + pathologies
- `GET /api/search?q&mode=semantic|keyword&pathology&limit`
- `GET /api/paper/{id}` → full detail (+ topic label)
- `GET /api/clusters` → nested `{macros: [{...subs: [...]}]}`
- `GET /api/map?pathology` → points `[x, y, macro, sub, year, pmask, is_oa]` (all 168k)
- `GET /api/map/at?x&y` → nearest paper id (click-to-open)

Data access: read-only connections to `index.sqlite` (search/detail) and
`vectors.sqlite` (sqlite-vec loaded; map/clusters). The embedding model is loaded
once and cached (`feed/embed.py:_model`).

Frontend (`webapp/static/`): map is drawn into an `ImageData` pixel buffer (fast for
all 168k points). Color = macro hue; sub-topics vary by **lightness** within the hue.
Features: expandable macro→sub legend, dual-handle year slider, open-access filter,
Topics/Conditions color modes (cross-condition = magenta, drawn larger/on top),
wheel-zoom toward cursor + drag-pan, zoom-scaled point size, click-to-open.

## Dependencies

Base (serving): `httpx, pyyaml, fastembed, sqlite-vec, numpy, fastapi, uvicorn`.
Optional `analysis` extra (offline clustering only, excluded from the Docker image):
`scikit-learn, umap-learn, hdbscan`. Embedding model: `BAAI/bge-small-en-v1.5` (384-d).
