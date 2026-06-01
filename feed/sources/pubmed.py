"""PubMed / MEDLINE via NCBI E-utilities (esearch + efetch).

The authoritative source for peer-reviewed biomedical literature: structured
abstracts, author lists, and MeSH controlled-vocabulary terms.
"""

from __future__ import annotations

import time
from typing import Iterator
from xml.etree import ElementTree as ET

from ..models import Paper, canonical_id
from .base import NCBI_API_KEY, get_bytes, get_json, month_num

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
# anonymous: 3 req/s -> 0.34s spacing; with key: 10 req/s -> 0.11s
_SPACING = 0.11 if NCBI_API_KEY else 0.34
_PAGE = 200


def _build_query(terms: list[str], mesh: list[str]) -> str:
    parts = [f'"{t}"[tiab]' if " " in t else f"{t}[tiab]" for t in terms]
    parts += [f'"{m}"[MeSH Terms]' for m in mesh]
    return "(" + " OR ".join(parts) + ")"


def _auth(params: dict) -> dict:
    params["tool"] = "iatromante"
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    return params


def _search(client, query: str, since: str, until: str) -> list[str]:
    pmids: list[str] = []
    retstart = 0
    while True:
        params = _auth({
            "db": "pubmed", "term": query, "retmode": "json",
            "retmax": str(_PAGE), "retstart": str(retstart),
            "datetype": "edat", "mindate": since.replace("-", "/"),
            "maxdate": until.replace("-", "/"),
        })
        res = get_json(client, f"{EUTILS}/esearch.fcgi", params)["esearchresult"]
        ids = res.get("idlist", [])
        pmids.extend(ids)
        total = int(res.get("count", "0"))
        retstart += _PAGE
        time.sleep(_SPACING)
        if retstart >= total or not ids:
            break
    return pmids


def _text(el) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _parse_article(art) -> Paper:
    medline = art.find("MedlineCitation")
    pmid = _text(medline.find("PMID")) if medline is not None else ""
    article = medline.find("Article") if medline is not None else None
    title = _text(article.find("ArticleTitle")) if article is not None else ""

    abstract = ""
    if article is not None:
        abs_el = article.find("Abstract")
        if abs_el is not None:
            chunks = []
            for at in abs_el.findall("AbstractText"):
                label = at.get("Label")
                txt = _text(at)
                if txt:
                    chunks.append(f"{label}: {txt}" if label else txt)
            abstract = "\n".join(chunks)

    authors = []
    if article is not None:
        for a in article.findall(".//Author"):
            name = f"{_text(a.find('ForeName'))} {_text(a.find('LastName'))}".strip()
            name = name or _text(a.find("CollectiveName"))
            if name:
                authors.append(name)

    journal = _text(article.find(".//Journal/Title")) if article is not None else ""

    doi = pmcid = None
    for aid in art.findall(".//ArticleIdList/ArticleId"):
        kind = aid.get("IdType")
        if kind == "doi":
            doi = _text(aid)
        elif kind == "pmc":
            pmcid = _text(aid)

    year = None
    pub_date = ""
    ad = article.find(".//ArticleDate") if article is not None else None
    if ad is not None and _text(ad.find("Year")):
        y = int(_text(ad.find("Year")))
        m = month_num(_text(ad.find("Month")))
        d = _text(ad.find("Day"))
        d = int(d) if d.isdigit() else 1
        year, pub_date = y, f"{y:04d}-{m:02d}-{d:02d}"
    if not pub_date:
        pd = article.find(".//Journal/JournalIssue/PubDate") if article is not None else None
        if pd is not None and _text(pd.find("Year")):
            y = int(_text(pd.find("Year")))
            m = month_num(_text(pd.find("Month")))
            year, pub_date = y, f"{y:04d}-{m:02d}-01"

    mesh = [_text(m.find("DescriptorName")) for m in medline.findall(".//MeshHeading")] \
        if medline is not None else []
    keywords = [_text(k) for k in medline.findall(".//KeywordList/Keyword")] \
        if medline is not None else []

    cid = canonical_id(doi, pmid, "pubmed", pmid, title)
    return Paper(
        id=cid, title=title, abstract=abstract, doi=doi, pmid=pmid or None,
        pmcid=pmcid, authors=authors, venue=journal, pub_date=pub_date, year=year,
        type="article",
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        mesh=[m for m in mesh if m], keywords=[k for k in keywords if k],
        sources=["pubmed"], source_ids={"pubmed": pmid},
    )


def fetch(client, pathology, terms, mesh, since, until, **_) -> Iterator[Paper]:
    query = _build_query(terms, mesh)
    pmids = _search(client, query, since, until)
    for i in range(0, len(pmids), _PAGE):
        batch = pmids[i:i + _PAGE]
        params = _auth({"db": "pubmed", "id": ",".join(batch), "retmode": "xml"})
        raw = get_bytes(client, f"{EUTILS}/efetch.fcgi", params)
        if not raw:
            continue
        root = ET.fromstring(raw)
        for art in root.findall(".//PubmedArticle"):
            p = _parse_article(art)
            p.pathologies = [pathology]
            yield p
        time.sleep(_SPACING)
