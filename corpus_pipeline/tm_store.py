"""翻译记忆库（SQLite）：精确 + 模糊匹配，带来源与相似度。"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from corpus_pipeline.config import TM_DB
from corpus_pipeline.quality import dedupe_key, is_noisy_pair, normalize_source_for_storage
from corpus_pipeline.quality_score import passes_quality
from corpus_pipeline.quarantine import append_quarantine


@dataclass
class TMEntry:
    source_text: str
    target_text: str
    source_lang: str
    target_lang: str
    domain: str
    confidence_score: float
    source_url: str = ""
    tm_purity_score: float = 0.75


@dataclass
class TMMatch:
    source_text: str
    target_text: str
    source_lang: str
    target_lang: str
    domain: str
    confidence_score: float
    source_url: str
    similarity: float
    match_kind: str  # exact | fuzzy
    tm_purity_score: float = 0.75


_SCHEMA = """
CREATE TABLE IF NOT EXISTS translation_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    source_text TEXT NOT NULL,
    target_text TEXT NOT NULL,
    domain TEXT DEFAULT '',
    confidence_score REAL DEFAULT 0.8,
    source_url TEXT DEFAULT '',
    UNIQUE(source_lang, target_lang, source_text)
)
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or TM_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    _migrate(conn)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tm_lookup "
        "ON translation_memory(source_lang, target_lang)"
    )
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(translation_memory)").fetchall()
    }
    if "source_url" not in cols:
        conn.execute(
            "ALTER TABLE translation_memory ADD COLUMN source_url TEXT DEFAULT ''"
        )
    if "tm_purity_score" not in cols:
        conn.execute(
            "ALTER TABLE translation_memory ADD COLUMN tm_purity_score REAL DEFAULT 0.75"
        )


def _similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0
    lr = la / lb if la > lb else lb / la
    if lr > 3.5 or lr < 0.28:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def insert_pairs(
    pairs: Iterable[TMEntry],
    *,
    db_path: Path | None = None,
    skip_noisy: bool = True,
    quality_gate: bool = True,
    quarantine_path: Path | None = None,
) -> tuple[int, int, int]:
    conn = _connect(db_path)
    added, skipped, quarantined = 0, 0, 0
    seen: set[str] = set()
    for p in pairs:
        if skip_noisy and is_noisy_pair(
            p.source_text, p.target_text, p.source_lang, p.target_lang
        ):
            skipped += 1
            continue
        if quality_gate:
            ok, pq = passes_quality(
                p.source_text,
                p.target_text,
                p.source_lang,
                p.target_lang,
                align_confidence=float(p.confidence_score),
            )
            if not ok:
                if quarantine_path is not None:
                    append_quarantine(
                        quarantine_path,
                        source_text=p.source_text,
                        target_text=p.target_text,
                        source_lang=p.source_lang,
                        target_lang=p.target_lang,
                        domain=p.domain or "",
                        source_url=p.source_url or "",
                        reason=pq.reject_reason,
                        quality=pq.to_dict(),
                        align_confidence=float(p.confidence_score),
                    )
                quarantined += 1
                continue
        src_store = normalize_source_for_storage(p.source_text, p.source_lang)
        key = dedupe_key(
            src_store, p.target_text, p.source_lang, p.target_lang
        )
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO translation_memory
                (source_lang, target_lang, source_text, target_text,
                 domain, confidence_score, source_url, tm_purity_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p.source_lang,
                    p.target_lang,
                    src_store,
                    p.target_text.strip(),
                    p.domain or "",
                    float(p.confidence_score),
                    p.source_url or "",
                    float(getattr(p, "tm_purity_score", 0.75) or 0.75),
                ),
            )
            if conn.total_changes:
                added += 1
            else:
                skipped += 1
        except sqlite3.Error:
            skipped += 1
    conn.commit()
    conn.close()
    return added, skipped, quarantined


def count_entries(
    db_path: Path | None = None,
    *,
    source_lang: str | None = None,
    target_lang: str | None = None,
) -> int:
    conn = _connect(db_path)
    sql = "SELECT COUNT(*) FROM translation_memory"
    params: list[str] = []
    if source_lang and target_lang:
        sql += " WHERE source_lang = ? AND target_lang = ?"
        params.extend([source_lang, target_lang])
    elif source_lang:
        sql += " WHERE source_lang = ?"
        params.append(source_lang)
    elif target_lang:
        sql += " WHERE target_lang = ?"
        params.append(target_lang)
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return int(row[0]) if row else 0


def iter_entries(
    *,
    source_lang: str | None = None,
    target_lang: str | None = None,
    db_path: Path | None = None,
    limit: int | None = None,
) -> list[TMEntry]:
    """列出 TM 条目（可选按语言对过滤）。"""
    conn = _connect(db_path)
    sql = """
        SELECT source_text, target_text, source_lang, target_lang,
               domain, confidence_score, source_url, tm_purity_score
        FROM translation_memory
    """
    params: list[str] = []
    if source_lang and target_lang:
        sql += " WHERE source_lang = ? AND target_lang = ?"
        params.extend([source_lang, target_lang])
    elif source_lang:
        sql += " WHERE source_lang = ?"
        params.append(source_lang)
    elif target_lang:
        sql += " WHERE target_lang = ?"
        params.append(target_lang)
    sql += " ORDER BY id DESC"
    if limit is not None and limit > 0:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    out: list[TMEntry] = []
    for r in rows:
        out.append(
            TMEntry(
                source_text=r["source_text"] or "",
                target_text=r["target_text"] or "",
                source_lang=r["source_lang"] or "",
                target_lang=r["target_lang"] or "",
                domain=r["domain"] or "",
                confidence_score=float(r["confidence_score"] or 0.8),
                source_url=r["source_url"] or "",
                tm_purity_score=float(r["tm_purity_score"] or 0.75),
            )
        )
    return out


def delete_entries(
    entries: Iterable[TMEntry],
    *,
    db_path: Path | None = None,
    delete_reverse: bool = True,
) -> int:
    """从 TM 删除指定句对；可选同时删除反向句对。返回实际删除行数。"""
    from corpus_pipeline.quality import normalize_source_for_storage

    items = list(entries)
    if not items:
        return 0
    conn = _connect(db_path)
    deleted = 0
    seen: set[tuple[str, str, str]] = set()
    for p in items:
        src_store = normalize_source_for_storage(p.source_text, p.source_lang)
        key = (p.source_lang, p.target_lang, src_store)
        if key not in seen:
            seen.add(key)
            cur = conn.execute(
                """
                DELETE FROM translation_memory
                WHERE source_lang = ? AND target_lang = ? AND source_text = ?
                """,
                key,
            )
            deleted += cur.rowcount
        if delete_reverse:
            rev_store = normalize_source_for_storage(p.target_text, p.target_lang)
            rev_key = (p.target_lang, p.source_lang, rev_store)
            if rev_key not in seen:
                seen.add(rev_key)
                cur = conn.execute(
                    """
                    DELETE FROM translation_memory
                    WHERE source_lang = ? AND target_lang = ? AND source_text = ?
                    """,
                    rev_key,
                )
                deleted += cur.rowcount
    conn.commit()
    conn.close()
    return deleted


def delete_lang_pair(
    source_lang: str,
    target_lang: str,
    *,
    db_path: Path | None = None,
    bidirectional: bool = True,
) -> int:
    """删除某语言对下的全部 TM 条目。"""
    conn = _connect(db_path)
    deleted = 0
    cur = conn.execute(
        """
        DELETE FROM translation_memory
        WHERE source_lang = ? AND target_lang = ?
        """,
        (source_lang, target_lang),
    )
    deleted += cur.rowcount
    if bidirectional:
        cur = conn.execute(
            """
            DELETE FROM translation_memory
            WHERE source_lang = ? AND target_lang = ?
            """,
            (target_lang, source_lang),
        )
        deleted += cur.rowcount
    conn.commit()
    conn.close()
    return int(deleted)


def delete_all_entries(*, db_path: Path | None = None) -> int:
    """清空 TM 数据库全部条目。"""
    conn = _connect(db_path)
    cur = conn.execute("DELETE FROM translation_memory")
    deleted = int(cur.rowcount)
    conn.commit()
    conn.close()
    return deleted


def delete_filtered(
    *,
    source_lang: str | None = None,
    target_lang: str | None = None,
    db_path: Path | None = None,
) -> int:
    """按语言侧删除 TM 条目（可只指定源语或目标语）。"""
    if not source_lang and not target_lang:
        return delete_all_entries(db_path=db_path)
    conn = _connect(db_path)
    sql = "DELETE FROM translation_memory"
    params: list[str] = []
    if source_lang and target_lang:
        sql += " WHERE source_lang = ? AND target_lang = ?"
        params.extend([source_lang, target_lang])
    elif source_lang:
        sql += " WHERE source_lang = ?"
        params.append(source_lang)
    else:
        sql += " WHERE target_lang = ?"
        params.append(target_lang or "")
    cur = conn.execute(sql, params)
    deleted = int(cur.rowcount)
    conn.commit()
    conn.close()
    return deleted


def _fuzzy_scan_limit() -> int:
    try:
        return max(100, int(os.environ.get("ARGOS_TM_FUZZY_SCAN_LIMIT", "1200")))
    except ValueError:
        return 1200


def _match_from_row(
    r: sqlite3.Row,
    *,
    ratio: float,
) -> TMMatch:
    kind = "exact" if ratio >= 0.999 else "fuzzy"
    purity = float(r["tm_purity_score"] or 0.75)
    conf = float(r["confidence_score"] or 0.8)
    return TMMatch(
        source_text=r["source_text"] or "",
        target_text=r["target_text"] or "",
        source_lang=r["source_lang"],
        target_lang=r["target_lang"],
        domain=r["domain"] or "",
        confidence_score=conf,
        source_url=r["source_url"] or "",
        similarity=round(ratio, 4),
        match_kind=kind,
        tm_purity_score=round(purity, 4),
    )


def lookup_exact(
    source_text: str,
    source_lang: str,
    target_lang: str,
    *,
    db_path: Path | None = None,
) -> TMMatch | None:
    """按归一化原文精确命中（索引查询，避免全表扫描）。"""
    query = (source_text or "").strip()
    if not query:
        return None
    src_store = normalize_source_for_storage(query, source_lang)
    conn = _connect(db_path)
    row = conn.execute(
        """
        SELECT source_text, target_text, source_lang, target_lang,
               domain, confidence_score, source_url, tm_purity_score
        FROM translation_memory
        WHERE source_lang = ? AND target_lang = ? AND source_text = ?
        LIMIT 1
        """,
        (source_lang, target_lang, src_store),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return _match_from_row(row, ratio=1.0)


def lookup_similar(
    source_text: str,
    source_lang: str,
    target_lang: str,
    *,
    min_ratio: float = 0.88,
    limit: int = 5,
    db_path: Path | None = None,
) -> list[TMMatch]:
    query = (source_text or "").strip()
    if not query:
        return []

    exact = lookup_exact(source_text, source_lang, target_lang, db_path=db_path)
    if exact is not None and exact.similarity >= min_ratio:
        return [exact]

    conn = _connect(db_path)
    rows = conn.execute(
        """
        SELECT source_text, target_text, source_lang, target_lang,
               domain, confidence_score, source_url, tm_purity_score
        FROM translation_memory
        WHERE source_lang = ? AND target_lang = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (source_lang, target_lang, _fuzzy_scan_limit()),
    ).fetchall()
    conn.close()

    q_len = len(query)
    q_store = normalize_source_for_storage(query, source_lang)
    scored: list[tuple[float, TMMatch]] = []
    for r in rows:
        src = (r["source_text"] or "").strip()
        if not src:
            continue
        if src == q_store:
            ratio = 1.0
        else:
            sl = len(src)
            lr = sl / q_len if sl > q_len else q_len / sl
            if lr > 2.2:
                continue
            ratio = _similarity(query, src)
            if ratio < min_ratio:
                continue
        purity = float(r["tm_purity_score"] or 0.75)
        conf = float(r["confidence_score"] or 0.8)
        purity_weight = max(0.15, min(1.0, purity))
        combined = ratio * conf * purity_weight
        scored.append(
            (
                combined,
                _match_from_row(r, ratio=ratio),
            )
        )
    scored.sort(key=lambda x: (-x[0], -x[1].similarity))
    return [m for _, m in scored[:limit]]


def best_match(
    source_text: str,
    source_lang: str,
    target_lang: str,
    *,
    min_ratio: float = 0.92,
    db_path: Path | None = None,
) -> TMMatch | None:
    hits = lookup_similar(
        source_text,
        source_lang,
        target_lang,
        min_ratio=min_ratio,
        limit=1,
        db_path=db_path,
    )
    return hits[0] if hits else None
