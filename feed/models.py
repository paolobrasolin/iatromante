"""Canonical paper record shared by every source."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Optional

_NONALNUM = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")
_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/",
                 "http://dx.doi.org/", "doi.org/", "doi:")


def clean_doi(raw: Optional[str]) -> Optional[str]:
    """Normalize a DOI to bare ``10.xxxx/...`` form, or None if it isn't a valid DOI.

    Strips URL/``doi:`` prefixes and stray leading slashes, lowercases (DOIs are
    case-insensitive). Upstream sources occasionally emit non-DOI identifiers
    (SciELO PIDs, journal-internal ids); those return None so links can fall back.
    """
    if not raw:
        return None
    d = raw.strip()
    low = d.lower()
    for pre in _DOI_PREFIXES:
        if low.startswith(pre):
            d = d[len(pre):]
            break
    d = d.strip().lstrip("/").strip().lower()
    return d if _DOI_RE.match(d) else None


def norm_title(title: str) -> str:
    """Lowercase, strip punctuation/whitespace -- for fuzzy title matching."""
    t = _NONALNUM.sub(" ", (title or "").lower())
    return _WS.sub(" ", t).strip()


def canonical_id(doi: Optional[str], pmid: Optional[str], source: str,
                 source_id: Optional[str], title: str) -> str:
    """Stable identity for a paper, preferring the most authoritative key."""
    if doi:
        return "doi:" + doi.lower().strip()
    if pmid:
        return "pmid:" + str(pmid).strip()
    nt = norm_title(title)
    if nt:
        return "title:" + hashlib.sha1(nt.encode()).hexdigest()[:16]
    return f"{source}:{source_id}"


@dataclass
class Paper:
    id: str
    title: str = ""
    abstract: str = ""
    doi: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    authors: list = field(default_factory=list)
    venue: str = ""
    pub_date: str = ""            # ISO "YYYY-MM-DD", or "YYYY" when only the year is known
    year: Optional[int] = None
    type: str = "article"         # article | preprint | clinical_trial
    url: str = ""
    full_text_url: str = ""
    is_oa: bool = False           # open access
    mesh: list = field(default_factory=list)
    keywords: list = field(default_factory=list)
    pathologies: list = field(default_factory=list)   # which configured diseases matched
    sources: list = field(default_factory=list)       # which providers supplied this record
    source_ids: dict = field(default_factory=dict)     # provider -> native id
    fetched_at: str = ""

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "Paper":
        return cls(**d)
