"""Hierarchical topic clustering + 2D map projection over the embeddings.

Two levels:
  macro  -- a handful of broad themes (KMeans on a 5D UMAP): full coverage, the
            map's colors, the early "big topics" view.
  sub    -- within each macro, HDBSCAN finds specific sub-topics; orphan points
            are folded into the nearest sub, so there is no "unclustered" grey.

Each level is labelled with its most distinctive title terms (class-based TF-IDF).
A 2D UMAP (separate from the 5D used for clustering) gives the map coordinates.

Companion tables in data/vectors.sqlite:
  paper_map(paper_id, x, y, cluster, macro)         cluster = leaf/sub id
  clusters(cluster, label, size, pathology_mix, parent, level)
      macro rows: level=1, parent=NULL ; sub rows: level=2, parent=<macro id>
"""

from __future__ import annotations

import sqlite3
from collections import Counter

import numpy as np
import sqlite_vec

from .embed import DIM, VECTORS_PATH

SUB_BASE = 1000  # sub-cluster ids start here so they never collide with macro ids


def _load(sample: int | None = None):
    db = sqlite3.connect(VECTORS_PATH)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    rows = db.execute("SELECT paper_id, embedding, title, pathologies FROM vec_papers").fetchall()
    db.close()
    if sample:
        rows = rows[:sample]
    ids = [r[0] for r in rows]
    vecs = np.frombuffer(b"".join(r[1] for r in rows), dtype="<f4").reshape(len(rows), DIM)
    titles = [r[2] or "" for r in rows]
    paths = [r[3] or "" for r in rows]
    return ids, np.ascontiguousarray(vecs), titles, paths


def _label_clusters(titles: list[str], labels) -> dict[int, str]:
    """Class-based TF-IDF label per cluster id present in `labels`."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    uniq = sorted({int(c) for c in labels})
    pos = {c: i for i, c in enumerate(uniq)}
    docs = [""] * len(uniq)
    for t, c in zip(titles, labels):
        docs[pos[int(c)]] += " " + t
    out: dict[int, str] = {}
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=8000, min_df=1)
    mat = vec.fit_transform(docs)
    terms = vec.get_feature_names_out()
    for c, i in pos.items():
        row = mat[i].toarray().ravel()
        top = [terms[j] for j in row.argsort()[::-1][:5] if row[j] > 0]
        out[c] = ", ".join(top) if top else f"cluster {c}"
    return out


def _assign_orphans(labels: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Fold HDBSCAN noise (-1) into the nearest real cluster via kNN."""
    noise = labels < 0
    if noise.all():
        return np.zeros(len(labels), dtype=int)
    if noise.any():
        from sklearn.neighbors import KNeighborsClassifier
        clf = KNeighborsClassifier(n_neighbors=15).fit(X[~noise], labels[~noise])
        labels = labels.copy()
        labels[noise] = clf.predict(X[noise])
    return labels


def _pathology_mix(assignment, paths) -> dict[int, Counter]:
    mix: dict[int, Counter] = {}
    for c, pth in zip(assignment, paths):
        m = mix.setdefault(int(c), Counter())
        for p in pth.split(","):
            if p:
                m[p] += 1
    return mix


def build(macro_k: int = 12, sub_min: int = 300, min_samples: int = 5,
          cluster_dim: int = 5, sample: int | None = None) -> dict:
    import hdbscan
    from sklearn.cluster import KMeans
    from umap import UMAP

    ids, vecs, titles, paths = _load(sample)
    n = len(ids)
    print(f"loaded {n} vectors; projecting to 2D (map) ...", flush=True)
    coords = UMAP(n_components=2, metric="cosine", n_neighbors=15,
                  min_dist=0.1, low_memory=True, verbose=False).fit_transform(vecs)
    print(f"projecting to {cluster_dim}D (clustering) ...", flush=True)
    cl = UMAP(n_components=cluster_dim, metric="cosine", n_neighbors=15,
              min_dist=0.0, low_memory=True, verbose=False).fit_transform(vecs).astype("float64")

    print(f"macro clustering (KMeans, k={macro_k}) ...", flush=True)
    macro = KMeans(n_clusters=macro_k, random_state=0, n_init=4).fit_predict(cl)

    print(f"sub clustering (HDBSCAN, min_cluster_size={sub_min}) per macro ...", flush=True)
    sub = np.full(n, -1, dtype=int)
    sub_parent: dict[int, int] = {}
    next_sub = SUB_BASE
    for m in range(macro_k):
        idx = np.where(macro == m)[0]
        if len(idx) < sub_min * 2:
            local = np.zeros(len(idx), dtype=int)            # too small to split
        else:
            local = hdbscan.HDBSCAN(min_cluster_size=sub_min, min_samples=min_samples,
                                    core_dist_n_jobs=-1).fit_predict(cl[idx])
            local = _assign_orphans(local, cl[idx])
        for lv in np.unique(local):
            gid = next_sub
            next_sub += 1
            sub[idx[local == lv]] = gid
            sub_parent[gid] = m

    print("labeling topics ...", flush=True)
    macro_labels = _label_clusters(titles, macro)
    sub_labels = _label_clusters(titles, sub)
    macro_mix = _pathology_mix(macro, paths)
    sub_mix = _pathology_mix(sub, paths)
    macro_sizes = Counter(int(c) for c in macro)
    sub_sizes = Counter(int(c) for c in sub)

    db = sqlite3.connect(VECTORS_PATH)
    db.executescript(
        """
        DROP TABLE IF EXISTS paper_map;
        DROP TABLE IF EXISTS clusters;
        CREATE TABLE paper_map (paper_id TEXT PRIMARY KEY, x REAL, y REAL, cluster INTEGER, macro INTEGER);
        CREATE TABLE clusters (cluster INTEGER PRIMARY KEY, label TEXT, size INTEGER,
                               pathology_mix TEXT, parent INTEGER, level INTEGER);
        """
    )
    db.executemany(
        "INSERT INTO paper_map VALUES (?,?,?,?,?)",
        [(ids[i], float(coords[i][0]), float(coords[i][1]), int(sub[i]), int(macro[i]))
         for i in range(n)],
    )

    def mix_str(mix, c):
        return ", ".join(f"{p}:{v}" for p, v in mix.get(c, Counter()).most_common())

    rows = [(m, macro_labels[m], macro_sizes[m], mix_str(macro_mix, m), None, 1)
            for m in range(macro_k)]
    rows += [(s, sub_labels[s], sub_sizes[s], mix_str(sub_mix, s), sub_parent[s], 2)
             for s in sorted(sub_parent)]
    db.executemany("INSERT INTO clusters VALUES (?,?,?,?,?,?)", rows)
    db.commit()
    db.close()
    return {"papers": n, "macros": macro_k, "subs": len(sub_parent),
            "macro_labels": macro_labels, "macro_sizes": dict(macro_sizes),
            "sub_labels": sub_labels, "sub_parent": sub_parent, "sub_sizes": dict(sub_sizes)}
