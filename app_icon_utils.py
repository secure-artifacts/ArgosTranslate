"""应用图标：任务栏 / 窗口 / 开始菜单快捷方式。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_USER_MODEL_ID = "ArgosTranslate.Portable.LocalTranslator.1"
_SHORTCUT_NAME = "本地翻译器（俄乌）.lnk"


def set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID
        )
    except Exception:
        pass


def find_app_icon(root: Path | None) -> Path | None:
    """安装根目录下 assets/app_icon.ico（优先）或 .png。"""
    if root is None:
        return None
    assets = root / "assets"
    for name in ("app_icon.ico", "app_icon.png"):
        p = assets / name
        if p.is_file():
            return p
    return None


def _load_win32_icon(path: Path, size: int):
    import ctypes

    user32 = ctypes.windll.user32
    LR_LOADFROMFILE = 0x10
    IMAGE_ICON = 1
    return user32.LoadImageW(
        None,
        str(path.resolve()),
        IMAGE_ICON,
        size,
        size,
        LR_LOADFROMFILE,
    )


def apply_windows_taskbar_icon(widget, icon_path: Path | None = None) -> bool:
    """
    pythonw 进程的任务栏图标需 WM_SETICON；须保留 hicon 引用避免被 GC。
    """
    if sys.platform != "win32":
        return False
    if icon_path is None:
        icon_path = find_app_icon(getattr(widget, "_portable_root", None))
    if icon_path is None or icon_path.suffix.lower() != ".ico":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = wintypes.HWND(int(widget.winId()))
        if not hwnd:
            return False

        handles: list[int] = []
        for size in (16, 32, 48):
            h = _load_win32_icon(icon_path, size)
            if h:
                handles.append(int(h))
        if not handles:
            import ctypes

            user32 = ctypes.windll.user32
            LR_LOADFROMFILE = 0x10
            LR_DEFAULTSIZE = 0x40
            IMAGE_ICON = 1
            h = user32.LoadImageW(
                None,
                str(icon_path.resolve()),
                IMAGE_ICON,
                0,
                0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            if not h:
                return False
            handles.append(int(h))

        user32 = ctypes.windll.user32
        WM_SETICON = 0x80
        ICON_SMALL = 0
        ICON_BIG = 1
        small = handles[0]
        big = handles[-1]
        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)

        store = getattr(widget, "_win_taskbar_icons", None)
        if store is None:
            store = []
            widget._win_taskbar_icons = store
        store.clear()
        store.extend(handles)
        return True
    except Exception:
        return False


def schedule_taskbar_icon_refresh(widget, icon_path: Path | None = None) -> None:
    """窗口显示后多次刷新任务栏图标（hwnd 可能尚未就绪）。"""
    if sys.platform != "win32":
        return
    try:
        from PyQt5.QtCore import QTimer
    except ImportError:
        return

    def _apply() -> None:
        apply_windows_taskbar_icon(widget, icon_path)

    for ms in (0, 50, 200, 800, 2000):
        QTimer.singleShot(ms, _apply)


def make_qicon(root: Path | None):
    from PyQt5.QtGui import QIcon

    path = find_app_icon(root)
    if path is not None:
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon
    return QIcon()


def create_start_menu_shortcut(install_root: Path) -> None:
    """安装后写入开始菜单快捷方式（图标指向 assets/app_icon.ico）。"""
    if sys.platform != "win32":
        return
    icon = find_app_icon(install_root)
    if icon is None:
        return
    pyw = install_root / "venv" / "Scripts" / "pythonw.exe"
    script = install_root / "portable_launcher.py"
    if not pyw.is_file() or not script.is_file():
        return
    appdata = os.environ.get("APPDATA", "").strip()
    if not appdata:
        return
    programs = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True, exist_ok=True)
    lnk = programs / _SHORTCUT_NAME
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:ARGOS_LNK);"
        f"$s.TargetPath = '{pyw}';"
        f"$s.Arguments = '\"{script}\"';"
        f"$s.WorkingDirectory = '{install_root}';"
        f"$s.IconLocation = '{icon},0';"
        "$s.Description = '本地翻译器（俄乌）';"
        "$s.Save()"
    )
    env = os.environ.copy()
    env["ARGOS_LNK"] = str(lnk)
    try:
        from win_path_utils import subprocess_hide_window_kwargs

        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            env=env,
            check=False,
            capture_output=True,
            timeout=30,
            **subprocess_hide_window_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
