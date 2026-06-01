"""Shared HTTP helpers for source adapters."""

from __future__ import annotations

import json as _json
import os
import time
import urllib.parse
import urllib.request

import httpx

CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def make_client() -> httpx.Client:
    ua = "iatromante/0.1 (biomedical literature archive)"
    if CONTACT_EMAIL:
        ua += f"; mailto:{CONTACT_EMAIL}"
    return httpx.Client(headers={"User-Agent": ua}, follow_redirects=True,
                        timeout=httpx.Timeout(120.0))


def month_num(m: str) -> int:
    m = (m or "").strip()
    if not m:
        return 1
    if m.isdigit():
        return max(1, min(12, int(m)))
    return _MONTHS.get(m[:3].lower(), 1)


def get_json(client: httpx.Client, url: str, params: dict, *, retries: int = 4) -> dict:
    """GET with exponential backoff on 429/5xx."""
    delay = 1.0
    for attempt in range(retries):
        try:
            r = client.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPStatusError, httpx.TransportError):
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    return {}


def get_json_stdlib(url: str, params: dict, *, retries: int = 4) -> dict:
    """GET via stdlib urllib -- used for hosts (e.g. ClinicalTrials.gov) whose
    bot-protection rejects httpx's TLS fingerprint but accepts the system stack."""
    full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    delay = 1.0
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                full, headers={"User-Agent": "iatromante/0.1", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return _json.loads(resp.read())
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    return {}


def get_bytes(client: httpx.Client, url: str, params: dict, *, retries: int = 4) -> bytes:
    delay = 1.0
    for attempt in range(retries):
        try:
            r = client.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
            r.raise_for_status()
            return r.content
        except (httpx.HTTPStatusError, httpx.TransportError):
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay *= 2
    return b""
