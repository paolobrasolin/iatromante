"""bioRxiv / medRxiv direct API (opt-in).

These servers have NO keyword search -- the API only serves papers by date
window. So we page through the requested range and filter locally against the
configured synonyms. This is heavier than the other sources and is therefore
disabled by default; Europe PMC (source=PPR) and OpenAlex (type=preprint) both
index these same preprints *with* search, which covers most needs.

Enable with ``feed fetch --source preprints`` (or add it to --source list).
"""

from __future__ import annotations

import re
import time
from typing import Iterator

from ..models import Paper, canonical_id
from .base import get_json

SERVERS = ("medrxiv", "biorxiv")   # medrxiv first: clinical relevance


def _matcher(terms: list[str]):
    pat = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
    return lambda text: bool(pat.search(text or ""))


def _parse(rec: dict, server: str, pathology: str) -> Paper:
    doi = rec.get("doi")
    title = rec.get("title", "") or ""
    authors = [a.strip() for a in (rec.get("authors", "") or "").split(";") if a.strip()]
    date = rec.get("date", "") or ""
    year = int(date[:4]) if date[:4].isdigit() else None
    cid = canonical_id(doi, None, server, doi, title)
    return Paper(
        id=cid, title=title, abstract=rec.get("abstract", "") or "",
        doi=doi, authors=authors, venue=server, pub_date=date, year=year,
        type="preprint",
        url=f"https://doi.org/{doi}" if doi else "",
        is_oa=True, pathologies=[pathology], sources=[server],
        source_ids={server: doi or rec.get("doi", "")},
    )


def fetch(client, pathology, terms, mesh, since, until, **_) -> Iterator[Paper]:
    matches = _matcher(terms)
    for server in SERVERS:
        cursor = 0
        while True:
            url = f"https://api.biorxiv.org/details/{server}/{since}/{until}/{cursor}"
            data = get_json(client, url, {})
            collection = data.get("collection", [])
            for rec in collection:
                if matches(rec.get("title")) or matches(rec.get("abstract")):
                    yield _parse(rec, server, pathology)
            messages = data.get("messages", [{}])
            total = int(messages[0].get("total", 0)) if messages else 0
            cursor += len(collection)
            if not collection or cursor >= total:
                break
            time.sleep(0.2)
