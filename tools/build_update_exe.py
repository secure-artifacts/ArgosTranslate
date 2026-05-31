"""
将 payload 打成可双击运行的更新 exe（需 PyInstaller）。
  venv\\Scripts\\python.exe tools\\build_update_package.py
  venv\\Scripts\\python.exe tools\\build_update_exe.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_version import APP_NAME, APP_VERSION


def main() -> int:
    subprocess.check_call(
        [str(ROOT / "venv" / "Scripts" / "python.exe"), str(ROOT / "tools" / "build_update_package.py")],
        cwd=str(ROOT),
    )
    payload = ROOT / "dist" / "update" / f"Argos翻译-{APP_VERSION}-更新包"
    py = ROOT / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        print("[ERROR] venv python not found")
        return 1

    subprocess.check_call(
        [str(py), "-m", "pip", "install", "pyinstaller"],
        cwd=str(ROOT),
    )

    name = f"Argos翻译-{APP_VERSION}-更新"
    dist = ROOT / "dist" / "update"
    dist.mkdir(parents=True, exist_ok=True)

    icon_arg: list[str] = []
    icon_ico = ROOT / "assets" / "app_icon.ico"
    if icon_ico.is_file():
        icon_arg = ["--icon", str(icon_ico)]

    cmd = [
        str(py),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        f"--name={name}",
        *icon_arg,
        "--add-data",
        f"{payload}{';'}payload",
        str(ROOT / "updater_main.py"),
    ]
    print("[INFO]", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))
    exe = dist / f"{name}.exe"
    if not exe.is_file():
        exe = ROOT / "dist" / f"{name}.exe"
    print(f"[OK] {APP_NAME} update exe: {exe}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
