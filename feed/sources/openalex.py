"""OpenAlex -- the widest legitimate net (replaces Google Scholar).

Free, open catalog of ~250M works with a real API (no scraping, no bans).
Abstracts arrive as an inverted index that we reconstruct. Provide a contact
email via $CONTACT_EMAIL to join the faster "polite pool".
"""

from __future__ import annotations

import time
from typing import Iterator

from ..models import Paper, canonical_id
from .base import CONTACT_EMAIL, get_json

BASE = "https://api.openalex.org/works"
_PAGE = 200


def _reconstruct_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def _strip_prefix(url: str | None, prefix: str) -> str | None:
    if url and url.startswith(prefix):
        return url[len(prefix):]
    return url


def _parse(work: dict, pathology: str) -> Paper:
    doi = _strip_prefix(work.get("doi"), "https://doi.org/")
    ids = work.get("ids", {}) or {}
    pmid = _strip_prefix(ids.get("pmid"), "https://pubmed.ncbi.nlm.nih.gov/")
    title = work.get("title") or work.get("display_name") or ""
    authors = [a.get("author", {}).get("display_name", "")
               for a in work.get("authorships", [])]
    authors = [a for a in authors if a]
    venue = ((work.get("primary_location") or {}).get("source") or {}).get("display_name", "") or ""
    oa = work.get("open_access", {}) or {}
    wtype = work.get("type", "article")
    is_preprint = wtype == "preprint" or (work.get("primary_location") or {}).get("version") == "submittedVersion"

    cid = canonical_id(doi, pmid, "openalex", work.get("id"), title)
    return Paper(
        id=cid, title=title,
        abstract=_reconstruct_abstract(work.get("abstract_inverted_index")),
        doi=doi, pmid=pmid, authors=authors, venue=venue,
        pub_date=work.get("publication_date", "") or "",
        year=work.get("publication_year"),
        type="preprint" if is_preprint else "article",
        url=work.get("doi") or work.get("id", ""),
        full_text_url=oa.get("oa_url", "") or "",
        is_oa=bool(oa.get("is_oa")),
        keywords=[k.get("display_name", "") for k in work.get("keywords", [])],
        pathologies=[pathology], sources=["openalex"],
        source_ids={"openalex": (work.get("id") or "").rsplit("/", 1)[-1]},
    )


def fetch(client, pathology, terms, mesh, since, until, **_) -> Iterator[Paper]:
    # OpenAlex search is phrase/stem based, not boolean -- one request per synonym,
    # global dedup folds the overlaps.
    for term in terms:
        cursor = "*"
        while True:
            params = {
                "filter": (f"title_and_abstract.search:{term},"
                           f"from_publication_date:{since},"
                           f"to_publication_date:{until}"),
                "per-page": str(_PAGE), "cursor": cursor,
            }
            if CONTACT_EMAIL:
                params["mailto"] = CONTACT_EMAIL
            data = get_json(client, BASE, params)
            for work in data.get("results", []):
                yield _parse(work, pathology)
            cursor = (data.get("meta", {}) or {}).get("next_cursor")
            if not cursor:
                break
            time.sleep(0.2)
