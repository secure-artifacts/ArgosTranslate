"""俄/乌 lemma 优选：同一中文义项对应多个词形时，选当地人更常用的。"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from terminology_registry import normalize_source_lang

_CYR = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]")


def _morph_analyzer(lang: str) -> Any | None:
    code = normalize_source_lang(lang)
    try:
        if code == "ru":
            import glossary_manager as gm

            return gm.shared_morph_analyzer()
        if code == "uk":
            import glossary_inflection as gi

            return gi._shared_uk_morph_analyzer()
    except Exception:
        return None
    return None


def _parse_best(word: str, lang: str) -> Any | None:
    morph = _morph_analyzer(lang)
    if morph is None:
        return None
    w = (word or "").strip()
    if not w:
        return None
    try:
        if lang == "ru":
            import glossary_manager as gm

            parses = morph.parse(w)
            return gm.pick_morph_parse(parses, w) if parses else None
        parses = morph.parse(w)
        return parses[0] if parses else None
    except Exception:
        return None


def slavic_normal_form(word: str, lang: str) -> str:
    p = _parse_best(word, lang)
    if p is not None:
        nf = str(getattr(p, "normal_form", "") or "").strip()
        if nf:
            return nf
    return (word or "").strip()


def _usage_rank_from_meta(meta: dict[str, Any] | None) -> float:
    if not isinstance(meta, dict):
        return 0.0
    for key in ("usage_rank", "frequency", "rank"):
        v = meta.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


def _pymorphy_score(word: str, lang: str) -> float:
    p = _parse_best(word, lang)
    if p is None:
        return 0.0
    try:
        return float(getattr(p, "score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _surface_register_bonus(word: str, lang: str) -> float:
    """同 lemma 多 surface 时：新闻/口语更常见的复数、短词形等。"""
    p = _parse_best(word, lang)
    if p is None:
        return 0.0
    bonus = 0.0
    try:
        tag = p.tag
        if getattr(tag, "number", None) == "plur":
            bonus += 0.12
        pos = getattr(tag, "POS", None)
        if pos == "NOUN" and len(word) >= 5:
            bonus += 0.02
    except (AttributeError, TypeError, ValueError):
        pass
    return bonus


@lru_cache(maxsize=1)
def _tm_source_substring_counts(lang: str) -> dict[str, int]:
    """TM 语料中 source 侧子串出现次数（小缓存，用于同义优选）。"""
    code = normalize_source_lang(lang)
    if code not in ("ru", "uk"):
        return {}
    try:
        from corpus_pipeline.config import TM_DB
        from corpus_pipeline.tm_store import _connect
    except ImportError:
        return {}
    counts: dict[str, int] = {}
    try:
        conn = _connect(TM_DB)
        rows = conn.execute(
            "SELECT source_text FROM tm_entries WHERE source_lang = ?",
            (code,),
        ).fetchall()
        conn.close()
    except Exception:
        return {}
    for (src,) in rows:
        low = (src or "").lower()
        if not low:
            continue
        seen: set[str] = set()
        for m in _CYR.finditer(low):
            tok = m.group(0)
            if len(tok) < 3 or tok in seen:
                continue
            seen.add(tok)
            counts[tok] = counts.get(tok, 0) + 1
    return counts


def _tm_boost(word: str, lang: str) -> float:
    w = (word or "").strip().lower()
    if len(w) < 3:
        return 0.0
    counts = _tm_source_substring_counts(lang)
    hits = counts.get(w, 0)
    if hits <= 0:
        return 0.0
    return min(0.35, 0.08 * hits)


def rank_slavic_lemma(
    word: str,
    lang: str,
    *,
    zh: str = "",
    meta: dict[str, Any] | None = None,
    list_index: int = 9999,
) -> tuple[float, str]:
    """
    分数越高越优先。返回 (score, normal_form) 便于同 lemma 分组。
    list_index 越小表示在术语表中越靠前（人工/分类默认优先级）。
    """
    _ = zh
    w = (word or "").strip()
    if not w:
        return (-1.0, "")
    nf = slavic_normal_form(w, lang)
    score = (
        _usage_rank_from_meta(meta) * 10.0
        + _pymorphy_score(w, lang)
        + _surface_register_bonus(w, lang)
        + _tm_boost(w, lang)
        + max(0.0, 0.05 - list_index * 0.0005)
    )
    return (score, nf)


def _is_plural_surface(word: str, lang: str) -> bool:
    p = _parse_best(word, lang)
    if p is None:
        return False
    try:
        return getattr(p.tag, "number", None) == "plur"
    except (AttributeError, TypeError):
        return False


def pick_preferred_slavic_lemma(
    candidates: list[str],
    lang: str,
    *,
    zh: str = "",
    metas: list[dict[str, Any] | None] | None = None,
) -> str:
    """
    从多个俄/乌候选词中选出更常用、更地道的 lemma/surface。
    """
    lang = normalize_source_lang(lang)
    uniq: list[str] = []
    seen: set[str] = set()
    for c in candidates:
        s = (c or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    if not uniq:
        return ""
    if len(uniq) == 1:
        return uniq[0]

    meta_list = metas or [None] * len(uniq)
    scored: list[tuple[float, int, str, str]] = []
    for i, w in enumerate(uniq):
        meta = meta_list[i] if i < len(meta_list) else None
        sc, nf = rank_slavic_lemma(w, lang, zh=zh, meta=meta, list_index=i)
        scored.append((sc, i, w, nf))
    scored.sort(key=lambda x: (-x[0], x[1]))

    normal_forms = {nf for _, _, _, nf in scored if nf}
    if len(normal_forms) == 1 and len(scored) > 1:
        plural = [w for _, _, w, _ in scored if _is_plural_surface(w, lang)]
        if plural:
            return plural[0]

    return scored[0][2]


def clear_slavic_lemma_rank_cache() -> None:
    _tm_source_substring_counts.cache_clear()
