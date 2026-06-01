"""On-disk corpus (JSONL) + per-source watermark state."""

from __future__ import annotations

import json
from pathlib import Path

from .dedup import merge
from .models import Paper

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CORPUS_PATH = DATA_DIR / "corpus.jsonl"
STATE_PATH = DATA_DIR / "state.json"


class Corpus:
    """In-memory paper set with cross-identifier deduplication.

    A paper seen by PubMed (PMID, no DOI yet) and by OpenAlex (DOI, no PMID)
    must collapse into one record. We index by both DOI and PMID so an incoming
    record merges into any existing record it shares an identifier with.
    """

    def __init__(self) -> None:
        self.by_id: dict[str, Paper] = {}
        self._doi: dict[str, str] = {}
        self._pmid: dict[str, str] = {}

    # ---- identity bookkeeping -------------------------------------------
    def _index(self, p: Paper) -> None:
        if p.doi:
            self._doi[p.doi.lower()] = p.id
        if p.pmid:
            self._pmid[str(p.pmid)] = p.id

    def _candidates(self, p: Paper) -> list[str]:
        ids: list[str] = []
        if p.doi and p.doi.lower() in self._doi:
            ids.append(self._doi[p.doi.lower()])
        if p.pmid and str(p.pmid) in self._pmid:
            cid = self._pmid[str(p.pmid)]
            if cid not in ids:
                ids.append(cid)
        if not ids and p.id in self.by_id:
            ids.append(p.id)
        return [i for i in ids if i in self.by_id]

    def add(self, paper: Paper) -> None:
        cands = self._candidates(paper)
        if not cands:
            self.by_id[paper.id] = paper
            self._index(paper)
            return
        keep = cands[0]
        base = self.by_id[keep]
        merge(base, paper)
        for other in cands[1:]:
            if other != keep and other in self.by_id:
                merge(base, self.by_id.pop(other))
        self._index(base)

    # ---- persistence ----------------------------------------------------
    @classmethod
    def load(cls) -> "Corpus":
        c = cls()
        if CORPUS_PATH.exists():
            with CORPUS_PATH.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        p = Paper.from_json(json.loads(line))
                        c.by_id[p.id] = p
                        c._index(p)
        return c

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # sort by id so git diffs stay minimal across runs
        tmp = CORPUS_PATH.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for pid in sorted(self.by_id):
                fh.write(json.dumps(self.by_id[pid].to_json(), ensure_ascii=False,
                                    sort_keys=True))
                fh.write("\n")
        tmp.replace(CORPUS_PATH)

    def __len__(self) -> int:
        return len(self.by_id)


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"sources": {}}


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
