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
    STUB.write_text(
        '''"""PyInstaller 用：只启动 venv pythonw，不导入 argostranslate。"""
import os
import subprocess
import sys
from pathlib import Path

def find_root():
    start = Path(sys.executable).resolve().parent
    for cand in (start, *start.parents[:8]):
        if (cand / "terminology_bridge.py").is_file():
            return cand
    return start

def main():
    root = find_root()
    pyw = root / "venv" / "Scripts" / "pythonw.exe"
    script = root / "portable_launcher.py"
    if not pyw.is_file() or not script.is_file():
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"缺少文件：\\n{pyw}\\n{script}",
                "本地翻译器",
                0x10,
            )
        return 1
    env = os.environ.copy()
    env.setdefault("XDG_DATA_HOME", str(root / "data" / "local"))
    env.setdefault("XDG_CONFIG_HOME", str(root / "data" / "config"))
    env.setdefault("XDG_CACHE_HOME", str(root / "data" / "cache"))
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) if sys.platform == "win32" else 0
    subprocess.Popen(
        [str(pyw), str(script)],
        cwd=str(root),
        env=env,
        creationflags=flags,
        close_fds=True,
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )


def main() -> int:
    py = ROOT / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        print("[ERROR] venv not found")
        return 1

    _write_stub()
    subprocess.check_call([str(py), "-m", "pip", "install", "pyinstaller"], cwd=str(ROOT))

    icon = ROOT / "assets" / "app_icon.ico"
    icon_args: list[str] = ["--icon", str(icon)] if icon.is_file() else []

    out_dir = ROOT / "dist" / "launcher_build"
    out_dir.mkdir(parents=True, exist_ok=True)
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
    print(f"[OK] {exe}")
    print("Double-click this exe; it starts venv pythonw (taskbar icon may show python briefly).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
