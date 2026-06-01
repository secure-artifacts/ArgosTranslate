#!/usr/bin/env python3
"""选择性清理 UN 域 TM：仅删除低质量/语义错配/零实体重合条目。"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from corpus_pipeline.quality_score import score_pair
    from corpus_pipeline.tm_store import _connect, count_entries

    before = count_entries()
    conn = _connect()
    rows = conn.execute(
        """
        SELECT id, source_lang, target_lang, source_text, target_text,
               domain, confidence_score, source_url
        FROM translation_memory
        WHERE domain LIKE 'un%'
        """
    ).fetchall()

    to_delete: set[int] = set()
    by_url: dict[str, list] = defaultdict(list)

    for r in rows:
        pq = score_pair(
            r["source_text"] or "",
            r["target_text"] or "",
            r["source_lang"] or "",
            r["target_lang"] or "",
            align_confidence=float(r["confidence_score"] or 0.5),
        )
        url = r["source_url"] or ""
        by_url[url].append((r["id"], pq))

        if pq.reject_reason in (
            "semantic_mismatch",
            "entity_mismatch",
            "navigation_pollution",
        ):
            to_delete.add(int(r["id"]))
            continue
        if pq.named_entity_overlap <= 0.0 and pq.semantic_similarity < 0.12:
            to_delete.add(int(r["id"]))
            continue
        if pq.corpus_quality_score < 0.58:
            to_delete.add(int(r["id"]))
            continue
        if pq.semantic_similarity < 0.15 and pq.named_entity_overlap < 0.35:
            to_delete.add(int(r["id"]))
            continue
        if float(r["confidence_score"] or 0) < 0.72:
            to_delete.add(int(r["id"]))

    # 整篇文章级：若某 URL 下 >60% 句对 entity_mismatch / semantic_mismatch，全删
    for url, items in by_url.items():
        if not url or len(items) < 3:
            continue
        bad = sum(
            1
            for _, pq in items
            if pq.reject_reason in ("semantic_mismatch", "entity_mismatch")
            or pq.named_entity_overlap <= 0.0
        )
        if bad / len(items) >= 0.6:
            for rid, _ in items:
                to_delete.add(int(rid))

    for rid in to_delete:
        conn.execute("DELETE FROM translation_memory WHERE id = ?", (rid,))
    conn.commit()
    conn.close()
    after = count_entries()
    print(
        f"un_selective_purge scanned={len(rows)} deleted={len(to_delete)} "
        f"tm_before={before} tm_after={after}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
