"""便携版安装目录定位与安装完整性检查。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_install_root(path: Path) -> bool:
    return (path / "terminology_bridge.py").is_file() and (
        path / "venv" / "Scripts" / "pythonw.exe"
    ).is_file()


# 主界面启动时必须在安装根目录存在（缺一会弹警告或无法使用功能）
REQUIRED_RUNTIME_FILES: tuple[str, ...] = (
    "terminology_bridge.py",
    "translation_tab_page.py",
    "portable_ui_theme.py",
    "native_dll_bootstrap.py",
    "bkrs_parser.py",
    "word_info_dialog.py",
    "glossary_alternatives.py",
    "glossary_cell_sanitize.py",
    "glossary_target_edit.py",
    "patches/argostranslategui_gui.py",
)


def missing_runtime_files(install_root: Path) -> list[str]:
    root = install_root.resolve()
    return [name for name in REQUIRED_RUNTIME_FILES if not (root / name).is_file()]


def resolve_install_root() -> Path | None:
    """
    解析便携版安装根目录。
    venv 联接在 ProgramData 时，gui.py 的 __file__ 在联接目标内，不能靠向上 walk。
    """
    def ok(path: Path) -> bool:
        try:
            return is_install_root(path)
        except OSError:
            return False

    custom = os.environ.get("ARGOS_TRANSLATE_HOME", "").strip()
    if custom:
        p = Path(custom).expanduser()
        if ok(p):
            return p.resolve()

    saved = load_install_pointer()
    if saved is not None:
        return saved

    try:
        cwd = Path.cwd()
        if ok(cwd):
            return cwd.resolve()
    except OSError:
        pass

    for entry in list(sys.path):
        if not entry:
            continue
        try:
            p = Path(entry)
            if ok(p):
                return p.resolve()
        except OSError:
            continue

    start = Path(__file__).resolve().parent
    cur = start
    for _ in range(12):
        if ok(cur):
            return cur.resolve()
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


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
    resolved = resolve_install_root()
    if resolved is not None:
        return resolved

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
        "可在软件顶栏「安装位置」或「检查更新 → 安装位置…」中查看与更改。"
    )
