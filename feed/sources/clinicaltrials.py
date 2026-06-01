"""ClinicalTrials.gov API v2.

Tracks interventional and observational studies (not publications) for each
condition. Incremental on LastUpdatePostDate so re-runs pick up status changes.
"""

from __future__ import annotations

import time
from typing import Iterator

from ..models import Paper, canonical_id
from .base import get_json_stdlib

BASE = "https://clinicaltrials.gov/api/v2/studies"
_PAGE = 100


def _parse(study: dict, pathology: str) -> Paper:
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    nct = ident.get("nctId", "")
    title = ident.get("officialTitle") or ident.get("briefTitle", "") or ""
    summary = ps.get("descriptionModule", {}).get("briefSummary", "") or ""
    status = ps.get("statusModule", {})
    start = (status.get("startDateStruct", {}) or {}).get("date", "")
    conditions = ps.get("conditionsModule", {}).get("conditions", [])
    sponsor = ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", "")

    year = None
    if start[:4].isdigit():
        year = int(start[:4])
    pub_date = start if len(start) == 10 else (f"{start}-01" if len(start) == 7 else start)

    cid = canonical_id(None, None, "clinicaltrials", nct, nct or title)
    return Paper(
        id=cid, title=title, abstract=summary, venue=sponsor,
        pub_date=pub_date, year=year, type="clinical_trial",
        url=f"https://clinicaltrials.gov/study/{nct}" if nct else "",
        keywords=conditions, pathologies=[pathology],
        sources=["clinicaltrials"], source_ids={"clinicaltrials": nct},
    )


def fetch(client, pathology, terms, mesh, since, until, **_) -> Iterator[Paper]:
    seen: set[str] = set()
    for term in terms:
        token = None
        while True:
            params = {
                "query.cond": term,
                "filter.advanced": f"AREA[LastUpdatePostDate]RANGE[{since},{until}]",
                "pageSize": str(_PAGE), "countTotal": "false",
            }
            if token:
                params["pageToken"] = token
            data = get_json_stdlib(BASE, params)
            for study in data.get("studies", []):
                nct = study.get("protocolSection", {}).get(
                    "identificationModule", {}).get("nctId", "")
                if nct and nct in seen:
                    continue
                if nct:
                    seen.add(nct)
                yield _parse(study, pathology)
            token = data.get("nextPageToken")
            if not token:
                break
            time.sleep(0.2)
