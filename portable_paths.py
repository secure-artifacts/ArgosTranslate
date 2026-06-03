"""便携版安装目录定位与安装完整性检查。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_install_root(path: Path) -> bool:
    return (path / "terminology_bridge.py").is_file() and (
        path / "venv" / "Scripts" / "pythonw.exe"
    ).is_file()


def install_pointer_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("USERPROFILE") or "."
    return Path(base) / "ArgosTranslatePortable" / "install_path.txt"


def load_install_pointer() -> Path | None:
    p = install_pointer_path()
    if not p.is_file():
        return None
    try:
        root = Path(p.read_text(encoding="utf-8").strip())
        if is_install_root(root):
            return root.resolve()
    except OSError:
        pass
    return None


def save_install_pointer(target: Path) -> None:
    if not is_install_root(target):
        return
    p = install_pointer_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(target.resolve()), encoding="utf-8")


def find_portable_root(start: Path | None = None) -> Path:
    custom = os.environ.get("ARGOS_TRANSLATE_HOME", "").strip()
    if custom:
        p = Path(custom).expanduser()
        if is_install_root(p):
            return p.resolve()

    saved = load_install_pointer()
    if saved is not None:
        return saved

    if start is None:
        if getattr(sys, "frozen", False):
            start = Path(sys.executable).resolve().parent
        else:
            start = Path(__file__).resolve().parent

    cur = start.resolve()
    for _ in range(12):
        if is_install_root(cur):
            return cur
        for name in ("ArgosTranslate",):
            sub = cur / name
            if is_install_root(sub):
                return sub.resolve()
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve()


def missing_install_message(attempted_root: Path) -> str:
    pointer = install_pointer_path()
    return (
        "尚未完成安装。\n\n"
        f"当前查找位置：{attempted_root}\n\n"
        "请从 GitHub Releases 下载 ArgosTranslate-vX.Y.Z.exe（只需 exe，无需 zip）：\n"
        "  双击后选择安装文件夹，程序会自动完成配置。\n\n"
        f"安装成功后路径记录在：{pointer}\n"
        "可在软件菜单「安装位置…」中更改。"
    )
