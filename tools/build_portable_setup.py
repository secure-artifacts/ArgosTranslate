"""
构建一键安装/启动 exe（内嵌程序 payload.zip）。

  venv\\Scripts\\python.exe tools\\build_portable_setup.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"


def _ensure_installer_assets() -> Path:
    assets = ROOT / "installer_assets"
    assets.mkdir(parents=True, exist_ok=True)
    dest = assets / "get-pip.py"
    if not dest.is_file():
        print(f"[INFO] downloading get-pip.py -> {dest}")
        urllib.request.urlretrieve(_GET_PIP_URL, dest)
    return dest


def main() -> int:
    py = ROOT / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(sys.executable)
        print(f"[INFO] using interpreter: {py}")

    subprocess.check_call([str(py), str(ROOT / "tools" / "build_update_package.py")], cwd=str(ROOT))

    zips = sorted((ROOT / "dist" / "update").glob("*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        print("[ERROR] update zip not found")
        return 1
    payload_dst = ROOT / "dist" / "app_payload.zip"
    shutil.copy2(zips[-1], payload_dst)
    print(f"[OK] payload -> {payload_dst}")

    subprocess.check_call([str(py), "-m", "pip", "install", "pyinstaller"], cwd=str(ROOT))

    icon = ROOT / "assets" / "app_icon.ico"
    icon_args: list[str] = ["--icon", str(icon)] if icon.is_file() else []
    out_dir = ROOT / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)

    get_pip = _ensure_installer_assets()
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        str(py),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "ArgosTranslate",
        "--paths",
        str(ROOT),
        "--hidden-import",
        "portable_installer",
        "--hidden-import",
        "portable_paths",
        "--hidden-import",
        "portable_updater",
        "--hidden-import",
        "install_wizard",
        "--hidden-import",
        "app_version",
        "--hidden-import",
        "network_policy",
        "--hidden-import",
        "win_path_utils",
        "--add-data",
        f"{get_pip}{sep}.",
        "--add-data",
        f"{payload_dst}{sep}.",
        "--distpath",
        str(out_dir),
        "--workpath",
        str(ROOT / "build" / "setup_work"),
        "--specpath",
        str(ROOT / "build"),
        *icon_args,
        str(ROOT / "setup_main.py"),
    ]
    print("[INFO]", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))
    built = out_dir / "ArgosTranslate.exe"
    print(f"[OK] {built}")
    print("Users only need this exe: pick install folder, auto setup, then launch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
