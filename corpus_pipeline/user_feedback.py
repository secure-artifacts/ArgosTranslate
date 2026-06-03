"""用户反馈闭环：采纳为 TM（pending）+ 低分自动审核 + 确认后 gold/TM。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_pipeline.config import (
    PENDING_TM_DIR,
    USER_AUTO_REVIEW_QUEUE,
    USER_FEEDBACK_SOURCE,
    USER_LOCK_TERM_PURITY_MIN,
    USER_PROMOTE_TM_PURITY_MIN,
)
from corpus_pipeline.manual_review_queue import (
    get_queue_item,
    list_pending,
    queue_file,
    set_status,
)
from corpus_pipeline.quarantine import append_quarantine, quarantine_file


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pair_id(
    source_text: str,
    source_lang: str,
    target_lang: str,
) -> str:
    raw = (
        f"{(source_lang or '').strip().lower()}|"
        f"{(target_lang or '').strip().lower()}|"
        f"{(source_text or '').strip()}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _pending_tm_file() -> Path:
    d = PENDING_TM_DIR / USER_FEEDBACK_SOURCE
    d.mkdir(parents=True, exist_ok=True)
    return d / "pairs.jsonl"


def _load_queue_index(path: Path) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    if not path.is_file():
        return idx
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = str(row.get("id") or "")
        if rid:
            idx[rid] = row
    return idx


def _append_queue_row(record: dict[str, Any]) -> tuple[bool, str]:
    path = queue_file(USER_FEEDBACK_SOURCE)
    idx = _load_queue_index(path)
    rid = str(record.get("id") or "")
    if not rid:
        return False, "missing_id"
    if rid in idx and idx[rid].get("status") in ("approved", "pending"):
        return False, "already_queued"
    row = {
        **record,
        "id": rid,
        "source": USER_FEEDBACK_SOURCE,
        "status": "pending",
        "queued_at": _now_iso(),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True, "queued"


def _append_pending_tm(record: dict[str, Any]) -> None:
    path = _pending_tm_file()
    row = {**record, "pending_tm_at": _now_iso(), "pending_tm": True}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _remove_pending_tm(item_ids: set[str]) -> int:
    """从 pending_tm 镜像中移除指定 ID 的行。"""
    if not item_ids:
        return 0
    path = _pending_tm_file()
    if not path.is_file():
        return 0
    kept: list[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        rid = str(row.get("id") or "")
        if rid and rid in item_ids:
            removed += 1
            continue
        kept.append(line)
    if removed:
        path.write_text(
            ("\n".join(kept) + "\n") if kept else "",
            encoding="utf-8",
        )
    return removed


def score_pair_quality(
    source_text: str,
    target_text: str,
    source_lang: str,
    target_lang: str,
) -> dict[str, Any]:
    """综合 TM 纯度 +（中→俄/乌）Argos 质量分。"""
    from corpus_pipeline.tm_purity_score import score_tm_purity

    sl = (source_lang or "").strip().lower()
    tl = (target_lang or "").strip().lower()
    meta: dict[str, Any] = {
        "source_lang": sl,
        "target_lang": tl,
        "tm_purity_score": 0.0,
        "quality_score": None,
        "issues": [],
        "reject_reason": "",
    }
    if not (source_text or "").strip() or not (target_text or "").strip():
        meta["issues"].append("empty")
        return meta

    purity = score_tm_purity(source_text, target_text, sl, tl, align_confidence=0.85)
    meta["tm_purity_score"] = purity.tm_purity_score
    meta["semantic_consistency"] = purity.semantic_consistency
    meta["reject_reason"] = purity.reject_reason or ""

    zh_slavic = sl in ("zh", "zt", "cn") and tl in ("ru", "uk")
    slavic_zh = tl in ("zh", "zt", "cn") and sl in ("ru", "uk")
    if zh_slavic or slavic_zh:
        try:
            import argos_translation_quality as atq

            src, hyp, fc, tc = (
                (source_text, target_text, sl, tl)
                if zh_slavic
                else (target_text, source_text, tl, sl)
            )
            rep = atq.score_translation(src, hyp, tc, from_code=fc, deep=False)
            meta["quality_score"] = rep.score
            meta["issues"].extend(rep.issues)
            if rep.needs_improvement:
                meta["issues"].append("needs_improvement")
        except ImportError:
            pass

    if purity.reject_reason:
        meta["issues"].append(purity.reject_reason)
    if purity.tm_purity_score < USER_PROMOTE_TM_PURITY_MIN:
        meta["issues"].append("low_purity")
    return meta


def should_auto_queue_review(quality: dict[str, Any]) -> tuple[bool, str]:
    if not USER_AUTO_REVIEW_QUEUE:
        return False, "auto_review_disabled"
    issues = set(quality.get("issues") or [])
    if "empty" in issues:
        return False, "empty"
    q = quality.get("quality_score")
    if q is not None and float(q) < 0.52:
        return True, "low_quality_score"
    if "needs_improvement" in issues:
        return True, "needs_improvement"
    if float(quality.get("tm_purity_score") or 0) < 0.55:
        return True, "low_tm_purity"
    if quality.get("reject_reason"):
        return True, str(quality["reject_reason"])
    return False, ""


def adopt_user_translation(
    source_text: str,
    target_text: str,
    source_lang: str,
    target_lang: str,
    *,
    note: str = "",
    origin: str = "ui_adopt",
) -> dict[str, Any]:
    """
    用户确认译文 → 直接写入 gold 语料与本机 TM（不再进审核队列）。
    """
    src = (source_text or "").strip()
    tgt = (target_text or "").strip()
    if not src or not tgt:
        return {"ok": False, "reason": "empty_text"}

    quality = score_pair_quality(src, tgt, source_lang, target_lang)
    rid = pair_id(src, source_lang, target_lang)
    record = {
        "id": rid,
        "kind": "user_adopt",
        "origin": origin,
        "user_confirmed": True,
        "source_text": src,
        "target_text": tgt,
        "source_lang": (source_lang or "").strip().lower(),
        "target_lang": (target_lang or "").strip().lower(),
        "domain": "user_gold",
        "quality": quality,
        "tm_purity_score": quality.get("tm_purity_score"),
        "note": note,
        "source": USER_FEEDBACK_SOURCE,
    }
    from corpus_pipeline.gold_corpus import promote_user_pair

    result = promote_user_pair(record, reviewer=note or origin or "ui_adopt")
    tm_added = int(result.get("tm_added") or 0)
    tm_skipped = int(result.get("tm_skipped") or 0)
    ok = tm_added > 0 or tm_skipped > 0 or int(result.get("gold_sentences") or 0) > 0
    return {
        "ok": ok,
        "reason": "promoted" if ok else "tm_write_failed",
        "id": rid,
        "direct": True,
        "tm_added": tm_added,
        "tm_skipped": tm_skipped,
        "quality": quality,
        **result,
    }


def enqueue_low_quality_translation(
    source_text: str,
    target_text: str,
    source_lang: str,
    target_lang: str,
    *,
    trigger: str = "auto_translate",
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """低分/低纯度 Argos 译文 → quarantine + review queue。"""
    src = (source_text or "").strip()
    tgt = (target_text or "").strip()
    if not src or not tgt:
        return {"ok": False, "reason": "empty_text"}

    qmeta = quality or score_pair_quality(src, tgt, source_lang, target_lang)
    should, why = should_auto_queue_review(qmeta)
    if not should:
        return {"ok": False, "reason": why or "quality_ok", "quality": qmeta}

    rid = pair_id(src, source_lang, target_lang)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    qpath = quarantine_file(USER_FEEDBACK_SOURCE, stamp)
    append_quarantine(
        qpath,
        source_text=src,
        target_text=tgt,
        source_lang=(source_lang or "").strip().lower(),
        target_lang=(target_lang or "").strip().lower(),
        domain="user_auto_review",
        source_url="",
        reason=why,
        quality=qmeta,
        align_confidence=float(qmeta.get("semantic_consistency") or 0.5),
    )

    record = {
        "id": rid,
        "kind": "auto_low_quality",
        "origin": trigger,
        "user_confirmed": False,
        "source_text": src,
        "target_text": tgt,
        "source_lang": (source_lang or "").strip().lower(),
        "target_lang": (target_lang or "").strip().lower(),
        "domain": "user_auto_review",
        "quality": qmeta,
        "tm_purity_score": qmeta.get("tm_purity_score"),
        "auto_reason": why,
        "quarantine_file": str(qpath),
    }
    ok, reason = _append_queue_row(record)
    return {
        "ok": ok,
        "reason": reason if ok else reason,
        "id": rid,
        "auto_reason": why,
        "quarantine_file": str(qpath),
        "quality": qmeta,
    }


def list_user_pending() -> list[dict[str, Any]]:
    return list_pending(USER_FEEDBACK_SOURCE)


def get_user_item(item_id: str) -> dict | None:
    return get_queue_item(USER_FEEDBACK_SOURCE, item_id)


def approve_user_item(
    item_id: str,
    *,
    reviewer: str = "cli",
    note: str = "",
) -> dict[str, Any]:
    """人工确认 → gold + high-purity TM + regression case +（可选）locked term。"""
    item = get_queue_item(USER_FEEDBACK_SOURCE, item_id)
    if not item:
        return {"ok": False, "reason": "not_found"}
    item = {**item, "user_confirmed": True}
    set_status(USER_FEEDBACK_SOURCE, item_id, "approved", note=note or reviewer)
    from corpus_pipeline.gold_corpus import promote_user_pair

    result = promote_user_pair(item, reviewer=note or reviewer)
    result["ok"] = True
    return result


def reject_user_item(item_id: str, *, note: str = "") -> bool:
    return set_status(USER_FEEDBACK_SOURCE, item_id, "rejected", note=note)


def delete_user_items(item_ids: list[str], *, note: str = "") -> dict[str, Any]:
    """从审核队列永久删除条目（不入 TM；同步清理 pending_tm 镜像）。"""
    from corpus_pipeline.manual_review_queue import delete_items

    ids = [str(i).strip() for i in item_ids if str(i).strip()]
    if not ids:
        return {"ok": False, "reason": "empty_ids", "deleted": 0}
    deleted = delete_items(USER_FEEDBACK_SOURCE, ids)
    pending_removed = _remove_pending_tm(set(ids))
    return {
        "ok": deleted > 0,
        "deleted": deleted,
        "pending_tm_removed": pending_removed,
        "requested": len(ids),
        "note": note,
    }


def delete_all_user_pending(*, note: str = "") -> dict[str, Any]:
    """永久删除 user 审核队列中全部 pending 条目。"""
    pending = list_user_pending()
    ids = [str(i.get("id") or "") for i in pending if i.get("id")]
    if not ids:
        return {
            "ok": False,
            "reason": "empty_pending",
            "deleted": 0,
            "pending_tm_removed": 0,
            "requested": 0,
        }
    result = delete_user_items(ids, note=note)
    result["mode"] = "all_pending"
    return result
