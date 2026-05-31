"""
Argos 翻译 — 更新程序入口。
用法：
  python updater_main.py
  python updater_main.py --target "D:\\ruanjian\\ArgosTranslate"
  python updater_main.py --payload "dist\\Argos翻译-1.0.0-更新包"

打包为 exe 后：将「Argos翻译-x.y.z-更新.exe」放到任意位置，双击即可更新已安装目录并启动程序。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app_version import APP_NAME, APP_VERSION, compare_versions
from portable_updater import (
    apply_update,
    find_install_root,
    launch_gui,
    read_installed_version,
    read_payload_version,
    save_install_pointer,
    update_summary,
)


def _is_windows() -> bool:
    return sys.platform == "win32"


def _message_box(title: str, text: str, style: int = 0) -> int:
    if _is_windows():
        import ctypes

        return int(ctypes.windll.user32.MessageBoxW(0, text, title, style))
    print(f"{title}\n{text}")
    return 0


def _pick_install_folder() -> Path | None:
    if not _is_windows():
        return None
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askdirectory(
        title="选择 ArgosTranslate 安装文件夹（含 venv 与 terminology_bridge.py）",
    )
    root.destroy()
    if not path:
        return None
    return Path(path)


def resolve_payload_root(explicit: Path | None) -> Path | None:
    if explicit is not None and explicit.is_dir():
        return explicit.resolve()
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        for name in ("payload",):
            cand = meipass / name
            if cand.is_dir() and (cand / "version.json").is_file():
                return cand.resolve()
    here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    for cand in (
        here / "payload",
        here / f"Argos翻译-{APP_VERSION}-更新包",
        here.parent / f"Argos翻译-{APP_VERSION}-更新包",
    ):
        if cand.is_dir() and (cand / "version.json").is_file():
            return cand.resolve()
    return None


def resolve_target_root(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return find_install_root(explicit=explicit)
    found = find_install_root()
    if found is not None:
        return found
    picked = _pick_install_folder()
    if picked is None:
        return None
    root = find_install_root(explicit=picked)
    if root is not None:
        save_install_pointer(root)
    return root


def run_update(
    *,
    payload: Path | None,
    target: Path | None,
    no_launch: bool,
    force: bool,
) -> int:
    payload_root = resolve_payload_root(payload)
    if payload_root is None:
        _message_box(
            APP_NAME,
            "未找到更新包内容（payload）。\n"
            "请使用官方发布的「Argos翻译-x.y.z-更新.exe」，或联系发布者重新打包。",
            0x10,
        )
        return 1

    target_root = resolve_target_root(target)
    if target_root is None:
        _message_box(
            APP_NAME,
            "未找到已安装的 ArgosTranslate 目录。\n"
            "请重新运行并选择包含 venv 与 terminology_bridge.py 的文件夹。",
            0x10,
        )
        return 1

    info = update_summary(payload_root, target_root)
    pv = info["payload_version"]
    iv = info["installed_version"]
    cmp = compare_versions(pv, iv)

    if cmp <= 0 and not force:
        msg = (
            f"当前安装版本：{iv}\n"
            f"更新包版本：{pv}\n\n"
            "已是最新版本，无需更新。"
        )
        _message_box(APP_NAME, msg, 0x40)
        if not no_launch:
            launch_gui(target_root)
        return 0

    lines: list[str] = []

    def on_progress(s: str) -> None:
        lines.append(s)
        if not getattr(sys, "frozen", False):
            print(s)

    count, errors = apply_update(payload_root, target_root, on_progress=on_progress)

    if errors:
        body = (
            f"从 {pv} 更新到安装目录时部分文件失败（已更新 {count} 个文件）。\n\n"
            + "\n".join(errors[:12])
        )
        if len(errors) > 12:
            body += f"\n…共 {len(errors)} 项"
        body += f"\n\n请先完全关闭 {APP_NAME} 后重试。"
        _message_box(APP_NAME, body, 0x10)
        return 2

    _message_box(
        APP_NAME,
        f"更新完成：{iv} → {pv}\n"
        f"共更新 {count} 个文件。\n"
        f"安装目录：\n{target_root}\n\n"
        "用户数据（data 文件夹）已保留。",
        0x40,
    )
    if not no_launch:
        launch_gui(target_root)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} 就地更新")
    parser.add_argument("--payload", type=Path, help="更新包 payload 目录")
    parser.add_argument("--target", type=Path, help="已安装的 ArgosTranslate 根目录")
    parser.add_argument("--no-launch", action="store_true", help="更新后不启动主程序")
    parser.add_argument("--force", action="store_true", help="即使版本相同也强制覆盖文件")
    args = parser.parse_args(argv)
    return run_update(
        payload=args.payload,
        target=args.target,
        no_launch=args.no_launch,
        force=args.force,
    )


if __name__ == "__main__":
    raise SystemExit(main())
