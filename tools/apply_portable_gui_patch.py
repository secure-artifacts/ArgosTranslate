"""将 patches/argostranslategui_gui.py 同步到 venv 中的 argostranslategui/gui.py。"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path


def apply(*, force: bool = False) -> bool:
    root = Path(__file__).resolve().parents[1]
    src = root / "patches" / "argostranslategui_gui.py"
    dst = root / "venv" / "Lib" / "site-packages" / "argostranslategui" / "gui.py"
    if not src.is_file():
        print(f"[skip] patch source missing: {src}", file=sys.stderr)
        return False
    if not dst.parent.is_dir():
        print(f"[skip] venv gui not found: {dst}", file=sys.stderr)
        return False
    if not force and dst.is_file():
        try:
            if hashlib.sha256(src.read_bytes()).digest() == hashlib.sha256(
                dst.read_bytes()
            ).digest():
                return True
        except OSError:
            pass
    shutil.copy2(src, dst)
    print(f"[ok] patched {dst}")
    return True


if __name__ == "__main__":
    ok = apply(force="--force" in sys.argv)
    raise SystemExit(0 if ok else 1)
