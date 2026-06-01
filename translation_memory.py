"""
翻译记忆库（TM）运行时查询：模糊匹配、相似度、命中日志与指标。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TMHit:
    target_text: str
    similarity: float
    match_kind: str
    domain: str
    source_url: str
    tm_source_text: str
    confidence_score: float


def tm_enabled() -> bool:
    v = os.environ.get("ARGOS_USE_TM", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _min_ratio() -> float:
    return float(os.environ.get("ARGOS_TM_MIN_RATIO", "0.93"))


def _min_confidence() -> float:
    return float(os.environ.get("ARGOS_TM_MIN_CONFIDENCE", "0.75"))


def lookup(
    source_text: str,
    source_lang: str,
    target_lang: str,
    *,
    min_ratio: float | None = None,
) -> TMHit | None:
    query = (source_text or "").strip().lstrip("\ufeff")
    if not tm_enabled() or not query:
        return None
    try:
        from bidirectional_terminology import lookup_tm_langs, is_bidirectional_pair
        from corpus_pipeline.tm_store import best_match
        from corpus_pipeline.metrics import record_tm_lookup
    except ImportError:
        return None

    src_norm, tgt_norm = lookup_tm_langs(source_lang, target_lang)
    if not is_bidirectional_pair(source_lang, target_lang):
        record_tm_lookup(hit=False, similarity=0.0, reason="unsupported_pair")
        return None

    ratio = min_ratio if min_ratio is not None else _min_ratio()
    hit = best_match(
        query,
        src_norm,
        tgt_norm,
        min_ratio=ratio,
    )
    if hit is None:
        record_tm_lookup(hit=False, similarity=0.0)
        return None
    if hit.confidence_score < _min_confidence():
        record_tm_lookup(hit=False, similarity=hit.similarity)
        return None
    purity = getattr(hit, "tm_purity_score", hit.confidence_score)
    if purity < float(os.environ.get("ARGOS_TM_MIN_PURITY", "0.55")):
        record_tm_lookup(hit=False, similarity=hit.similarity, reason="low_purity")
        return None

    record_tm_lookup(
        hit=True,
        similarity=hit.similarity,
        match_kind=hit.match_kind,
        domain=hit.domain,
    )
    return TMHit(
        target_text=hit.target_text,
        similarity=hit.similarity,
        match_kind=hit.match_kind,
        domain=hit.domain,
        source_url=hit.source_url,
        tm_source_text=hit.source_text,
        confidence_score=min(hit.confidence_score, purity),
    )


def lookup_translation(
    source_text: str,
    source_lang: str,
    target_lang: str,
    *,
    min_ratio: float | None = None,
) -> str | None:
    h = lookup(source_text, source_lang, target_lang, min_ratio=min_ratio)
    return h.target_text if h else None


def format_hit_log(hit: TMHit, *, query: str = "") -> str:
    dom = hit.domain or "general"
    url = hit.source_url or "-"
    return (
        f"[TM {hit.match_kind}] sim={hit.similarity:.2%} domain={dom} url={url}\n"
        f"  query: {(query or '')[:120]}\n"
        f"  tm_src: {hit.tm_source_text[:120]}\n"
        f"  → {hit.target_text[:200]}"
    )


def append_hit_log(hit: TMHit, *, query: str = "") -> None:
    try:
        from corpus_pipeline.config import REPORTS, TM_LOG

        REPORTS.mkdir(parents=True, exist_ok=True)
        line = format_hit_log(hit, query=query) + "\n---\n"
        with open(TM_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def format_status_message(hit: TMHit) -> str:
    pct = int(hit.similarity * 100)
    dom = hit.domain or "语料"
    kind = "精确" if hit.match_kind == "exact" else "模糊"
    return f"TM{kind}命中 {pct}% · {dom}"
