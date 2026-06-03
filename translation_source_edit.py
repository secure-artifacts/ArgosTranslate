"""原文/译文输入：纯文本粘贴（跳过 HTML/富文本格式）。"""
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


def sanitize_target_paste_text(text: str) -> str:
    if not text:
        return text
    try:
        import translation_quality as tq

        t = tq.sanitize_source_text(text, for_llm=False)
        return tq.sanitize_llm_translation_output(t)
    except ImportError:
        return text


def is_paste_plain_shortcut(event) -> bool:
    return (
        event.key() == Qt.Key_V
        and event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier)
    )


def is_paste_shortcut(event) -> bool:
    return event.key() == Qt.Key_V and event.modifiers() == Qt.ControlModifier


def paste_plain_into_text_edit(
    edit: QTextEdit,
    *,
    for_target: bool = False,
) -> None:
    sanitizer = sanitize_target_paste_text if for_target else sanitize_paste_text
    text = sanitizer(QApplication.clipboard().text())
    if text:
        edit.insertPlainText(text)


def insert_plain_from_mime(edit: QTextEdit, source, *, for_target: bool = False) -> bool:
    """从剪贴板 MIME 插入纯文本；已处理则返回 True。"""
    if source is None:
        return False
    sanitizer = sanitize_target_paste_text if for_target else sanitize_paste_text
    text = ""
    if source.hasText():
        text = sanitizer(source.text())
    elif source.hasFormat("text/plain"):
        raw = source.data("text/plain")
        if isinstance(raw, bytes):
            text = sanitizer(raw.decode("utf-8", errors="replace"))
        else:
            text = sanitizer(str(raw))
    if text:
        edit.insertPlainText(text)
        return True
    return False


class SourceTranslationTextEdit(QTextEdit):
    """翻译原文区：支持 Ctrl+Shift+V 纯文本粘贴。"""

    def keyPressEvent(self, event) -> None:
        if is_paste_plain_shortcut(event):
            paste_plain_into_text_edit(self)
            return
        super().keyPressEvent(event)


class TargetTranslationTextEdit(QTextEdit):
    """翻译译文区：粘贴时仅写入纯文本值（Ctrl+V / Ctrl+Shift+V）。"""

    def insertFromMimeData(self, source) -> None:
        if insert_plain_from_mime(self, source, for_target=True):
            return
        super().insertFromMimeData(source)

    def keyPressEvent(self, event) -> None:
        if is_paste_plain_shortcut(event) or is_paste_shortcut(event):
            paste_plain_into_text_edit(self, for_target=True)
            return
        super().keyPressEvent(event)
