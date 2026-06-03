"""人工审核队列：高置信 article 对，确认后再入 gold/TM。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_pipeline.config import (
    MANUAL_REVIEW_DIR,
    REVIEW_PAIR_CONF_MIN,
    REVIEW_TM_PURITY_MIN,
    REVIEW_TOPIC_HITS_MIN,
)


def _queue_dir(source: str) -> Path:
    d = MANUAL_REVIEW_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    return d


def queue_file(source: str) -> Path:
    return _queue_dir(source) / "pending.jsonl"


def _estimate_article_purity(pair_meta: dict[str, Any]) -> float:
    """article 级 tm_purity 估计（句对齐前）。"""
    emb = float(pair_meta.get("embedding_combined") or 0)
    ent = float(pair_meta.get("entity_overlap") or 0)
    para = float(pair_meta.get("paragraph_topic_consistency") or 0)
    topic = float(pair_meta.get("topic_overlap") or 0)
    return round(min(1.0, 0.35 * emb + 0.25 * ent + 0.25 * para + 0.15 * topic), 4)


def qualifies_for_review(pair_meta: dict[str, Any]) -> tuple[bool, str]:
    pc = float(pair_meta.get("pair_confidence") or 0)
    hits = int(pair_meta.get("topic_keyword_hits") or 0)
    purity = _estimate_article_purity(pair_meta)
    if pc < REVIEW_PAIR_CONF_MIN:
        return False, f"pair_confidence<{REVIEW_PAIR_CONF_MIN}"
    if hits < REVIEW_TOPIC_HITS_MIN:
        return False, f"topic_hits<{REVIEW_TOPIC_HITS_MIN}"
    if purity < REVIEW_TM_PURITY_MIN:
        return False, f"article_purity<{REVIEW_TM_PURITY_MIN}"
    return True, ""


def _load_index(path: Path) -> dict[str, dict]:
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
        key = row.get("id") or f"{row.get('ru_url')}|{row.get('zh_url')}"
        idx[key] = row
    return idx


def enqueue_for_review(
    source: str,
    record: dict[str, Any],
    *,
    pair_meta: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    meta = pair_meta or record
    ok, reason = qualifies_for_review(meta)
    if not ok:
        return False, reason

    path = queue_file(source)
    idx = _load_index(path)
    rid = record.get("id") or f"{record.get('ru_url')}|{record.get('zh_url')}"
    if rid in idx and idx[rid].get("status") in ("approved", "pending"):
        return False, "already_queued"

    row = {
        **record,
        "id": rid,
        "source": source,
        "status": "pending",
        "pair_confidence": float(meta.get("pair_confidence") or 0),
        "topic_keyword_hits": int(meta.get("topic_keyword_hits") or 0),
        "article_tm_purity_estimate": _estimate_article_purity(meta),
        "pair_meta": meta,
        "queued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True, "queued"


def get_queue_item(source: str, item_id: str) -> dict | None:
    return _load_index(queue_file(source)).get(item_id)


def list_pending(source: str) -> list[dict[str, Any]]:
    idx = _load_index(queue_file(source))
    return [r for r in idx.values() if r.get("status") == "pending"]


def set_status(source: str, item_id: str, status: str, *, note: str = "") -> bool:
    path = queue_file(source)
    idx = _load_index(path)
    if item_id not in idx:
        return False
    idx[item_id]["status"] = status
    idx[item_id]["reviewed_at"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    if note:
        idx[item_id]["review_note"] = note
    with open(path, "w", encoding="utf-8") as f:
        for row in idx.values():
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


def delete_items(source: str, item_ids: list[str]) -> int:
    """从审核队列文件中永久删除条目（任意 status）。"""
    ids = [str(i).strip() for i in item_ids if str(i).strip()]
    if not ids:
        return 0
    path = queue_file(source)
    idx = _load_index(path)
    deleted = 0
    for iid in ids:
        if iid in idx:
            del idx[iid]
            deleted += 1
    if not deleted:
        return 0
    with open(path, "w", encoding="utf-8") as f:
        for row in idx.values():
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return deleted


def delete_all_pending(source: str) -> int:
    """永久删除某来源审核队列中的全部 pending 条目。"""
    pending = list_pending(source)
    ids = [str(i.get("id") or "") for i in pending if i.get("id")]
    return delete_items(source, ids)
