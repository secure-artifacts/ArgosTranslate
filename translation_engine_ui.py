"""
翻译引擎切换（Argos / Ollama）与用户说明。
"""
from __future__ import annotations

from typing import Any

ENGINE_HELP_TITLE = "翻译引擎说明"

ENGINE_HELP_TEXT = """【Argos 强化 · 默认主引擎】
本软件直接强化 Argos，不依赖 Ollama 做日常翻译：
  · 多核 CPU 加速 + 短/中/长句分档 beam（快且尽量译全）
  · 中→俄/乌：宗教用语、口语搭配、变格、术语库（与精译路径同源数据）
  · 劣质句（重复直译、漏译心情等）规则修补，必要时自动重译一次
  · 预热后短句通常数秒内；内存约 0.5～1.5 GB
局限：语气不如大模型华丽；正式合同仍须人工审校

【Ollama + Qwen · 可选精译】
优点：
  · 大模型理解更好，长句、复杂表述更自然
  · 适合需要「润色感」的段落（仍建议人工定稿）
缺点：
  · 明显更慢（常需数秒～数分钟，长文按块计算）
  · 需额外下载约 7 GB（Ollama + 模型），内存约 5～8 GB
  · 首次使用需顶栏或菜单「下载引擎」

【如何选择】
  · 默认一直用 Argos 强化即可（快 + 准度已调优）
  · 仅当个别段落要「大模型润色感」时再切 Ollama
  · 固定译法、人名、教术语 → 请维护「术语库」（Argos 优先受益）

切换方式：每个翻译页上方「引擎」下拉框；选择会保存到 settings.json。"""

ENGINE_COMBO_TOOLTIP = (
    "Argos 强化：默认主引擎（快，中→俄/乌已深度优化）\n"
    "Ollama：可选精译（慢，需下载引擎）\n"
    "点「?」查看详细对比"
)


def engine_combo_index() -> int:
    try:
        import ollama_translate as ot

        return 1 if ot.use_ollama_backend() else 0
    except ImportError:
        return 0


def sync_engine_combo(combo: Any) -> None:
    if combo is None:
        return
    combo.blockSignals(True)
    combo.setCurrentIndex(engine_combo_index())
    combo.blockSignals(False)


def apply_engine_choice(use_ollama: bool, *, host: Any = None) -> None:
    try:
        import ollama_translate as ot
    except ImportError:
        return
    if ot.use_ollama_backend() == use_ollama:
        return
    ot.set_use_ollama_backend(use_ollama)
    if host is None:
        return
    chrome = getattr(host, "_chrome_engine_combo", None)
    sync_engine_combo(chrome)
    for tab in getattr(host, "_iter_tabs", lambda: [])():
        sync_engine_combo(getattr(tab, "_engine_combo", None))
        refresh_ph = getattr(tab, "refresh_engine_placeholders", None)
        if callable(refresh_ph):
            refresh_ph()
    start = getattr(host, "_start_language_load_async", None)
    if callable(start):
        start()
    if use_ollama:
        from PyQt5.QtCore import QTimer

        setup = getattr(host, "maybe_setup_ollama_on_startup", None)
        if callable(setup):
            QTimer.singleShot(400, setup)


def show_engine_help(parent: Any = None) -> None:
    from PyQt5.QtWidgets import QMessageBox

    QMessageBox.information(parent, ENGINE_HELP_TITLE, ENGINE_HELP_TEXT)


def populate_engine_combo(combo: Any) -> None:
    combo.clear()
    combo.addItem("Argos 强化", "argos")
    combo.addItem("Ollama 精", "ollama")
    combo.setToolTip(ENGINE_COMBO_TOOLTIP)
    sync_engine_combo(combo)
