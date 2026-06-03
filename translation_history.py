"""
翻译历史：本地 JSON 持久化（不上传）。
在语音输入会话中清空原文前，由 GUI 调用 append_record 保存当前原文与译文。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from terminology_bridge import portable_root


def history_path() -> Path:
    p = portable_root() / "data" / "config" / "translation_history.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_items() -> list[dict[str, Any]]:
    path = history_path()
    if not path.is_file():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        items = raw.get("items")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []


def save_items(items: list[dict[str, Any]]) -> None:
    """覆盖保存历史列表。"""
    path = history_path()
    tmp = path.with_suffix(".json.tmp")
    payload = {"version": 1, "items": [x for x in items if isinstance(x, dict)]}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def delete_indices(indices: list[int]) -> int:
    """按索引删除多条记录，返回删除数量。"""
    items = load_items()
    if not items:
        return 0
    to_del = {i for i in indices if isinstance(i, int) and 0 <= i < len(items)}
    if not to_del:
        return 0
    kept = [it for i, it in enumerate(items) if i not in to_del]
    save_items(kept)
    return len(items) - len(kept)


def clear_all() -> int:
    """清空全部历史，返回清空前条数。"""
    items = load_items()
    if not items:
        return 0
    save_items([])
    return len(items)


def append_record(
    source: str,
    target: str,
    src_lang_code: str,
    tgt_lang_code: str,
    src_lang_label: str = "",
    tgt_lang_label: str = "",
    *,
    max_items: int = 400,
) -> None:
    """在列表头部插入一条记录（最新在前）。"""
    ts = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    entry: dict[str, Any] = {
        "ts": ts,
        "src_lang": (src_lang_code or "").strip(),
        "tgt_lang": (tgt_lang_code or "").strip(),
        "src_lang_label": (src_lang_label or src_lang_code or "").strip(),
        "tgt_lang_label": (tgt_lang_label or tgt_lang_code or "").strip(),
        "source": source or "",
        "target": target or "",
    }
    items = load_items()
    items.insert(0, entry)
    del items[max_items:]
    save_items(items)
