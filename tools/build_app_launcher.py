"""
生成 dist\\本地翻译器\\本地翻译器.exe：
  仅含极简启动逻辑 + 你的图标，运行后调用 venv\\Scripts\\pythonw.exe portable_launcher.py

  venv\\Scripts\\python.exe tools\\build_app_launcher.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUB = ROOT / "launcher_stub.py"


def _write_stub() -> None:
    """使用仓库根目录 launcher_stub.py（含安装路径记忆与友好报错）。"""
    src = ROOT / "launcher_stub.py"
    if not src.is_file():
        print("[ERROR] launcher_stub.py missing")
        raise SystemExit(1)
    STUB.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def main() -> int:
    py = ROOT / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        py = Path(sys.executable)
    if not py.is_file():
        print("[ERROR] Python not found")
        return 1

    _write_stub()
    subprocess.check_call([str(py), "-m", "pip", "install", "pyinstaller"], cwd=str(ROOT))

    icon = ROOT / "assets" / "app_icon.ico"
    icon_args: list[str] = ["--icon", str(icon)] if icon.is_file() else []

    out_dir = ROOT / "dist" / "launcher_build"
    out_dir.mkdir(parents=True, exist_ok=True)
    hidden = (
        "portable_paths",
        "portable_installer",
        "setup_main",
        "win_path_utils",
    )
    cmd = [
        str(py),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "本地翻译器",
        "--paths",
        str(ROOT),
        *sum([["--hidden-import", h] for h in hidden], []),
        "--distpath",
        str(out_dir),
        "--workpath",
        str(ROOT / "build" / "launcher_work"),
        "--specpath",
        str(ROOT / "build"),
        *icon_args,
        str(STUB),
    ]
    print("[INFO]", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(ROOT))
    built = out_dir / "本地翻译器.exe"
    target_dir = ROOT / "dist" / "本地翻译器"
    target_dir.mkdir(parents=True, exist_ok=True)
    exe = target_dir / "本地翻译器.exe"
    import shutil

    try:
        shutil.copy2(built, exe)
    except OSError:
        alt = target_dir / "本地翻译器-新.exe"
        shutil.copy2(built, alt)
        exe = alt
        print(f"[WARN] Old exe locked; wrote {alt} — close running app and replace manually.")
    payload_exe = ROOT / "本地翻译器.exe"
    try:
        shutil.copy2(built, payload_exe)
        print(f"[OK] payload -> {payload_exe}")
    except OSError as e:
        print(f"[WARN] Could not copy to {payload_exe}: {e}")
    print(f"[OK] {exe}")
    print("Place 本地翻译器.exe in install root; shortcuts use it for icon + launch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
