"""采集任务结构化日志 → logs/*.json（质量回溯）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_pipeline.config import ROOT

LOGS_DIR = ROOT / "logs"
from corpus_pipeline.config import LOW_CONFIDENCE_THRESHOLD


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CrawlLogger:
    def __init__(self, source: str, stamp: str) -> None:
        self.source = source
        self.stamp = stamp
        self.started_at = _now()
        self.pages: list[dict[str, Any]] = []
        self.documents: list[dict[str, Any]] = []
        self.errors: list[str] = []

    def add_page(self, entry: dict[str, Any]) -> None:
        entry.setdefault("fetched_at", _now())
        self.pages.append(entry)

    def add_document(self, entry: dict[str, Any]) -> None:
        self.documents.append(entry)

    def save(
        self,
        summary: dict[str, Any],
        *,
        sample_pairs: list[dict[str, Any]] | None = None,
        sample_glossary: list[dict[str, Any]] | None = None,
    ) -> Path:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        path = LOGS_DIR / f"crawl_{self.source}_{self.stamp}.json"
        payload = {
            "source": self.source,
            "stamp": self.stamp,
            "started_at": self.started_at,
            "finished_at": _now(),
            "summary": summary,
            "pages": self.pages,
            "documents": self.documents,
            "errors": self.errors,
            "sample_pairs": sample_pairs or [],
            "sample_glossary": sample_glossary or [],
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path


def count_glossary_entries() -> int:
    from corpus_pipeline.config import GLOSSARY_DIR

    total = 0
    if not GLOSSARY_DIR.is_dir():
        return 0
    for p in GLOSSARY_DIR.glob("*_*_zh.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            total += len(data.get("entries") or [])
        except (OSError, json.JSONDecodeError):
            continue
    return total
