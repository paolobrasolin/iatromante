"""Build a queryable SQLite + FTS5 index from data/corpus.jsonl.

The JSONL file is the source of truth (committed to git); this index is a
derived, rebuildable artifact (git-ignored) for fast full-text search.
"""

from __future__ import annotations

import json
import sqlite3

from .store import CORPUS_PATH, DATA_DIR

INDEX_PATH = DATA_DIR / "index.sqlite"


def build() -> int:
    if INDEX_PATH.exists():
        INDEX_PATH.unlink()
    con = sqlite3.connect(INDEX_PATH)
    con.executescript(
        """
        CREATE TABLE papers (
            id TEXT PRIMARY KEY, title TEXT, abstract TEXT, doi TEXT, pmid TEXT,
            venue TEXT, pub_date TEXT, year INTEGER, type TEXT, url TEXT,
            is_oa INTEGER, pathologies TEXT, sources TEXT
        );
        CREATE VIRTUAL TABLE papers_fts USING fts5(
            title, abstract, content='papers', content_rowid='rowid'
        );
        """
    )
    n = 0
    if CORPUS_PATH.exists():
        with CORPUS_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                p = json.loads(line)
                con.execute(
                    "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (p["id"], p["title"], p["abstract"], p.get("doi"), p.get("pmid"),
                     p.get("venue"), p.get("pub_date"), p.get("year"), p.get("type"),
                     p.get("url"), int(p.get("is_oa", False)),
                     ",".join(p.get("pathologies", [])), ",".join(p.get("sources", []))),
                )
                n += 1
    con.execute(
        "INSERT INTO papers_fts(rowid, title, abstract) "
        "SELECT rowid, title, abstract FROM papers"
    )
    con.commit()
    con.close()
    return n


def search(query: str, limit: int = 20) -> list[dict]:
    if not INDEX_PATH.exists():
        raise FileNotFoundError("index missing -- run `feed index` first")
    con = sqlite3.connect(INDEX_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT p.id, p.title, p.year, p.type, p.url, p.pathologies,
               snippet(papers_fts, 1, '[', ']', ' ... ', 12) AS snip
        FROM papers_fts JOIN papers p ON p.rowid = papers_fts.rowid
        WHERE papers_fts MATCH ?
        ORDER BY rank LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]
