"""Command-line entry point.

    feed fetch [--pathology NAME] [--source S ...] [--since YYYY-MM-DD | --all]
    feed index
    feed search "query terms"
    feed stats
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from . import fulltext as fulltext_mod
from . import index as index_mod
from .sources import DEFAULT_SOURCES, REGISTRY
from .sources.base import make_client
from .store import Corpus, load_state, save_state

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


def cmd_index(args) -> int:
    n = index_mod.build()
    print(f"indexed {n} papers -> {index_mod.INDEX_PATH}")
    return 0


def cmd_search(args) -> int:
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

    i = sub.add_parser("index", help="(re)build the SQLite/FTS5 search index")
    i.set_defaults(func=cmd_index)

    s = sub.add_parser("search", help="full-text search the corpus")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_search)

    st = sub.add_parser("stats", help="summarize the corpus")
    st.set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
