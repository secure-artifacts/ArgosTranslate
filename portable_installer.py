"""
一键安装：用户选择目录后自动释放程序、创建 venv、安装依赖。
供 setup.exe / launcher 首次运行及「更改安装位置」使用。
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from portable_paths import is_install_root, missing_runtime_files, save_install_pointer
from portable_updater import UPDATE_REL_PATHS
from network_policy import (
    assert_allowed_download_url,
    pip_index_attempts,
    sanitized_install_environ,
)
from win_path_utils import (
    cleanup_broken_install,
    configure_windows_utf8,
    embed_toolchain_dir,
    ensure_venv_junction,
    path_has_non_ascii,
    remove_venv_junction,
    remove_venv_storage,
    subprocess_hide_window_kwargs,
    toolchain_cache_hint,
    venv_storage_dir,
)

configure_windows_utf8()

INSTALL_STEP_TITLES: tuple[str, ...] = (
    "释放程序文件",
    "创建虚拟环境 (venv)",
    "安装翻译依赖 (pip)",
    "安装语言包",
    "应用界面补丁",
)
INSTALL_STEP_COUNT = len(INSTALL_STEP_TITLES)


@dataclass
class InstallProgress:
    step: int
    step_title: str
    step_fraction: float
    message: str

    @property
    def overall_percent(self) -> int:
        frac = ((self.step - 1) + max(0.0, min(1.0, self.step_fraction))) / INSTALL_STEP_COUNT
        return min(100, max(0, int(frac * 100)))


ProgressCb = Callable[[InstallProgress], None]

_EMBED_PYTHON_VERSION = "3.12.10"
_EMBED_PYTHON_URL = (
    f"https://www.python.org/ftp/python/{_EMBED_PYTHON_VERSION}/"
    f"python-{_EMBED_PYTHON_VERSION}-embed-amd64.zip"
)
_GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
_PIP_DEFAULT_TIMEOUT = "600"
_PIP_IDLE_HEARTBEAT_SEC = 15
_PIP_INSTALL_STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("PyQt5 界面库", ("PyQt5>=5.15.0",)),
    (
        "词典与常用组件",
        (
            "beautifulsoup4>=4.12.0",
            "requests>=2.31.0",
            "lxml>=4.9.0",
            "zhconv>=1.4.0",
            "openpyxl>=3.1.0",
        ),
    ),
    (
        "形态分析组件",
        (
            "pymorphy3>=2.0.6",
            "pymorphy3-dicts-ru>=2.4.0",
            "pymorphy3-dicts-uk>=2.4.0",
        ),
    ),
    ("CTranslate2 核心", ("ctranslate2>=4.0,<5",)),
    (
        "Argos 翻译组件",
        ("argostranslate>=1.9.0", "argostranslategui>=1.6.0"),
    ),
)
# (import 名, pip 包) — 启动 / 查词 / 术语常用依赖
_RUNTIME_PIP_SPECS: tuple[tuple[str, str], ...] = (
    ("bs4", "beautifulsoup4>=4.12.0"),
    ("requests", "requests>=2.31.0"),
    ("lxml", "lxml>=4.9.0"),
    ("zhconv", "zhconv>=1.4.0"),
    ("openpyxl", "openpyxl>=3.1.0"),
)
_EMBED_ZIP_NAMES = ("python-embed-amd64.zip", "python-embed.zip")


def dev_source_root() -> Path:
    return Path(__file__).resolve().parent


def bundled_payload_zip() -> Path | None:
    """安装 exe 内嵌的程序包（PyInstaller --add-data app_payload.zip）。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
        for name in ("app_payload.zip", "payload.zip"):
            p = base / name
            if p.is_file():
                return p
    zips = sorted((dev_source_root() / "dist" / "update").glob("*.zip"), reverse=True)
    return zips[0] if zips else None


def install_payload_cache_path(install_root: Path) -> Path:
    return install_root / "data" / "install" / "app_payload.zip"


def _persist_payload_cache(install_root: Path, source: Path) -> None:
    if not source.is_file():
        return
    dest = install_payload_cache_path(install_root)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file() and dest.stat().st_size == source.stat().st_size:
            return
        shutil.copy2(source, dest)
    except OSError:
        pass


def persist_payload_cache(install_root: Path, source: Path) -> None:
    """将 payload zip 缓存到安装目录，供 run_gui / pythonw 启动时补全缺失文件。"""
    _persist_payload_cache(install_root, source)


def resolve_payload_zip(install_root: Path | None = None) -> Path | None:
    """内嵌 zip → 安装目录缓存 → 开发机 dist/update。"""
    bundled = bundled_payload_zip()
    if bundled is not None:
        return bundled
    if install_root is not None:
        cache = install_payload_cache_path(install_root)
        if cache.is_file() and cache.stat().st_size > 10_000:
            return cache
    return bundled_payload_zip()


def verify_installer_bundle() -> None:
    """打包后的安装 exe 必须内嵌 app_payload.zip，否则无法完成首次安装。"""
    if not getattr(sys, "frozen", False):
        return
    if bundled_payload_zip() is None:
        raise RuntimeError(
            "安装程序不完整：缺少内嵌程序包。\n"
            "请从 GitHub Releases 重新下载 ArgosTranslate-vX.Y.Z.exe（只需 exe，无需 zip）。"
        )


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local and not path_has_non_ascii(local):
        return Path(local) / "ArgosTranslate"
    for cand in (Path(r"C:\ArgosTranslate"), Path.home() / "ArgosTranslate"):
        if not path_has_non_ascii(cand):
            return cand
    return Path(local) / "ArgosTranslate" if local else Path.home() / "ArgosTranslate"


def cleanup_failed_install(install_root: Path) -> list[str]:
    """清理失败安装留下的 venv / 联接，便于用户重试。"""
    return cleanup_broken_install(install_root.resolve())


def _emit(
    cb: ProgressCb | None,
    step: int,
    step_fraction: float,
    message: str,
) -> None:
    if not cb:
        return
    title = (
        INSTALL_STEP_TITLES[step - 1]
        if 1 <= step <= INSTALL_STEP_COUNT
        else ""
    )
    cb(
        InstallProgress(
            step=step,
            step_title=title,
            step_fraction=step_fraction,
            message=message,
        )
    )


def _subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    configure_windows_utf8()
    env, _removed = sanitized_install_environ()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    merged = _subprocess_env(env)
    run_cwd = str(cwd.resolve()) if cwd else None
    r = subprocess.run(
        cmd,
        cwd=run_cwd,
        env=merged,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **subprocess_hide_window_kwargs(),
    )
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "")[-2000:]
        cwd_hint = f"\n工作目录：{cwd}" if cwd else ""
        raise RuntimeError(
            f"命令失败 ({r.returncode}): {' '.join(cmd)}{cwd_hint}\n{tail}"
        )


def _python_can_import(py: Path, module: str, *, cwd: Path | None = None) -> bool:
    try:
        _run(
            [str(py), "-c", f"import {module}"],
            cwd=cwd,
        )
        return True
    except RuntimeError:
        return False


def _network_troubleshoot_hint() -> str:
    lines = [
        "请检查：",
        "  · 虚拟机/电脑能否访问 https://www.python.org 与 https://pypi.org",
        "  · Windows 防火墙、杀毒软件是否拦截安装程序",
        "  · 虚拟机网络是否为 NAT/桥接且能上网",
    ]
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        val = os.environ.get(key, "").strip()
        if val and ("127.0.0.1" in val or "localhost" in val.lower()):
            lines.append(
                f"  · 检测到 {key}={val}（本地代理未运行时会失败；安装程序已自动忽略，若仍失败请删除该环境变量）"
            )
    return "\n".join(lines)


def _is_network_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if isinstance(exc, urllib.error.URLError):
        return True
    markers = (
        "urlopen error",
        "10061",
        "10060",
        "10054",
        "timed out",
        "connection refused",
        "connection reset",
        "无法下载",
        "getaddrinfo failed",
        "network is unreachable",
    )
    return any(m in text for m in markers)


def _download(
    url: str,
    dest: Path,
    cb: ProgressCb | None = None,
    *,
    step: int = 2,
    base_frac: float = 0.0,
    span: float = 1.0,
) -> None:
    url = assert_allowed_download_url(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _emit(cb, step, base_frac, f"正在下载：{urlparse(url).netloc}…")

    def rep(block: int, block_size: int, total: int) -> None:
        if total > 0 and cb and block % 16 == 0:
            pct = min(1.0, block * block_size / total)
            _emit(cb, step, base_frac + span * pct, f"正在下载… {int(pct * 100)}%")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ArgosTranslate-Installer/1.0"},
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=120) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total > 0 and cb and done % (256 * 1024 * 16) < len(chunk):
                    pct = min(1.0, done / total)
                    _emit(cb, step, base_frac + span * pct, f"正在下载… {int(pct * 100)}%")
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"无法下载安装组件（网络连接失败）。\n"
            f"地址：{url}\n"
            f"原因：{e}\n\n"
            f"{_network_troubleshoot_hint()}"
        ) from e


def _find_python_launcher() -> list[str] | None:
    for cmd in (
        ["py", "-3.12"],
        ["py", "-3.11"],
        ["py", "-3"],
        ["python"],
        ["python3"],
    ):
        try:
            _run(
                [
                    *cmd,
                    "-c",
                    "import sys, venv; "
                    "assert sys.version_info[:2] >= (3, 10), sys.version",
                ]
            )
            return cmd
        except (RuntimeError, FileNotFoundError):
            continue
    return None


def _venv_is_usable(py: Path) -> bool:
    if not py.is_file():
        return False
    pyw = py.with_name("pythonw.exe")
    if not pyw.is_file():
        return False
    return _python_can_import(py, "pip")


def _pip_index_attempts() -> list[str]:
    return pip_index_attempts()


def _pip_install_cmd(py: Path, req: Path, index_url: str) -> list[str]:
    cmd = [
        str(py),
        "-m",
        "pip",
        "install",
        "-r",
        str(req),
        "--no-warn-script-location",
        "--no-input",
        "--prefer-binary",
        "--default-timeout",
        _PIP_DEFAULT_TIMEOUT,
        "--proxy",
        "",
    ]
    if index_url:
        host = urlparse(index_url).netloc
        cmd.extend(["-i", index_url])
        if host:
            cmd.extend(["--trusted-host", host.split(":")[0]])
    return cmd


def _pip_packages_cmd(
    py: Path,
    packages: tuple[str, ...],
    index_url: str,
    *,
    wheels_dir: Path | None = None,
    offline: bool = False,
) -> list[str]:
    cmd = [
        str(py),
        "-m",
        "pip",
        "install",
        *packages,
        "--no-warn-script-location",
        "--no-input",
        "--prefer-binary",
        "--default-timeout",
        _PIP_DEFAULT_TIMEOUT,
        "--proxy",
        "",
    ]
    if wheels_dir is not None:
        cmd.extend(["--find-links", str(wheels_dir)])
    if offline:
        cmd.append("--no-index")
    elif index_url:
        host = urlparse(index_url).netloc
        cmd.extend(["-i", index_url])
        if host:
            cmd.extend(["--trusted-host", host.split(":")[0]])
    return cmd


def _pip_streaming_run(
    cmd: list[str],
    *,
    cwd: Path,
    cb: ProgressCb | None,
    step: int,
    base_frac: float,
    span: float,
    idle_hint: str,
) -> int:
    """
    运行 pip 并逐行回显；长时间无输出时发心跳（Installing PyQt5 等阶段常静默数分钟）。
    """
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=_subprocess_env({"PYTHONUNBUFFERED": "1"}),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **subprocess_hide_window_kwargs(),
    )
    out_q: queue.Queue[tuple[str, object]] = queue.Queue()

    def _reader() -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                out_q.put(("line", line))
        finally:
            out_q.put(("done", proc.wait()))

    threading.Thread(target=_reader, daemon=True).start()

    lines = 0
    idle_rounds = 0
    sub_frac = base_frac
    while True:
        try:
            kind, payload = out_q.get(timeout=_PIP_IDLE_HEARTBEAT_SEC)
        except queue.Empty:
            idle_rounds += 1
            wait_sec = idle_rounds * _PIP_IDLE_HEARTBEAT_SEC
            sub_frac = min(base_frac + span * 0.98, sub_frac + span * 0.03)
            _emit(
                cb,
                step,
                sub_frac,
                f"{idle_hint}（已等待约 {wait_sec} 秒，仍在进行…）",
            )
            continue
        if kind == "done":
            return int(payload)
        line = str(payload).strip()
        if not line:
            continue
        idle_rounds = 0
        lines += 1
        sub_frac = min(base_frac + span * 0.98, base_frac + span * min(0.95, lines * 0.04))
        short = line if len(line) <= 72 else line[:69] + "…"
        _emit(cb, step, sub_frac, short)


def _pip_install_package(
    py: Path,
    packages: list[str],
    *,
    cwd: Path | None,
    cb: ProgressCb | None,
    step: int,
    base_frac: float,
) -> None:
    req = Path(packages[0]) if len(packages) == 1 and packages[0].endswith(".txt") else None
    last_error = ""
    for index_url in _pip_index_attempts():
        label = index_url or "pypi.org"
        _emit(cb, step, base_frac, f"pip → {label}")
        cmd = (
            _pip_install_cmd(py, req, index_url)
            if req
            else [
                str(py),
                "-m",
                "pip",
                "install",
                *packages,
                "--no-warn-script-location",
                "--default-timeout",
                _PIP_DEFAULT_TIMEOUT,
                "--proxy",
                "",
            ]
        )
        if not req and index_url:
            host = urlparse(index_url).netloc
            cmd.extend(["-i", index_url])
            if host:
                cmd.extend(["--trusted-host", host])
        try:
            _run(cmd, cwd=cwd)
            return
        except RuntimeError as e:
            last_error = str(e)
    raise RuntimeError(
        "pip 安装失败（已尝试 pypi.org 及欧美备用镜像）。\n"
        f"{last_error}\n\n"
        f"{_network_troubleshoot_hint()}\n\n"
        "也可设置 ARGOS_PIP_INDEX_URL 为其他可用源（不得使用中国大陆 / .cn 镜像）。"
    )


def _clear_broken_venv(install_root: Path, real_venv: Path, cb: ProgressCb | None) -> None:
    py_exe = real_venv / "Scripts" / "python.exe"
    if py_exe.is_file() and _venv_is_usable(py_exe):
        return
    if not real_venv.exists() and not (install_root / "venv").exists():
        return
    _emit(cb, 2, 0.02, "检测到损坏或未完成的虚拟环境，正在清理…")
    remove_venv_junction(install_root)
    remove_venv_storage(install_root)


def _enable_embed_site(embed_dir: Path) -> None:
    """取消注释 python*._pth 中的 import site（否则 pip 装上了也无法 -m pip）。"""
    for pth in embed_dir.glob("python*._pth"):
        text = pth.read_text(encoding="utf-8")
        if re.search(r"^\s*import site\s*$", text, re.MULTILINE):
            continue
        text = re.sub(
            r"^\s*#\s*import site\s*$",
            "import site",
            text,
            flags=re.MULTILINE,
        )
        if not re.search(r"^\s*import site\s*$", text, re.MULTILINE):
            text = text.rstrip() + "\nimport site\n"
        pth.write_text(text, encoding="utf-8")


def _bundled_get_pip_script() -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / "get-pip.py"
        if p.is_file():
            return p
    p = dev_source_root() / "installer_assets" / "get-pip.py"
    return p if p.is_file() else None


def _bundled_bootstrap_wheels_dir() -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / "bootstrap_wheels"
        if p.is_dir() and any(p.glob("*.whl")):
            return p
    p = dev_source_root() / "installer_assets" / "bootstrap_wheels"
    if p.is_dir() and any(p.glob("*.whl")):
        return p
    return None


def _bundled_install_wheels_dir() -> Path | None:
    """内嵌 PyQt5 / ctranslate2 / torch 等安装 wheel，避免用户机上下载 200MB+。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / "install_wheels"
        if p.is_dir() and any(p.glob("ctranslate2-*.whl")):
            return p
    p = dev_source_root() / "installer_assets" / "install_wheels"
    if p.is_dir() and any(p.glob("ctranslate2-*.whl")):
        return p
    return None


def _bundled_embed_python_zip() -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
        for name in _EMBED_ZIP_NAMES:
            p = base / name
            if p.is_file():
                return p
    for name in _EMBED_ZIP_NAMES:
        p = dev_source_root() / "installer_assets" / name
        if p.is_file():
            return p
    return None


def _ensure_get_pip_script(dest: Path, cb: ProgressCb | None) -> Path:
    bundled = _bundled_get_pip_script()
    if bundled is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled, dest)
        return dest
    if not dest.is_file():
        _download(_GET_PIP_URL, dest, cb, step=2, base_frac=0.55, span=0.15)
    return dest


def _install_pip_into_embed(py: Path, embed_dir: Path, cb: ProgressCb | None) -> None:
    _enable_embed_site(embed_dir)
    get_pip = _ensure_get_pip_script(embed_dir.parent / "get-pip.py", cb)
    py_arg = str(py)
    get_pip_arg = str(get_pip)
    wheels = _bundled_bootstrap_wheels_dir()
    args = [py_arg, get_pip_arg, "--no-warn-script-location"]
    if wheels is not None:
        _emit(cb, 2, 0.72, "正在配置 pip（离线）…")
        args.extend(["--no-index", f"--find-links={wheels}"])
    else:
        _emit(cb, 2, 0.72, "正在配置 pip…")
    _run(args, cwd=embed_dir)
    if not _python_can_import(py, "pip", cwd=embed_dir):
        _enable_embed_site(embed_dir)
        retry = [*args, "--force-reinstall"]
        _run(retry, cwd=embed_dir)
    if not _python_can_import(py, "pip", cwd=embed_dir):
        raise RuntimeError(
            "便携 Python 未能启用 pip。\n"
            "请删除 C:\\ProgramData\\ArgosTranslate\\embed-toolchain 后重试。"
        )


def _bootstrap_embed_python(embed_dir: Path, cb: ProgressCb | None) -> Path:
    py = embed_dir / "python.exe"
    if not py.is_file():
        zip_path = embed_dir.parent / "python-embed.zip"
        bundled = _bundled_embed_python_zip()
        if bundled is not None:
            _emit(cb, 2, 0.15, "正在解压内置便携 Python…")
            shutil.copy2(bundled, zip_path)
        else:
            _download(_EMBED_PYTHON_URL, zip_path, cb, step=2, base_frac=0.15, span=0.35)
            _emit(cb, 2, 0.52, "正在解压便携 Python…")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(embed_dir)
        zip_path.unlink(missing_ok=True)
    _install_pip_into_embed(py, embed_dir, cb)
    return py


def _create_venv_with_embed(install_root: Path, real_venv: Path, cb: ProgressCb | None) -> Path:
    venv_arg = str(real_venv)
    _emit(cb, 2, 0.1, "正在配置便携 Python 环境…")
    embed = embed_toolchain_dir(install_root)
    py = _bootstrap_embed_python(embed, cb)
    py_arg = str(py)
    _emit(cb, 2, 0.85, "正在创建虚拟环境…")
    try:
        _run([py_arg, "-m", "venv", venv_arg], cwd=embed.parent)
    except RuntimeError:
        _emit(cb, 2, 0.78, "正在安装 virtualenv（需联网访问 pypi.org）…")
        _pip_install_package(
            Path(py_arg),
            ["virtualenv"],
            cwd=embed,
            cb=cb,
            step=2,
            base_frac=0.78,
        )
        _run([py_arg, "-m", "virtualenv", venv_arg], cwd=embed.parent)
    ensure_venv_junction(install_root, real_venv)
    _emit(cb, 2, 1.0, "虚拟环境创建完成。")
    return real_venv / "Scripts" / "python.exe"


def _create_venv(install_root: Path, cb: ProgressCb | None) -> Path:
    install_root = install_root.resolve()
    real_venv = venv_storage_dir(install_root)
    _clear_broken_venv(install_root, real_venv, cb)
    py_exe = real_venv / "Scripts" / "python.exe"
    if py_exe.is_file() and _venv_is_usable(py_exe):
        ensure_venv_junction(install_root, real_venv)
        _emit(cb, 2, 1.0, "虚拟环境已就绪。")
        return py_exe

    venv_arg = str(real_venv)
    _emit(cb, 2, 0.05, "正在检测本机 Python…")
    launcher = _find_python_launcher()
    if launcher:
        _emit(cb, 2, 0.35, "正在用本机 Python 创建虚拟环境…")
        try:
            _run([*launcher, "-m", "venv", venv_arg], cwd=install_root)
            ensure_venv_junction(install_root, real_venv)
            _emit(cb, 2, 1.0, "虚拟环境创建完成。")
            return real_venv / "Scripts" / "python.exe"
        except RuntimeError:
            if real_venv.exists():
                shutil.rmtree(real_venv, ignore_errors=True)
            _emit(
                cb,
                2,
                0.4,
                "本机 Python 创建虚拟环境失败，改用内置便携环境…",
            )

    return _create_venv_with_embed(install_root, real_venv, cb)


def _payload_root_from_zip(zpath: Path, extract_to: Path) -> Path:
    if extract_to.exists():
        shutil.rmtree(extract_to, ignore_errors=True)
    extract_to.mkdir(parents=True)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(extract_to)
    tops = [p for p in extract_to.iterdir() if p.is_dir()]
    return tops[0] if len(tops) == 1 else extract_to


def _copy_payload_item(src: Path, dest: Path) -> None:
    if src.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return
    if src.is_dir():
        if dest.exists() and dest.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
        elif dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            shutil.copytree(src, dest, dirs_exist_ok=True)


def _copy_payload_manifest(
    payload_root: Path,
    install_root: Path,
    cb: ProgressCb | None,
    *,
    step: int = 1,
    base_frac: float = 0.0,
    span: float = 1.0,
) -> None:
    todo = [rel for rel in UPDATE_REL_PATHS if (payload_root / rel).exists()]
    n = max(1, len(todo))
    for i, rel in enumerate(todo):
        _copy_payload_item(payload_root / rel, install_root / rel)
        _emit(
            cb,
            step,
            base_frac + span * (i + 1) / n,
            f"正在释放：{rel}",
        )


def repair_missing_payload_files(
    install_root: Path, cb: ProgressCb | None = None
) -> list[str]:
    """从安装 exe / 本地缓存 / 开发目录补全缺失项。返回仍缺失路径。"""
    _sync_missing_payload_files(install_root, cb)
    return missing_runtime_files(install_root)


def _sync_missing_payload_files(install_root: Path, cb: ProgressCb | None) -> None:
    """已部分释放时补全缺失文件（如 patches/，避免重试安装仍缺补丁）。"""
    missing = [rel for rel in UPDATE_REL_PATHS if not (install_root / rel).exists()]
    if not missing:
        return
    zpath = resolve_payload_zip(install_root)
    if zpath is None:
        src_root = dev_source_root()
        if (src_root / "terminology_bridge.py").is_file():
            _emit(cb, 1, 0.5, "正在补全缺失程序文件…")
            for rel in missing:
                s = src_root / rel
                if s.exists():
                    _copy_payload_item(s, install_root / rel)
            return
        return
    _emit(cb, 1, 0.5, f"正在补全 {len(missing)} 项缺失文件…")
    tmp = install_root / "_payload_sync"
    try:
        payload_root = _payload_root_from_zip(zpath, tmp)
        for rel in missing:
            src = payload_root / rel
            if src.exists():
                _copy_payload_item(src, install_root / rel)
                _emit(cb, 1, 0.9, f"已补全：{rel}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _deploy_payload(install_root: Path, cb: ProgressCb | None) -> None:
    install_root.mkdir(parents=True, exist_ok=True)
    if (install_root / "terminology_bridge.py").is_file():
        _sync_missing_payload_files(install_root, cb)
        _emit(cb, 1, 1.0, "程序文件已就绪。")
        return

    src_root = dev_source_root()
    if not getattr(sys, "frozen", False) and (src_root / "terminology_bridge.py").is_file():
        _emit(cb, 1, 0.05, "正在复制程序文件…")
        todo = [rel for rel in UPDATE_REL_PATHS if (src_root / rel).exists()]
        n = max(1, len(todo))
        for i, rel in enumerate(todo):
            s = src_root / rel
            d = install_root / rel
            if s.is_file():
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, d)
            else:
                shutil.copytree(s, d, dirs_exist_ok=True)
            _emit(cb, 1, (i + 1) / n, f"正在复制：{rel}")
        _emit(cb, 1, 1.0, "程序文件复制完成。")
        return

    zpath = resolve_payload_zip(install_root)
    if zpath is None:
        raise RuntimeError(
            "未找到内嵌程序包。\n"
            "请重新下载 Release 中的 ArgosTranslate-vX.Y.Z.exe（只需 exe，无需 zip）。"
        )

    _emit(cb, 1, 0.05, "正在从内嵌程序包释放文件…")
    tmp = install_root / "_payload_extract"
    payload_root = _payload_root_from_zip(zpath, tmp)
    _copy_payload_manifest(payload_root, install_root, cb, step=1, base_frac=0.2, span=0.75)
    shutil.rmtree(tmp, ignore_errors=True)
    _persist_payload_cache(install_root, zpath)
    _sync_missing_payload_files(install_root, cb)
    _emit(cb, 1, 1.0, "程序文件释放完成。")


def _pip_install(py: Path, install_root: Path, cb: ProgressCb | None) -> None:
    stage_count = len(_PIP_INSTALL_STAGES)
    wheels = _resolve_install_wheels_dir(install_root)
    if wheels is None:
        wheels = _ensure_install_wheels_available(install_root, cb)
    if wheels is not None:
        _emit(
            cb,
            3,
            0.02,
            "正在从安装包内置组件安装（无需联网下载，约 3～10 分钟；解压大组件时可能无新文字）…",
        )
    else:
        _emit(
            cb,
            3,
            0.02,
            "正在联网安装组件（约 5～20 分钟；VM 下载 CTranslate2/PyTorch 可能很慢）…",
        )
    stage_idle_hints = {
        "PyQt5 界面库": "正在解压 PyQt5（体积较大，可能数分钟无新输出）",
        "词典与常用组件": "正在安装查词 / 术语常用组件（beautifulsoup4、requests 等）",
        "形态分析组件": "正在安装 pymorphy3 词典",
        "CTranslate2 核心": "正在解压 CTranslate2（约 1～3 分钟无新输出属正常）",
        "Argos 翻译组件": "正在安装 Argos / Stanza / PyTorch（解压最慢，请耐心等待）",
    }
    for stage_idx, (stage_label, packages) in enumerate(_PIP_INSTALL_STAGES):
        stage_base = 0.05 + (0.90 * stage_idx / stage_count)
        stage_span = 0.90 / stage_count
        idle_hint = stage_idle_hints.get(stage_label, f"仍在安装 {stage_label}")
        success = False
        last_tail = ""
        attempts: list[tuple[str, str, bool]] = []
        if wheels is not None:
            attempts.append(("内置离线包", "", True))
        for index_url in _pip_index_attempts():
            src = urlparse(index_url).netloc if index_url else "pypi.org"
            attempts.append((src, index_url, False))
        for src_label, index_url, offline in attempts:
            _emit(
                cb,
                3,
                stage_base,
                f"[{stage_idx + 1}/{stage_count}] {stage_label} ← {src_label}",
            )
            cmd = _pip_packages_cmd(
                py,
                packages,
                index_url,
                wheels_dir=wheels,
                offline=offline,
            )
            code = _pip_streaming_run(
                cmd,
                cwd=install_root,
                cb=cb,
                step=3,
                base_frac=stage_base,
                span=stage_span,
                idle_hint=idle_hint,
            )
            if code == 0:
                success = True
                break
            last_tail = f"pip 退出码 {code}（{stage_label}，源 {src_label}）"
        if not success:
            raise RuntimeError(
                "pip 安装失败（已尝试内置离线包与 pypi.org 等源）。\n"
                f"{last_tail}\n\n"
                "请检查网络，或通过 ARGOS_PIP_INDEX_URL 指定可用源（不得使用中国大陆 / .cn 镜像）。\n"
                "也可点击「清理并重试」后再次安装。"
            )
    try:
        from native_dll_bootstrap import find_qt_platforms_dir

        if find_qt_platforms_dir(install_root) is None:
            raise RuntimeError(
                "PyQt5 安装不完整：未找到 Qt 平台插件 qwindows.dll。\n"
                "请点击「清理并重试」重新安装；若仍失败，请换英文路径（如 D:\\ArgosTranslate）。"
            )
    except ImportError:
        pass
    for mod, _pkg in _RUNTIME_PIP_SPECS:
        if not _python_can_import(py, mod, cwd=install_root):
            raise RuntimeError(
                f"依赖 {mod} 未安装成功。\n"
                "请点击「清理并重试」重新安装。"
            )
    _emit(cb, 3, 1.0, "翻译依赖安装完成。")


def _resolve_install_wheels_dir(install_root: Path | None = None) -> Path | None:
    bundled = _bundled_install_wheels_dir()
    if bundled is not None:
        return bundled
    if install_root is not None:
        cache = install_root / "data" / "install" / "install_wheels"
        if cache.is_dir() and any(cache.glob("ctranslate2-*.whl")):
            return cache
    return None


def _install_wheels_download_urls(version: str) -> list[str]:
    tag = f"v{version.strip().lstrip('v')}"
    base = f"https://github.com/secure-artifacts/ArgosTranslate/releases/download/{tag}"
    return [
        f"{base}/install_wheels-{tag}.zip",
        f"{base}/ArgosTranslate-{tag}-install_wheels.zip",
        f"{base}/install_wheels.zip",
    ]


def _ensure_install_wheels_available(
    install_root: Path, cb: ProgressCb | None
) -> Path | None:
    """内嵌 wheel → 安装目录缓存 → 从 GitHub Release 下载。"""
    resolved = _resolve_install_wheels_dir(install_root)
    if resolved is not None:
        return resolved

    from app_version import APP_VERSION

    cache = install_root / "data" / "install" / "install_wheels"
    cache.mkdir(parents=True, exist_ok=True)
    zip_path = install_root / "data" / "install" / "install_wheels.zip"
    last_err = ""
    for url in _install_wheels_download_urls(APP_VERSION):
        try:
            _emit(
                cb,
                3,
                0.01,
                "正在下载离线依赖包（约 200MB，仅首次需要；也可改用联网 pip）…",
            )
            _download(url, zip_path, cb, step=3, base_frac=0.02, span=0.06)
            tmp = install_root / "data" / "install" / "_install_wheels_extract"
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
            for whl in tmp.rglob("*.whl"):
                target = cache / whl.name
                if not target.is_file():
                    shutil.copy2(whl, target)
            shutil.rmtree(tmp, ignore_errors=True)
            if any(cache.glob("ctranslate2-*.whl")):
                _emit(cb, 3, 0.08, "离线依赖包已就绪。")
                return cache
        except Exception as e:
            last_err = str(e)
            continue
    if last_err:
        _emit(cb, 3, 0.02, f"离线依赖包下载未成功，将尝试联网 pip…（{last_err[:80]}）")
    return None


def _persist_install_wheels_cache(install_root: Path) -> None:
    """缓存 pip wheel 到安装目录，供后续 pythonw 启动时离线补装依赖。"""
    src = _bundled_install_wheels_dir()
    if src is None:
        return
    dest = install_root / "data" / "install" / "install_wheels"
    try:
        if dest.is_dir() and len(list(dest.glob("*.whl"))) >= len(list(src.glob("*.whl"))):
            return
        dest.mkdir(parents=True, exist_ok=True)
        for whl in src.glob("*.whl"):
            target = dest / whl.name
            if not target.is_file() or target.stat().st_size != whl.stat().st_size:
                shutil.copy2(whl, target)
    except OSError:
        pass


persist_install_wheels_cache = _persist_install_wheels_cache


def _pip_install_missing(
    py: Path,
    install_root: Path,
    packages: tuple[str, ...],
) -> bool:
    if not packages:
        return True
    wheels = _resolve_install_wheels_dir(install_root)
    attempts: list[tuple[str, str, bool]] = []
    if wheels is not None:
        attempts.append(("内置离线包", "", True))
    for index_url in _pip_index_attempts():
        src = urlparse(index_url).netloc if index_url else "pypi.org"
        attempts.append((src, index_url, False))
    for _src, index_url, offline in attempts:
        cmd = _pip_packages_cmd(
            py,
            packages,
            index_url,
            wheels_dir=wheels,
            offline=offline,
        )
        try:
            _run(cmd, cwd=install_root)
            return True
        except RuntimeError:
            continue
    return False


def ensure_runtime_python_deps(install_root: Path) -> None:
    """已安装用户缺运行时 pip 包时静默补装。"""
    py = install_root / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        return
    need: list[str] = []
    for mod, pkg in _RUNTIME_PIP_SPECS:
        if not _python_can_import(py, mod, cwd=install_root):
            need.append(pkg)
    if not need:
        return
    _pip_install_missing(py, install_root, tuple(need))


def ensure_morph_python_deps(install_root: Path) -> None:
    """嵌入 Python 3.12 无法使用原版 pymorphy2；启动时为旧安装补装 pymorphy3。"""
    py = install_root / "venv" / "Scripts" / "python.exe"
    if not py.is_file():
        return
    if _python_can_import(py, "pymorphy3", cwd=install_root):
        return
    _pip_install_missing(
        py,
        install_root,
        (
            "pymorphy3>=2.0.6",
            "pymorphy3-dicts-ru>=2.4.0",
            "pymorphy3-dicts-uk>=2.4.0",
        ),
    )


def ensure_lookup_python_deps(install_root: Path) -> None:
    """兼容旧名。"""
    ensure_runtime_python_deps(install_root)


def apply_gui_patch_to_venv(install_root: Path) -> bool:
    """将 patches/argostranslategui_gui.py 同步到 venv（更新 / 启动时调用）。"""
    patch = install_root / "patches" / "argostranslategui_gui.py"
    dst = (
        install_root
        / "venv"
        / "Lib"
        / "site-packages"
        / "argostranslategui"
        / "gui.py"
    )
    if not patch.is_file() or not dst.parent.is_dir():
        return False
    try:
        shutil.copy2(patch, dst)
        return True
    except OSError:
        return False


def _ensure_language_packages(
    install_root: Path, py: Path, cb: ProgressCb | None
) -> None:
    script = install_root / "ensure_language_packages.py"
    if not script.is_file():
        _sync_missing_payload_files(install_root, cb)
    if not script.is_file():
        _emit(
            cb,
            4,
            1.0,
            "未找到语言包安装脚本，请稍后在软件内「管理语言包」中下载。",
        )
        return

    def _progress(frac: float, msg: str) -> None:
        _emit(cb, 4, max(0.0, min(1.0, frac)), msg)

    env = _subprocess_env(
        {
            "XDG_DATA_HOME": str(install_root / "data" / "local"),
            "XDG_CONFIG_HOME": str(install_root / "data" / "config"),
            "XDG_CACHE_HOME": str(install_root / "data" / "cache"),
            "ARGOS_TRANSLATE_HOME": str(install_root.resolve()),
        }
    )

    try:
        from ensure_language_packages import ensure_default_language_packages

        ensure_default_language_packages(
            install_root,
            py,
            progress=_progress,
            skip_if_sufficient=True,
        )
    except ImportError:
        _emit(cb, 4, 0.05, "正在安装语言包（首次需联网，约 10～40 分钟）…")
        _run(
            [str(py), str(script), str(install_root)],
            cwd=install_root,
            env=env,
        )
        _emit(cb, 4, 1.0, "语言包安装完成。")
    except Exception as e:
        try:
            from ensure_language_packages import has_usable_language_packages
        except ImportError:
            has_usable_language_packages = None  # type: ignore[assignment,misc]
        if has_usable_language_packages and has_usable_language_packages(install_root):
            _emit(
                cb,
                4,
                1.0,
                f"部分语言包未安装（{e}），可在软件内继续下载。",
            )
            return
        if _is_network_error(e):
            raise
        raise RuntimeError(
            f"语言包安装失败：{e}\n\n"
            "请确认网络畅通后重试，或安装完成后在软件内点「管理语言包 → 下载语言包」。"
        ) from e


def _apply_gui_patch(install_root: Path, py: Path, cb: ProgressCb | None) -> None:
    _emit(cb, 5, 0.1, "正在应用界面补丁…")
    if apply_gui_patch_to_venv(install_root):
        _emit(cb, 5, 1.0, "界面补丁已应用。")
        return
    patch = install_root / "patches" / "argostranslategui_gui.py"
    if not patch.is_file():
        _sync_missing_payload_files(install_root, cb)
    if apply_gui_patch_to_venv(install_root):
        _emit(cb, 5, 1.0, "界面补丁已应用。")
        return
    if not patch.is_file():
        raise RuntimeError(
            "安装包不完整：缺少 patches/argostranslategui_gui.py。\n"
            "请重新下载最新 ArgosTranslate-vX.Y.Z.exe，并点击「清理并重试」。"
        )
    tool = install_root / "tools" / "apply_portable_gui_patch.py"
    if tool.is_file():
        _run(
            [str(py), str(tool), "--force"],
            cwd=install_root,
        )
        _emit(cb, 5, 1.0, "界面补丁已应用。")
        return
    _emit(cb, 5, 1.0, "未找到补丁工具，已跳过。")


def install_to(install_root: Path, cb: ProgressCb | None = None) -> Path:
    install_root = install_root.resolve()
    _emit(cb, 1, 0.0, f"安装到：{install_root}")
    try:
        _deploy_payload(install_root, cb)
        py = _create_venv(install_root, cb)
        _pip_install(py, install_root, cb)
        _persist_install_wheels_cache(install_root)
        try:
            from win_path_utils import ensure_packages_junction

            ensure_packages_junction(install_root)
        except ImportError:
            pass
        _ensure_language_packages(install_root, py, cb)
        _apply_gui_patch(install_root, py, cb)
        write_version = install_root / "version.json"
        if not write_version.is_file():
            try:
                from app_version import write_version_json

                write_version_json(install_root)
            except Exception:
                pass
        if not is_install_root(install_root):
            raise RuntimeError("安装未完成：缺少 venv 或程序文件。")
        still = missing_runtime_files(install_root)
        if still:
            raise RuntimeError(
                "安装不完整，缺少程序文件：\n"
                + "\n".join(f"  - {n}" for n in still)
                + "\n\n请用最新版安装 exe 点「清理并重试」，或删除安装目录后重装。"
            )
        save_install_pointer(install_root)
        try:
            from app_icon_utils import ensure_windows_launch_entries

            ensure_windows_launch_entries(install_root)
        except Exception:
            pass
        _emit(cb, 5, 1.0, "安装完成，即将启动软件。")
        return install_root
    except Exception as e:
        if not is_install_root(install_root):
            cleanup_broken_install(install_root)
        if _is_network_error(e):
            raise
        hint = toolchain_cache_hint()
        raise RuntimeError(
            f"{e}\n\n若仍失败，可手动删除以下缓存后重试：\n{hint}"
        ) from e


def _launch_app_impl(install_root: Path) -> bool:
    """启动已安装的 GUI（优先 os.startfile，避免安装 exe 退出时带走子进程）。"""
    install_root = install_root.resolve()
    configure_windows_utf8()
    for rel in ("run_gui.bat", "本地翻译器.bat", "本地翻译器.exe"):
        cand = install_root / rel
        if cand.is_file():
            try:
                os.startfile(str(cand))
                return True
            except OSError:
                pass
    pyw = install_root / "venv" / "Scripts" / "pythonw.exe"
    script = install_root / "portable_launcher.py"
    if not pyw.is_file() or not script.is_file():
        return False
    env = _subprocess_env()
    env["XDG_DATA_HOME"] = str(install_root / "data" / "local")
    env["XDG_CONFIG_HOME"] = str(install_root / "data" / "config")
    env["XDG_CACHE_HOME"] = str(install_root / "data" / "cache")
    env["ARGOS_TRANSLATE_HOME"] = str(install_root)
    try:
        from native_dll_bootstrap import runtime_env_for_root

        env.update(runtime_env_for_root(install_root))
    except ImportError:
        pass
    try:
        popen_kw: dict = {
            "args": [str(pyw), str(script)],
            "cwd": str(install_root),
            "env": env,
            "close_fds": True,
        }
        if sys.platform == "win32":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            si = subprocess.STARTUPINFO()
            si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
            si.wShowWindow = 0
            popen_kw["creationflags"] = flags
            popen_kw["startupinfo"] = si
        subprocess.Popen(**popen_kw)
        return True
    except OSError:
        return False


def _launch_app_worker(install_root: Path, delay_sec: float) -> None:
    if delay_sec > 0:
        time.sleep(delay_sec)
    if not _launch_app_impl(install_root):
        log_dir = install_root / "data" / "logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "launch_errors.log").write_text(
                "安装/更新完成后自动启动失败。"
                "请手动运行 run_gui.bat 或桌面快捷方式。\n",
                encoding="utf-8",
            )
        except OSError:
            pass


def launch_app(install_root: Path) -> bool:
    """
    安装/更新完成后启动主程序。
    从 PyInstaller 安装 exe 调用时延迟启动，避免父进程退出带走子进程。
    """
    install_root = install_root.resolve()
    delay = 1.0 if getattr(sys, "frozen", False) else 0.0
    if delay > 0:
        threading.Thread(
            target=_launch_app_worker,
            args=(install_root, delay),
            name="post-install-launch",
            daemon=False,
        ).start()
        return True
    return _launch_app_impl(install_root)


def notify_launch_failed(install_root: Path) -> None:
    bat = install_root / "run_gui.bat"
    msg = (
        "安装已完成，但未能自动打开软件。\n\n"
        f"请手动双击运行：\n{bat}\n\n"
        "或从开始菜单 / 桌面快捷方式打开「本地翻译器」。"
    )
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, msg, "本地翻译器", 0x30)
    else:
        print(msg, file=sys.stderr)


def ensure_installed(
    install_root: Path | None = None,
    *,
    progress: ProgressCb | None = None,
) -> Path | None:
    if install_root is not None and is_install_root(install_root):
        save_install_pointer(install_root)
        return install_root.resolve()

    from portable_paths import find_portable_root, load_install_pointer

    root = find_portable_root()
    if is_install_root(root):
        save_install_pointer(root)
        return root

    saved = load_install_pointer()
    if saved and is_install_root(saved):
        return saved

    if install_root is None:
        return None
    try:
        return install_to(install_root, progress)
    except Exception as e:
        if progress:
            progress(
                InstallProgress(
                    step=1,
                    step_title="安装失败",
                    step_fraction=0.0,
                    message=str(e),
                )
            )
        raise


def relocate_pointer(new_root: Path) -> bool:
    new_root = new_root.resolve()
    if is_install_root(new_root):
        save_install_pointer(new_root)
        return True
    return False
