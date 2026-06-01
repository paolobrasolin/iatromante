"""Fetch open-access full text for papers that have a PMC id.

Uses NCBI efetch (db=pmc), the same E-utilities service as the PubMed source, so
rate limits are shared and an NCBI_API_KEY raises the ceiling to 10 req/s.

Full text is stored *decoupled* from data/corpus.jsonl: one text file per paper
under data/fulltext/, plus a manifest mapping paper id -> file. This keeps the
corpus lean and avoids racing the fetch pipeline's rewrite of corpus.jsonl.
Only the open-access subset is retrievable; paywalled papers keep their abstract.
"""

from __future__ import annotations

import json
import re
import time
from xml.etree import ElementTree as ET

import httpx

from .sources.base import NCBI_API_KEY
from .store import CORPUS_PATH, DATA_DIR

FULLTEXT_DIR = DATA_DIR / "fulltext"
MANIFEST_PATH = FULLTEXT_DIR / "manifest.json"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_SPACING = 0.11 if NCBI_API_KEY else 0.34


def _safe(pid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", pid)


def _jats_to_text(xml: bytes) -> tuple[str, int]:
    """Return (readable_text, body_char_count). body_char_count==0 => no full body."""
    root = ET.fromstring(xml)
    out: list[str] = []

    title = root.find(".//front//article-title")
    if title is not None:
        out.append("# " + "".join(title.itertext()).strip())

    abstract = root.find(".//front//abstract")
    if abstract is not None:
        out.append("## Abstract\n" + " ".join("".join(abstract.itertext()).split()))

    body = root.find(".//body")
    body_chars = 0
    if body is not None:
        out.append("## Full text")
        for el in body.iter():
            if el.tag == "title":
                txt = " ".join("".join(el.itertext()).split())
                if txt:
                    out.append("\n### " + txt)
            elif el.tag == "p":
                txt = " ".join("".join(el.itertext()).split())
                if txt:
                    out.append(txt)
                    body_chars += len(txt)
    return "\n\n".join(out), body_chars


def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


def fetch_all(pathology: str | None = None, limit: int | None = None,
              fetched_at: str = "") -> dict:
    FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()

    targets = []
    with CORPUS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            if not p.get("pmcid"):
                continue
            if pathology and pathology not in p.get("pathologies", []):
                continue
            if p["id"] in manifest:          # already attempted
                continue
            targets.append((p["id"], p["pmcid"]))
    if limit:
        targets = targets[:limit]

    stats = {"attempted": 0, "with_body": 0, "abstract_only": 0, "failed": 0}
    client = httpx.Client(timeout=120)
    try:
        for pid, pmcid in targets:
            stats["attempted"] += 1
            params = {"db": "pmc", "id": pmcid.replace("PMC", ""), "retmode": "xml"}
            if NCBI_API_KEY:
                params["api_key"] = NCBI_API_KEY
            try:
                r = client.get(EFETCH, params=params)
                if r.status_code == 429:
                    time.sleep(2.0)
                    r = client.get(EFETCH, params=params)
                r.raise_for_status()
                text, body_chars = _jats_to_text(r.content)
            except Exception as exc:
                stats["failed"] += 1
                print(f"  !! {pmcid}: {exc}")
                time.sleep(_SPACING)
                continue

            rel = f"fulltext/{_safe(pid)}.txt"
            (DATA_DIR / rel).write_text(text, encoding="utf-8")
            manifest[pid] = {"pmcid": pmcid, "path": rel, "body_chars": body_chars,
                             "fetched_at": fetched_at}
            if body_chars > 0:
                stats["with_body"] += 1
            else:
                stats["abstract_only"] += 1
            if stats["attempted"] % 25 == 0:
                MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                         encoding="utf-8")
                print(f"  ... {stats['attempted']}/{len(targets)} "
                      f"({stats['with_body']} with full body)")
            time.sleep(_SPACING)
    finally:
        client.close()
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                 encoding="utf-8")
    return stats
