"""Windows 中文/非 ASCII 安装路径支持。"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
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


def app_data_argos_dir() -> Path:
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    base = Path(local) if local else Path(tempfile.gettempdir())
    d = base / "ArgosTranslate"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ascii_cache_root() -> Path:
    """
    供 embed / venv 使用的纯 ASCII 目录。
    当安装路径或 %LOCALAPPDATA% 含中文（如 Windows 用户名为中文）时，
    virtualenv 在 Unicode 路径下会失败，需改用 ProgramData 等 ASCII 路径。
    """
    candidates: list[Path] = []
    prog = (os.environ.get("ProgramData") or "").strip()
    if prog:
        candidates.append(Path(prog) / "ArgosTranslate")
    candidates.append(Path(r"C:\ProgramData") / "ArgosTranslate")
    allusers = (os.environ.get("ALLUSERSPROFILE") or "").strip()
    if allusers:
        candidates.append(Path(allusers) / "ArgosTranslate")
    tmp = Path(tempfile.gettempdir())
    if not path_has_non_ascii(tmp):
        candidates.append(tmp / "ArgosTranslate")

    seen: set[str] = set()
    for cand in candidates:
        key = str(cand).lower()
        if key in seen:
            continue
        seen.add(key)
        if path_has_non_ascii(cand):
            continue
        cand.mkdir(parents=True, exist_ok=True)
        return cand

    return app_data_argos_dir()


def _needs_external_toolchain_store(install_root: Path) -> bool:
    install_root = install_root.resolve()
    if path_has_non_ascii(install_root):
        return True
    return path_has_non_ascii(app_data_argos_dir())


def _external_toolchain_store(install_root: Path) -> Path:
    cache = _ascii_cache_root()
    marker = cache / "install_root.txt"
    try:
        marker.write_text(str(install_root.resolve()), encoding="utf-8")
    except OSError:
        pass
    return cache


def embed_toolchain_dir(install_root: Path) -> Path:
    """
    嵌入式 Python / pip / virtualenv 的工作目录。
    安装路径或 %LOCALAPPDATA% 含非 ASCII 时，放在 ProgramData 等 ASCII 缓存目录。
    """
    install_root = install_root.resolve()
    if not _needs_external_toolchain_store(install_root):
        embed = install_root / "_bootstrap" / "embed"
        embed.mkdir(parents=True, exist_ok=True)
        return embed

    cache = _external_toolchain_store(install_root) / "embed-toolchain"
    cache.mkdir(parents=True, exist_ok=True)
    embed = cache / "embed"
    embed.mkdir(parents=True, exist_ok=True)
    return embed


def venv_storage_dir(install_root: Path) -> Path:
    """
    虚拟环境实际目录。
    非 ASCII 安装路径或 %LOCALAPPDATA% 时放在 ASCII 缓存目录下的 venvs\\<hash>，
    避免 virtualenv 在 Unicode 路径下复制 pip 失败。
    """
    install_root = install_root.resolve()
    if not _needs_external_toolchain_store(install_root):
        return install_root / "venv"

    key = hashlib.sha256(str(install_root).encode("utf-8")).hexdigest()[:16]
    store = _external_toolchain_store(install_root) / "venvs" / key
    store.mkdir(parents=True, exist_ok=True)
    marker = store / "install_root.txt"
    try:
        marker.write_text(str(install_root), encoding="utf-8")
    except OSError:
        pass
    return store


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def ensure_venv_junction(install_root: Path, real_venv: Path) -> None:
    """在安装目录创建 venv 目录联接，指向实际 venv（中文路径必需）。"""
    install_root = install_root.resolve()
    real_venv = real_venv.resolve()
    link = install_root / "venv"
    if _same_path(link, real_venv):
        return
    if link.exists() or link.is_symlink():
        if link.is_dir() and _same_path(link, real_venv):
            return
        if link.is_dir() and not link.is_symlink():
            shutil.rmtree(link, ignore_errors=True)
        else:
            try:
                link.unlink()
            except OSError:
                shutil.rmtree(link, ignore_errors=True)
    real_venv.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        link.symlink_to(real_venv, target_is_directory=True)
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(real_venv)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=flags,
    )
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(
            "无法在安装目录创建 venv 联接。\n"
            f"{link}\n→ {real_venv}\n{tail}"
        )


def subprocess_path(path: Path | str) -> str:
    """传给 subprocess 的路径（普通 Unicode 字符串，不用 \\\\?\\ 前缀）。"""
    return str(Path(path).resolve())
