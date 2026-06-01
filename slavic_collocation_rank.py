"""搭配优选：中文触发 → 俄/乌固定 collocation（超越 lemma 级）。"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from native_fluency_config import COLLOC_DIR, detect_domain, native_fluency_enabled
from terminology_registry import normalize_source_lang

_HAN = re.compile(r"[\u4e00-\u9fff]")


@lru_cache(maxsize=4)
def _load_collocations(lang: str) -> tuple[dict[str, Any], ...]:
    code = normalize_source_lang(lang)
    base = COLLOC_DIR / code
    if not base.is_dir():
        return tuple()
    entries: list[dict[str, Any]] = []
    for p in sorted(base.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in data.get("entries") or []:
            if isinstance(row, dict):
                entries.append(row)
    entries.sort(
        key=lambda e: (-int(e.get("rank") or 0), -len(str(e.get("zh") or "")))
    )
    return tuple(entries)


def _domain_match(entry_domain: str, active: str) -> bool:
    ed = (entry_domain or "").strip().lower()
    if not ed:
        return True
    return ed == active or active == "news"


def _apply_entry(
    source: str,
    text: str,
    entry: dict[str, Any],
    *,
    active_domain: str,
) -> str:
    zh = str(entry.get("zh") or "").strip()
    pref = str(entry.get("preferred") or "").strip()
    if not zh or not pref or zh not in source:
        return text
    if not _domain_match(str(entry.get("domain") or ""), active_domain):
        return text
    out = text
    if pref.lower() in out.lower():
        return out
    for bad in entry.get("avoid") or []:
        bs = str(bad).strip()
        if bs and bs.lower() in out.lower():
            out = re.sub(re.escape(bs), pref, out, flags=re.IGNORECASE)
            return out
    if len(zh) >= 8 and _HAN.search(zh):
        if pref.endswith(".") and len(source) < len(pref) + 20:
            return pref
    return out


def apply_collocation_ranking(
    source_text: str,
    target_text: str,
    target_lang: str,
    *,
    domain: str | None = None,
) -> str:
    """源文含中文触发短语时，将译文中的 calque 替换为地道搭配。"""
    if not native_fluency_enabled():
        return target_text
    lang = normalize_source_lang(target_lang)
    if lang not in ("ru", "uk"):
        return target_text
    src = (source_text or "").strip()
    out = target_text or ""
    if not src or not out:
        return out
    dom = domain or detect_domain(src)
    for entry in _load_collocations(lang):
        out = _apply_entry(src, out, entry, active_domain=dom)
    return out


def rank_collocation_candidates(
    candidates: list[str],
    *,
    zh_trigger: str = "",
    domain: str = "news",
    ranks: list[int] | None = None,
) -> list[tuple[str, float]]:
    """对多个搭配候选打分（供 rerank / eval 使用）。"""
    scored: list[tuple[str, float]] = []
    for i, c in enumerate(candidates):
        c = (c or "").strip()
        if not c:
            continue
        base = float(ranks[i] if ranks and i < len(ranks) else 5)
        bonus = 0.5 if zh_trigger and len(zh_trigger) >= 4 else 0.0
        scored.append((c, base + bonus))
    scored.sort(key=lambda x: -x[1])
    return scored


def clear_collocation_cache() -> None:
    _load_collocations.cache_clear()
