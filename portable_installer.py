"""
一键安装：用户选择目录后自动释放程序、创建 venv、安装依赖。
供 setup.exe / launcher 首次运行及「更改安装位置」使用。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from portable_paths import is_install_root, save_install_pointer
from portable_updater import UPDATE_REL_PATHS
from win_path_utils import (
    configure_windows_utf8,
    embed_toolchain_dir,
    subprocess_path,
)

configure_windows_utf8()

INSTALL_STEP_TITLES: tuple[str, ...] = (
    "释放程序文件",
    "创建虚拟环境 (venv)",
    "安装翻译依赖 (pip)",
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


def dev_source_root() -> Path:
    return Path(__file__).resolve().parent


def bundled_payload_zip() -> Path | None:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
        for name in ("app_payload.zip", "payload.zip"):
            p = base / name
            if p.is_file():
                return p
    zips = sorted((dev_source_root() / "dist" / "update").glob("*.zip"), reverse=True)
    return zips[0] if zips else None


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return Path(local) / "ArgosTranslate"
    return Path.home() / "ArgosTranslate"


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
    env = os.environ.copy()
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
    run_cwd = subprocess_path(cwd) if cwd else None
    r = subprocess.run(
        cmd,
        cwd=run_cwd,
        env=merged,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
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


def _download(
    url: str,
    dest: Path,
    cb: ProgressCb | None = None,
    *,
    step: int = 2,
    base_frac: float = 0.0,
    span: float = 1.0,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _emit(cb, step, base_frac, f"正在下载…")

    def rep(block: int, block_size: int, total: int) -> None:
        if total > 0 and cb and block % 16 == 0:
            pct = min(1.0, block * block_size / total)
            _emit(cb, step, base_frac + span * pct, f"正在下载… {int(pct * 100)}%")

    urllib.request.urlretrieve(url, dest, rep)


def _find_python_launcher() -> list[str] | None:
    for cmd in (
        ["py", "-3.12"],
        ["py", "-3.11"],
        ["py", "-3"],
        ["python"],
        ["python3"],
    ):
        try:
            _run([*cmd, "-c", "import sys; print(sys.version_info[:2])"])
            return cmd
        except (RuntimeError, FileNotFoundError):
            continue
    return None


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
    _emit(cb, 2, 0.72, "正在配置 pip…")
    py_arg = subprocess_path(py)
    get_pip_arg = subprocess_path(get_pip)
    _run(
        [py_arg, get_pip_arg, "--no-warn-script-location"],
        cwd=embed_dir,
    )
    if not _python_can_import(py, "pip", cwd=embed_dir):
        _enable_embed_site(embed_dir)
        _run(
            [py_arg, get_pip_arg, "--no-warn-script-location", "--force-reinstall"],
            cwd=embed_dir,
        )
    if not _python_can_import(py, "pip", cwd=embed_dir):
        raise RuntimeError(
            "便携 Python 未能启用 pip。\n"
            "请删除安装目录下的 _bootstrap 文件夹后重试；"
            "若安装路径含中文，也可删除 "
            "%LOCALAPPDATA%\\ArgosTranslate\\embed-toolchain 后重装。"
        )


def _bootstrap_embed_python(embed_dir: Path, cb: ProgressCb | None) -> Path:
    py = embed_dir / "python.exe"
    if not py.is_file():
        zip_path = embed_dir.parent / "python-embed.zip"
        _download(_EMBED_PYTHON_URL, zip_path, cb, step=2, base_frac=0.15, span=0.35)
        _emit(cb, 2, 0.52, "正在解压便携 Python…")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(embed_dir)
        zip_path.unlink(missing_ok=True)
    _install_pip_into_embed(py, embed_dir, cb)
    return py


def _create_venv(install_root: Path, cb: ProgressCb | None) -> Path:
    venv = install_root / "venv"
    if (venv / "Scripts" / "python.exe").is_file():
        _emit(cb, 2, 1.0, "虚拟环境已存在，跳过创建。")
        return venv / "Scripts" / "python.exe"

    _emit(cb, 2, 0.05, "正在检测本机 Python…")
    launcher = _find_python_launcher()
    venv_arg = subprocess_path(venv)
    if launcher:
        _emit(cb, 2, 0.35, "正在用本机 Python 创建虚拟环境…")
        _run([*launcher, "-m", "venv", venv_arg], cwd=install_root)
        _emit(cb, 2, 1.0, "虚拟环境创建完成。")
        return venv / "Scripts" / "python.exe"

    _emit(cb, 2, 0.1, "本机未检测到 Python，正在下载便携运行环境（约 25MB）…")
    embed = embed_toolchain_dir(install_root)
    py = _bootstrap_embed_python(embed, cb)
    py_arg = subprocess_path(py)
    get_pip_arg = subprocess_path(embed.parent / "get-pip.py")
    _emit(cb, 2, 0.78, "正在安装 virtualenv…")
    _run(
        [py_arg, "-m", "pip", "install", "virtualenv", "--no-warn-script-location"],
        cwd=embed,
    )
    _emit(cb, 2, 0.9, "正在创建虚拟环境…")
    _run([py_arg, "-m", "virtualenv", venv_arg], cwd=install_root)
    _emit(cb, 2, 1.0, "虚拟环境创建完成。")
    return venv / "Scripts" / "python.exe"


def _deploy_payload(install_root: Path, cb: ProgressCb | None) -> None:
    install_root.mkdir(parents=True, exist_ok=True)
    if (install_root / "terminology_bridge.py").is_file():
        _emit(cb, 1, 1.0, "程序文件已存在，跳过释放。")
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

    zpath = bundled_payload_zip()
    if zpath is None:
        raise RuntimeError("未找到内置程序包 app_payload.zip，请重新下载安装程序。")

    _emit(cb, 1, 0.05, "正在解压内置程序包…")
    tmp = install_root / "_payload_extract"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(tmp)
    tops = [p for p in tmp.iterdir() if p.is_dir()]
    payload_root = tops[0] if len(tops) == 1 else tmp
    items = list(payload_root.iterdir())
    n = max(1, len(items))
    for i, item in enumerate(items):
        dest = install_root / item.name
        if dest.exists() and dest.is_dir():
            shutil.rmtree(dest, ignore_errors=True)
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
        _emit(cb, 1, 0.2 + 0.8 * (i + 1) / n, f"正在释放：{item.name}")
    shutil.rmtree(tmp, ignore_errors=True)
    _emit(cb, 1, 1.0, "程序文件释放完成。")


def _pip_install(py: Path, install_root: Path, cb: ProgressCb | None) -> None:
    req = install_root / "requirements-install.txt"
    if not req.is_file():
        req = dev_source_root() / "requirements-install.txt"
    _emit(
        cb,
        3,
        0.05,
        "正在安装翻译组件（首次约 3～8 分钟，需联网）…",
    )
    proc = subprocess.Popen(
        [
            subprocess_path(py),
            "-m",
            "pip",
            "install",
            "-r",
            subprocess_path(req),
            "--no-warn-script-location",
        ],
        cwd=subprocess_path(install_root),
        env=_subprocess_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    lines = 0
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        lines += 1
        frac = min(0.95, 0.08 + lines * 0.015)
        short = line if len(line) <= 72 else line[:69] + "…"
        _emit(cb, 3, frac, short)
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"pip 安装失败，退出码 {code}")
    _emit(cb, 3, 1.0, "翻译依赖安装完成。")


def _apply_gui_patch(install_root: Path, py: Path, cb: ProgressCb | None) -> None:
    _emit(cb, 4, 0.1, "正在应用界面补丁…")
    patch = install_root / "patches" / "argostranslategui_gui.py"
    dst = (
        install_root
        / "venv"
        / "Lib"
        / "site-packages"
        / "argostranslategui"
        / "gui.py"
    )
    if patch.is_file() and dst.parent.is_dir():
        shutil.copy2(patch, dst)
        _emit(cb, 4, 1.0, "界面补丁已应用。")
        return
    tool = install_root / "tools" / "apply_portable_gui_patch.py"
    if tool.is_file():
        _run(
            [subprocess_path(py), subprocess_path(tool)],
            cwd=install_root,
        )
        _emit(cb, 4, 1.0, "界面补丁已应用。")
        return
    _emit(cb, 4, 1.0, "未找到补丁文件，已跳过。")


def install_to(install_root: Path, cb: ProgressCb | None = None) -> Path:
    install_root = install_root.resolve()
    _emit(cb, 1, 0.0, f"安装到：{install_root}")
    _deploy_payload(install_root, cb)
    py = _create_venv(install_root, cb)
    _pip_install(py, install_root, cb)
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
    save_install_pointer(install_root)
    _emit(cb, 4, 1.0, "安装完成，即将启动软件。")
    return install_root


def launch_app(install_root: Path) -> int:
    configure_windows_utf8()
    pyw = install_root / "venv" / "Scripts" / "pythonw.exe"
    script = install_root / "portable_launcher.py"
    env = _subprocess_env()
    env["XDG_DATA_HOME"] = str(install_root / "data" / "local")
    env["XDG_CONFIG_HOME"] = str(install_root / "data" / "config")
    env["XDG_CACHE_HOME"] = str(install_root / "data" / "cache")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) if sys.platform == "win32" else 0
    subprocess.Popen(
        [subprocess_path(pyw), subprocess_path(script)],
        cwd=subprocess_path(install_root),
        env=env,
        creationflags=flags,
        close_fds=True,
    )
    return 0


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
