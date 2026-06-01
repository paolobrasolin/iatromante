"""Europe PMC REST API.

Unifies PubMed, PMC, Agricola, patents and preprints behind one searchable
endpoint, and exposes open-access full-text links. ``resultType=core`` returns
abstracts and full-text URLs.
"""

from __future__ import annotations

import time
from typing import Iterator

from ..models import Paper, canonical_id
from .base import get_json

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_PAGE = 1000


def _build_query(terms: list[str], since: str, until: str) -> str:
    syn = " OR ".join(f'"{t}"' for t in terms)
    return f"({syn}) AND (FIRST_PDATE:[{since} TO {until}])"


def _parse(rec: dict, pathology: str) -> Paper:
    doi = rec.get("doi")
    pmid = rec.get("pmid")
    pmcid = rec.get("pmcid")
    title = rec.get("title", "") or ""
    src = rec.get("source", "")
    is_preprint = src == "PPR" or rec.get("pubType", "").lower().find("preprint") >= 0

    full_text_url = ""
    for u in (rec.get("fullTextUrlList", {}) or {}).get("fullTextUrl", []):
        if u.get("availabilityCode") == "OA" or u.get("documentStyle") == "pdf":
            full_text_url = u.get("url", "")
            break

    authors = []
    author_str = rec.get("authorString", "")
    if author_str:
        authors = [a.strip() for a in author_str.rstrip(".").split(",") if a.strip()]

    journal = (rec.get("journalInfo", {}) or {}).get("journal", {}).get("title", "") \
        or rec.get("bookOrReportDetails", {}).get("publisher", "")
    pub_date = rec.get("firstPublicationDate", "") or ""
    year = int(rec["pubYear"]) if rec.get("pubYear", "").isdigit() else None

    cid = canonical_id(doi, pmid, "europepmc", rec.get("id"), title)
    url = ""
    if doi:
        url = f"https://doi.org/{doi}"
    elif pmid:
        url = f"https://europepmc.org/article/MED/{pmid}"

    return Paper(
        id=cid, title=title, abstract=rec.get("abstractText", "") or "",
        doi=doi, pmid=pmid, pmcid=pmcid, authors=authors, venue=journal,
        pub_date=pub_date, year=year,
        type="preprint" if is_preprint else "article",
        url=url, full_text_url=full_text_url,
        is_oa=rec.get("isOpenAccess") == "Y",
        pathologies=[pathology], sources=["europepmc"],
        source_ids={"europepmc": f"{src}:{rec.get('id')}"},
    )


def fetch(client, pathology, terms, mesh, since, until, **_) -> Iterator[Paper]:
    query = _build_query(terms, since, until)
    cursor = "*"
    seen_cursors = set()
    while True:
        params = {
            "query": query, "format": "json", "pageSize": str(_PAGE),
            "cursorMark": cursor, "resultType": "core",
        }
        data = get_json(client, BASE, params)
        for rec in data.get("resultList", {}).get("result", []):
            yield _parse(rec, pathology)
        nxt = data.get("nextCursorMark")
        if not nxt or nxt == cursor or nxt in seen_cursors:
            break
        seen_cursors.add(cursor)
        cursor = nxt
        time.sleep(0.2)
