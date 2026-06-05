"""
æœ¬åœ°ç¿»è¯‘å™¨ï¼ˆä¿„ä¹Œï¼‰â€” ç‰ˆæœ¬å·ï¼ˆå‘å¸ƒå‰åœ¨æ­¤ä¿®æ”¹ï¼Œå†è¿è¡Œ tools/build_update_package.py æ‰“æ›´æ–°åŒ…ï¼‰ã€‚
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

APP_NAME = "æœ¬åœ°ç¿»è¯‘å™¨ï¼ˆä¿„ä¹Œï¼‰"
APP_VERSION = "1.4.45"
APP_BUILD = "20260605"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def version_tuple(version: str) -> tuple[int, int, int]:
    m = _VERSION_RE.match((version or "").strip())
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def compare_versions(a: str, b: str) -> int:
    """a > b è¿”å›žæ­£æ•°ï¼Œç›¸ç­‰è¿”å›ž 0ã€‚"""
    ta, tb = version_tuple(a), version_tuple(b)
    if ta > tb:
        return 1
    if ta < tb:
        return -1
    return 0


def version_info_dict() -> dict[str, Any]:
    return {
        "name": APP_NAME,
        "version": APP_VERSION,
        "build": APP_BUILD,
    }


def write_version_json(root: Path) -> Path:
    path = root / "version.json"
    path.write_text(
        json.dumps(version_info_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_version_json(root: Path) -> dict[str, Any]:
    path = root / "version.json"
    if not path.is_file():
        return {"name": APP_NAME, "version": "0.0.0", "build": ""}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {"name": APP_NAME, "version": "0.0.0", "build": ""}


def format_version_label(root: Path | None = None) -> str:
    if root is not None:
        data = read_version_json(root)
        ver = str(data.get("version") or APP_VERSION)
        build = str(data.get("build") or "").strip()
    else:
        ver = APP_VERSION
        build = APP_BUILD.strip()
    if build:
        return f"v{ver} ({build})"
    return f"v{ver}"
