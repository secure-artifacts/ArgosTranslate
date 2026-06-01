"""低质量句对隔离区（不写入 TM，待人工抽检）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_pipeline.config import QUARANTINE_DIR


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def quarantine_file(source: str, run_stamp: str) -> Path:
    d = QUARANTINE_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    return d / f"quarantine_{run_stamp}.jsonl"


def append_quarantine(
    path: Path,
    *,
    source_text: str,
    target_text: str,
    source_lang: str,
    target_lang: str,
    domain: str,
    source_url: str,
    reason: str,
    quality: dict[str, Any],
    align_confidence: float,
) -> None:
    row = {
        "quarantined_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_lang": source_lang,
        "target_lang": target_lang,
        "source_text": source_text,
        "target_text": target_text,
        "domain": domain,
        "source_url": source_url,
        "reason": reason,
        "align_confidence": align_confidence,
        "quality": quality,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
