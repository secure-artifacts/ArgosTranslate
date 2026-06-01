"""语料与翻译质量指标记录（TM 命中率、术语覆盖、对齐成功率等）。"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_pipeline.config import REPORTS

_METRICS_FILE = REPORTS / "metrics.jsonl"
_LOCK = threading.Lock()
_COUNTERS: dict[str, int] = {
    "tm_lookup": 0,
    "tm_hit": 0,
    "tm_miss": 0,
    "translate_total": 0,
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_event(event: str, **fields: Any) -> None:
    row = {"ts": _now(), "event": event, **fields}
    REPORTS.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with open(_METRICS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def bump(counter: str, n: int = 1) -> None:
    with _LOCK:
        _COUNTERS[counter] = _COUNTERS.get(counter, 0) + n


def record_tm_lookup(*, hit: bool, similarity: float = 0.0, **extra: Any) -> None:
    bump("tm_lookup")
    if hit:
        bump("tm_hit")
    else:
        bump("tm_miss")
    record_event(
        "tm_lookup",
        hit=hit,
        similarity=round(similarity, 4),
        **extra,
    )


def record_pipeline_stats(pipeline_source: str, stats: dict[str, Any]) -> None:
    record_event("pipeline_run", pipeline_source=pipeline_source, **stats)


def record_glossary_coverage(
    *,
    source_lang: str,
    tokens_checked: int,
    tokens_covered: int,
    sample_text_len: int,
) -> None:
    rate = tokens_covered / max(tokens_checked, 1)
    record_event(
        "glossary_coverage",
        source_lang=source_lang,
        tokens_checked=tokens_checked,
        tokens_covered=tokens_covered,
        coverage_rate=round(rate, 4),
        sample_text_len=sample_text_len,
    )


def record_entity_consistency(
    *,
    source_lang: str,
    consistent: int,
    inconsistent: int,
) -> None:
    total = consistent + inconsistent
    record_event(
        "entity_consistency",
        source_lang=source_lang,
        consistent=consistent,
        inconsistent=inconsistent,
        consistency_rate=round(consistent / max(total, 1), 4),
    )


def summary() -> dict[str, Any]:
    with _LOCK:
        counters = dict(_COUNTERS)
    tm_rate = counters.get("tm_hit", 0) / max(counters.get("tm_lookup", 0), 1)
    return {
        "counters": counters,
        "tm_hit_rate": round(tm_rate, 4),
        "metrics_file": str(_METRICS_FILE),
    }


def load_recent_pipeline_reports(limit: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not REPORTS.is_dir():
        return out
    files = sorted(REPORTS.glob("report_*.json"), reverse=True)[:limit]
    for p in files:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out
