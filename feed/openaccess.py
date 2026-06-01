"""Find legal open-access copies of paywalled papers via Unpaywall.

Unpaywall (by the OurResearch nonprofit, same people as OpenAlex) maps a DOI to
the best *legitimate* open-access location -- author manuscripts, repository
deposits, publisher OA -- that a paywall often hides. Free API, requires a
contact email.

We resolve papers that have a DOI but no PMC full text yet, and record the legal
OA location (landing URL + PDF URL + license) in data/openaccess/manifest.json.
This stays decoupled from corpus.jsonl, like the full-text store.
"""

from __future__ import annotations

import json
import time

import httpx

from .fulltext import MANIFEST_PATH as FULLTEXT_MANIFEST
from .sources.base import CONTACT_EMAIL
from .store import CORPUS_PATH, DATA_DIR

OA_DIR = DATA_DIR / "openaccess"
MANIFEST_PATH = OA_DIR / "manifest.json"
API = "https://api.unpaywall.org/v2/"


def _load(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def resolve(pathology: str | None = None, limit: int | None = None) -> dict:
    if not CONTACT_EMAIL:
        raise SystemExit("Unpaywall requires a contact email -- set CONTACT_EMAIL in .env")

    OA_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _load(MANIFEST_PATH)
    have_fulltext = set(_load(FULLTEXT_MANIFEST).keys())

    targets = []
    with CORPUS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            if not p.get("doi"):
                continue
            if pathology and pathology not in p.get("pathologies", []):
                continue
            if p["id"] in manifest or p["id"] in have_fulltext:
                continue  # already resolved, or we already have its full text from PMC
            targets.append((p["id"], p["doi"]))
    if limit:
        targets = targets[:limit]

    stats = {"checked": 0, "oa_found": 0, "no_oa": 0, "not_indexed": 0, "failed": 0}
    by_host: dict[str, int] = {}
    client = httpx.Client(timeout=60)
    try:
        for pid, doi in targets:
            stats["checked"] += 1
            try:
                r = client.get(API + doi, params={"email": CONTACT_EMAIL})
                if r.status_code == 404:
                    stats["not_indexed"] += 1
                    manifest[pid] = {"doi": doi, "is_oa": False, "status": "not_in_unpaywall"}
                    time.sleep(0.1)
                    continue
                r.raise_for_status()
                d = r.json()
            except Exception as exc:
                stats["failed"] += 1
                print(f"  !! {doi}: {exc}")
                time.sleep(0.3)
                continue

            loc = d.get("best_oa_location") or {}
            entry = {"doi": doi, "is_oa": bool(d.get("is_oa")),
                     "oa_status": d.get("oa_status")}
            if d.get("is_oa") and loc:
                host = loc.get("host_type") or "unknown"
                by_host[host] = by_host.get(host, 0) + 1
                entry.update({
                    "oa_url": loc.get("url"),
                    "pdf_url": loc.get("url_for_pdf"),
                    "host_type": host,
                    "version": loc.get("version"),
                    "license": loc.get("license"),
                })
                stats["oa_found"] += 1
            else:
                stats["no_oa"] += 1
            manifest[pid] = entry

            if stats["checked"] % 25 == 0:
                MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                         encoding="utf-8")
                print(f"  ... {stats['checked']}/{len(targets)} "
                      f"({stats['oa_found']} legal OA copies found)")
            time.sleep(0.1)
    finally:
        client.close()
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                 encoding="utf-8")
    stats["by_host"] = by_host
    return stats
