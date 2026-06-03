"""新闻/外交风格 rerank、反 MT 规则、domain-aware 动词优选。"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from native_fluency_config import (
    _anti_mt_config,
    _phrase_config,
    detect_domain,
    native_fluency_enabled,
)
from terminology_registry import normalize_source_lang

_WEAK_NEWS_VERBS_RU = re.compile(
    r"\b(сказал|сказала|сказали|говорит|говорил|говорила)\b", re.I
)
_WEAK_NEWS_VERBS_UK = re.compile(
    r"\b(сказав|сказала|сказали|говорить|говорив|говорила)\b", re.I
)


def clear_style_cache() -> None:
    _phrase_patterns.cache_clear()


@lru_cache(maxsize=2)
def _phrase_patterns(lang: str) -> tuple[dict[str, Any], ...]:
    code = normalize_source_lang(lang)
    cfg = _phrase_config()
    key = "ru" if code == "ru" else "uk"
    rows = cfg.get("patterns") or {}
    if isinstance(rows, dict):
        items = rows.get(key) or []
    else:
        items = []
    out = [x for x in items if isinstance(x, dict)]
    out.sort(key=lambda e: -len(str(e.get("zh") or "")))
    return tuple(out)


def _domain_verbs(zh_verb: str, domain: str, lang: str) -> list[str]:
    cfg = _phrase_config()
    code = normalize_source_lang(lang)
    key = "domain_verbs_uk" if code == "uk" else "domain_verbs"
    dv = cfg.get(key) or cfg.get("domain_verbs") or {}
    cell = dv.get(zh_verb) or {}
    if not isinstance(cell, dict):
        return []
    preferred = cell.get(domain) or cell.get("news") or []
    return [str(x).strip() for x in preferred if str(x).strip()]


def apply_native_phrase_patterns(
    source_text: str,
    target_text: str,
    target_lang: str,
    *,
    domain: str | None = None,
) -> str:
    """native_phrase_patterns.json：整句/短语母语表达。"""
    if not native_fluency_enabled():
        return target_text
    lang = normalize_source_lang(target_lang)
    src = (source_text or "").strip()
    out = target_text or ""
    if not src or not out:
        return out
    dom = domain or detect_domain(src)
    for item in _phrase_patterns(lang):
        zh = str(item.get("zh") or "").strip()
        if not zh or zh not in src:
            continue
        item_dom = str(item.get("domain") or "")
        if item_dom and item_dom != dom and dom != "news":
            continue
        prefs = item.get("preferred") or []
        if isinstance(prefs, str):
            prefs = [prefs]
        for pref in prefs:
            ps = str(pref).strip()
            if ps and ps.lower() in out.lower():
                break
        else:
            pref = str(prefs[0]).strip() if prefs else ""
        if not pref:
            continue
        for bad in item.get("calques") or []:
            bs = str(bad).strip()
            if bs and bs.lower() in out.lower():
                out = re.sub(re.escape(bs), pref, out, flags=re.IGNORECASE)
                break
    return out


def apply_anti_mt_patterns(
    target_text: str,
    target_lang: str,
    *,
    domain: str | None = None,
) -> str:
    """anti_mt_patterns.json：去中文腔/英语腔/机翻味。"""
    if not native_fluency_enabled():
        return target_text
    lang = normalize_source_lang(target_lang)
    cfg = _anti_mt_config()
    rows = cfg.get(lang) or []
    out = target_text or ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_dom = str(row.get("domain") or "")
        if row_dom and domain and row_dom != domain:
            continue
        avoid = str(row.get("avoid") or "").strip()
        prefer = str(row.get("prefer") or "").strip()
        if avoid and prefer and avoid.lower() in out.lower():
            out = re.sub(re.escape(avoid), prefer, out, flags=re.IGNORECASE)
    return out


def apply_domain_verb_rerank(
    source_text: str,
    target_text: str,
    target_lang: str,
    *,
    domain: str | None = None,
) -> str:
    """
    源文含「表示/说」等时，新闻/外交域优先 заявил/сообщил，替换 сказал。
    """
    if not native_fluency_enabled():
        return target_text
    lang = normalize_source_lang(target_lang)
    src = (source_text or "").strip()
    out = target_text or ""
    if not src or not out:
        return out
    dom = domain or detect_domain(src)
    if dom == "colloquial":
        return out
    zh_verbs = ("表示", "称", "指出", "强调", "说")
    hit = next((v for v in zh_verbs if v in src), "")
    if not hit:
        return out
    prefs = _domain_verbs("表示" if hit in ("表示", "称", "指出", "强调") else "说", dom, lang)
    if not prefs:
        return out
    repl = prefs[0]
    if lang == "ru":
        pat = _WEAK_NEWS_VERBS_RU
    else:
        pat = _WEAK_NEWS_VERBS_UK

    def _sub(m: re.Match[str]) -> str:
        w = m.group(0)
        if w.lower() == repl.lower():
            return w
        if w[0].isupper():
            return repl[0].upper() + repl[1:]
        return repl

    return pat.sub(_sub, out, count=1)


def news_style_score(text: str, *, domain: str = "news") -> float:
    """0–1：新闻体特征（弱动词惩罚、固定搭配加分）。"""
    t = (text or "").strip()
    if not t:
        return 0.0
    score = 0.65
    low = t.lower()
    if _WEAK_NEWS_VERBS_RU.search(low) or _WEAK_NEWS_VERBS_UK.search(low):
        score -= 0.15
    good = ("заявил", "сообщил", "подчеркнул", "выступил", "обсудили", "переговоры")
    if any(g in low for g in good):
        score += 0.12
    bad = ("иметь возможность", "провести обсуждение", "осуществить", "в настоящее время")
    if any(b in low for b in bad):
        score -= 0.2
    if domain in ("diplomacy", "politics") and "заявил" in low:
        score += 0.05
    return round(max(0.0, min(1.0, score)), 4)


def diplomatic_style_score(text: str) -> float:
    t = (text or "").lower()
    if not t:
        return 0.0
    score = 0.5
    for g in ("заявление", "переговор", "дипломат", "министерство", "совет", "резолюц"):
        if g in t:
            score += 0.08
    for b in ("сказал", "сделал заявление"):
        if b in t:
            score -= 0.1
    return round(max(0.0, min(1.0, score)), 4)


def native_fluency_score(text: str, *, source_text: str = "", domain: str = "news") -> float:
    ns = news_style_score(text, domain=domain)
    ds = diplomatic_style_score(text)
    anti = 1.0
    low = (text or "").lower()
    for b in ("иметь возможность", "проводить обсуждение", "осуществить контроль"):
        if b in low:
            anti -= 0.25
    anti = max(0.0, anti)
    return round(min(1.0, 0.45 * ns + 0.35 * ds + 0.2 * anti), 4)


def apply_style_rerank(
    source_text: str,
    target_text: str,
    target_lang: str,
    *,
    domain: str | None = None,
) -> str:
    """综合：native phrases + anti-MT + domain verb rerank。"""
    dom = domain or detect_domain(source_text or "")
    t = apply_native_phrase_patterns(source_text, target_text, target_lang, domain=dom)
    t = apply_anti_mt_patterns(t, target_lang, domain=dom)
    t = apply_domain_verb_rerank(source_text, t, target_lang, domain=dom)
    return t
