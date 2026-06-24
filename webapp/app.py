"""FastAPI backend for the iatromante corpus.

Reads the derived artifacts built by the `feed` pipeline:
  data/index.sqlite    -- FTS5 keyword search + paper metadata/abstracts
  data/vectors.sqlite  -- embeddings (semantic search) + map coords + clusters

Serves a small single-page UI (Latest / Search / Map). Latest is a
reverse-chronological feed of the newest papers; Search offers both
keyword (FTS5) and semantic (embedding) modes over the same corpus.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from feed import embed as embed_mod
from feed.index import INDEX_PATH

STATIC = Path(__file__).resolve().parent / "static"
VECTORS_PATH = embed_mod.VECTORS_PATH
PATHOLOGIES = ["endometriosis", "lipedema", "fibromyalgia"]
PMASK = {"endometriosis": 1, "lipedema": 2, "fibromyalgia": 4}  # bitmask for the map
TYPE_CODE = {"article": 1, "preprint": 2, "clinical_trial": 3}  # compact type code for map points


def _mask(pathologies: str) -> int:
    m = 0
    for p in (pathologies or "").split(","):
        m |= PMASK.get(p, 0)
    return m

app = FastAPI(title="iatromante")


# ---- db helpers ---------------------------------------------------------
def _index_db() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{INDEX_PATH}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _vectors_db() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{VECTORS_PATH}?mode=ro", uri=True, check_same_thread=False)
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    con.enable_load_extension(False)
    con.row_factory = sqlite3.Row
    return con


def _card(row: sqlite3.Row, score: float | None = None, snippet: str | None = None) -> dict:
    authors = (row["authors"] or "").split("; ")
    author_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
    abstract = row["abstract"] or ""
    return {
        "id": row["id"], "title": row["title"] or "(untitled)",
        "authors": author_str, "venue": row["venue"] or "",
        "year": row["year"], "pub_date": row["pub_date"] or "",
        "type": row["type"], "url": row["url"] or "",
        "pathologies": [p for p in (row["pathologies"] or "").split(",") if p],
        "is_oa": bool(row["is_oa"]),
        "snippet": snippet or (abstract[:280] + ("…" if len(abstract) > 280 else "")),
        "score": score,
    }


def _meta_for(con: sqlite3.Connection, ids: list[str]) -> dict[str, sqlite3.Row]:
    if not ids:
        return {}
    q = "SELECT * FROM papers WHERE id IN (%s)" % ",".join("?" * len(ids))
    return {r["id"]: r for r in con.execute(q, ids)}


# ---- API ----------------------------------------------------------------
@app.get("/api/meta")
def api_meta():
    con = _index_db()
    total = con.execute("SELECT count(*) FROM papers").fetchone()[0]
    con.close()
    return {"total": total, "pathologies": PATHOLOGIES}


@app.get("/api/search")
def api_search(q: str = Query(...), mode: str = "semantic",
               pathology: str | None = None, limit: int = 30):
    q = q.strip()
    if not q:
        return {"mode": mode, "results": []}
    con = _index_db()
    try:
        if mode == "semantic":
            hits = embed_mod.search(q, k=limit, pathology=pathology)
            meta = _meta_for(con, [h["id"] for h in hits])
            results = [_card(meta[h["id"]], score=h["score"])
                       for h in hits if h["id"] in meta]
        else:
            where = "papers_fts MATCH ?"
            params: list = [q]
            if pathology:
                where += " AND p.pathologies LIKE '%'||?||'%'"
                params.append(pathology)
            params.append(limit)
            rows = con.execute(
                f"""SELECT p.*, snippet(papers_fts, 1, '<b>', '</b>', '…', 14) AS snip
                    FROM papers_fts JOIN papers p ON p.rowid = papers_fts.rowid
                    WHERE {where} ORDER BY rank LIMIT ?""", params).fetchall()
            results = [_card(r, snippet=r["snip"]) for r in rows]
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        con.close()
    return {"mode": mode, "results": results}


@app.get("/api/latest")
def api_latest(limit: int = 30, offset: int = 0, pathology: str | None = None,
               type: str | None = Query(None), oa: bool = False):
    """Reverse-chronological feed of the newest papers (by publication date)."""
    con = _index_db()
    clauses = ["pub_date <> ''"]
    params: list = []
    if pathology:
        clauses.append("pathologies LIKE '%'||?||'%'")
        params.append(pathology)
    if type:
        clauses.append("type = ?")
        params.append(type)
    if oa:
        clauses.append("is_oa = 1")
    params += [limit, offset]
    rows = con.execute(
        f"""SELECT * FROM papers WHERE {' AND '.join(clauses)}
            ORDER BY pub_date DESC, rowid DESC LIMIT ? OFFSET ?""", params).fetchall()
    con.close()
    return {"results": [_card(r) for r in rows]}


@app.get("/api/paper/{paper_id:path}")
def api_paper(paper_id: str):
    con = _index_db()
    row = con.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    con.close()
    if not row:
        return JSONResponse({"error": "not found"}, status_code=404)
    vcon = _vectors_db()
    cl = vcon.execute(
        """SELECT c.cluster, c.label FROM paper_map m JOIN clusters c
           ON c.cluster = m.cluster WHERE m.paper_id = ?""", (paper_id,)).fetchone()
    vcon.close()
    authors = (row["authors"] or "").split("; ")
    return {
        "id": row["id"], "title": row["title"], "abstract": row["abstract"] or "",
        "authors": [a for a in authors if a], "venue": row["venue"] or "",
        "year": row["year"], "type": row["type"], "doi": row["doi"],
        "url": row["url"] or "", "full_text_url": row["full_text_url"] or "",
        "is_oa": bool(row["is_oa"]),
        "pathologies": [p for p in (row["pathologies"] or "").split(",") if p],
        "sources": [s for s in (row["sources"] or "").split(",") if s],
        "cluster": cl["cluster"] if cl else None,
        "cluster_label": cl["label"] if cl else None,
    }


@app.get("/api/clusters")
def api_clusters():
    con = _vectors_db()
    clusters = con.execute(
        "SELECT cluster, label, size, pathology_mix, parent, level FROM clusters").fetchall()
    macro_c = {r["macro"]: (r["cx"], r["cy"]) for r in con.execute(
        "SELECT macro, avg(x) AS cx, avg(y) AS cy FROM paper_map GROUP BY macro")}
    sub_c = {r["cluster"]: (r["cx"], r["cy"]) for r in con.execute(
        "SELECT cluster, avg(x) AS cx, avg(y) AS cy FROM paper_map GROUP BY cluster")}
    con.close()

    macros, subs = {}, []
    for r in clusters:
        if r["level"] == 1:
            cx, cy = macro_c.get(r["cluster"], (0, 0))
            macros[r["cluster"]] = {"cluster": r["cluster"], "label": r["label"],
                                    "size": r["size"], "mix": r["pathology_mix"],
                                    "cx": cx, "cy": cy, "subs": []}
        else:
            cx, cy = sub_c.get(r["cluster"], (0, 0))
            subs.append((r["parent"], {"cluster": r["cluster"], "label": r["label"],
                                       "size": r["size"], "mix": r["pathology_mix"],
                                       "cx": cx, "cy": cy}))
    for parent, s in subs:
        if parent in macros:
            macros[parent]["subs"].append(s)
    out = sorted(macros.values(), key=lambda m: -m["size"])
    for m in out:
        m["subs"].sort(key=lambda s: -s["size"])
    return {"macros": out}


@app.get("/api/map")
def api_map(pathology: str | None = None):
    # All embedded papers, each as [x, y, cluster, year]. The client renders via a
    # pixel buffer (fast enough for the full set) and filters by year live.
    con = _vectors_db()
    con.execute("ATTACH DATABASE ? AS idx", (f"file:{INDEX_PATH}?mode=ro",))
    where = ""
    params: list = []
    if pathology:
        where = "WHERE p.pathologies LIKE '%'||?||'%'"
        params.append(pathology)
    rows = con.execute(
        f"""SELECT m.x, m.y, m.macro, m.cluster, p.year, p.pathologies, p.is_oa, p.type FROM paper_map m
            JOIN idx.papers p ON p.id = m.paper_id {where}""", params).fetchall()
    con.close()
    # [x, y, macro, sub, year, pmask, is_oa, type_code]
    points = [[round(r["x"], 2), round(r["y"], 2), r["macro"], r["cluster"], r["year"] or 0,
               _mask(r["pathologies"]), int(r["is_oa"] or 0), TYPE_CODE.get(r["type"], 0)] for r in rows]
    return {"points": points}


@app.get("/api/map/at")
def api_map_at(x: float, y: float):
    """Nearest paper to a map coordinate (for click-to-open)."""
    con = _vectors_db()
    row = con.execute(
        "SELECT paper_id FROM paper_map ORDER BY (x-?)*(x-?)+(y-?)*(y-?) LIMIT 1",
        (x, x, y, y)).fetchone()
    con.close()
    return {"id": row["paper_id"] if row else None}


@app.get("/")
def root():
    return FileResponse(STATIC / "index.html")


app.mount("/", StaticFiles(directory=STATIC), name="static")
