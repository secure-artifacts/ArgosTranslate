"""
首次安装向导（tkinter，不依赖 PyQt）。
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from portable_installer import (
    INSTALL_STEP_TITLES,
    InstallProgress,
    cleanup_failed_install,
    default_install_dir,
    install_to,
)
from portable_paths import is_install_root, load_install_pointer


class InstallWizard:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("本地翻译器 — 安装")
        self.root.geometry("540x470")
        self.root.resizable(False, False)
        self._target = tk.StringVar()
        saved = load_install_pointer()
        self._target.set(
            str(saved) if saved else str(default_install_dir())
        )
        self._result: Path | None = None
        self._build()

    def _build(self) -> None:
        pad = {"padx": 12, "pady": 6}
        tk.Label(
            self.root,
            text="欢迎使用本地翻译器（俄乌）",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w", **pad)
        tk.Label(
            self.root,
            text=(
                "只需本安装程序（exe），程序文件已内嵌，无需另下载 zip。\n"
                "请选择安装文件夹（可任意盘符，支持中文路径如 F:\\本地翻译）。\n"
                "首次安装需联网（约 5～20 分钟）。安装 PyQt5 / 翻译引擎时\n"
                "进度条可能停在 70% 左右数分钟，界面会提示「仍在进行」，属正常现象："
            ),
            justify="left",
            wraplength=500,
        ).pack(anchor="w", **pad)

        steps_frame = tk.Frame(self.root)
        steps_frame.pack(anchor="w", padx=12, pady=(0, 4))
        self._step_markers: list[tk.Label] = []
        for i, title in enumerate(INSTALL_STEP_TITLES, start=1):
            lbl = tk.Label(
                steps_frame,
                text=f"  {i}. {title}",
                anchor="w",
                fg="#666",
                font=("Microsoft YaHei UI", 9),
            )
            lbl.pack(anchor="w")
            self._step_markers.append(lbl)

        row = tk.Frame(self.root)
        row.pack(fill="x", **pad)
        tk.Entry(row, textvariable=self._target, width=52).pack(
            side="left", fill="x", expand=True
        )
        tk.Button(row, text="浏览…", command=self._browse).pack(
            side="left", padx=(8, 0)
        )

        self._step_title = tk.StringVar(value="等待开始安装")
        tk.Label(
            self.root,
            textvariable=self._step_title,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(anchor="w", **pad)

        self._pct = tk.IntVar(value=0)
        bar_row = tk.Frame(self.root)
        bar_row.pack(fill="x", padx=12, pady=(0, 4))
        self._bar = ttk.Progressbar(
            bar_row,
            mode="determinate",
            maximum=100,
            variable=self._pct,
            length=420,
        )
        self._bar.pack(side="left", fill="x", expand=True)
        self._pct_label = tk.Label(bar_row, text="0%", width=5)
        self._pct_label.pack(side="left", padx=(8, 0))

        self._detail = tk.StringVar(value="")
        tk.Label(
            self.root,
            textvariable=self._detail,
            fg="#333",
            wraplength=500,
            justify="left",
        ).pack(anchor="w", **pad)

        btn_row = tk.Frame(self.root)
        btn_row.pack(fill="x", padx=12, pady=12)
        self._btn_install = tk.Button(
            btn_row, text="开始安装", width=12, command=self._start_install
        )
        self._btn_install.pack(side="right")
        self._btn_clean = tk.Button(
            btn_row,
            text="清理并重试",
            width=12,
            command=self._clean_and_retry,
        )
        self._btn_clean.pack(side="right", padx=(0, 8))
        tk.Button(btn_row, text="取消", width=8, command=self.root.destroy).pack(
            side="right", padx=(0, 8)
        )

    def _browse(self) -> None:
        d = filedialog.askdirectory(
            title="选择安装文件夹",
            initialdir=str(Path(self._target.get()).parent),
        )
        if d:
            self._target.set(d)

    def _highlight_step(self, current: int) -> None:
        for i, lbl in enumerate(self._step_markers, start=1):
            if i < current:
                lbl.config(fg="#2e7d32", text=f"  ✓ {i}. {INSTALL_STEP_TITLES[i - 1]}")
            elif i == current:
                lbl.config(
                    fg="#1565c0",
                    text=f"  ▶ {i}. {INSTALL_STEP_TITLES[i - 1]}",
                    font=("Microsoft YaHei UI", 9, "bold"),
                )
            else:
                lbl.config(
                    fg="#666",
                    text=f"  {i}. {INSTALL_STEP_TITLES[i - 1]}",
                    font=("Microsoft YaHei UI", 9),
                )

    def _apply_progress(self, p: InstallProgress) -> None:
        self._step_title.set(f"步骤 {p.step}/{len(INSTALL_STEP_TITLES)}：{p.step_title}")
        self._detail.set(p.message)
        pct = p.overall_percent
        self._pct.set(pct)
        self._pct_label.config(text=f"{pct}%")
        self._highlight_step(p.step)
        self.root.update_idletasks()

    def _clean_and_retry(self) -> None:
        path = Path(self._target.get().strip())
        if not path:
            messagebox.showwarning("安装", "请先选择安装路径。")
            return
        if not messagebox.askyesno(
            "清理并重试",
            f"将删除该路径下未完成/损坏的 venv 与联接（保留已释放的程序文件与 data/）：\n{path}\n\n继续？",
        ):
            return
        cleaned = cleanup_failed_install(path)
        msg = "\n".join(cleaned) if cleaned else "（未发现需清理项）"
        messagebox.showinfo("清理完成", f"{msg}\n\n请点击「开始安装」重新安装。")
        self._step_title.set("已清理，请点击「开始安装」")
        self._detail.set("")

    def _start_install(self) -> None:
        path = Path(self._target.get().strip())
        if not path:
            messagebox.showwarning("安装", "请选择安装路径。")
            return
        if path.exists() and any(path.iterdir()) and not is_install_root(path):
            if not messagebox.askyesno(
                "安装",
                f"文件夹已有内容：\n{path}\n\n仍要安装到此位置吗？",
            ):
                return
        self._btn_install.config(state="disabled")
        self._pct.set(0)
        self._highlight_step(1)

        def work() -> None:
            try:
                root = install_to(path, self._thread_progress)
                self._result = root
                self.root.after(
                    0,
                    lambda: self._apply_progress(
                        InstallProgress(4, "完成", 1.0, "安装成功")
                    ),
                )
                self.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "安装完成", f"已安装到：\n{root}\n\n即将启动软件。"
                    ),
                )
                self.root.after(0, self.root.destroy)
            except Exception as e:
                self.root.after(
                    0,
                    lambda: messagebox.showerror("安装失败", str(e)),
                )
                self.root.after(0, self._install_failed)

        threading.Thread(target=work, daemon=True).start()

    def _thread_progress(self, p: InstallProgress) -> None:
        self.root.after(0, lambda: self._apply_progress(p))

    def _install_failed(self) -> None:
        self._btn_install.config(state="normal")
        self._step_title.set("安装失败 — 可点「清理并重试」后再次安装")

    def run(self) -> Path | None:
        self.root.mainloop()
        return self._result


def run_install_wizard() -> Path | None:
    return InstallWizard().run()
