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


def subprocess_hide_window_kwargs(*, detached: bool = False) -> dict:
    """Windows 子进程不弹出 cmd 黑窗（安装 pip / mklink / 启动 pythonw 等）。"""
    if sys.platform != "win32":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    if detached:
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    si = subprocess.STARTUPINFO()
    si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
    si.wShowWindow = 0  # SW_HIDE
    return {"creationflags": flags, "startupinfo": si}


def path_has_non_ascii(path: Path | str) -> bool:
    try:
        str(path).encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def path_for_shortcut(path: Path) -> str:
    """cscript 写 .lnk 时含中文的路径易乱码，优先 8.3 短路径。"""
    text = str(path.resolve())
    if not path_has_non_ascii(text):
        return text
    try:
        import ctypes
        from ctypes import wintypes

        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        n = ctypes.windll.kernel32.GetShortPathNameW(text, buf, wintypes.MAX_PATH)
        if n and buf.value and not path_has_non_ascii(buf.value):
            return buf.value
    except Exception:
        pass
    return text


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
    r = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(real_venv)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **subprocess_hide_window_kwargs(),
    )
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(
            "无法在安装目录创建 venv 联接。\n"
            f"{link}\n→ {real_venv}\n{tail}"
        )


def argos_packages_link(install_root: Path) -> Path:
    return (
        install_root.resolve()
        / "data"
        / "local"
        / "argos-translate"
        / "packages"
    )


def argos_packages_storage_dir(install_root: Path) -> Path:
    """语言包实际目录；非 ASCII 安装路径时放在 ProgramData。"""
    install_root = install_root.resolve()
    if not _needs_external_toolchain_store(install_root):
        link = argos_packages_link(install_root)
        link.mkdir(parents=True, exist_ok=True)
        return link

    key = hashlib.sha256(str(install_root).encode("utf-8")).hexdigest()[:16]
    store = _external_toolchain_store(install_root) / "packages" / key
    store.mkdir(parents=True, exist_ok=True)
    marker = store / "install_root.txt"
    try:
        marker.write_text(str(install_root), encoding="utf-8")
    except OSError:
        pass
    return store


def _copy_tree_merge(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if target.is_dir():
                _copy_tree_merge(item, target)
            else:
                shutil.copytree(item, target, dirs_exist_ok=True)
        elif item.is_file() and not target.is_file():
            shutil.copy2(item, target)


def ensure_packages_junction(install_root: Path) -> Path:
    """
    语言包目录联接：SentencePiece/CTranslate2 无法打开中文路径下的 model 文件。
    返回实际 packages 目录（供 ARGOS_PACKAGES_DIR）。
    """
    install_root = install_root.resolve()
    real = argos_packages_storage_dir(install_root)
    if not _needs_external_toolchain_store(install_root):
        return real

    link = argos_packages_link(install_root)
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        if _same_path(link, real):
            return real
        if link.is_dir() and not link.is_symlink():
            try:
                if any(link.iterdir()):
                    _copy_tree_merge(link, real)
            except OSError:
                pass
            shutil.rmtree(link, ignore_errors=True)
        else:
            try:
                link.unlink()
            except OSError:
                shutil.rmtree(link, ignore_errors=True)

    real.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        link.symlink_to(real, target_is_directory=True)
        return real

    r = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(real)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **subprocess_hide_window_kwargs(),
    )
    if r.returncode != 0 and not _same_path(link, real):
        tail = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(
            "无法为语言包创建目录联接（中文安装路径必需）。\n"
            f"{link}\n→ {real}\n{tail}"
        )
    return real


def apply_argos_packages_env(install_root: Path, env: dict[str, str] | None = None) -> Path:
    """设置 ARGOS_PACKAGES_DIR，并在已 import 时同步 argostranslate.settings。"""
    target = env if env is not None else os.environ
    pkg_dir = ensure_packages_junction(install_root)
    target["ARGOS_PACKAGES_DIR"] = str(pkg_dir)
    try:
        import argostranslate.settings as s

        s.package_data_dir = Path(pkg_dir)
        os.makedirs(s.package_data_dir, exist_ok=True)
    except ImportError:
        pass
    return pkg_dir


def subprocess_path(path: Path | str) -> str:
    """传给 subprocess 的路径（普通 Unicode 字符串，不用 \\\\?\\ 前缀）。"""
    return str(Path(path).resolve())


def remove_venv_junction(install_root: Path) -> None:
    """删除安装目录下的 venv 目录联接（不删除实际 venv 存储目录）。"""
    install_root = install_root.resolve()
    link = install_root / "venv"
    if not link.exists() and not link.is_symlink():
        return
    real_venv = venv_storage_dir(install_root)
    if link.is_dir() and not link.is_symlink() and not _same_path(link, real_venv):
        shutil.rmtree(link, ignore_errors=True)
        return
    if link.is_symlink() or (link.is_dir() and _same_path(link, real_venv)):
        try:
            link.unlink()
        except OSError:
            shutil.rmtree(link, ignore_errors=True)


def remove_venv_storage(install_root: Path) -> None:
    """删除该安装路径对应的实际 venv 目录。"""
    store = venv_storage_dir(install_root).resolve()
    if store.is_dir():
        shutil.rmtree(store, ignore_errors=True)


def toolchain_cache_hint() -> str:
    """安装失败时提示用户可手动清理的缓存路径。"""
    lines = [
        r"C:\ProgramData\ArgosTranslate\embed-toolchain",
        r"C:\ProgramData\ArgosTranslate\venvs",
    ]
    local = app_data_argos_dir()
    lines.append(str(local / "embed-toolchain"))
    lines.append(str(local / "venvs"))
    return "\n".join(f"  · {p}" for p in lines)


def cleanup_broken_install(install_root: Path) -> list[str]:
    """
    清理未完成或损坏的安装产物（保留已释放的程序文件与 data/）。
    返回已清理项的说明列表。
    """
    install_root = install_root.resolve()
    cleaned: list[str] = []
    link = install_root / "venv"
    if link.exists() or link.is_symlink():
        remove_venv_junction(install_root)
        cleaned.append(f"已删除：{link}")
    store = venv_storage_dir(install_root)
    if store.is_dir():
        remove_venv_storage(install_root)
        cleaned.append(f"已删除：{store}")
    bootstrap = install_root / "_bootstrap"
    complete = (install_root / "terminology_bridge.py").is_file() and (
        install_root / "venv" / "Scripts" / "pythonw.exe"
    ).is_file()
    if bootstrap.is_dir() and not complete:
        shutil.rmtree(bootstrap, ignore_errors=True)
        cleaned.append(f"已删除：{bootstrap}")
    return cleaned
