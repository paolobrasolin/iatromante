"""Command-line entry point.

    feed fetch [--pathology NAME] [--source S ...] [--since YYYY-MM-DD | --all]
    feed index
    feed search "query terms"
    feed stats
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from . import cluster as cluster_mod
from . import embed as embed_mod
from . import fulltext as fulltext_mod
from . import index as index_mod
from . import openaccess as openaccess_mod
from .models import clean_doi
from .sources import DEFAULT_SOURCES, REGISTRY
from .sources.base import make_client
from .store import CORPUS_PATH, Corpus, load_state, save_state

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "pathologies.yaml"


def _load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _since_for(source: str, state: dict, cfg: dict, override: str | None,
               fetch_all: bool) -> str:
    if fetch_all:
        return "1900-01-01"
    if override:
        return override
    watermark = state.get("sources", {}).get(source)
    if watermark:
        # re-scan a few days back to catch late-indexed records
        lookback = int(cfg.get("lookback_days", 5))
        wm = datetime.strptime(watermark, "%Y-%m-%d").date()
        return (wm - timedelta(days=lookback)).isoformat()
    return cfg.get("backfill_start", "2015-01-01")


def cmd_fetch(args) -> int:
    cfg = _load_config()
    pathologies = cfg["pathologies"]
    if args.pathology:
        pathologies = {k: v for k, v in pathologies.items() if k in args.pathology}
        if not pathologies:
            print(f"no such pathology; known: {list(cfg['pathologies'])}", file=sys.stderr)
            return 2

    sources = args.source or DEFAULT_SOURCES
    until = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")

    corpus = Corpus.load()
    state = load_state()
    state.setdefault("sources", {})
    before = len(corpus)

    with make_client() as client:
        for sname in sources:
            module = REGISTRY[sname]
            since = _since_for(sname, state, cfg, args.since, args.all)
            added = 0
            for pname, pdef in pathologies.items():
                terms = pdef.get("terms", [])
                mesh = pdef.get("mesh", [])
                print(f"[{sname}] {pname}: since {since} ...", flush=True)
                try:
                    for paper in module.fetch(client, pname, terms, mesh, since, until):
                        paper.fetched_at = now
                        corpus.add(paper)
                        added += 1
                except Exception as exc:  # one source/pathology failing must not abort the run
                    print(f"  !! {sname}/{pname} failed: {exc}", file=sys.stderr)
            # only advance the watermark when no override was used
            if not args.since and not args.all and args.pathology is None:
                state["sources"][sname] = until
            print(f"[{sname}] processed {added} records")

    corpus.save()
    save_state(state)
    print(f"\ncorpus: {before} -> {len(corpus)} unique papers "
          f"(+{len(corpus) - before}); saved to data/corpus.jsonl")
    return 0


def cmd_fulltext(args) -> int:
    now = datetime.now().isoformat(timespec="seconds")
    paths = args.pathology[0] if args.pathology else None
    stats = fulltext_mod.fetch_all(pathology=paths, limit=args.limit, fetched_at=now)
    print(f"\nfull text: attempted {stats['attempted']} | "
          f"{stats['with_body']} with body | {stats['abstract_only']} front-only | "
          f"{stats['failed']} failed")
    print(f"stored under data/fulltext/ (manifest: data/fulltext/manifest.json)")
    return 0


def cmd_resolve_oa(args) -> int:
    paths = args.pathology[0] if args.pathology else None
    stats = openaccess_mod.resolve(pathology=paths, limit=args.limit)
    print(f"\nopen-access resolution: checked {stats['checked']} paywalled-or-unknown papers")
    print(f"  legal OA copy found : {stats['oa_found']}")
    print(f"  no OA copy          : {stats['no_oa']}")
    print(f"  not in Unpaywall    : {stats['not_indexed']}")
    print(f"  failed              : {stats['failed']}")
    if stats.get("by_host"):
        print("  by host:")
        for h, c in sorted(stats["by_host"].items(), key=lambda kv: -kv[1]):
            print(f"    {h:14s} {c}")
    print("recorded in data/openaccess/manifest.json")
    return 0


def cmd_embed(args) -> int:
    stats = embed_mod.build(limit=args.limit)
    print(f"\nembeddings: {stats['embedded']} newly embedded "
          f"({stats['already']} already present) -> {embed_mod.VECTORS_PATH}")
    return 0


def cmd_cluster(args) -> int:
    r = cluster_mod.build(method=args.method, k=args.k,
                          min_cluster_size=args.min_cluster_size, min_samples=args.min_samples)
    noise = r.get("noise", 0)
    print(f"\nclustered {r['papers']} papers into {r['clusters']} topics "
          f"({noise} unclustered) via {args.method}")
    for c in sorted(r["sizes"], key=lambda c: -r["sizes"][c])[:15]:
        if c < 0:
            continue
        print(f"  [{r['sizes'][c]:5d}] {r['labels'][c]}")
    return 0


def cmd_clean_dois(args) -> int:
    tmp = CORPUS_PATH.with_suffix(".jsonl.tmp")
    total = fixed = nulled = 0
    with CORPUS_PATH.open(encoding="utf-8") as fh, tmp.open("w", encoding="utf-8") as out:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            total += 1
            old = p.get("doi")
            new = clean_doi(old)
            if new != old:
                p["doi"] = new
                url = p.get("url", "") or ""
                if "doi.org/" in url:  # the broken doi was the link target -> repair/fallback
                    if new:
                        p["url"] = f"https://doi.org/{new}"
                    elif p.get("pmid"):
                        p["url"] = f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid']}/"
                    else:
                        p["url"] = ""
                nulled += new is None
                fixed += new is not None
            out.write(json.dumps(p, ensure_ascii=False, sort_keys=True) + "\n")
    tmp.replace(CORPUS_PATH)
    print(f"scanned {total}; normalized {fixed}, nulled {nulled} invalid DOIs")
    print("rebuilding index ...")
    print(f"reindexed {index_mod.build()} papers")
    return 0


def cmd_index(args) -> int:
    n = index_mod.build()
    print(f"indexed {n} papers -> {index_mod.INDEX_PATH}")
    return 0


def cmd_search(args) -> int:
    pathology = args.pathology[0] if args.pathology else None
    if args.semantic:
        hits = embed_mod.search(args.query, k=args.limit, pathology=pathology)
        if not hits:
            print("no matches")
            return 0
        for h in hits:
            tags = f" [{h['pathologies']}]" if h["pathologies"] else ""
            print(f"\n• [{h['score']}] {h['title']} ({h['year']}, {h['type']}){tags}")
            print(f"  {h['url']}")
        return 0
    hits = index_mod.search(args.query, limit=args.limit)
    if not hits:
        print("no matches")
        return 0
    for h in hits:
        tags = f" [{h['pathologies']}]" if h["pathologies"] else ""
        print(f"\n• {h['title']} ({h['year']}, {h['type']}){tags}")
        print(f"  {h['url']}")
        if h["snip"]:
            print(f"  {h['snip']}")
    return 0


def cmd_stats(args) -> int:
    corpus = Corpus.load()
    by_path: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for p in corpus.by_id.values():
        for x in p.pathologies:
            by_path[x] = by_path.get(x, 0) + 1
        for x in p.sources:
            by_source[x] = by_source.get(x, 0) + 1
        by_type[p.type] = by_type.get(p.type, 0) + 1
    print(f"total unique papers: {len(corpus)}")
    for label, d in (("pathology", by_path), ("source", by_source), ("type", by_type)):
        print(f"\nby {label}:")
        for k, v in sorted(d.items(), key=lambda kv: -kv[1]):
            print(f"  {k:20s} {v}")
    state = load_state()
    print("\nwatermarks:")
    for s, wm in sorted(state.get("sources", {}).items()):
        print(f"  {s:20s} {wm}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="feed", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="pull new papers from sources into the corpus")
    f.add_argument("--pathology", action="append", help="limit to this pathology (repeatable)")
    f.add_argument("--source", action="append", choices=list(REGISTRY),
                   help="limit to this source (repeatable); default: all but preprints")
    f.add_argument("--since", help="override start date YYYY-MM-DD (does not advance watermark)")
    f.add_argument("--all", action="store_true", help="fetch full history (ignore watermark)")
    f.set_defaults(func=cmd_fetch)

    ft = sub.add_parser("fulltext", help="download open-access full text (PMC) into data/fulltext/")
    ft.add_argument("--pathology", action="append", help="limit to this pathology")
    ft.add_argument("--limit", type=int, help="cap number of papers fetched this run")
    ft.set_defaults(func=cmd_fulltext)

    ro = sub.add_parser("resolve-oa", help="find legal open-access copies of paywalled papers (Unpaywall)")
    ro.add_argument("--pathology", action="append", help="limit to this pathology")
    ro.add_argument("--limit", type=int, help="cap number of DOIs checked this run")
    ro.set_defaults(func=cmd_resolve_oa)

    e = sub.add_parser("embed", help="compute local semantic embeddings (deep search) into data/vectors.sqlite")
    e.add_argument("--limit", type=int, help="cap number of papers embedded this run")
    e.set_defaults(func=cmd_embed)

    cl = sub.add_parser("cluster", help="topic-cluster + 2D-project the embeddings for the map")
    cl.add_argument("--method", choices=["hdbscan", "kmeans"], default="hdbscan",
                    help="hdbscan finds the topic count from the data (default); kmeans uses --k")
    cl.add_argument("--min-cluster-size", type=int, default=500,
                    help="HDBSCAN: smallest group counted as a topic (default 500)")
    cl.add_argument("--min-samples", type=int, default=5,
                    help="HDBSCAN: lower = fewer points left unclustered (default 5)")
    cl.add_argument("--k", type=int, default=60, help="KMeans: number of topics (default 60)")
    cl.set_defaults(func=cmd_cluster)

    cd = sub.add_parser("clean-dois", help="normalize/validate DOIs in the corpus, then reindex")
    cd.set_defaults(func=cmd_clean_dois)

    i = sub.add_parser("index", help="(re)build the SQLite/FTS5 search index")
    i.set_defaults(func=cmd_index)

    s = sub.add_parser("search", help="search the corpus (keyword by default, --semantic for deep search)")
    s.add_argument("query")
    s.add_argument("--semantic", "-s", action="store_true", help="semantic/vector search instead of keyword")
    s.add_argument("--pathology", action="append", help="limit to this pathology")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_search)

    st = sub.add_parser("stats", help="summarize the corpus")
    st.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
