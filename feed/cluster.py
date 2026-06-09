"""Topic clustering + 2D map projection over the embeddings.

Reads vectors back out of data/vectors.sqlite, projects them to 2D with UMAP
(for the Map tab), groups them into topics with KMeans, and labels each topic
with its most distinctive title terms (class-based TF-IDF, the BERTopic trick).

Results are written to companion tables in the same database:
  paper_map(paper_id, x, y, cluster)
  clusters(cluster, label, size, pathology_mix)

Relevance stays non-destructive: nothing is deleted. Off-topic grey-lit shows up
as its own labeled cluster the UI can dim or filter.
"""

from __future__ import annotations

import sqlite3
from collections import Counter

import numpy as np
import sqlite_vec

from .embed import DIM, VECTORS_PATH


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


def _label_clusters(titles: list[str], labels: np.ndarray) -> dict[int, str]:
    """Class-based TF-IDF label per cluster. Label -1 (HDBSCAN noise) is named."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    uniq = sorted({int(c) for c in labels if c >= 0})
    docs = [""] * len(uniq)
    pos = {c: i for i, c in enumerate(uniq)}
    for t, c in zip(titles, labels):
        if c >= 0:
            docs[pos[int(c)]] += " " + t
    out: dict[int, str] = {-1: "(unclustered)"}
    if not uniq:
        return out
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=8000, min_df=1)
    mat = vec.fit_transform(docs)
    terms = vec.get_feature_names_out()
    for c, i in pos.items():
        row = mat[i].toarray().ravel()
        top = [terms[j] for j in row.argsort()[::-1][:5] if row[j] > 0]
        out[c] = ", ".join(top) if top else f"cluster {c}"
    return out


def build(method: str = "hdbscan", k: int = 60, min_cluster_size: int = 500,
          sample: int | None = None) -> dict:
    from umap import UMAP

    ids, vecs, titles, paths = _load(sample)
    n = len(ids)
    print(f"loaded {n} vectors; projecting to 2D (UMAP) ...", flush=True)
    coords = UMAP(n_components=2, metric="cosine", n_neighbors=15,
                  min_dist=0.1, low_memory=True, verbose=False).fit_transform(vecs)

    if method == "hdbscan":
        import hdbscan
        print(f"clustering (HDBSCAN, min_cluster_size={min_cluster_size}) ...", flush=True)
        # cluster on the 2D layout so topics align with the visible blobs
        labels = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, min_samples=10,
                                 core_dist_n_jobs=-1).fit_predict(coords.astype("float64"))
    else:
        from sklearn.cluster import MiniBatchKMeans
        print(f"clustering into {k} topics (KMeans) ...", flush=True)
        labels = MiniBatchKMeans(n_clusters=k, random_state=0, n_init=3,
                                 batch_size=4096).fit_predict(vecs)

    print("labeling topics ...", flush=True)
    cluster_labels = _label_clusters(titles, labels)

    present = sorted({int(c) for c in labels})
    mix: dict[int, Counter] = {c: Counter() for c in present}
    for c, pth in zip(labels, paths):
        for p in pth.split(","):
            if p:
                mix[int(c)][p] += 1

    db = sqlite3.connect(VECTORS_PATH)
    db.executescript(
        """
        DROP TABLE IF EXISTS paper_map;
        DROP TABLE IF EXISTS clusters;
        CREATE TABLE paper_map (paper_id TEXT PRIMARY KEY, x REAL, y REAL, cluster INTEGER);
        CREATE TABLE clusters (cluster INTEGER PRIMARY KEY, label TEXT, size INTEGER, pathology_mix TEXT);
        """
    )
    db.executemany(
        "INSERT INTO paper_map VALUES (?,?,?,?)",
        [(ids[i], float(coords[i][0]), float(coords[i][1]), int(labels[i])) for i in range(n)],
    )
    sizes = Counter(int(c) for c in labels)
    db.executemany(
        "INSERT INTO clusters VALUES (?,?,?,?)",
        [(c, cluster_labels.get(c, f"cluster {c}"), sizes[c],
          ", ".join(f"{p}:{m}" for p, m in mix[c].most_common())) for c in present],
    )
    db.commit()
    db.close()
    n_topics = sum(1 for c in present if c >= 0)
    noise = sizes.get(-1, 0)
    return {"papers": n, "clusters": n_topics, "noise": noise,
            "labels": cluster_labels, "sizes": dict(sizes)}
