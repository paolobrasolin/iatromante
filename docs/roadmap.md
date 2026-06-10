# Roadmap — done, loose ends, next steps

## Done ✅

- **Acquisition pipeline** (`feed fetch`): 5 sources, dedup, incremental. Full backfill →
  **208,082 papers**.
- **Full-text fetcher** (`feed fulltext`) — PMC OA. *Only run on a 10-paper sample.*
- **Unpaywall resolver** (`feed resolve-oa`). *Only run on a 40-paper sample (~70% hit).*
- **DOI cleanup** (`feed clean-dois`) — ran: 195 normalized, 29 nulled.
- **Embeddings** (`feed embed`) — 168,046 vectors, local.
- **Hierarchical clustering** (`feed cluster`) — 12 macro / 120 sub, full coverage.
- **FTS index** (`feed index`) — rebuilt over full corpus (carries authors + full_text_url).
- **Web app** — Ask / Search / Map, fully featured map (zoom/pan, year slider, OA filter,
  Topics/Conditions modes, expandable legend, sub-shading, click-to-open).
- **Deployment scaffolding** — Dockerfile, Swarm stack, GHCR workflow; built + smoke-tested.

## Loose ends (small)

- **PubMed top-up not run** — only ~1.3k PubMed records. Low value (Europe PMC has MEDLINE);
  would mainly add MeSH tags.
- **Watermarks not set** (`state.json`) → first scheduled fetch re-scans from 2015 once.
- **Full-text & OA only sampled**, not run at scale (deferred: hours + GBs).
- Map is downsampled? No — it now renders **all** 168k points (pixel buffer).

## Next steps (priority order)

1. **Finish deploying** (see [deployment.md](deployment.md)): set image owner, push tag,
   get data onto the server, **reverse proxy + TLS + auth gate**, then `docker stack deploy`.
2. **AI answers** — wire a model into the `/api/ask` seam so the Ask tab returns a written,
   **cited** summary over retrieved papers. Options: **Mistral API** (key already in `.env`)
   or a local LLM. `answer` is currently always `null` by design — just fill it.
3. **Automate updates** — daily `fetch → embed → index` (+ weekly `cluster`). Set watermarks.
4. **Full-text at scale (legitimate)** — run OA **text** extraction across the corpus
   (~2 GB), store as local files + embed. Optionally add a **publisher TDM API** fetcher if
   an institutional key exists. PDFs → own storage only. (No Sci-Hub — see decisions.md.)
5. **Private HF sync** — build `feed publish-data` / `feed pull-data` (needs
   `huggingface_hub`) to push **embeddings + corpus** to a **private** HF dataset and pull
   them on the server (wire to `DATA_PULL_CMD` in the container). See data-and-rights.md.

## Pending decisions

- **AI answer model:** Mistral API vs. local LLM (privacy vs. quality/effort).
- **Full text depth:** OA-only, or also TDM via an institutional key? (Which publisher?)
- **PDF archiving:** keep original PDFs at all (80–400 GB), or just extracted text (~GBs)?

## Where we paused (2026-06)

User chose **private HF** for data sharing and was weighing whether to include **paywalled
full texts** (answer: only legitimately-acquired, on own storage, never a third-party host;
no Sci-Hub). We checked sizes (embeddings 309 MB; full text ~2–5 GB; PDFs 80–400 GB). The
**next concrete build** is the private HF sync (`publish-data`/`pull-data`) — paused here to
write these docs first.
