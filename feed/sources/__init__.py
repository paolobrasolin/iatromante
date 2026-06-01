"""Literature source adapters.

Each module exposes ``fetch(client, pathology, terms, mesh, since, until, **opts)``
and yields :class:`feed.models.Paper` records.
"""

from . import clinicaltrials, europepmc, openalex, preprints, pubmed

# name -> module, in a sensible default order
REGISTRY = {
    "pubmed": pubmed,
    "europepmc": europepmc,
    "openalex": openalex,
    "clinicaltrials": clinicaltrials,
    "preprints": preprints,   # bioRxiv/medRxiv direct (opt-in; heavier)
}

# enabled unless explicitly selected otherwise; preprints is opt-in because the
# bioRxiv/medRxiv API has no keyword search (we date-scan + filter locally),
# and Europe PMC + OpenAlex already index those preprints with proper search.
DEFAULT_SOURCES = ["pubmed", "europepmc", "openalex", "clinicaltrials"]
