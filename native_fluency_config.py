"""领域检测与母语润色配置。"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
COLLOC_DIR = ROOT / "data" / "collocations"
STYLE_DIR = ROOT / "data" / "style"

DOMAINS = ("news", "diplomacy", "politics", "military", "colloquial")


def native_fluency_enabled() -> bool:
    v = os.environ.get("ARGOS_NATIVE_FLUENCY", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


@lru_cache(maxsize=1)
def _phrase_config() -> dict[str, Any]:
    p = STYLE_DIR / "native_phrase_patterns.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=1)
def _anti_mt_config() -> dict[str, Any]:
    p = STYLE_DIR / "anti_mt_patterns.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def detect_domain(source_text: str, *, default: str = "news") -> str:
    """根据中文源文关键词推断领域（politics/diplomacy/military/news）。"""
    src = (source_text or "").strip()
    if not src:
        return default
    cfg = _phrase_config()
    kw_map = cfg.get("domain_keywords") or {}
    scores: dict[str, int] = {d: 0 for d in DOMAINS if d != "colloquial"}
    for dom, words in kw_map.items():
        if dom not in scores:
            continue
        for w in words or []:
            ws = str(w).strip()
            if ws and ws in src:
                scores[dom] += 1
    best = max(scores.items(), key=lambda x: x[1])
    if best[1] <= 0:
        return default
    return best[0]


def clear_native_fluency_cache() -> None:
    _phrase_config.cache_clear()
    _anti_mt_config.cache_clear()
    try:
        import slavic_collocation_rank as scr

        scr.clear_collocation_cache()
    except ImportError:
        pass
    try:
        import news_style_rerank as nsr

        nsr.clear_style_cache()
    except ImportError:
        pass
