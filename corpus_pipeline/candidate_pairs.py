"""Stage-1 候选文章对缓存（宽召回，不入 TM）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_pipeline.config import CANDIDATE_PAIRS_DIR


def candidate_pairs_path(source: str, stamp: str) -> Path:
    d = CANDIDATE_PAIRS_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    return d / f"candidates_{stamp}.jsonl"


def append_candidate(
    path: Path,
    record: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(record)
    row.setdefault(
        "cached_at",
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_candidates(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
