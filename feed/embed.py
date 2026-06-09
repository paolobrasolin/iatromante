"""Local semantic embeddings + vector store ("deep search").

Embeddings are computed on-device with fastembed (ONNX, CPU-friendly) -- nothing
leaves the machine. Vectors and just-enough display metadata live together in a
sqlite-vec database (data/vectors.sqlite), separate from the FTS index so that
rebuilding the keyword index never discards the expensive embeddings.

The store is keyed by paper id and is resumable: re-running only embeds papers
not already present.
"""

from __future__ import annotations

import json
import sqlite3

import sqlite_vec

from .store import CORPUS_PATH, DATA_DIR

VECTORS_PATH = DATA_DIR / "vectors.sqlite"
MODEL_NAME = "BAAI/bge-small-en-v1.5"   # 384-dim, fast; swap for a biomedical model later
DIM = 384
# bge-v1.5 retrieval convention: prefix queries (not documents) with an instruction
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
MIN_ABSTRACT = 100


_MODEL = None


def _model():
    """Lazily load and cache the embedding model (load once, reuse — e.g. a server)."""
    global _MODEL
    if _MODEL is None:
        from fastembed import TextEmbedding
        _MODEL = TextEmbedding(model_name=MODEL_NAME)
    return _MODEL


def _connect() -> sqlite3.Connection:
    db = sqlite3.connect(VECTORS_PATH)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_papers USING vec0(
            paper_id TEXT PRIMARY KEY,
            embedding float[{DIM}],
            +title TEXT,
            +year INTEGER,
            +type TEXT,
            +url TEXT,
            +pathologies TEXT
        )
        """
    )
    return db


def _doc_text(p: dict) -> str:
    return f"{p.get('title', '')}\n\n{p.get('abstract', '')}".strip()


def build(limit: int | None = None, batch_size: int = 256) -> dict:
    db = _connect()
    existing = {r[0] for r in db.execute("SELECT paper_id FROM vec_papers")}

    pending: list[dict] = []
    with CORPUS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            if len(p.get("abstract", "")) < MIN_ABSTRACT:
                continue
            if p["id"] in existing:
                continue
            pending.append(p)
            if limit and len(pending) >= limit:
                break

    stats = {"already": len(existing), "to_embed": len(pending), "embedded": 0}
    if not pending:
        db.close()
        return stats

    model = _model()
    buf_meta: list[dict] = []
    buf_text: list[str] = []

    def flush():
        if not buf_text:
            return
        vecs = list(model.embed(buf_text, batch_size=batch_size))
        rows = []
        for p, v in zip(buf_meta, vecs):
            rows.append((
                p["id"], sqlite_vec.serialize_float32(v.tolist()),
                p.get("title", ""), p.get("year"), p.get("type", ""),
                p.get("url", ""), ",".join(p.get("pathologies", [])),
            ))
        db.executemany(
            "INSERT OR REPLACE INTO vec_papers"
            "(paper_id, embedding, title, year, type, url, pathologies)"
            " VALUES (?,?,?,?,?,?,?)", rows)
        db.commit()
        stats["embedded"] += len(rows)
        buf_meta.clear()
        buf_text.clear()
        print(f"  ... {stats['embedded']}/{stats['to_embed']} embedded", flush=True)

    for p in pending:
        buf_meta.append(p)
        buf_text.append(_doc_text(p))
        if len(buf_text) >= 2000:
            flush()
    flush()
    db.close()
    return stats


def search(query: str, k: int = 20, pathology: str | None = None) -> list[dict]:
    if not VECTORS_PATH.exists():
        raise FileNotFoundError("no vector store -- run `feed embed` first")
    qvec = next(iter(_model().embed([QUERY_PREFIX + query]))).tolist()

    db = _connect()
    # over-fetch when filtering by pathology, since KNN can't pre-filter aux columns
    knn = k * 5 if pathology else k
    rows = db.execute(
        """
        SELECT paper_id, title, year, type, url, pathologies, distance
        FROM vec_papers
        WHERE embedding MATCH ? AND k = ?
        ORDER BY distance
        """,
        (sqlite_vec.serialize_float32(qvec), knn),
    ).fetchall()
    db.close()

    out = []
    for pid, title, year, typ, url, paths, dist in rows:
        if pathology and pathology not in (paths or "").split(","):
            continue
        out.append({"id": pid, "title": title, "year": year, "type": typ,
                    "url": url, "pathologies": paths, "score": round(1 - dist, 3)})
        if len(out) >= k:
            break
    return out
