"""将 patches/argostranslategui_gui.py 同步到 venv 中的 argostranslategui/gui.py。"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path


def apply(*, force: bool = False) -> bool:
    root = Path(__file__).resolve().parents[1]
    try:
        import argos_settings_compat as asc

        asc.ensure_extended_settings()
    except ImportError:
        pass
    ok = _copy_patch(
        root,
        root / "patches" / "argostranslategui_gui.py",
        root / "venv" / "Lib" / "site-packages" / "argostranslategui" / "gui.py",
        force=force,
    )
    ok = _patch_argostranslate_translate(root) or ok
    return ok


def _copy_patch(root: Path, src: Path, dst: Path, *, force: bool) -> bool:
    if not src.is_file():
        print(f"[skip] patch source missing: {src}", file=sys.stderr)
        return False
    if not dst.parent.is_dir():
        print(f"[skip] venv target not found: {dst}", file=sys.stderr)
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


def _patch_argostranslate_translate(root: Path) -> bool:
    dst = root / "venv" / "Lib" / "site-packages" / "argostranslate" / "translate.py"
    if not dst.is_file():
        print(f"[skip] translate.py not found: {dst}", file=sys.stderr)
        return False
    try:
        text = dst.read_text(encoding="utf-8")
    except OSError:
        return False
    if "max_decoding_length=settings.max_decoding_tokens" in text:
        return True
    old = (
        "        length_penalty=0.2,\n"
        "        return_scores=True,"
    )
    new = (
        "        length_penalty=settings.length_penalty,\n"
        "        patience=settings.beam_patience,\n"
        "        coverage_penalty=settings.coverage_penalty,\n"
        "        repetition_penalty=settings.repetition_penalty,\n"
        "        max_input_length=settings.max_input_tokens,\n"
        "        max_decoding_length=settings.max_decoding_tokens,\n"
        "        return_scores=True,"
    )
    if old not in text:
        print("[skip] argostranslate translate.py layout changed", file=sys.stderr)
        return False
    dst.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"[ok] patched {dst}")
    return True


if __name__ == "__main__":
    ok = apply(force="--force" in sys.argv)
    raise SystemExit(0 if ok else 1)
