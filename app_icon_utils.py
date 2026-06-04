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
    folder = (
        Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "本地翻译器"
    )
    folder.mkdir(parents=True, exist_ok=True)
    return folder


_tmp_counter = 0


def _shortcut_temp_path() -> Path:
    global _tmp_counter
    import tempfile

    _tmp_counter += 1
    return (
        Path(tempfile.gettempdir())
        / f"argos_shortcut_{os.getpid()}_{_tmp_counter}.lnk"
    )


def _finalize_shortcut_path(tmp_lnk: Path, lnk_path: Path) -> bool:
    """cscript/COM 对中文路径会乱码，先写 ASCII 临时文件再 move。"""
    lnk_path = lnk_path.resolve()
    try:
        if lnk_path.is_file():
            lnk_path.unlink()
        tmp_lnk.replace(lnk_path)
        return lnk_path.is_file()
    except OSError:
        try:
            if tmp_lnk.is_file() and not lnk_path.is_file():
                tmp_lnk.rename(lnk_path)
                return lnk_path.is_file()
        except OSError:
            pass
        return False
    finally:
        try:
            if tmp_lnk.is_file() and tmp_lnk != lnk_path:
                tmp_lnk.unlink()
        except OSError:
            pass


def _write_shortcut_com(
    lnk_path: Path,
    *,
    target: Path,
    arguments: str,
    work_dir: Path,
    icon: Path | None,
    description: str,
) -> bool:
    """用 Windows COM 写 .lnk（不依赖 PowerShell）。"""
    if sys.platform != "win32":
        return False
    lnk_path = lnk_path.resolve()
    lnk_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_lnk = _shortcut_temp_path()
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8),
            ]

        CLSID_ShellLink = GUID(
            0x00021401,
            0x0000,
            0x0000,
            (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46),
        )
        IID_IShellLinkW = GUID(
            0x000214F9,
            0x0000,
            0x0000,
            (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46),
        )
        IID_IPersistFile = GUID(
            0x0000010B,
            0x0000,
            0x0000,
            (0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46),
        )

        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        try:
            psl = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(CLSID_ShellLink),
                None,
                1,
                ctypes.byref(IID_IShellLinkW),
                ctypes.byref(psl),
            )
            if hr != 0 or not psl.value:
                return False

            iface = ctypes.cast(psl, ctypes.POINTER(ctypes.c_void_p))
            vtbl = ctypes.cast(iface[0], ctypes.POINTER(ctypes.c_void_p))

            def _method_w(index: int):
                return ctypes.WINFUNCTYPE(
                    ctypes.HRESULT, ctypes.c_void_p, ctypes.c_wchar_p
                )(vtbl[index])

            def _method_icon(index: int):
                return ctypes.WINFUNCTYPE(
                    ctypes.HRESULT,
                    ctypes.c_void_p,
                    ctypes.c_wchar_p,
                    ctypes.c_int,
                )(vtbl[index])

            iface_p = ctypes.c_void_p(psl.value)
            # IShellLinkW: IUnknown(0-2) + GetPath(3) SetPath(4) ...
            _method_w(4)(iface_p, str(target.resolve()))
            _method_w(12)(iface_p, arguments or "")
            _method_w(10)(iface_p, str(work_dir.resolve()))
            _method_w(8)(iface_p, description)
            if icon and icon.is_file():
                _method_icon(21)(iface_p, str(icon.resolve()), 0)

            QueryInterface = ctypes.WINFUNCTYPE(
                ctypes.HRESULT,
                ctypes.c_void_p,
                ctypes.POINTER(GUID),
                ctypes.POINTER(ctypes.c_void_p),
            )(vtbl[0])
            ppf = ctypes.c_void_p()
            hr = QueryInterface(iface_p, ctypes.byref(IID_IPersistFile), ctypes.byref(ppf))
            if hr != 0 or not ppf.value:
                return False

            persist_vtbl = ctypes.cast(
                ctypes.cast(ppf, ctypes.POINTER(ctypes.c_void_p))[0],
                ctypes.POINTER(ctypes.c_void_p),
            )
            Save = ctypes.WINFUNCTYPE(
                ctypes.HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int
            )(persist_vtbl[5])
            lnk_path.parent.mkdir(parents=True, exist_ok=True)
            hr = Save(ctypes.c_void_p(ppf.value), str(tmp_lnk.resolve()), 1)
            if hr != 0 or not tmp_lnk.is_file():
                return False
            return _finalize_shortcut_path(tmp_lnk, lnk_path)
        finally:
            ole32.CoUninitialize()
    except Exception:
        return False


def _write_shortcut(
    lnk_path: Path,
    *,
    target: Path,
    arguments: str,
    work_dir: Path,
    icon: Path | None,
    description: str,
) -> bool:
    if _write_shortcut_com(
        lnk_path,
        target=target,
        arguments=arguments,
        work_dir=work_dir,
        icon=icon,
        description=description,
    ):
        return True
    if _write_shortcut_vbs(
        lnk_path,
        target=target,
        arguments=arguments,
        work_dir=work_dir,
        icon=icon,
        description=description,
    ):
        return True
    return _write_shortcut_powershell(
        lnk_path,
        target=target,
        arguments=arguments,
        work_dir=work_dir,
        icon=icon,
        description=description,
    )


def _write_shortcut_vbs(
    lnk_path: Path,
    *,
    target: Path,
    arguments: str,
    work_dir: Path,
    icon: Path | None,
    description: str,
) -> bool:
    """cscript + UTF-16 VBS（PowerShell 对中文路径易乱码）。"""
    if sys.platform != "win32":
        return False
    lnk_path = lnk_path.resolve()
    lnk_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_lnk = _shortcut_temp_path()
    args_line = ""
    if arguments:
        escaped = arguments.replace('"', '""')
        args_line = f'sc.Arguments = "{escaped}"\r\n'
    icon_line = ""
    if icon and icon.is_file():
        icon_line = f'sc.IconLocation = "{icon.resolve()},0"\r\n'
    vbs = (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'Set sc = sh.CreateShortcut("{tmp_lnk}")\r\n'
        f'sc.TargetPath = "{target.resolve()}"\r\n'
        f"{args_line}"
        f'sc.WorkingDirectory = "{work_dir.resolve()}"\r\n'
        f"{icon_line}"
        f'sc.Description = "{description.replace(chr(34), "")}"\r\n'
        "sc.Save\r\n"
    )
    import tempfile

    vbs_path = Path(tempfile.gettempdir()) / "argos_create_shortcut.vbs"
    try:
        vbs_path.write_text(vbs, encoding="utf-16")
        from win_path_utils import subprocess_hide_window_kwargs

        r = subprocess.run(
            ["cscript", "//nologo", str(vbs_path)],
            check=False,
            capture_output=True,
            timeout=30,
            **subprocess_hide_window_kwargs(),
        )
        if r.returncode != 0 or not tmp_lnk.is_file():
            return False
        return _finalize_shortcut_path(tmp_lnk, lnk_path)
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        try:
            vbs_path.unlink(missing_ok=True)
        except OSError:
            pass


def _write_shortcut_powershell(
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
        "$s.Description = $env:ARGOS_DESC;"
        "$s.Save()"
    )
    env = os.environ.copy()
    env["ARGOS_LNK"] = str(lnk_path)
    env["ARGOS_TARGET"] = str(target)
    env["ARGOS_ARGS"] = arguments
    env["ARGOS_WORKDIR"] = str(work_dir)
    env["ARGOS_ICON"] = str(icon.resolve()) if icon and icon.is_file() else ""
    env["ARGOS_DESC"] = description
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


def ensure_launcher_bat(install_root: Path) -> Path | None:
    """安装目录内可双击的 本地翻译器.bat（便于搜索/固定路径启动）。"""
    install_root = install_root.resolve()
    bat = install_root / "本地翻译器.bat"
    pyw = install_root / "venv" / "Scripts" / "pythonw.exe"
    script = install_root / "portable_launcher.py"
    if not pyw.is_file() or not script.is_file():
        return None
    content = (
        "@echo off\r\n"
        "chcp 65001 >nul 2>&1\r\n"
        'cd /d "%~dp0"\r\n'
        'start "" "%~dp0venv\\Scripts\\pythonw.exe" "%~dp0portable_launcher.py"\r\n'
        "exit /b 0\r\n"
    )
    try:
        bat.write_text(content, encoding="utf-8")
        return bat
    except OSError:
        return None


def register_windows_search(install_root: Path) -> bool:
    """写入「应用和功能」列表，帮助 Windows 搜索找到本程序。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        icon = find_app_icon(install_root)
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ArgosTranslatePortable"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "本地翻译器")
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(icon or install_root))
            winreg.SetValueEx(
                key, "InstallLocation", 0, winreg.REG_SZ, str(install_root.resolve())
            )
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "ArgosTranslate")
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        return True
    except OSError:
        return False


def _cmd_exe_path() -> Path:
    root = os.environ.get("SystemRoot", r"C:\Windows").strip() or r"C:\Windows"
    return Path(root) / "System32" / "cmd.exe"


def _launcher_shortcut_spec(
    install_root: Path,
) -> tuple[Path, str, Path, Path | None] | None:
    install_root = install_root.resolve()
    icon = find_app_icon(install_root)
    if icon is None:
        return None
    launcher_exe = install_root / "本地翻译器.exe"
    if launcher_exe.is_file():
        return launcher_exe, "", install_root, icon
    cmd = _cmd_exe_path()
    run_bat = install_root / "run_gui.bat"
    if run_bat.is_file() and cmd.is_file():
        return cmd, f'/c "{run_bat}"', install_root, icon
    launch_bat = ensure_launcher_bat(install_root)
    if launch_bat is not None and launch_bat.is_file() and cmd.is_file():
        return cmd, f'/c "{launch_bat}"', install_root, icon
    pyw = install_root / "venv" / "Scripts" / "pythonw.exe"
    script = install_root / "portable_launcher.py"
    if pyw.is_file() and script.is_file():
        return pyw, str(script), install_root, icon
    return None


def ensure_start_menu_shortcut(install_root: Path) -> bool:
    """写入开始菜单快捷方式（Programs 根目录 + 本地翻译器 子文件夹）。"""
    appdata = os.environ.get("APPDATA", "").strip()
    if not appdata:
        return False
    programs_root = (
        Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    )
    programs_sub = _start_menu_programs_dir()
    spec = _launcher_shortcut_spec(install_root)
    if spec is None:
        return False
    target, arguments, work_dir, icon = spec
    desc = "本地翻译器 俄语 乌克兰语 离线翻译 ArgosTranslate"
    ok = False
    for programs in (programs_root, programs_sub):
        if programs is None:
            continue
        programs.mkdir(parents=True, exist_ok=True)
        names = _START_MENU_NAMES if programs == programs_sub else ("本地翻译器.lnk",)
        for name in names:
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
    ensure_windows_launch_entries(install_root)


def ensure_windows_launch_entries(install_root: Path) -> bool:
    """开始菜单 + 桌面快捷方式 + 系统搜索注册 + 本地翻译器.bat。"""
    install_root = install_root.resolve()
    ensure_launcher_bat(install_root)
    register_windows_search(install_root)
    ok_menu = ensure_start_menu_shortcut(install_root)
    ensure_desktop_shortcut(install_root)
    return ok_menu
