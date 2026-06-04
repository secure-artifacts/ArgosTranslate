"""
PyInstaller 入口：先显示「正在启动」提示，再在后台加载安装逻辑。
单文件 exe 解压完成后，用户能立刻看到窗口，而不是长时间无反馈。
"""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk


def _center_window(root: tk.Tk, width: int, height: int) -> None:
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 3)
    root.geometry(f"{width}x{height}+{x}+{y}")


def main() -> int:
    root = tk.Tk()
    root.title("本地翻译器")
    root.resizable(False, False)
    root.configure(bg="#E8F0FE")
    _center_window(root, 440, 150)

    tk.Label(
        root,
        text="正在启动安装程序…",
        font=("Microsoft YaHei UI", 12, "bold"),
        bg="#E8F0FE",
        fg="#1A1A1A",
    ).pack(pady=(22, 6))
    tk.Label(
        root,
        text="首次双击 exe 需解压内置文件（约 30 秒～2 分钟），请稍候。",
        font=("Microsoft YaHei UI", 9),
        bg="#E8F0FE",
        fg="#444444",
        wraplength=400,
        justify="center",
    ).pack(pady=(0, 12))
    bar = ttk.Progressbar(root, mode="indeterminate", length=360)
    bar.pack(padx=24, pady=(0, 18))
    bar.start(10)
    root.update()

    done: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=1)
    exit_code = 1

    def _load() -> None:
        try:
            import setup_main

            done.put(("ok", setup_main))
        except Exception as exc:
            done.put(("err", exc))

    threading.Thread(target=_load, daemon=True).start()

    def _poll() -> None:
        nonlocal exit_code
        try:
            kind, payload = done.get_nowait()
        except queue.Empty:
            root.after(120, _poll)
            return
        bar.stop()
        root.destroy()
        if kind == "err":
            raise payload
        mod = payload
        exit_code = int(mod.main())

    root.after(120, _poll)
    root.mainloop()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
