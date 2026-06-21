# iatromante — project docs

These docs capture the project's state, architecture, and decisions so work can be
resumed cold. Written 2026-06 after building the corpus, search, map, and the
Docker deployment.

## What this is

A **continuously-updatable, in-repo corpus** of the biomedical literature on three
pathologies — **endometriosis, lipedema (incl. UK spelling *lipoedema*), and
fibromyalgia** — plus a **self-hosted web app** (Search / Map) to browse and
search it. Everything runs locally; embeddings are computed on-device.

**Why:** the maintainer's partner lives with these three (frequently co-occurring)
conditions; the goal is a private research aid that surfaces evidence, trials, and
the cross-condition intersection. It is an **aid, not medical advice**, and not a
substitute for a care team.

## Current status (snapshot)

- **Corpus:** 208,082 unique papers (full historical backfill). `data/` is gitignored.
- **Search:** keyword (FTS5) + semantic/"deep" (local embeddings) — both working.
- **Map:** hierarchical topic map (12 macro-topics / 120 sub-topics), fully featured.
- **Web app:** runs locally (`uvicorn webapp.app:app`, port 8077). Search (keyword +
  semantic) and the topic/condition map; a generated AI summary is not yet built.
- **Deployment:** Dockerfile + Swarm stack + GHCR workflow built and verified; **not
  yet pushed/deployed**.
- **Data sharing:** decided on **private Hugging Face Hub**; sync commands **not yet built**.

See [roadmap.md](roadmap.md) for what's done vs. next, and where exactly we paused.

## Doc index

- [architecture.md](architecture.md) — components, data flow, `feed` CLI, web app, schemas
- [decisions.md](decisions.md) — key choices and their rationale
- [data-and-rights.md](data-and-rights.md) — data assets, sizes, sharing plan, copyright
- [deployment.md](deployment.md) — Docker / GHCR / Swarm, and how to finish deploying
- [roadmap.md](roadmap.md) — done, loose ends, next steps, pending decisions

## Quick reference

```bash
# environment: Python + uv + nix flake. Dev install (incl. clustering libs):
uv sync --extra analysis

# pipeline
uv run feed fetch                 # pull new papers -> data/corpus.jsonl
uv run feed embed                 # local embeddings -> data/vectors.sqlite
uv run feed cluster               # hierarchical topics + 2D map
uv run feed index                 # FTS5 index (derived, rebuildable)
uv run feed fulltext              # PMC open-access full text
uv run feed resolve-oa            # Unpaywall legal OA copies
uv run feed clean-dois            # normalize/validate DOIs
uv run feed search "..." [-s]     # keyword, or -s for semantic
uv run feed stats

# web app
uv run uvicorn webapp.app:app --port 8077    # then open http://localhost:8077
```

Env (`.env`, gitignored): `MISTRAL_API_KEY` (for future AI answers),
`CONTACT_EMAIL` (OpenAlex polite pool / NCBI; optional), `NCBI_API_KEY` (optional).
