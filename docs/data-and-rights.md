# Data assets, sizes, and distribution rights

## Asset inventory & sizes (measured + estimated)

| Asset | Size | Notes |
|---|---|---|
| `corpus.jsonl` | 430 MB | dataset: metadata + abstracts, 208,082 papers |
| `vectors.sqlite` | 309 MB | embeddings (258 MB pure) + map + clusters — **precious** |
| `index.sqlite` | 634 MB | FTS5 — derived, rebuildable, don't ship |
| extracted full **text** (OA) | ~2 GB | ~24 KB/paper × ~79k w/ body (sampled) |
| extracted full **text** (all, hypothetical) | ~5 GB | 208k × ~24 KB |
| full **PDFs** (OA) | ~80 GB (could be 150–400 GB) | ~1–5 MB/paper; medical PDFs are figure-heavy |
| full **PDFs** (all, hypothetical) | ~210 GB+ | — |

Corpus composition: 168,037 (80%) have abstracts (embeddable); ~1,900 are
cross-condition (tagged with 2+ pathologies); ~98,619 have a PMCID (OA full-text
candidates). Spans 1900s–2027.

## Distribution rights (not legal advice)

The legal line is mostly about **how papers are acquired** and **whether content lands
on a third party's servers** — *not* whether a repo is marked private.

| Layer | Rights | Public redistribution? |
|---|---|---|
| IDs + metadata (DOI, PMID, title, authors, journal, year) | facts; PubMed metadata public-domain, OpenAlex CC0 | ✅ yes |
| Abstracts (full text) | publisher/author copyright | ⚠️ no (except OA subset) |
| Embeddings (`vectors.sqlite`) | numeric transform, not human-readable | ✅ low-risk |
| OA full papers | CC-BY / CC-BY-NC etc. | ✅ with attribution + license |
| Paywalled full papers | copyright | ❌ never |

> OpenAlex itself ships an *inverted index* instead of plain abstracts for exactly this
> reason. Re-publishing 200k reconstructed abstracts publicly = redistributing
> copyrighted text at scale.

## Sharing plan (decided)

- **Private HF Hub** for **embeddings + corpus** (personal/server use = not
  redistribution; fine). ~310 MB embeddings, ~740 MB with corpus.
- **Full text** plain (~2–5 GB): OK on private HF if wanted, but it *is* the copyrighted
  content — keep private.
- **PDFs** (80–400 GB): **own storage only** (swarm volume + backup, or own R2/B2 bucket).
  Not needed for search anyway — the ~2–5 GB of extracted text feeds embeddings + UI.
- **Paywalled full text:** only if **legitimately accessed**, stored on infrastructure
  **you control**, never uploaded to a third party. Uploading subscription PDFs to HF
  (even private) typically breaches the subscription license and HF ToS.

## Legitimate full-text-at-scale routes

- **Built & free:** PMC OA (`feed fulltext`), Unpaywall (`feed resolve-oa`).
- **Sanctioned bulk:** publisher **TDM APIs** (Elsevier, Wiley, Springer…) with a key
  tied to an institutional subscription; **Crossref TDM** links.
- **Other:** institutional / library access (incl. interlibrary loan), author requests.

If an institutional/TDM key is available, a TDM fetcher can be added (which publisher
determines the adapter). Otherwise OA-only is the clean default.

## If publishing publicly (not currently planned)

Safe shape would be: embeddings + **IDs/metadata without abstracts** (others rehydrate
via `feed fetch`), plus OA-only full text with attribution. A `--metadata-only` export
mode was proposed for this but not built (we chose private-only).
