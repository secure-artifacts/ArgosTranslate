"""黄金语料层：人工确认、高纯度、长期稳定。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_pipeline.align import align_document
from corpus_pipeline.config import GOLD_CORPUS_DIR
from corpus_pipeline.tm_purity_score import score_tm_purity
from corpus_pipeline.tm_store import TMEntry, insert_pairs


def gold_article_path(source: str, item_id: str) -> Path:
    safe = item_id.replace("|", "_").replace(":", "_")[:120]
    d = GOLD_CORPUS_DIR / source / "articles"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.json"


def gold_sentences_path(source: str) -> Path:
    d = GOLD_CORPUS_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    return d / "sentences.jsonl"


def promote_from_review(
    item: dict[str, Any],
    *,
    reviewer: str = "manual",
) -> dict[str, Any]:
    """审核通过 → 对齐 → 写入 gold_corpus + TM（仅高纯度句对）。"""
    source = str(item.get("source") or "un")
    ru_text = item.get("ru_text") or item.get("source_text") or ""
    zh_text = item.get("zh_text") or item.get("target_text") or ""
    ru_url = item.get("ru_url") or item.get("url") or ""
    domain = item.get("domain") or f"{source}_gold"

    aligned = align_document(ru_text, zh_text, "ru", "zh")
    sentence_rows: list[dict[str, Any]] = []
    tm_batch: list[TMEntry] = []
    purities: list[float] = []

    pair_conf = float(item.get("pair_confidence") or 0)

    for ap in aligned.sentence_pairs:
        purity = score_tm_purity(
            ap.source,
            ap.target,
            "ru",
            "zh",
            align_confidence=ap.confidence,
        )
        purities.append(purity.tm_purity_score)
        row = {
            "source": ap.source,
            "target": ap.target,
            "source_lang": "ru",
            "target_lang": "zh",
            "align_confidence": ap.confidence,
            "tm_purity_score": purity.tm_purity_score,
            "corpus_quality_score": purity.semantic_consistency,
            "domain": domain,
            "source_url": ru_url,
            "gold": True,
            "reviewer": reviewer,
        }
        sentence_rows.append(row)
        if purity.tm_purity_score >= 0.75 and not purity.reject_reason:
            conf = min(ap.confidence, purity.tm_purity_score, pair_conf)
            tm_batch.append(
                TMEntry(
                    source_text=ap.source,
                    target_text=ap.target,
                    source_lang="ru",
                    target_lang="zh",
                    domain=domain,
                    confidence_score=conf,
                    source_url=ru_url,
                    tm_purity_score=purity.tm_purity_score,
                )
            )
            tm_batch.append(
                TMEntry(
                    source_text=ap.target,
                    target_text=ap.source,
                    source_lang="zh",
                    target_lang="ru",
                    domain=domain,
                    confidence_score=max(0.75, conf * 0.95),
                    source_url=ru_url,
                    tm_purity_score=purity.tm_purity_score,
                )
            )

    item_id = str(item.get("id") or f"{ru_url}|{item.get('zh_url')}")
    article_payload = {
        "id": item_id,
        "source": source,
        "ru_url": ru_url,
        "zh_url": item.get("zh_url") or "",
        "domain": domain,
        "pair_confidence": pair_conf,
        "sentence_count": len(sentence_rows),
        "avg_tm_purity": round(sum(purities) / len(purities), 4) if purities else 0.0,
        "promoted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reviewer": reviewer,
        "ru_text": ru_text,
        "zh_text": zh_text,
        "sentences": sentence_rows,
    }
    gold_article_path(source, item_id).write_text(
        json.dumps(article_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    sp = gold_sentences_path(source)
    with open(sp, "a", encoding="utf-8") as f:
        for row in sentence_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    added, skipped, quarantined = insert_pairs(
        tm_batch,
        quality_gate=True,
        skip_noisy=True,
    )
    return {
        "item_id": item_id,
        "gold_article": str(gold_article_path(source, item_id)),
        "sentences": len(sentence_rows),
        "avg_tm_purity": article_payload["avg_tm_purity"],
        "tm_added": added,
        "tm_skipped": skipped,
        "tm_quarantined": quarantined,
    }
