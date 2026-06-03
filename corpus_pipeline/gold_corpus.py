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


def _maybe_lock_terms_from_pair(
    source_text: str,
    target_text: str,
    source_lang: str,
    target_lang: str,
    *,
    purity_score: float,
    domain: str,
) -> int:
    """高纯度短句对：写入 locked glossary（俄/乌→中）。"""
    from corpus_pipeline.config import USER_LOCK_TERM_PURITY_MIN
    from corpus_pipeline.locked_glossary import add_locked_entry

    if purity_score < USER_LOCK_TERM_PURITY_MIN:
        return 0
    sl = (source_lang or "").strip().lower()
    tl = (target_lang or "").strip().lower()
    locked = 0
    if sl in ("ru", "uk") and tl in ("zh", "zt", "cn"):
        src, tgt, lang = source_text.strip(), target_text.strip(), sl
    elif tl in ("ru", "uk") and sl in ("zh", "zt", "cn"):
        src, tgt, lang = target_text.strip(), source_text.strip(), tl
    else:
        return 0
    if len(src) > 48 or len(tgt) > 48:
        return 0
    if len(src.split()) > 6:
        return 0
    add_locked_entry(
        source=src,
        target=tgt,
        lang=lang,
        entity_type="USER_GOLD",
        sources_count=1,
        domains=[domain],
        note="user_feedback_promote",
    )
    locked += 1
    return locked


def promote_user_pair(
    item: dict[str, Any],
    *,
    reviewer: str = "manual",
) -> dict[str, Any]:
    """用户确认句对 → gold + 双向 TM + regression + locked。"""
    from bidirectional_terminology import lookup_tm_langs
    from corpus_pipeline.config import USER_FEEDBACK_SOURCE, USER_PROMOTE_TM_PURITY_MIN
    from corpus_pipeline.translation_eval import append_user_regression_case

    source = str(item.get("source") or USER_FEEDBACK_SOURCE)
    src = (item.get("source_text") or "").strip()
    tgt = (item.get("target_text") or "").strip()
    sl_in = (item.get("source_lang") or "zh").strip().lower()
    tl_in = (item.get("target_lang") or "ru").strip().lower()
    sl, tl = lookup_tm_langs(sl_in, tl_in)
    domain = item.get("domain") or "user_gold"
    item_id = str(item.get("id") or f"user|{sl}|{tl}|{src[:40]}")
    user_confirmed = bool(item.get("user_confirmed")) or str(
        item.get("kind") or ""
    ).strip() in ("user_adopt",)

    purity = score_tm_purity(src, tgt, sl, tl, align_confidence=0.9)
    pscore = float(purity.tm_purity_score or 0)
    if item.get("tm_purity_score") is not None:
        pscore = max(pscore, float(item.get("tm_purity_score") or 0))
    if user_confirmed:
        pscore = max(pscore, 0.80)

    row = {
        "source": src,
        "target": tgt,
        "source_lang": sl,
        "target_lang": tl,
        "align_confidence": 0.95,
        "tm_purity_score": pscore,
        "corpus_quality_score": purity.semantic_consistency,
        "domain": domain,
        "source_url": "user_gold",
        "gold": True,
        "reviewer": reviewer,
        "kind": item.get("kind"),
        "user_confirmed": user_confirmed,
    }
    sp = gold_sentences_path(source)
    with open(sp, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    article_payload = {
        "id": item_id,
        "source": source,
        "domain": domain,
        "kind": "user_pair",
        "tm_purity_score": pscore,
        "promoted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reviewer": reviewer,
        "source_text": src,
        "target_text": tgt,
        "source_lang": sl,
        "target_lang": tl,
        "sentences": [row],
    }
    gold_article_path(source, item_id).write_text(
        json.dumps(article_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    tm_batch: list[TMEntry] = []
    allow_tm = user_confirmed or (
        pscore >= USER_PROMOTE_TM_PURITY_MIN and not purity.reject_reason
    )
    if allow_tm and src and tgt:
        conf = min(0.98, max(0.85, pscore))
        tm_batch.append(
            TMEntry(
                source_text=src,
                target_text=tgt,
                source_lang=sl,
                target_lang=tl,
                domain=domain,
                confidence_score=conf,
                source_url="user_gold",
                tm_purity_score=pscore,
            )
        )
        tm_batch.append(
            TMEntry(
                source_text=tgt,
                target_text=src,
                source_lang=tl,
                target_lang=sl,
                domain=domain,
                confidence_score=max(0.75, conf * 0.95),
                source_url="user_gold",
                tm_purity_score=pscore,
            )
        )

    added, skipped, quarantined = insert_pairs(
        tm_batch,
        quality_gate=not user_confirmed,
        skip_noisy=not user_confirmed,
    )

    locked = _maybe_lock_terms_from_pair(
        src, tgt, sl, tl, purity_score=pscore, domain=domain
    )

    reg_id = append_user_regression_case(
        src,
        tgt,
        sl,
        tl,
        tags=["user_gold", str(item.get("kind") or "user")],
    )

    try:
        from corpus_pipeline.locked_glossary import merge_locked_into_registry

        merge_locked_into_registry()
    except Exception:
        pass

    return {
        "item_id": item_id,
        "gold_sentences": 1,
        "tm_purity_score": pscore,
        "tm_added": added,
        "tm_skipped": skipped,
        "tm_quarantined": quarantined,
        "source_lang": sl,
        "target_lang": tl,
        "locked_terms": locked,
        "regression_case_id": reg_id,
    }
