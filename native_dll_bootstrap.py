"""
Windows：在导入 torch / ctranslate2 之前把 DLL 目录加入搜索路径，缓解 WinError 1114。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def prepare_native_dll_paths(portable_root: Path | None = None) -> None:
    if sys.platform != "win32":
        return
    root = portable_root
    if root is None:
        return
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    os.environ.setdefault("CTRANSLATE2_LOG_LEVEL", "ERROR")
    os.environ.setdefault("ARGOS_DEVICE_TYPE", "cpu")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "0")

    candidates = [
        root / "venv" / "Lib" / "site-packages" / "torch" / "lib",
        root / "venv" / "Lib" / "site-packages" / "ctranslate2",
        root / "venv" / "Lib" / "site-packages" / "vosk",
    ]
    path_parts: list[str] = []
    add_dll = getattr(os, "add_dll_directory", None)
    for d in candidates:
        if not d.is_dir():
            continue
        p = str(d.resolve())
        path_parts.append(p)
        if callable(add_dll):
            try:
                add_dll(p)
            except OSError:
                pass
    if path_parts:
        old = os.environ.get("PATH", "")
        os.environ["PATH"] = os.pathsep.join(path_parts) + (
            (os.pathsep + old) if old else ""
        )


def preload_torch_dlls(portable_root: Path | None = None) -> bool:
    """
    在导入 ctranslate2/torch 之前预加载 c10.dll 等，缓解 WinError 1114。
    返回是否成功预加载 c10.dll。
    """
    if sys.platform != "win32" or portable_root is None:
        return False
    prepare_native_dll_paths(portable_root)
    torch_lib = portable_root / "venv" / "Lib" / "site-packages" / "torch" / "lib"
    if not torch_lib.is_dir():
        return False
    import ctypes

    ok = False
    for name in ("c10.dll", "torch_cpu.dll", "torch.dll", "uv.dll", "asmjit.dll"):
        path = torch_lib / name
        if not path.is_file():
            continue
        try:
            ctypes.WinDLL(str(path.resolve()))
            if name == "c10.dll":
                ok = True
        except OSError:
            continue
    return ok
