"""
Microsoft Visual C++ 2015-2022 Redistributable (x64) — download and silent install.

Uses only Microsoft global official URLs (download.visualstudio.microsoft.com via aka.ms).
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

# Microsoft official global redirect (Visual Studio 2015-2022 x64 runtime)
VCREDIST_X64_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
VCREDIST_MIN_BYTES = 20_000_000
STATUS_CB = Callable[[str], None] | None


def is_vcredist_x64_installed() -> bool:
    """检测本机是否已注册 VC++ 2015-2022 x64 运行库。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
    except ImportError:
        return False
    subkeys = (
        r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
    )
    for subkey in subkeys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as key:
                installed, _ = winreg.QueryValueEx(key, "Installed")
                if int(installed) == 1:
                    return True
        except OSError:
            continue
    return False


def is_torch_dll_init_error(message: str) -> bool:
    m = (message or "").lower()
    return "1114" in message or "c10.dll" in m or (
        "dll" in m and "torch" in m and "初始化" in message
    )


def _log(portable_root: Path, line: str) -> None:
    try:
        log_dir = portable_root / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "vcredist_install.log"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except OSError:
        pass


def _emit(status_cb: STATUS_CB, msg: str) -> None:
    if status_cb is not None:
        status_cb(msg)


def download_vcredist_x64(
    portable_root: Path,
    *,
    status_cb: STATUS_CB = None,
) -> Path:
    """Download vc_redist.x64.exe into data/cache."""
    cache = portable_root / "data" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / "vc_redist.x64.exe"
    _emit(status_cb, "正在从 Microsoft 官方服务器下载运行库…")
    _log(portable_root, f"download start: {VCREDIST_X64_URL}")

    req = urllib.request.Request(
        VCREDIST_X64_URL,
        headers={
            "User-Agent": "ArgosTranslate-Portable/1.0",
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except urllib.error.URLError as e:
        raise OSError(f"下载失败：{e}") from e

    if len(data) < VCREDIST_MIN_BYTES:
        raise OSError(
            f"下载文件过小（{len(data)} 字节），可能未完整下载，请检查网络后重试。"
        )

    dest.write_bytes(data)
    _log(portable_root, f"download ok: {dest} ({len(data)} bytes)")
    _emit(status_cb, "下载完成，正在启动安装程序…")
    return dest


def _run_installer_windows(exe: Path, portable_root: Path) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "仅支持 Windows。"

    args = "/install /quiet /norestart"
    _log(portable_root, f"install start: {exe} {args}")

    try:
        import ctypes

        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            str(exe.resolve()),
            args,
            None,
            1,
        )
        if rc > 32:
            _log(portable_root, f"ShellExecuteW runas ok: {rc}")
            return True, (
                "安装程序已启动（若弹出 UAC，请选择「是」）。\n"
                "安装完成后请完全退出本程序，再重新运行 run_gui.bat。"
            )
    except Exception as e:
        _log(portable_root, f"ShellExecuteW failed: {e}")

    try:
        proc = subprocess.run(
            [str(exe), "/install", "/quiet", "/norestart"],
            timeout=600,
            capture_output=True,
            text=True,
        )
        _log(
            portable_root,
            f"subprocess exit={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}",
        )
        if proc.returncode in (0, 1638, 3010, 1641):
            return True, (
                "运行库安装已完成（或本机已安装相同版本）。\n"
                "请完全退出后重新运行 run_gui.bat。"
            )
        return False, (
            f"安装程序返回代码 {proc.returncode}。\n"
            f"{proc.stderr or proc.stdout or ''}"
        ).strip()
    except subprocess.TimeoutExpired:
        return False, "安装超时，请稍后手动运行 data\\cache\\vc_redist.x64.exe。"
    except OSError as e:
        return False, str(e)


def download_and_install_vcredist_x64(
    portable_root: Path,
    *,
    status_cb: STATUS_CB = None,
) -> tuple[bool, str]:
    """Download and install VC++ 2015-2022 x64. Returns (success, message)."""
    if sys.platform != "win32":
        return False, "仅 Windows 需要此运行库。"

    exe = portable_root / "data" / "cache" / "vc_redist.x64.exe"
    try:
        if not exe.is_file() or exe.stat().st_size < VCREDIST_MIN_BYTES:
            exe = download_vcredist_x64(portable_root, status_cb=status_cb)
        else:
            _emit(status_cb, "使用已缓存的安装包…")
        ok, msg = _run_installer_windows(exe, portable_root)
        return ok, msg
    except OSError as e:
        _log(portable_root, f"error: {e}")
        return False, str(e)
