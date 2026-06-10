# Decisions & rationale

Why things are the way they are — so we don't relitigate settled calls.

## Sources

- **Google Scholar excluded.** No public API; scraping violates ToS and gets IP-banned.
  Its breadth is covered legitimately by **OpenAlex + Europe PMC + preprint servers**.
- **OpenAlex** is the wide net; **Europe PMC** the unifier (includes MEDLINE + OA
  full-text links); **PubMed** for MeSH; **ClinicalTrials.gov** for trials.
- **PubMed top-up deprioritized:** Europe PMC already carries MEDLINE records, so the
  only thing a full PubMed backfill adds is MeSH tags. Not worth it yet.

## No Sci-Hub / legitimate acquisition only

**The infringing act is acquisition**, not storage —
marking a repo "private" does not launder pirated PDFs. We will not wire up
paywall-bypass. Legitimate bulk full-text routes: PMC OA + Unpaywall (built), publisher
**TDM (text-&-data-mining) APIs** with an institutional key, library/interlibrary loan,
author requests. See [data-and-rights.md](data-and-rights.md).

## Relevance is non-destructive

The corpus is inflated by loose OpenAlex/Europe PMC matches (endometriosis ~124k,
fibromyalgia ~84k vs. real literature ~30k / ~12k; lipedema ~2.5k is clean). We do
**not** delete "off-topic" papers — semantic search simply doesn't rank them, and
clustering surfaces them as their own topics (e.g. the big herbal/"extract,
antioxidant" cluster). Relevance is a *facet*, not a filter.

## Embeddings: local

`fastembed` + `BAAI/bge-small-en-v1.5` on-device. Nothing leaves the machine (health
context). 168,046 vectors. Stored in `vectors.sqlite` via `sqlite-vec` so the vector
store, metadata, and map all live in one file.

## Clustering: hierarchical (the journey matters)

We iterated several times; the final design is deliberate:

1. KMeans k=60 — arbitrary count, mega-blurry. ❌
2. HDBSCAN on **2D** UMAP — 26% noise, two mega-clusters swallowing ⅓ of the corpus. ❌
3. HDBSCAN on **5D** UMAP — split the mega-clusters into specific topics, but ~41%
   "unclustered" (too much grey). `min_samples` barely moved it (it's 5D sparsity). ❌
4. **Hierarchical (final):** KMeans **macro** (k=12) on 5D = a dozen broad themes with
   full coverage (the "big topics" we liked); then **HDBSCAN sub-topics** within each
   macro (`min_cluster_size=300`), with orphans folded into the nearest sub via kNN so
   there is **no grey**. Result: 12 macros / 120 subs. ✅

Tunable: `--macro-k`, `--sub-min`. Labels: class-based TF-IDF on **titles** (BERTopic
trick) — rough, sometimes filler words. 2D UMAP is for the map only; clustering uses 5D.

## Map color scheme

Color by **macro** (golden-angle hue, ~12 distinct). Sub-topics share the macro hue but
vary **lightness** (40–66%) so they're distinguishable while still reading as one family.
Condition mode: endometriosis/lipedema/fibromyalgia colors + **cross-condition in
magenta**, drawn larger/on top (the ~1,900 multi-condition papers are the high-value slice).

## Derived vs. precious data

`index.sqlite` is cheap to rebuild from `corpus.jsonl` (don't ship it). `vectors.sqlite`
takes hours (embedding + clustering) — it's the artifact worth saving/sharing.

## Data sharing: private Hugging Face Hub

Chosen for embeddings + corpus. **Private only** (personal/server use). HF is the right
fit for ML data + embeddings (LFS, versioned, one-line pull). PDFs are too big and too
rights-sensitive for a third-party host → own storage. (Sync commands not built yet.)

## Misc gotchas baked into code

- ClinicalTrials.gov via stdlib `urllib` (httpx TLS fingerprint → Akamai 403).
- NCBI esearch JSON parsed `strict=False` (raw control chars in query translation).
- DOIs normalized/validated; 29 non-DOIs (SciELO PIDs, journal-internal ids) nulled,
  links fall back to PubMed when possible (`feed clean-dois`).
