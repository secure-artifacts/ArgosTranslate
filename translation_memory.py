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


def export_to_file(
    path: str | Path,
    *,
    source_lang: str | None = None,
    target_lang: str | None = None,
) -> dict:
    """导出本地 TM（json / jsonl / csv）。"""
    from corpus_pipeline.tm_io import export_tm

    return export_tm(
        path,
        source_lang=source_lang,
        target_lang=target_lang,
    )


def import_from_file(
    path: str | Path,
    *,
    source_lang: str = "",
    target_lang: str = "",
    quality_gate: bool = False,
    bidirectional: bool = True,
) -> dict:
    """从本地文件导入 TM。"""
    from corpus_pipeline.tm_io import import_tm

    return import_tm(
        path,
        default_source_lang=source_lang,
        default_target_lang=target_lang,
        quality_gate=quality_gate,
        bidirectional=bidirectional,
    )


def import_batch_from_files(
    paths: list[str | Path],
    *,
    source_lang: str = "",
    target_lang: str = "",
    quality_gate: bool = False,
    bidirectional: bool = True,
) -> dict:
    """批量导入本地 TM（多文件 / 目录，按源句去重）。"""
    from corpus_pipeline.tm_io import import_tm_batch

    return import_tm_batch(
        paths,
        default_source_lang=source_lang,
        default_target_lang=target_lang,
        quality_gate=quality_gate,
        bidirectional=bidirectional,
    )


def import_from_table_text(
    text: str,
    *,
    source_lang: str = "",
    target_lang: str = "",
    quality_gate: bool = False,
    bidirectional: bool = True,
) -> dict:
    """从 Google 表格等复制的 TSV 文本导入 TM。"""
    from corpus_pipeline.tm_io import import_tm_from_table_text

    return import_tm_from_table_text(
        text,
        default_source_lang=source_lang,
        default_target_lang=target_lang,
        quality_gate=quality_gate,
        bidirectional=bidirectional,
    )


def entry_count() -> int:
    try:
        from corpus_pipeline.tm_store import count_entries

        return count_entries()
    except ImportError:
        return 0


def delete_entries(
    entries: list[dict],
    *,
    delete_reverse: bool = True,
) -> dict:
    """从本地 TM 删除指定句对。"""
    from corpus_pipeline.tm_io import delete_tm

    return delete_tm(entries=entries, delete_reverse=delete_reverse)


def list_entries(
    *,
    source_lang: str | None = None,
    target_lang: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """列出 TM 条目（供查看器 / 工具）。"""
    try:
        from corpus_pipeline.tm_store import iter_entries
    except ImportError:
        return []
    sl = tl = None
    if source_lang and target_lang:
        from bidirectional_terminology import lookup_tm_langs

        sl, tl = lookup_tm_langs(source_lang, target_lang)
    entries = iter_entries(
        source_lang=sl,
        target_lang=tl,
        limit=limit,
    )
    return [
        {
            "source_text": e.source_text,
            "target_text": e.target_text,
            "source_lang": e.source_lang,
            "target_lang": e.target_lang,
            "domain": e.domain,
            "confidence_score": e.confidence_score,
            "tm_purity_score": e.tm_purity_score,
            "source_url": e.source_url,
        }
        for e in entries
    ]
