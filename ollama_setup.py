"""
Ollama 引擎与 Qwen 模型的检测、下载、安装（供首次启动向导使用）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

from ollama_translate import base_url, model_name, use_ollama_backend

ProgressCB = Callable[[int, int], None] | None
StatusCB = Callable[[str], None] | None
LineCB = Callable[[str], None] | None

OLLAMA_SETUP_URL = (
    "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe"
)
OLLAMA_SETUP_MIN_BYTES = 50_000_000
_PULL_PERCENT_RE = re.compile(r"(\d+)\s*%")


def portable_root() -> Path:
    return Path(__file__).resolve().parent


def _log(line: str) -> None:
    try:
        log_dir = portable_root() / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "ollama_setup.log", "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except OSError:
        pass


def _emit(cb: StatusCB, msg: str) -> None:
    if cb is not None:
        cb(msg)


def find_ollama_executable() -> Path | None:
    found = shutil.which("ollama")
    if found:
        return Path(found)
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        if local:
            for name in ("ollama.exe", "Ollama.exe"):
                cand = Path(local) / "Programs" / "Ollama" / name
                if cand.is_file():
                    return cand
    return None


def find_ollama_tray_app() -> Path | None:
    if sys.platform != "win32":
        return None
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        return None
    cand = Path(local) / "Programs" / "Ollama" / "Ollama.exe"
    return cand if cand.is_file() else None


def is_ollama_installed() -> bool:
    return find_ollama_executable() is not None


def is_ollama_server_running() -> bool:
    try:
        req = urllib.request.Request(f"{base_url()}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def wait_for_server(timeout_sec: float = 90.0, poll_sec: float = 1.5) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if is_ollama_server_running():
            return True
        time.sleep(poll_sec)
    return False


def start_ollama_app() -> bool:
    tray = find_ollama_tray_app()
    if tray is not None:
        try:
            subprocess.Popen(
                [str(tray)],
                cwd=str(tray.parent),
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                close_fds=True,
            )
            _log(f"started tray app: {tray}")
            return True
        except OSError as exc:
            _log(f"start tray failed: {exc}")
    exe = find_ollama_executable()
    if exe is None:
        return False
    try:
        subprocess.Popen(
            [str(exe), "serve"],
            cwd=str(exe.parent),
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
        _log(f"started serve: {exe}")
        return True
    except OSError as exc:
        _log(f"start serve failed: {exc}")
        return False


def get_installed_model_names() -> list[str]:
    try:
        req = urllib.request.Request(f"{base_url()}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("models") or []
        out: list[str] = []
        for item in models:
            if isinstance(item, dict):
                name = (item.get("name") or "").strip()
                if name:
                    out.append(name)
        return out
    except Exception:
        return []


def is_model_available(model: str | None = None) -> bool:
    want = (model or model_name()).strip()
    if not want:
        return False
    base = want.split(":")[0]
    for name in get_installed_model_names():
        n = name.strip()
        if n == want or n.startswith(want + ":") or n.split(":")[0] == base:
            return True
    return False


def get_setup_status(model: str | None = None) -> dict[str, object]:
    m = model or model_name()
    return {
        "model": m,
        "ollama_installed": is_ollama_installed(),
        "ollama_running": is_ollama_server_running(),
        "model_ready": is_model_available(m),
        "ollama_path": str(find_ollama_executable() or ""),
    }


def needs_setup(model: str | None = None) -> bool:
    if not use_ollama_backend():
        return False
    st = get_setup_status(model)
    return not (
        st["ollama_installed"] and st["ollama_running"] and st["model_ready"]
    )


def ollama_installer_cache_path(root: Path | None = None) -> Path:
    root = root or portable_root()
    cache = root / "data" / "cache" / "ollama"
    cache.mkdir(parents=True, exist_ok=True)
    return cache / "OllamaSetup.exe"


def download_ollama_installer(
    root: Path | None = None,
    *,
    status_cb: StatusCB = None,
    progress_cb: ProgressCB = None,
) -> Path:
    root = root or portable_root()
    dest = ollama_installer_cache_path(root)
    if dest.is_file() and dest.stat().st_size >= OLLAMA_SETUP_MIN_BYTES:
        _emit(status_cb, "安装包已缓存，跳过下载。")
        return dest

    _emit(status_cb, "正在从 Ollama 官方下载引擎安装包（约 2 GB）…")
    _log(f"download start: {OLLAMA_SETUP_URL}")

    req = urllib.request.Request(
        OLLAMA_SETUP_URL,
        headers={"User-Agent": "ArgosTranslate-OllamaSetup/1.0"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        chunk = 1024 * 256
        tmp = dest.with_suffix(".exe.part")
        with open(tmp, "wb") as out:
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                out.write(buf)
                read += len(buf)
                if progress_cb is not None and total > 0:
                    progress_cb(read, total)
        tmp.replace(dest)

    if dest.stat().st_size < OLLAMA_SETUP_MIN_BYTES:
        raise RuntimeError("Ollama 安装包下载不完整，请检查网络后重试。")
    _emit(status_cb, "引擎安装包下载完成。")
    _log(f"download ok: {dest} ({dest.stat().st_size} bytes)")
    return dest


def run_ollama_installer(installer_path: Path, *, silent: bool = False) -> None:
    if not installer_path.is_file():
        raise FileNotFoundError(installer_path)
    args = [str(installer_path)]
    if silent and sys.platform == "win32":
        args.append("/S")
    _log(f"run installer: {' '.join(args)}")
    subprocess.Popen(args, close_fds=True)


def ensure_ollama_running(*, status_cb: StatusCB = None) -> bool:
    if is_ollama_server_running():
        return True
    if not is_ollama_installed():
        return False
    _emit(status_cb, "正在启动 Ollama 引擎…")
    if not start_ollama_app():
        return False
    ok = wait_for_server(timeout_sec=120.0)
    if ok:
        _emit(status_cb, "Ollama 引擎已就绪。")
    return ok


def pull_model(
    model: str | None = None,
    *,
    status_cb: StatusCB = None,
    line_cb: LineCB = None,
    progress_cb: ProgressCB = None,
) -> None:
    m = (model or model_name()).strip()
    exe = find_ollama_executable()
    if exe is None:
        raise RuntimeError("未找到 Ollama，请先安装引擎。")
    if not ensure_ollama_running(status_cb=status_cb):
        raise RuntimeError("Ollama 未运行，请从开始菜单打开 Ollama 后重试。")

    _emit(status_cb, f"正在下载翻译模型 {m}（约 4.7 GB，仅需一次）…")
    _log(f"pull start: {m}")

    proc = subprocess.Popen(
        [str(exe), "pull", m],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    last_pct = -1
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            _log(line)
            if line_cb is not None:
                line_cb(line)
            m_pct = _PULL_PERCENT_RE.search(line)
            if m_pct and progress_cb is not None:
                pct = int(m_pct.group(1))
                if pct != last_pct:
                    last_pct = pct
                    progress_cb(pct, 100)
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"模型下载失败（退出码 {code}）。")
    if not is_model_available(m):
        raise RuntimeError("模型下载完成但未检测到，请重启 Ollama 后重试。")
    _emit(status_cb, f"模型 {m} 已就绪，可以离线翻译。")
    _log(f"pull ok: {m}")
