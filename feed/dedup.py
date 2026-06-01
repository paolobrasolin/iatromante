"""Merge two records that refer to the same paper."""

from __future__ import annotations

from .models import Paper


def _prefer(a: str, b: str) -> str:
    return a if a else b


def merge(base: Paper, other: Paper) -> Paper:
    """Fold `other` into `base` in place, keeping the richest field from each."""
    base.title = _prefer(base.title, other.title)
    # keep the longer abstract -- structured PubMed abstracts beat truncated ones
    if len(other.abstract) > len(base.abstract):
        base.abstract = other.abstract
    base.doi = _prefer(base.doi or "", other.doi or "") or None
    base.pmid = _prefer(base.pmid or "", other.pmid or "") or None
    base.pmcid = _prefer(base.pmcid or "", other.pmcid or "") or None
    if not base.authors:
        base.authors = other.authors
    base.venue = _prefer(base.venue, other.venue)
    base.pub_date = _prefer(base.pub_date, other.pub_date)
    base.year = base.year or other.year
    base.url = _prefer(base.url, other.url)
    base.full_text_url = _prefer(base.full_text_url, other.full_text_url)
    base.is_oa = base.is_oa or other.is_oa
    base.mesh = sorted(set(base.mesh) | set(other.mesh))
    base.keywords = sorted(set(base.keywords) | set(other.keywords))
    base.pathologies = sorted(set(base.pathologies) | set(other.pathologies))
    base.sources = sorted(set(base.sources) | set(other.sources))
    base.source_ids.update(other.source_ids)
    if base.fetched_at and other.fetched_at:
        base.fetched_at = max(base.fetched_at, other.fetched_at)
    else:
        base.fetched_at = base.fetched_at or other.fetched_at
    # a real publication supersedes a preprint/trial placeholder
    if base.type == "article" and other.type != "article":
        pass
    elif base.type != "article" and other.type == "article":
        base.type = "article"
    return base
