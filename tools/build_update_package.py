"""
生成就地更新用的 payload 目录与 zip。
  venv\\Scripts\\python.exe tools\\build_update_package.py
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_version import APP_NAME, APP_VERSION, write_version_json
from portable_updater import UPDATE_REL_PATHS, collect_payload_files


def build_payload(out_dir: Path | None = None) -> Path:
    write_version_json(ROOT)
    name = f"Argos翻译-{APP_VERSION}-更新包"
    dest = out_dir or (ROOT / "dist" / "update" / name)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    for rel in UPDATE_REL_PATHS:
        src = ROOT / rel
        if not src.exists():
            print(f"[WARN] missing: {rel}")
            continue
        dst = dest / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        else:
            shutil.copytree(
                src,
                dst,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )

    files = collect_payload_files(dest)
    print(f"[OK] payload -> {dest} ({len(files)} files)")

    zip_path = dest.parent / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            full = dest / rel
            zf.write(full, arcname=rel.as_posix())
    print(f"[OK] zip -> {zip_path}")
    return dest


if __name__ == "__main__":
    build_payload()
