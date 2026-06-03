"""Windows 中文/非 ASCII 安装路径支持。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def configure_windows_utf8() -> None:
    """进程与子进程统一使用 UTF-8（尽早调用）。"""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass


def path_has_non_ascii(path: Path | str) -> bool:
    try:
        str(path).encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def extended_path_str(path: Path | str) -> str:
    """Windows 长路径/Unicode 前缀，便于子进程打开中文路径。"""
    p = Path(path).resolve()
    s = str(p)
    if sys.platform != "win32":
        return s
    if s.startswith("\\\\?\\"):
        return s
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def subprocess_path(path: Path | str) -> str:
    """传给 subprocess 参数列表的路径字符串。"""
    return extended_path_str(path) if sys.platform == "win32" else str(path)


def embed_toolchain_dir(install_root: Path) -> Path:
    """
    嵌入式 Python / pip / virtualenv 的工作目录。
    安装路径含中文时，放在 %LOCALAPPDATA%\\ArgosTranslate\\embed-toolchain，
    避免 embed 版 python.exe 无法从自身中文路径加载模块。
    """
    install_root = install_root.resolve()
    if not path_has_non_ascii(install_root):
        embed = install_root / "_bootstrap" / "embed"
        embed.mkdir(parents=True, exist_ok=True)
        return embed

    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    base = Path(local) if local else Path(tempfile.gettempdir())
    cache = base / "ArgosTranslate" / "embed-toolchain"
    cache.mkdir(parents=True, exist_ok=True)
    marker = cache / "install_root.txt"
    try:
        marker.write_text(str(install_root), encoding="utf-8")
    except OSError:
        pass
    embed = cache / "embed"
    embed.mkdir(parents=True, exist_ok=True)
    return embed
