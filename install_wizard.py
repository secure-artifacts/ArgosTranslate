"""
首次安装向导（tkinter，不依赖 PyQt）。
配色与 portable_ui_theme 浅色主题一致。
"""
from __future__ import annotations

import sys
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
from app_version import APP_VERSION
from portable_paths import is_install_root, load_install_pointer
from portable_ui_theme import PALETTE_LIGHT

# 与主界面 QSS 一致
P = PALETTE_LIGHT
FONT = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 16, "bold")
FONT_SUB = ("Microsoft YaHei UI", 9)
FONT_STEP = ("Microsoft YaHei UI", 9)
CHROME_SUB = "#E8F0FE"

# 仅属于 tk.Label，不能传给 .pack() / .grid()
_LABEL_WIDGET_KEYS = frozenset(
    {
        "wraplength",
        "anchor",
        "width",
        "height",
        "padx",
        "pady",
        "image",
        "compound",
        "underline",
        "cursor",
    }
)


def _set_wizard_window_icon(root: tk.Tk) -> None:
    if sys.platform != "win32":
        return
    candidates: list[Path] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidates.append(Path(sys._MEIPASS) / "assets" / "app_icon.ico")
    candidates.append(Path(__file__).resolve().parent / "assets" / "app_icon.ico")
    for ico in candidates:
        if ico.is_file():
            try:
                root.iconbitmap(str(ico))
            except Exception:
                pass
            return


def _apply_ttk_theme(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Install.Horizontal.TProgressbar",
        troughcolor=P["surface_alt"],
        background=P["accent"],
        bordercolor=P["border"],
        lightcolor=P["accent"],
        darkcolor=P["accent_pressed"],
        thickness=12,
    )
    style.configure(
        "Install.TEntry",
        fieldbackground=P["surface"],
        bordercolor=P["border"],
        lightcolor=P["border"],
        darkcolor=P["border"],
        padding=6,
    )
    return style


class InstallWizard:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"本地翻译器 — 安装 (v{APP_VERSION})")
        self.root.geometry("560x640")
        self.root.minsize(520, 580)
        self.root.resizable(True, True)
        self.root.configure(bg=P["bg"])
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.bind("<Return>", lambda _e: self._start_install())
        _set_wizard_window_icon(self.root)
        self._style = _apply_ttk_theme(self.root)
        self._target = tk.StringVar()
        saved = load_install_pointer()
        self._target.set(str(saved) if saved else str(default_install_dir()))
        self._result: Path | None = None
        self._build()

    def _label(
        self,
        parent: tk.Misc,
        *,
        text: str = "",
        textvariable: tk.StringVar | None = None,
        font: tuple = FONT,
        fg: str | None = None,
        bg: str | None = None,
        bold: bool = False,
        **pack_kw,
    ) -> tk.Label:
        kw: dict = {
            "font": font if not bold else FONT_BOLD,
            "fg": fg or P["text"],
            "bg": bg or P["bg"],
            "justify": "left",
        }
        if textvariable is not None:
            kw["textvariable"] = textvariable
        else:
            kw["text"] = text
        label_extra = {k: pack_kw.pop(k) for k in list(pack_kw) if k in _LABEL_WIDGET_KEYS}
        lbl = tk.Label(parent, **kw, **label_extra)
        if pack_kw:
            lbl.pack(**pack_kw)
        else:
            lbl.pack()
        return lbl

    def _button(
        self,
        parent: tk.Misc,
        text: str,
        command,
        *,
        primary: bool = False,
        width: int = 10,
    ) -> tk.Button:
        if primary:
            bg, fg, active = P["accent"], "#FFFFFF", P["accent_hover"]
            bd, relief = 0, "flat"
        else:
            bg, fg, active = P["surface"], P["text"], P["surface_alt"]
            bd, relief = 1, "solid"
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            font=FONT,
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg if not primary else "#FFFFFF",
            relief=relief,
            bd=bd,
            highlightthickness=1,
            highlightbackground=P["border"],
            highlightcolor=P["accent"],
            cursor="hand2",
            padx=8,
            pady=6,
        )
        return btn

    def _build(self) -> None:
        header = tk.Frame(self.root, bg=P["chrome_bg"], height=76)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        tk.Label(
            header,
            text="本地翻译器（俄乌）",
            font=FONT_TITLE,
            fg=P["chrome_fg"],
            bg=P["chrome_bg"],
        ).pack(anchor="w", padx=18, pady=(16, 0))
        tk.Label(
            header,
            text="首次安装向导",
            font=FONT_SUB,
            fg=CHROME_SUB,
            bg=P["chrome_bg"],
        ).pack(anchor="w", padx=18, pady=(2, 0))

        body = tk.Frame(self.root, bg=P["bg"])
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=14)

        footer = tk.Frame(self.root, bg=P["bg"], height=52)
        footer.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 14))
        footer.grid_propagate(False)
        btn_row = tk.Frame(footer, bg=P["bg"])
        btn_row.pack(expand=True)
        self._btn_install = self._button(
            btn_row, "开始安装", self._start_install, primary=True, width=12
        )
        self._btn_install.pack(side="right")
        self._btn_clean = self._button(
            btn_row, "清理并重试", self._clean_and_retry, width=12
        )
        self._btn_clean.pack(side="right", padx=(0, 8))
        cancel = self._button(btn_row, "取消", self.root.destroy, width=8)
        cancel.pack(side="right", padx=(0, 8))

        card = tk.Frame(
            body,
            bg=P["surface"],
            highlightthickness=1,
            highlightbackground=P["border"],
        )
        card.pack(fill="x", pady=(0, 12))
        card_inner = tk.Frame(card, bg=P["surface"])
        card_inner.pack(fill="x", padx=14, pady=12)

        self._label(
            card_inner,
            text=(
                "只需本安装程序（exe），程序文件已内嵌，无需另下载 zip。\n"
                "请选择安装文件夹（可任意盘符，支持中文路径）。\n"
                "双击 exe 后约 30 秒～2 分钟会先出现启动提示（exe 自解压）；"
                "完整安装约 15～40 分钟（含下载依赖与语言包，需联网；pip 阶段可能长时间无新文字）："
            ),
            fg=P["text_muted"],
            bg=P["surface"],
            wraplength=500,
        )

        steps_frame = tk.Frame(card_inner, bg=P["surface"])
        steps_frame.pack(anchor="w", pady=(10, 0))
        self._step_markers: list[tk.Label] = []
        for i, title in enumerate(INSTALL_STEP_TITLES, start=1):
            lbl = tk.Label(
                steps_frame,
                text=f"  {i}. {title}",
                anchor="w",
                fg=P["text_muted"],
                bg=P["surface"],
                font=FONT_STEP,
            )
            lbl.pack(anchor="w", pady=1)
            self._step_markers.append(lbl)

        path_card = tk.Frame(
            body,
            bg=P["surface"],
            highlightthickness=1,
            highlightbackground=P["border"],
        )
        path_card.pack(fill="x", pady=(0, 12))
        path_inner = tk.Frame(path_card, bg=P["surface"])
        path_inner.pack(fill="x", padx=14, pady=12)
        self._label(
            path_inner,
            text="安装位置",
            font=FONT_BOLD,
            fg=P["text"],
            bg=P["surface"],
        )
        row = tk.Frame(path_inner, bg=P["surface"])
        row.pack(fill="x", pady=(6, 0))
        entry = tk.Entry(
            row,
            textvariable=self._target,
            font=FONT,
            bg=P["surface"],
            fg=P["text"],
            insertbackground=P["accent"],
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=P["border"],
            highlightcolor=P["accent"],
        )
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        browse = tk.Button(
            row,
            text="浏览…",
            command=self._browse,
            font=FONT,
            bg=P["surface_alt"],
            fg=P["text"],
            activebackground=P["sel_bg"],
            activeforeground=P["accent"],
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground=P["border"],
            cursor="hand2",
            padx=10,
            pady=4,
        )
        browse.pack(side="left", padx=(8, 0))

        progress_card = tk.Frame(
            body,
            bg=P["surface"],
            highlightthickness=1,
            highlightbackground=P["border"],
        )
        progress_card.pack(fill="x")
        prog_inner = tk.Frame(progress_card, bg=P["surface"])
        prog_inner.pack(fill="x", padx=14, pady=12)

        self._step_title = tk.StringVar(value="等待开始安装")
        self._label(
            prog_inner,
            textvariable=self._step_title,
            bold=True,
            fg=P["text"],
            bg=P["surface"],
        )

        self._pct = tk.IntVar(value=0)
        bar_row = tk.Frame(prog_inner, bg=P["surface"])
        bar_row.pack(fill="x", pady=(8, 6))
        self._bar = ttk.Progressbar(
            bar_row,
            style="Install.Horizontal.TProgressbar",
            mode="determinate",
            maximum=100,
            variable=self._pct,
            length=420,
        )
        self._bar.pack(side="left", fill="x", expand=True)
        self._pct_label = tk.Label(
            bar_row,
            text="0%",
            width=5,
            font=FONT_BOLD,
            fg=P["accent"],
            bg=P["surface"],
        )
        self._pct_label.pack(side="left", padx=(8, 0))

        self._detail = tk.StringVar(value="")
        self._label(
            prog_inner,
            textvariable=self._detail,
            fg=P["text_muted"],
            bg=P["surface"],
            wraplength=500,
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
                lbl.config(
                    fg=P["success"],
                    text=f"  ✓ {i}. {INSTALL_STEP_TITLES[i - 1]}",
                    font=FONT_STEP,
                )
            elif i == current:
                lbl.config(
                    fg=P["accent"],
                    text=f"  ▶ {i}. {INSTALL_STEP_TITLES[i - 1]}",
                    font=FONT_BOLD,
                )
            else:
                lbl.config(
                    fg=P["text_muted"],
                    text=f"  {i}. {INSTALL_STEP_TITLES[i - 1]}",
                    font=FONT_STEP,
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
        self._btn_install.config(state="disabled", bg=P["border"], fg=P["text_muted"])
        self._pct.set(0)
        self._highlight_step(1)

        def work() -> None:
            try:
                root = install_to(path, self._thread_progress)
                def _finish() -> None:
                    self._apply_progress(
                        InstallProgress(4, "完成", 1.0, "安装成功")
                    )
                    messagebox.showinfo(
                        "安装完成",
                        f"已安装到：\n{root}\n\n"
                        "点击「确定」后软件将自动打开。\n"
                        "若未见窗口，请查看任务栏或从开始菜单重新打开。",
                    )
                    self.root.destroy()

                self._result = root
                self.root.after(0, _finish)
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
        self._btn_install.config(
            state="normal", bg=P["accent"], fg="#FFFFFF"
        )
        self._step_title.set("安装失败 — 可点「清理并重试」后再次安装")

    def run(self) -> Path | None:
        self.root.mainloop()
        return self._result


def run_install_wizard() -> Path | None:
    return InstallWizard().run()
