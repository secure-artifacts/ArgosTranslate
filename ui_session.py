"""
保存 / 恢复上次关闭时的界面状态（多标签、文本、语言、音频设置、窗口位置）。
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

SESSION_VERSION = 1
MAX_TEXT_CHARS = 500_000


def session_path(portable_root: Path) -> Path:
    return portable_root / "data" / "config" / "ui_session.json"


def load_session(portable_root: Path) -> dict[str, Any] | None:
    path = session_path(portable_root)
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return None
        if int(raw.get("version") or 0) != SESSION_VERSION:
            return None
        tabs = raw.get("tabs")
        if not isinstance(tabs, list) or len(tabs) < 1:
            return None
        return raw
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def save_session(portable_root: Path, data: dict[str, Any]) -> None:
    path = session_path(portable_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _trim_text(s: str) -> str:
    if len(s) <= MAX_TEXT_CHARS:
        return s
    return s[:MAX_TEXT_CHARS] + "\n\n[… 超出保存上限，部分内容未写入会话文件 …]"
