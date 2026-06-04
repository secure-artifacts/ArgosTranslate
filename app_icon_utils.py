"""应用图标：任务栏 / 窗口 / 开始菜单快捷方式。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_USER_MODEL_ID = "ArgosTranslate.Portable.LocalTranslator.1"
_START_MENU_NAMES: tuple[str, ...] = (
    "本地翻译器.lnk",
    "本地翻译器（俄乌）.lnk",
)
_DESKTOP_NAME = "本地翻译器.lnk"


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


def _start_menu_programs_dir() -> Path | None:
    appdata = os.environ.get("APPDATA", "").strip()
    if not appdata:
        return None
    programs = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True, exist_ok=True)
    return programs


def _write_shortcut(
    lnk_path: Path,
    *,
    target: Path,
    arguments: str,
    work_dir: Path,
    icon: Path | None,
    description: str,
) -> bool:
    if sys.platform != "win32":
        return False
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:ARGOS_LNK);"
        "$s.TargetPath = $env:ARGOS_TARGET;"
        "$s.Arguments = $env:ARGOS_ARGS;"
        "$s.WorkingDirectory = $env:ARGOS_WORKDIR;"
        "if ($env:ARGOS_ICON) { $s.IconLocation = $env:ARGOS_ICON + ',0' };"
        f"$s.Description = '{description}';"
        "$s.Save()"
    )
    env = os.environ.copy()
    env["ARGOS_LNK"] = str(lnk_path)
    env["ARGOS_TARGET"] = str(target)
    env["ARGOS_ARGS"] = arguments
    env["ARGOS_WORKDIR"] = str(work_dir)
    env["ARGOS_ICON"] = str(icon.resolve()) if icon and icon.is_file() else ""
    try:
        from win_path_utils import subprocess_hide_window_kwargs

        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            env=env,
            check=False,
            capture_output=True,
            timeout=30,
            **subprocess_hide_window_kwargs(),
        )
        return r.returncode == 0 and lnk_path.is_file()
    except (OSError, subprocess.TimeoutExpired):
        return False


def _launcher_shortcut_spec(install_root: Path) -> tuple[Path, str, Path, Path | None] | None:
    install_root = install_root.resolve()
    icon = find_app_icon(install_root)
    if icon is None:
        return None
    pyw = install_root / "venv" / "Scripts" / "pythonw.exe"
    script = install_root / "portable_launcher.py"
    bat = install_root / "run_gui.bat"
    if pyw.is_file() and script.is_file():
        return pyw, f'"{script}"', install_root, icon
    if bat.is_file():
        return bat, "", install_root, icon
    return None


def ensure_start_menu_shortcut(install_root: Path) -> bool:
    """写入/刷新开始菜单快捷方式，便于 Windows 搜索「本地翻译器」。"""
    programs = _start_menu_programs_dir()
    spec = _launcher_shortcut_spec(install_root)
    if programs is None or spec is None:
        return False
    target, arguments, work_dir, icon = spec
    desc = "本地翻译器（俄乌）— 俄语乌克兰语离线翻译 ArgosTranslate"
    ok = False
    for name in _START_MENU_NAMES:
        if _write_shortcut(
            programs / name,
            target=target,
            arguments=arguments,
            work_dir=work_dir,
            icon=icon,
            description=desc,
        ):
            ok = True
    return ok


def ensure_desktop_shortcut(install_root: Path) -> bool:
    """可选：桌面快捷方式（与开始菜单相同目标）。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        # CSIDL_DESKTOP = 0
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0, None, 0, buf) != 0:
            return False
        desktop = Path(buf.value)
    except Exception:
        return False
    spec = _launcher_shortcut_spec(install_root)
    if spec is None:
        return False
    target, arguments, work_dir, icon = spec
    return _write_shortcut(
        desktop / _DESKTOP_NAME,
        target=target,
        arguments=arguments,
        work_dir=work_dir,
        icon=icon,
        description="本地翻译器（俄乌）",
    )


def create_start_menu_shortcut(install_root: Path) -> None:
    """安装后写入开始菜单快捷方式（兼容旧名）。"""
    ensure_start_menu_shortcut(install_root)
