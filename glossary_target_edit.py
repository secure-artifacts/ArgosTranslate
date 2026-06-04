"""译文区：术语多义高亮、悬停选义、点击替换。"""
from __future__ import annotations

from typing import Any, Callable

from PyQt5.QtCore import QPoint, Qt, QTimer
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from translation_source_edit import TargetTranslationTextEdit

_GLOSSARY_BG = QColor(255, 243, 205)
_GLOSSARY_FG = QColor(26, 115, 232)
_POPUP_HIDE_MS = 420


class GlossaryChoicePopup(QFrame):
    """悬停时展示术语库一行内的各译法（每行一种）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName("GlossaryChoicePopup")
        self.setStyleSheet(
            """
            QFrame#GlossaryChoicePopup {
                background: palette(base);
                border: 1px solid palette(mid);
                border-radius: 6px;
            }
            QPushButton#glossaryAltBtn {
                text-align: left;
                padding: 6px 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton#glossaryAltBtn:hover {
                background: palette(highlight);
                color: palette(highlighted-text);
            }
            QLabel#glossaryAltHead {
                color: palette(mid);
                font-size: 11px;
                padding: 4px 10px 2px 10px;
            }
            """
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)
        self._head = QLabel("")
        self._head.setObjectName("glossaryAltHead")
        self._head.setWordWrap(True)
        outer.addWidget(self._head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(220)
        self._body = QWidget()
        self._body_l = QVBoxLayout(self._body)
        self._body_l.setContentsMargins(0, 0, 0, 0)
        self._body_l.setSpacing(0)
        scroll.setWidget(self._body)
        outer.addWidget(scroll)
        self._on_pick: Callable[[int], None] | None = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_choices(
        self,
        global_pos: QPoint,
        *,
        zh_source: str,
        alternatives: list[str],
        chosen_index: int,
        on_pick: Callable[[int], None],
    ) -> None:
        self._on_pick = on_pick
        while self._body_l.count():
            item = self._body_l.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        head = (zh_source or "").strip()
        self._head.setText(f"术语：{head}" if head else "术语译法")
        self._head.setVisible(bool(head))
        for i, alt in enumerate(alternatives):
            label = (alt or "").strip()
            if not label:
                continue
            btn = QPushButton(label)
            btn.setObjectName("glossaryAltBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumWidth(280)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            if i == chosen_index:
                btn.setStyleSheet(
                    "font-weight: 600; color: #1A73E8; background: #E8F0FE;"
                )
            idx = i

            def _clicked(_checked: bool = False, pick: int = idx) -> None:
                if self._on_pick is not None:
                    self._on_pick(pick)
                self.hide()

            btn.clicked.connect(_clicked)
            self._body_l.addWidget(btn)
        self.adjustSize()
        self.move(global_pos)
        self.show()
        self.raise_()
        self._hide_timer.stop()

    def schedule_hide(self) -> None:
        self._hide_timer.start(_POPUP_HIDE_MS)

    def cancel_hide(self) -> None:
        self._hide_timer.stop()

    def enterEvent(self, event) -> None:
        self.cancel_hide()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.schedule_hide()
        super().leaveEvent(event)


class GlossarySpanMixin:
    """术语多义高亮与悬停切换（可混入 QTextEdit 子类）。"""

    def _init_glossary_spans(self) -> None:
        if not hasattr(self, "_glossary_spans"):
            self._glossary_spans: list[dict[str, Any]] = []
        self._programmatic_update = False
        self._active_span_index: int | None = None
        self._popup = GlossaryChoicePopup(None)
        self.setMouseTracking(True)
        if not getattr(self, "_glossary_text_hooked", False):
            self.textChanged.connect(self._on_glossary_user_text_changed)
            self._glossary_text_hooked = True

    def set_glossary_translation(
        self, text: str, spans: list[dict[str, Any]] | None
    ) -> None:
        self._init_glossary_spans()
        self._programmatic_update = True
        try:
            self.setPlainText(text or "")
            self._glossary_spans = [dict(s) for s in (spans or [])]
            self._apply_glossary_highlights()
        finally:
            self._programmatic_update = False

    def glossary_spans(self) -> list[dict[str, Any]]:
        return [dict(s) for s in getattr(self, "_glossary_spans", [])]

    def _on_glossary_user_text_changed(self) -> None:
        if getattr(self, "_programmatic_update", False):
            return
        self._glossary_spans = []
        self._active_span_index = None
        if hasattr(self, "_popup"):
            self._popup.hide()

    def _apply_glossary_highlights(self) -> None:
        doc = self.document()
        if doc is None:
            return
        plain = self.toPlainText()
        fmt_clear = QTextCharFormat()
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.Document)
        cursor.setCharFormat(fmt_clear)
        cursor.clearSelection()
        if not self._glossary_spans:
            return
        fmt = QTextCharFormat()
        fmt.setBackground(_GLOSSARY_BG)
        fmt.setForeground(_GLOSSARY_FG)
        fmt.setFontUnderline(True)
        for sp in self._glossary_spans:
            start = int(sp.get("start") or 0)
            end = int(sp.get("end") or 0)
            if end <= start or start >= len(plain):
                continue
            end = min(end, len(plain))
            c = QTextCursor(doc)
            c.setPosition(start)
            c.setPosition(end, QTextCursor.KeepAnchor)
            c.mergeCharFormat(fmt)

    def _span_index_at(self, pos: int) -> int | None:
        for i, sp in enumerate(getattr(self, "_glossary_spans", [])):
            start = int(sp.get("start") or 0)
            end = int(sp.get("end") or 0)
            if start <= pos < end:
                return i
        return None

    def _show_popup_for_span(self, index: int, global_pos: QPoint) -> None:
        spans = getattr(self, "_glossary_spans", [])
        if index < 0 or index >= len(spans):
            return
        sp = spans[index]
        alts = sp.get("alternatives")
        if not isinstance(alts, list) or len(alts) < 2:
            return
        self._active_span_index = index
        self._popup.show_choices(
            global_pos,
            zh_source=str(sp.get("zh_source") or ""),
            alternatives=alts,
            chosen_index=int(sp.get("chosen_index") or 0),
            on_pick=lambda pick, ix=index: self._apply_span_choice(ix, pick),
        )

    def _apply_span_choice(self, span_index: int, option_index: int) -> None:
        spans = getattr(self, "_glossary_spans", [])
        if span_index < 0 or span_index >= len(spans):
            return
        sp = spans[span_index]
        alts = sp.get("alternatives")
        if not isinstance(alts, list) or option_index < 0 or option_index >= len(
            alts
        ):
            return
        option = (alts[option_index] or "").strip()
        if not option:
            return
        lang = str(sp.get("target_lang") or "ru")
        try:
            import glossary_alternatives as ga
        except ImportError:
            ga = None  # type: ignore
        ctx_before = str(sp.get("context_before") or "")
        ctx_after = str(sp.get("context_after") or "")
        if ga is not None:
            new_surface = ga.inflect_option(
                option,
                lang,
                ctx_before,
                ctx_after,
                fixed_grammemes=sp.get("fixed_grammemes"),
                pos_hint=sp.get("pos"),
                words=sp.get("words") if isinstance(sp.get("words"), list) else None,
            )
        else:
            new_surface = option
        start = int(sp.get("start") or 0)
        end = int(sp.get("end") or 0)
        plain = self.toPlainText()
        if end > len(plain) or start < 0:
            return
        delta = len(new_surface) - (end - start)
        new_plain = plain[:start] + new_surface + plain[end:]
        self._programmatic_update = True
        try:
            self.setPlainText(new_plain)
            sp["surface"] = new_surface
            sp["chosen_index"] = option_index
            sp["end"] = start + len(new_surface)
            sp["context_before"] = new_plain[:start]
            sp["context_after"] = new_plain[start + len(new_surface) :]
            for j, other in enumerate(spans):
                if j == span_index:
                    continue
                ostart = int(other.get("start") or 0)
                if ostart >= end:
                    other["start"] = ostart + delta
                    other["end"] = int(other.get("end") or 0) + delta
                    oend = int(other.get("end") or 0)
                    other["context_before"] = new_plain[: int(other["start"])]
                    other["context_after"] = new_plain[oend:]
            self._apply_glossary_highlights()
        finally:
            self._programmatic_update = False
        self._popup.hide()

    def _glossary_mouse_move(self, event) -> bool:
        """若处理了术语悬停则返回 True。"""
        self._init_glossary_spans()
        if not self._glossary_spans:
            return False
        pos = self.cursorForPosition(event.pos()).position()
        idx = self._span_index_at(pos)
        if idx is not None:
            self._popup.cancel_hide()
            if idx != self._active_span_index or not self._popup.isVisible():
                self._show_popup_for_span(
                    idx, self.mapToGlobal(event.pos() + QPoint(12, 16))
                )
            return True
        self._active_span_index = None
        if self._popup.isVisible():
            self._popup.schedule_hide()
        return False

    def _glossary_leave_event(self) -> None:
        if hasattr(self, "_popup") and self._popup.isVisible():
            self._popup.schedule_hide()


class GlossaryTargetTranslationTextEdit(GlossarySpanMixin, TargetTranslationTextEdit):
    """译文区（含术语多义交互）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_glossary_spans()

    def mouseMoveEvent(self, event) -> None:
        if self._glossary_mouse_move(event):
            super().mouseMoveEvent(event)
            return
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._glossary_leave_event()
        super().leaveEvent(event)


def make_glossary_clickable_target_class(clickable_cls: type) -> type:
    """与 ClickableTranslationTextEdit 组合，保留查词 + 术语切换。"""

    class GlossaryClickableTargetTextEdit(GlossarySpanMixin, clickable_cls):
        def __init__(self, parent_window, *, role: str = "target"):
            super().__init__(parent_window, role=role)
            self._init_glossary_spans()

        def mouseMoveEvent(self, event) -> None:
            self._glossary_mouse_move(event)
            super().mouseMoveEvent(event)

        def leaveEvent(self, event) -> None:
            self._glossary_leave_event()
            super().leaveEvent(event)

    GlossaryClickableTargetTextEdit.__name__ = "GlossaryClickableTargetTextEdit"
    return GlossaryClickableTargetTextEdit
