"""
Windows 启动入口。
- 开发：venv\\Scripts\\pythonw.exe portable_launcher.py
- 发布：dist\\本地翻译器\\本地翻译器.exe（仅带图标启动器）→ 调用本目录 venv 中的 pythonw 运行本脚本
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from win_path_utils import configure_windows_utf8

configure_windows_utf8()


def find_portable_root() -> Path:
    try:
        from portable_paths import find_portable_root as _find

        if getattr(sys, "frozen", False):
            start = Path(sys.executable).resolve().parent
        else:
            start = Path(__file__).resolve().parent
        return _find(start)
    except ImportError:
        pass
    if getattr(sys, "frozen", False):
        start = Path(sys.executable).resolve().parent
    else:
        start = Path(__file__).resolve().parent
    for cand in (start, *start.parents[:8]):
        if (cand / "terminology_bridge.py").is_file():
            return cand
        if (cand / "venv" / "Scripts" / "pythonw.exe").is_file() and (
            cand / "portable_launcher.py"
        ).is_file():
            return cand
    return start


def _apply_portable_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("XDG_DATA_HOME", str(root / "data" / "local"))
    env.setdefault("XDG_CONFIG_HOME", str(root / "data" / "config"))
    env.setdefault("XDG_CACHE_HOME", str(root / "data" / "cache"))
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    env.setdefault("CUDA_VISIBLE_DEVICES", "")
    env.setdefault("CTRANSLATE2_LOG_LEVEL", "ERROR")
    env.setdefault("ARGOS_DEVICE_TYPE", "cpu")
    env.setdefault("OMP_NUM_THREADS", "1")
    if sys.platform == "win32":
        dll_dirs = [
            root / "venv" / "Lib" / "site-packages" / "torch" / "lib",
            root / "venv" / "Lib" / "site-packages" / "ctranslate2",
            root / "venv" / "Lib" / "site-packages" / "vosk",
        ]
        extra = [str(d.resolve()) for d in dll_dirs if d.is_dir()]
        if extra:
            old = env.get("PATH", "")
            env["PATH"] = os.pathsep.join(extra) + (
                (os.pathsep + old) if old else ""
            )
    return env


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "ArgosTranslate.Portable.LocalTranslator.1"
        )
    except Exception:
        pass


def _bootstrap_for_gui(root: Path) -> None:
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from native_dll_bootstrap import prepare_native_dll_paths, preload_torch_dlls

        prepare_native_dll_paths(root)
        preload_torch_dlls(root)
    except Exception:
        boot = root / "native_dll_bootstrap.py"
        if boot.is_file():
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "native_dll_bootstrap", boot
            )
            if spec is not None and spec.loader is not None:
                try:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    mod.prepare_native_dll_paths(root)
                except Exception:
                    pass
    site = root / "venv" / "Lib" / "site-packages"
    if site.is_dir():
        ps = str(site)
        if ps not in sys.path:
            sys.path.insert(0, ps)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    for k, v in _apply_portable_env(root).items():
        os.environ[k] = v
    try:
        import importlib.util

        patch_tool = root / "tools" / "apply_portable_gui_patch.py"
        if patch_tool.is_file():
            spec = importlib.util.spec_from_file_location(
                "apply_portable_gui_patch", patch_tool
            )
            if spec is not None and spec.loader is not None:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.apply()
    except Exception:
        pass


def _apply_fast_startup_env() -> None:
    """启动加速：界面先显示，语言包后台加载；空原文不预加载翻译模型。"""
    os.environ.setdefault("ARGOS_FAST_STARTUP", "1")
    os.environ.setdefault("ARGOS_DEBUG", "0")


def _launch_via_venv_pythonw(root: Path) -> int:
    """打包 exe 只做启动器，实际 GUI 在 venv 的 pythonw 中运行（避免缺 stdlib）。"""
    pyw = root / "venv" / "Scripts" / "pythonw.exe"
    script = root / "portable_launcher.py"
    if not pyw.is_file() or not script.is_file():
        try:
            from portable_paths import missing_install_message

            _show_error(missing_install_message(root))
        except ImportError:
            _show_error(
                f"未找到完整安装目录。\n\n{pyw}\n{script}\n\n"
                "请勿只把 exe 放在「下载」文件夹，详见 命令\\首次安装说明.txt"
            )
        return 1
    env = _apply_portable_env(root)
    log_dir = root / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    err_log = log_dir / "launch_errors.log"
    try:
        subprocess.Popen(
            [str(pyw), str(script)],
            cwd=str(root),
            env=env,
        )
    except OSError as e:
        err_log.write_text(f"启动失败: {e}\n", encoding="utf-8")
        _show_error(f"无法启动翻译程序：\n{e}\n\n详见 data\\logs\\launch_errors.log")
        return 1
    return 0


def _show_error(msg: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, msg, "本地翻译器（俄乌）", 0x10)
        except Exception:
            print(msg, file=sys.stderr)
    else:
        print(msg, file=sys.stderr)


def main() -> int:
    root = find_portable_root()
    _set_windows_app_user_model_id()

    if getattr(sys, "frozen", False):
        return _launch_via_venv_pythonw(root)

    try:
        from portable_paths import is_install_root, save_install_pointer

        if is_install_root(root):
            save_install_pointer(root)
    except ImportError:
        pass

    _bootstrap_for_gui(root)
    _apply_fast_startup_env()
    try:
        import argos_enhance as ae

        ae.bootstrap_on_startup()
    except ImportError:
        pass
    try:
        import startup_warmup as sw

        sw.schedule_early()
    except Exception:
        pass
    try:
        import importlib

        gui = importlib.import_module("argostranslategui.gui")
        gui.main()
    except Exception as e:
        log_dir = root / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        err_log = log_dir / "launch_errors.log"
        import traceback

        err_log.write_text(
            traceback.format_exc(),
            encoding="utf-8",
        )
        _show_error(
            f"启动失败：\n{e}\n\n详见 data\\logs\\launch_errors.log"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
