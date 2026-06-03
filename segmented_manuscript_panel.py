"""分句稿件模式：每行原文与译文同一行对齐。"""
from __future__ import annotations

from typing import Callable

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QTextOption
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from translation_source_edit import (
    SourceTranslationTextEdit,
    TargetTranslationTextEdit,
    sanitize_paste_text,
)


def _min_edit_height(edit) -> int:
    fm = edit.fontMetrics()
    return max(40, fm.lineSpacing() + 18)


def _measure_edit_height(edit) -> int:
    """按当前宽度与换行后的文档高度计算编辑框高度。"""
    doc = edit.document()
    if doc is None:
        return _min_edit_height(edit)
    viewport_w = edit.viewport().width()
    if viewport_w < 40:
        viewport_w = max(40, edit.width() - 8)
    doc.setTextWidth(max(40, viewport_w))
    layout = doc.documentLayout()
    if layout is None:
        return _min_edit_height(edit)
    content_h = int(layout.documentSize().height())
    frame = edit.frameWidth() * 2
    return max(_min_edit_height(edit), content_h + frame + 12)


class SegmentSourceEdit(SourceTranslationTextEdit):
    """分句原文：Enter 在下一行插入新句；粘贴多行自动拆分。"""

    new_row_requested = pyqtSignal()
    multiline_pasted = pyqtSignal(list)

    def insertFromMimeData(self, source) -> None:
        text = ""
        if source is not None and source.hasText():
            text = sanitize_paste_text(source.text())
        if text and ("\n" in text or "\r" in text):
            parts = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            self.multiline_pasted.emit(parts)
            return
        from translation_source_edit import insert_plain_from_mime

        if insert_plain_from_mime(self, source):
            return
        super().insertFromMimeData(source)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
            event.modifiers() & Qt.ShiftModifier
        ):
            self.new_row_requested.emit()
            return
        super().keyPressEvent(event)


class _SegmentRow(QWidget):
    def __init__(
        self,
        index: int,
        *,
        on_adopt: Callable[[int], None],
        on_source_changed: Callable[[], None] | None,
        on_new_row: Callable[[int], None],
        on_multiline_paste: Callable[[int, list], None],
        on_delete_row: Callable[[int], None],
        on_target_changed: Callable[[], None] | None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.index = index
        self._height_sync_timer = QTimer(self)
        self._height_sync_timer.setSingleShot(True)
        self._height_sync_timer.timeout.connect(self._sync_row_heights)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)

        self._num = QLabel(f"{index + 1}")
        self._num.setObjectName("SegmentRowNum")
        self._num.setFixedWidth(28)
        self._num.setAlignment(Qt.AlignTop | Qt.AlignRight)

        self.src_edit = SegmentSourceEdit()
        self.src_edit.setPlaceholderText("原文…")
        self.src_edit.setLineWrapMode(SegmentSourceEdit.WidgetWidth)
        self.src_edit.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.src_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.src_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.src_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.src_edit.new_row_requested.connect(lambda: on_new_row(index))
        self.src_edit.multiline_pasted.connect(
            lambda parts, idx=index: on_multiline_paste(idx, parts)
        )

        self.tgt_edit = TargetTranslationTextEdit()
        self.tgt_edit.setPlaceholderText("译文…")
        self.tgt_edit.setLineWrapMode(TargetTranslationTextEdit.WidgetWidth)
        self.tgt_edit.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.tgt_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tgt_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tgt_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.adopt_btn = QPushButton("采纳为 TM")
        self.adopt_btn.setObjectName("TextAction")
        self.adopt_btn.setToolTip("将本行原文与译文写入本机 TM")
        self.adopt_btn.clicked.connect(lambda: on_adopt(index))

        self.delete_btn = QPushButton("删除")
        self.delete_btn.setObjectName("DangerButton")
        self.delete_btn.setToolTip("删除本行原文与译文")
        self.delete_btn.clicked.connect(lambda: on_delete_row(index))

        layout.addWidget(self._num, 0, Qt.AlignTop)
        layout.addWidget(self.src_edit, 1)
        layout.addWidget(self.tgt_edit, 1)
        layout.addWidget(self.adopt_btn, 0, Qt.AlignTop)
        layout.addWidget(self.delete_btn, 0, Qt.AlignTop)

        if on_source_changed is not None:
            self.src_edit.textChanged.connect(on_source_changed)
        if on_target_changed is not None:
            self.tgt_edit.textChanged.connect(on_target_changed)
        if on_target_changed is not None:
            self.tgt_edit.textChanged.connect(on_target_changed)
        for edit in (self.src_edit, self.tgt_edit):
            edit.textChanged.connect(self._schedule_sync_row_heights)
            edit.document().contentsChanged.connect(self._schedule_sync_row_heights)
        self._schedule_sync_row_heights()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_sync_row_heights()

    def _schedule_sync_row_heights(self) -> None:
        self._height_sync_timer.start(0)

    def set_index(self, index: int) -> None:
        self.index = index
        self._num.setText(f"{index + 1}")

    def _sync_row_heights(self) -> None:
        h = max(
            _measure_edit_height(self.src_edit),
            _measure_edit_height(self.tgt_edit),
        )
        for edit in (self.src_edit, self.tgt_edit):
            edit.setMinimumHeight(h)
            edit.setMaximumHeight(h)

    def source_text(self) -> str:
        return (self.src_edit.toPlainText() or "").strip()

    def target_text(self) -> str:
        return (self.tgt_edit.toPlainText() or "").strip()

    def set_source_text(self, text: str) -> None:
        self.src_edit.blockSignals(True)
        self.src_edit.setPlainText(text or "")
        self.src_edit.blockSignals(False)
        self._schedule_sync_row_heights()

    def set_target_text(self, text: str) -> None:
        self.tgt_edit.blockSignals(True)
        self.tgt_edit.setPlainText(text or "")
        self.tgt_edit.blockSignals(False)
        self._schedule_sync_row_heights()

    def char_count(self) -> int:
        return len(self.src_edit.toPlainText()) + len(self.tgt_edit.toPlainText())

    def focus_source(self) -> None:
        self.src_edit.setFocus()


class SegmentedManuscriptPanel(QWidget):
    """每行：原文 | 译文 | 采纳为 TM，保证逐句对齐。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._on_adopt: Callable[[int], None] | None = None
        self._on_source_changed: Callable[[], None] | None = None
        self._on_target_changed: Callable[[], None] | None = None
        self._block_sync = False
        self._rows: list[_SegmentRow] = []
        self._pending_sources: list[str] = []
        self._pending_targets: list[str] = []

        hint = QLabel(
            "每行一句：在原文框输入或粘贴，按 Enter 换到下一句；"
            "可编辑译文后「采纳为 TM」，不需要的行点「删除」。"
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)

        header = QHBoxLayout()
        header.setSpacing(6)
        header.addSpacing(28)
        src_hdr = QLabel("原文")
        src_hdr.setObjectName("HintLabel")
        tgt_hdr = QLabel("译文")
        tgt_hdr.setObjectName("HintLabel")
        header.addWidget(src_hdr, 1)
        header.addWidget(tgt_hdr, 1)
        header.addSpacing(132)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._container = QWidget()
        self._rows_layout = QVBoxLayout(self._container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        self._rows_layout.addStretch()
        self._scroll.setWidget(self._container)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        root.addWidget(hint)
        root.addLayout(header)
        root.addWidget(self._scroll, 1)

    def refresh_row_heights(self) -> None:
        self._sync_all_row_heights()

    def set_adopt_handler(self, handler: Callable[[int], None]) -> None:
        self._on_adopt = handler

    def set_source_changed_handler(self, handler: Callable[[], None]) -> None:
        self._on_source_changed = handler

    def set_target_changed_handler(self, handler: Callable[[], None]) -> None:
        self._on_target_changed = handler

    def row_count(self) -> int:
        return len(self._rows)

    def ensure_min_rows(self, count: int) -> None:
        self._set_row_count(max(1, int(count)))

    def _set_row_count(self, count: int) -> None:
        if self._block_sync:
            return
        count = max(0, int(count))
        if count == len(self._rows):
            return
        preserved_src = self.get_source_lines()
        preserved_tgt = self.get_target_lines()
        if len(preserved_src) < count:
            preserved_src.extend([""] * (count - len(preserved_src)))
        else:
            preserved_src = preserved_src[:count]
        if len(preserved_tgt) < count:
            preserved_tgt.extend([""] * (count - len(preserved_tgt)))
        else:
            preserved_tgt = preserved_tgt[:count]
        self._pending_sources = preserved_src
        self._pending_targets = preserved_tgt
        self._rebuild_rows(count)

    def _rebuild_rows(self, count: int) -> None:
        while self._rows_layout.count() > 1:
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()
        handler = self._on_adopt or (lambda _i: None)
        for i in range(count):
            row = _SegmentRow(
                i,
                on_adopt=handler,
                on_source_changed=self._on_source_changed,
                on_new_row=self._insert_row_after,
                on_multiline_paste=self._apply_multiline_paste,
                on_delete_row=self._delete_row,
                on_target_changed=self._on_target_changed,
                parent=self._container,
            )
            if i < len(self._pending_sources):
                row.set_source_text(self._pending_sources[i])
            if i < len(self._pending_targets):
                row.set_target_text(self._pending_targets[i])
            self._rows.append(row)
            self._rows_layout.insertWidget(i, row)
        self._pending_sources = []
        self._pending_targets = []
        QTimer.singleShot(0, self._sync_all_row_heights)

    def _sync_all_row_heights(self) -> None:
        for row in self._rows:
            row._schedule_sync_row_heights()

    def _insert_row_after(self, index: int) -> None:
        if self._block_sync:
            return
        pos = max(0, min(index, len(self._rows) - 1)) + 1
        sources = self.get_source_lines()
        targets = self.get_target_lines()
        sources.insert(pos, "")
        targets.insert(pos, "")
        self._block_sync = True
        try:
            self._pending_sources = sources
            self._pending_targets = targets
            self._rebuild_rows(len(sources))
            if 0 <= pos < len(self._rows):
                self._rows[pos].focus_source()
        finally:
            self._block_sync = False

    def _delete_row(self, index: int) -> None:
        if self._block_sync:
            return
        if not (0 <= index < len(self._rows)):
            return
        sources = self.get_source_lines()
        targets = self.get_target_lines()
        if len(sources) <= 1:
            self._block_sync = True
            try:
                self._rows[0].set_source_text("")
                self._rows[0].set_target_text("")
                if self._on_source_changed is not None:
                    self._on_source_changed()
            finally:
                self._block_sync = False
            return
        del sources[index]
        del targets[index]
        self._block_sync = True
        try:
            self._pending_sources = sources
            self._pending_targets = targets
            self._rebuild_rows(len(sources))
            focus = min(index, len(self._rows) - 1)
            if 0 <= focus < len(self._rows):
                self._rows[focus].focus_source()
            if self._on_source_changed is not None:
                self._on_source_changed()
        finally:
            self._block_sync = False

    def _apply_multiline_paste(self, index: int, parts: list) -> None:
        if self._block_sync or not parts:
            return
        lines = [str(p) for p in parts]
        sources = self.get_source_lines()
        targets = self.get_target_lines()
        if not sources:
            sources = [""]
            targets = [""]
        index = max(0, min(index, len(sources) - 1))
        head_src = sources[:index]
        head_tgt = targets[:index]
        tail_src = sources[index + 1 :]
        tail_tgt = targets[index + 1 :]
        mid_tgt = [""] * len(lines)
        merged_src = head_src + lines + tail_src
        merged_tgt = head_tgt + mid_tgt + tail_tgt
        self._block_sync = True
        try:
            self._pending_sources = merged_src
            self._pending_targets = merged_tgt
            self._rebuild_rows(len(merged_src))
            focus = index + len(lines) - 1
            if 0 <= focus < len(self._rows):
                self._rows[focus].focus_source()
            if self._on_source_changed is not None:
                self._on_source_changed()
        finally:
            self._block_sync = False

    def get_source_lines(self) -> list[str]:
        return [row.src_edit.toPlainText() for row in self._rows]

    def get_target_lines(self) -> list[str]:
        return [row.tgt_edit.toPlainText() for row in self._rows]

    def joined_source_text(self) -> str:
        return "\n".join(self.get_source_lines())

    def joined_target_text(self) -> str:
        return "\n".join(self.get_target_lines())

    def total_char_count(self) -> int:
        return sum(row.char_count() for row in self._rows)

    def total_source_char_count(self) -> int:
        return sum(len(row.src_edit.toPlainText()) for row in self._rows)

    def total_target_char_count(self) -> int:
        return sum(len(row.tgt_edit.toPlainText()) for row in self._rows)

    def set_target_line(self, index: int, text: str) -> None:
        if 0 <= index < len(self._rows):
            self._rows[index].set_target_text(text)

    def set_all_rows(
        self,
        sources: list[str],
        targets: list[str] | None = None,
    ) -> None:
        self._block_sync = True
        try:
            n = max(1, len(sources)) if sources else 1
            tgt = list(targets or [])
            if len(tgt) < n:
                tgt.extend([""] * (n - len(tgt)))
            self._pending_sources = list(sources) if sources else [""]
            self._pending_targets = tgt[:n]
            if not self._pending_sources:
                self._pending_sources = [""]
            self._rebuild_rows(len(self._pending_sources))
        finally:
            self._block_sync = False

    def set_all_targets(self, lines: list[str]) -> None:
        sources = self.get_source_lines() or [""]
        n = max(len(sources), len(lines))
        if len(sources) < n:
            sources.extend([""] * (n - len(sources)))
        tgt = list(lines)
        if len(tgt) < n:
            tgt.extend([""] * (n - len(tgt)))
        self.set_all_rows(sources, tgt)

    def clear_targets(self) -> None:
        self._block_sync = True
        try:
            for row in self._rows:
                row.set_target_text("")
        finally:
            self._block_sync = False

    def clear_all(self) -> None:
        self.set_all_rows([""], [""])

    def source_line_for(self, index: int) -> str:
        if 0 <= index < len(self._rows):
            return self._rows[index].source_text()
        return ""

    def target_line_for(self, index: int) -> str:
        if 0 <= index < len(self._rows):
            return self._rows[index].target_text()
        return ""

    def non_empty_source_lines(self) -> list[str]:
        return [ln for ln in self.get_source_lines() if (ln or "").strip()]
