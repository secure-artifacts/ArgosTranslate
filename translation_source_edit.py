"""原文输入：Ctrl+Shift+V 仅粘贴纯文本（跳过 HTML/富文本格式）。"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QTextEdit


def sanitize_paste_text(text: str) -> str:
    if not text:
        return text
    try:
        import translation_quality as tq

        return tq.sanitize_source_text(text, for_llm=False)
    except ImportError:
        return text


def is_paste_plain_shortcut(event) -> bool:
    return (
        event.key() == Qt.Key_V
        and event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier)
    )


def paste_plain_into_text_edit(edit: QTextEdit) -> None:
    text = sanitize_paste_text(QApplication.clipboard().text())
    if text:
        edit.insertPlainText(text)


class SourceTranslationTextEdit(QTextEdit):
    """翻译原文区：支持 Ctrl+Shift+V 纯文本粘贴。"""

    def keyPressEvent(self, event) -> None:
        if is_paste_plain_shortcut(event):
            paste_plain_into_text_edit(self)
            return
        super().keyPressEvent(event)
