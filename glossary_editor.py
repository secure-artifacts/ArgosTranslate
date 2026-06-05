"""
术语库：源语词条 → 多目标语字段（zh_glossary.json）。
界面：选择语言对，批量添加/删除，导入/导出。
"""
from __future__ import annotations

import csv
import json
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import terminology_bridge as tb

from glossary_manager import GlossaryStore, infer_pos_for_target
from glossary_cell_sanitize import parse_clipboard_table, sanitize_glossary_cell

from PyQt5.QtCore import Qt, QEvent, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHeaderView,
)


def _prefs_path() -> Path:
    return _root / "data" / "config" / "glossary_gui_prefs.json"


def _load_prefs() -> dict:
    p = _prefs_path()
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_prefs(patch: dict) -> None:
    data = _load_prefs()
    data.update(patch)
    p = _prefs_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_open_on_startup() -> bool:
    return bool(_load_prefs().get("open_glossary_on_startup", False))


def save_open_on_startup(enabled: bool) -> None:
    _save_prefs({"open_glossary_on_startup": enabled})


def load_lang_pair_prefs() -> tuple[str, str]:
    d = _load_prefs()
    src = (d.get("src_lang") or "zh").strip().lower()
    tgt = (d.get("tgt_lang") or "ru").strip().lower()
    return src, tgt


def save_lang_pair_prefs(src_lang: str, tgt_lang: str) -> None:
    _save_prefs(
        {
            "src_lang": (src_lang or "zh").strip().lower(),
            "tgt_lang": (tgt_lang or "ru").strip().lower(),
        }
    )


def _normalize_pos(raw_pos: str) -> str:
    value = (raw_pos or "").strip().lower()
    if value in {"verb", "v", "动词"}:
        return "verb"
    if value in {"adj", "adjective", "a", "形容词"}:
        return "adj"
    if value in {"other", "phrase", "短语", "其他"}:
        return "other"
    return "noun"


class GlossaryPasteTableWidget(QTableWidget):
    """支持从 Google 表格 / Excel 粘贴，并自动清理 \"\" 等引号。"""

    def __init__(self, rows: int = 0, columns: int = 2, parent=None) -> None:
        super().__init__(rows, columns, parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setWordWrap(True)
        hdr = self.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        if columns > 1:
            hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        vhdr = self.verticalHeader()
        vhdr.setDefaultSectionSize(36)
        vhdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        self._row_resize_timer = QTimer(self)
        self._row_resize_timer.setSingleShot(True)
        self._row_resize_timer.timeout.connect(self._resize_rows_for_contents)
        self.itemChanged.connect(self._schedule_row_resize)

    @staticmethod
    def _make_item(text: str) -> QTableWidgetItem:
        t = text or ""
        it = QTableWidgetItem(t)
        it.setToolTip(t)
        it.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
        return it

    def _set_cell(self, row: int, col: int, text: str) -> None:
        self.setItem(row, col, self._make_item(text))

    def _schedule_row_resize(self, *_args) -> None:
        self._row_resize_timer.start(0)

    def _resize_rows_for_contents(self) -> None:
        self.resizeRowsToContents()
        for r in range(self.rowCount()):
            self.setRowHeight(r, max(self.rowHeight(r), 36))

    def _cell_text(self, row: int, col: int) -> str:
        it = self.item(row, col)
        return sanitize_glossary_cell(it.text() if it else "")

    def _close_cell_editor(self, *, revert: bool = True) -> None:
        if self.state() != QAbstractItemView.EditingState:
            return
        editor = QApplication.focusWidget()
        if editor is None:
            return
        hint = (
            QAbstractItemDelegate.RevertModelCache
            if revert
            else QAbstractItemDelegate.SubmitModelCache
        )
        self.closeEditor(editor, hint)

    def paste_from_clipboard(self) -> bool:
        clip = QApplication.clipboard().text()
        rows = parse_clipboard_table(clip)
        if not rows:
            return False
        self._close_cell_editor(revert=True)
        indexes = self.selectedIndexes()
        if indexes:
            start_row = min(i.row() for i in indexes)
            start_col = min(i.column() for i in indexes)
        else:
            start_row = max(0, self.currentRow())
            start_col = max(0, self.currentColumn())
        max_cols = max(len(r) for r in rows)
        single_col = max_cols == 1 and len(rows) > 1
        anchor_src = ""
        if single_col and start_col >= 1:
            anchor_src = self._cell_text(start_row, 0)
        need = start_row + len(rows)
        while self.rowCount() < need:
            self.insertRow(self.rowCount())
        for i, row_cells in enumerate(rows):
            r = start_row + i
            for j, cell in enumerate(row_cells):
                col = start_col + j
                if col >= self.columnCount():
                    break
                self._set_cell(r, col, cell)
            if single_col and start_col >= 1 and anchor_src:
                if not self._cell_text(r, 0):
                    self._set_cell(r, 0, anchor_src)
        self._resize_rows_for_contents()
        return True

    def editItem(self, item: QTableWidgetItem) -> None:
        super().editItem(item)
        editor = QApplication.focusWidget()
        if editor is not None:
            editor.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.KeyPress
            and event.matches(QKeySequence.Paste)
            and isinstance(watched, QLineEdit)
        ):
            if self.paste_from_clipboard():
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.Paste):
            if self.paste_from_clipboard():
                return
        super().keyPressEvent(event)

    def ensure_trailing_blank_row(self) -> None:
        """末尾保留一行空行，便于继续输入。"""
        if self.rowCount() == 0:
            self.insertRow(0)
            return
        last = self.rowCount() - 1
        if any(self._cell_text(last, c) for c in range(self.columnCount())):
            self.insertRow(self.rowCount())
        elif self.rowCount() > 1:
            prev = self.rowCount() - 2
            if not any(self._cell_text(prev, c) for c in range(self.columnCount())):
                self.removeRow(last)


class BulkAddDialog(QDialog):
    def __init__(
        self,
        src_label: str,
        tgt_label: str,
        *,
        show_pos: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量添加术语")
        self.setMinimumSize(640, 420)
        self.resize(720, 480)
        self._show_pos = bool(show_pos)
        cols = 3 if self._show_pos else 2
        hint = QLabel(
            f"在表格中填写或从 Google 表格 / Excel 复制后 Ctrl+V 粘贴。"
            f"同一{src_label}可占多行，每行一种{tgt_label}译法。"
            + (
                f"第三列可选词性（名词/动词/形容词）。"
                if self._show_pos
                else ""
            )
        )
        hint.setWordWrap(True)
        self.table = GlossaryPasteTableWidget(6, cols, self)
        headers = [f"源语（{src_label}）", f"译文（{tgt_label}）"]
        if self._show_pos:
            headers.append("词性")
        self.table.setHorizontalHeaderLabels(headers)
        btn_add = QPushButton("添加行")
        btn_add.clicked.connect(self._add_rows)
        btn_del = QPushButton("删除选中行")
        btn_del.clicked.connect(self._delete_selected_rows)
        tool = QHBoxLayout()
        tool.addWidget(btn_add)
        tool.addWidget(btn_del)
        tool.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addWidget(self.table, 1)
        lay.addLayout(tool)
        lay.addWidget(buttons)

    def _add_rows(self) -> None:
        for _ in range(3):
            self.table.insertRow(self.table.rowCount())

    def _delete_selected_rows(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        if self.table.rowCount() == 0:
            self.table.insertRow(0)

    def _on_accept(self) -> None:
        if not self.entries():
            QMessageBox.warning(
                self,
                "批量添加",
                "请至少填写一行有效的源语与译文。",
            )
            return
        self.accept()

    def entries(self) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        for r in range(self.table.rowCount()):
            src = self.table._cell_text(r, 0)
            tgt = self.table._cell_text(r, 1)
            if not src and not tgt:
                continue
            if not src or not tgt:
                continue
            pos_raw = self.table._cell_text(r, 2) if self._show_pos else ""
            out.append((src, tgt, pos_raw))
        return out


class GlossaryEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(720, 480)
        self.resize(860, 560)

        self._lang_choices = tb.list_glossary_language_choices()
        self._code_to_label = dict(self._lang_choices)

        pref_src, pref_tgt = load_lang_pair_prefs()

        pair_row = QHBoxLayout()
        pair_row.addWidget(QLabel("源语言"))
        self.src_lang_combo = QComboBox()
        self.tgt_lang_combo = QComboBox()
        for code, label in self._lang_choices:
            self.src_lang_combo.addItem(label, code)
            self.tgt_lang_combo.addItem(label, code)
        self._set_combo_code(self.src_lang_combo, pref_src)
        self._set_combo_code(self.tgt_lang_combo, pref_tgt)
        self.src_lang_combo.currentIndexChanged.connect(self._on_lang_pair_changed)
        self.tgt_lang_combo.currentIndexChanged.connect(self._on_lang_pair_changed)
        pair_row.addWidget(self.src_lang_combo, 1)
        pair_row.addWidget(QLabel("→"))
        pair_row.addWidget(self.tgt_lang_combo, 1)

        self.hint = QLabel()
        self.hint.setObjectName("HintLabel")
        self.hint.setWordWrap(True)
        self._refresh_hint()

        self.table = GlossaryPasteTableWidget(0, 2, self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._update_table_headers()

        btn_bulk = QPushButton("批量添加…")
        btn_bulk.clicked.connect(self._on_bulk_add)
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self.delete_selected_rows)
        btn_clear_all = QPushButton("删除全部…")
        btn_clear_all.clicked.connect(self.clear_all_entries)
        btn_import = QPushButton("导入…")
        btn_import.clicked.connect(self.import_table_file)
        btn_export = QPushButton("导出…")
        btn_export.clicked.connect(self.export_csv_file)

        row_tools = QHBoxLayout()
        row_tools.setSpacing(8)
        row_tools.addWidget(btn_bulk)
        row_tools.addWidget(btn_del)
        row_tools.addWidget(btn_clear_all)
        row_tools.addWidget(btn_import)
        row_tools.addWidget(btn_export)
        row_tools.addStretch()

        btn_save = QPushButton("保存")
        btn_save.setDefault(True)
        btn_save.clicked.connect(lambda: self.save_to_file())
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.hide)

        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(btn_save)
        bottom.addWidget(btn_close)

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addLayout(pair_row)
        layout.addWidget(self.hint)
        layout.addWidget(self.table, 1)
        layout.addLayout(row_tools)
        layout.addLayout(bottom)
        self.setLayout(layout)

        try:
            import portable_ui_theme as put

            btn_save.setObjectName("PrimaryButton")
            btn_bulk.setObjectName("AccentButton")
            btn_import.setObjectName("AccentButton")
            btn_del.setObjectName("DangerButton")
            btn_clear_all.setObjectName("DangerButton")
            btn_close.setObjectName("GhostButton")
            for b in (
                btn_save,
                btn_bulk,
                btn_import,
                btn_export,
                btn_del,
                btn_clear_all,
                btn_close,
            ):
                put.polish_widget(b)
            put.polish_widget(self.hint)
        except ImportError:
            pass

        sc_save = QShortcut(QKeySequence.Save, self)
        sc_save.activated.connect(self.save_to_file)

        self._update_window_title()
        self.reload_from_file()

    @staticmethod
    def _set_combo_code(combo: QComboBox, code: str) -> None:
        want = (code or "").strip().lower()
        for i in range(combo.count()):
            if combo.itemData(i) == want:
                combo.setCurrentIndex(i)
                return
        if combo.count():
            combo.setCurrentIndex(0)

    def _src_code(self) -> str:
        return (self.src_lang_combo.currentData() or "zh").strip().lower()

    def _tgt_code(self) -> str:
        return (self.tgt_lang_combo.currentData() or "ru").strip().lower()

    def _src_label(self) -> str:
        return self._code_to_label.get(self._src_code(), self._src_code())

    def _tgt_label(self) -> str:
        return self._code_to_label.get(self._tgt_code(), self._tgt_code())

    def _update_window_title(self) -> None:
        self.setWindowTitle(
            f"术语库（{self._src_label()} → {self._tgt_label()}）"
        )

    def _update_table_headers(self) -> None:
        self.table.setHorizontalHeaderLabels(
            [f"源语（{self._src_label()}）", f"译文（{self._tgt_label()}）"]
        )

    def _refresh_hint(self) -> None:
        text = (
            f"编辑当前语言对「{self._src_label()} → {self._tgt_label()}」的术语；"
            "其它语言的译文保存在同一条目中，切换语言对即可查看。"
            "表格改字后点「保存」。"
            "可从 Google 表格 / Excel 复制后直接 Ctrl+V 粘贴（会自动去掉多余引号）。"
        )
        if self._src_code() in ("zh", "zt"):
            text += (
                "\n同一外语多种中文说法：源语可写 词A/词B（如 牧师/神父），"
                "译文中出现任一侧都会替换为对应外语。"
            )
        if self._tgt_code() in ("ru", "uk"):
            text += (
                "\n俄/乌语译文可填任意词形（不必原形）；保存时将自动识别各词格并规范为词典原形。"
                "\n同一中文多种外语译法：可写多行（同一中文重复多行，每行一种外语），"
                "或在译文格用 / 、; 或换行分隔；"
                "某译法下还有用词变体时用括号（如 священник (батько/батьки)）。"
                "翻译时在全部译法中随机取一种；译文中相关词会高亮，鼠标悬停可改选。"
            )
        if self._tgt_code() == "uk":
            try:
                import glossary_inflection as gi

                if not gi.uk_morph_analyzer_available():
                    text += (
                        "\n\n乌克兰语自动变格需安装 pymorphy2-dicts-uk。"
                        "在程序目录终端运行：\n"
                        f"{gi.uk_morph_install_command()}\n"
                        "安装后请重启程序。"
                    )
            except ImportError:
                pass
        self.hint.setText(text)

    def _on_lang_pair_changed(self) -> None:
        save_lang_pair_prefs(self._src_code(), self._tgt_code())
        self._update_window_title()
        self._update_table_headers()
        self._refresh_hint()
        self.reload_from_file()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def _build_bulk_entries(
        self, rows: list[tuple[str, str, str]], tgt_lang: str
    ) -> tuple[list[tuple[str, str, str]], list[int]]:
        entries: list[tuple[str, str, str]] = []
        bad: list[int] = []
        for line_number, (src_raw, tgt_raw, pos_raw) in enumerate(rows, start=1):
            src = sanitize_glossary_cell(src_raw)
            tgt = sanitize_glossary_cell(tgt_raw)
            if not src and not tgt:
                continue
            if not src or not tgt:
                bad.append(line_number)
                continue
            pos = (
                _normalize_pos(pos_raw)
                if pos_raw
                else infer_pos_for_target(tgt, tgt_lang)
            )
            entries.append((src, tgt, pos))
        return entries, bad

    def _on_bulk_add(self) -> None:
        tgt_lang = self._tgt_code()
        dlg = BulkAddDialog(
            self._src_label(),
            self._tgt_label(),
            show_pos=tgt_lang in ("ru", "uk"),
            parent=self,
        )
        if dlg.exec_() != QDialog.Accepted:
            return
        entries, bad_lines = self._build_bulk_entries(dlg.entries(), tgt_lang)
        if not entries:
            QMessageBox.warning(
                self,
                "批量添加",
                "没有有效行。请在表格中填写源语与译文（可从 Google 表格粘贴）。",
            )
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            gs = GlossaryStore().load()
            for src, tgt, pos in entries:
                gs.upsert_term(src, tgt_lang, tgt, pos=pos)
            gs.save()
        except OSError as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.reload_from_file()
        msg = f"已添加 {len(entries)} 条（{self._src_label()} → {self._tgt_label()}）。"
        if bad_lines:
            preview = ", ".join(str(i) for i in bad_lines[:12])
            if len(bad_lines) > 12:
                preview += " …"
            msg += f"\n格式不完整行号: {preview}"
        QMessageBox.information(self, "批量添加", msg)

    def _target_rows_for_entry(self, entry: Any, tgt_lang: str) -> list[str]:
        """将一条术语展开为表格行（多行外语 / 单元格内多义）。"""
        try:
            import glossary_alternatives as ga
        except ImportError:
            ga = None
        if not isinstance(entry, dict):
            text = tb.target_cell_text(entry, tgt_lang)
            return [text] if text else []
        val = entry.get(tgt_lang)
        if isinstance(val, list):
            rows: list[str] = []
            for item in val:
                show = tb.target_cell_text({tgt_lang: item}, tgt_lang)
                if show:
                    rows.append(show)
            return rows
        text = tb.target_cell_text(entry, tgt_lang)
        if not text:
            return []
        if ga is not None:
            opts = ga.list_all_options(text)
            if len(opts) > 1:
                return opts
        return [text]

    def reload_from_file(self) -> None:
        data = tb.load_glossary()
        tgt_lang = self._tgt_code()
        keys = [
            k
            for k in sorted(data.keys(), key=lambda s: (len(s), s), reverse=True)
            if isinstance(k, str) and k.strip()
        ]
        display_rows: list[tuple[str, str]] = []
        for src in keys:
            entry = data[src]
            for tgt_show in self._target_rows_for_entry(entry, tgt_lang):
                display_rows.append((src, tgt_show))
        n = len(display_rows) + 1
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(n)
            for row, (src, tgt_show) in enumerate(display_rows):
                self.table.setItem(row, 0, GlossaryPasteTableWidget._make_item(src))
                self.table.setItem(
                    row, 1, GlossaryPasteTableWidget._make_item(tgt_show)
                )
            last = n - 1
            self.table.setItem(last, 0, GlossaryPasteTableWidget._make_item(""))
            self.table.setItem(last, 1, GlossaryPasteTableWidget._make_item(""))
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.blockSignals(False)
        self.table._resize_rows_for_contents()

    def delete_selected_rows(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "删除", "请先选中要删除的行。")
            return
        tgt_lang = self._tgt_code()
        to_remove: list[tuple[str, str]] = []
        for r in rows:
            it0 = self.table.item(r, 0)
            it1 = self.table.item(r, 1)
            src = sanitize_glossary_cell(it0.text() if it0 else "")
            tgt = sanitize_glossary_cell(it1.text() if it1 else "")
            if src and tgt:
                to_remove.append((src, tgt))
        if not to_remove:
            for r in rows:
                self.table.removeRow(r)
            return
        confirm = QMessageBox.question(
            self,
            "删除选中",
            f"确定删除 {len(to_remove)} 条「{self._tgt_label()}」译文吗？\n"
            "（同中文多行时只删对应译法；其它语言保留。）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            gs = GlossaryStore().load()
            for src, tgt in to_remove:
                gs.remove_target_variant(src, tgt_lang, tgt)
            gs.save()
        except OSError as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self.reload_from_file()
        QMessageBox.information(self, "删除", f"已删除 {len(to_remove)} 条译文。")

    def clear_all_entries(self) -> None:
        """清空术语库文件中的全部条目（所有语言对）。"""
        data = tb.load_glossary()
        n_total = len(data)
        if n_total == 0:
            QMessageBox.information(self, "删除全部", "术语库已是空的。")
            return
        n_pair = sum(
            1
            for entry in data.values()
            if tb.target_cell_text(entry, self._tgt_code()).strip()
        )
        confirm = QMessageBox.question(
            self,
            "删除全部术语",
            f"确定删除全部 {n_total} 条术语吗？\n"
            f"（当前语言对「{self._src_label()} → {self._tgt_label()}」显示 {n_pair} 条。）\n\n"
            f"此操作不可撤销，将清空：\n{tb.glossary_path()}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            GlossaryStore().load().clear_all().save()
        except OSError as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        try:
            import glossary_manager as gm

            def _reindex_glossary() -> None:
                gm.preload_morph_analyzer()
                gm.build_ru_lemma_index({})

            threading.Thread(
                target=_reindex_glossary, name="glossary-reindex", daemon=True
            ).start()
        except Exception:
            pass
        self.reload_from_file()
        QMessageBox.information(
            self,
            "删除全部",
            f"已删除全部 {n_total} 条术语并已保存。",
        )

    def export_csv_file(self) -> None:
        src_code = self._src_code()
        tgt_code = self._tgt_code()
        default_name = f"glossary_{src_code}_{tgt_code}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 CSV",
            str(_root / default_name),
            "CSV (*.csv);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(
                    [
                        f"源语({self._src_label()})",
                        f"译文({self._tgt_label()})",
                        f"src_lang={src_code}",
                        f"tgt_lang={tgt_code}",
                    ]
                )
                for r in range(self.table.rowCount()):
                    it0 = self.table.item(r, 0)
                    it1 = self.table.item(r, 1)
                    src = sanitize_glossary_cell(it0.text() if it0 else "")
                    tgt = sanitize_glossary_cell(it1.text() if it1 else "")
                    if not src and not tgt:
                        continue
                    w.writerow([src, tgt])
        except OSError as e:
            QMessageBox.warning(self, "导出失败", str(e))
            return
        QMessageBox.information(self, "导出", f"已写入：\n{path}")

    def import_table_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"导入表格（第1列{self._src_label()}，第2列{self._tgt_label()}）",
            str(_root),
            "表格 (*.csv *.xlsx);;CSV (*.csv);;Excel (*.xlsx);;所有文件 (*.*)",
        )
        if not path:
            return
        p = Path(path)
        tgt_lang = self._tgt_code()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            gs = GlossaryStore().load()
            if p.suffix.lower() == ".xlsx":
                n = gs.import_xlsx(p, merge=True, target_lang=tgt_lang)
            else:
                n = gs.import_csv_pair(p, target_lang=tgt_lang, merge=True)
            gs.save()
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.reload_from_file()
        QMessageBox.information(
            self,
            "导入",
            f"已合并导入 {n} 行（→ {self._tgt_label()}）并保存。",
        )

    def save_to_file(self, *, show_message: bool = True) -> bool:
        old_all = tb.load_glossary()
        tgt_lang = self._tgt_code()
        new_data: dict = {k: v for k, v in old_all.items() if isinstance(k, str)}

        src_tgts: OrderedDict[str, list[str]] = OrderedDict()

        for r in range(self.table.rowCount()):
            it0 = self.table.item(r, 0)
            it1 = self.table.item(r, 1)
            src = sanitize_glossary_cell(it0.text() if it0 else "")
            tgt_raw = sanitize_glossary_cell(it1.text() if it1 else "")
            if not src:
                continue
            if not tgt_raw:
                gs_entry = old_all.get(src)
                if isinstance(gs_entry, dict) and tgt_lang in gs_entry:
                    merged = dict(gs_entry)
                    merged.pop(tgt_lang, None)
                    if merged:
                        new_data[src] = merged
                    else:
                        new_data.pop(src, None)
                continue
            if src not in src_tgts:
                src_tgts[src] = []
            parts = [
                sanitize_glossary_cell(p)
                for p in tgt_raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                if sanitize_glossary_cell(p)
            ]
            if not parts:
                continue
            src_tgts[src].extend(parts)

        multi_row = 0
        for src, tgts in src_tgts.items():
            tgt_vals = [tb.parse_target_cell(t, tgt_lang) for t in tgts if t.strip()]
            if not tgt_vals:
                continue
            old = old_all.get(src)
            if isinstance(old, dict):
                merged = {**old}
            elif isinstance(old, str) and tgt_lang == "ru":
                merged = {"ru": old}
            else:
                merged = {}
            if len(tgt_vals) == 1:
                merged[tgt_lang] = tgt_vals[0]
            else:
                merged[tgt_lang] = tgt_vals
                multi_row += 1
            if tgt_lang in ("ru", "uk"):
                merged["pos"] = infer_pos_for_target(tgts[0], tgt_lang)
            new_data[src] = merged

        try:
            tb.save_glossary(new_data)
        except OSError as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return False
        if tgt_lang == "ru":
            try:
                import glossary_manager as gm

                data_copy = dict(new_data)

                def _reindex_glossary() -> None:
                    gm.preload_morph_analyzer()
                    gm.build_ru_lemma_index(data_copy)

                threading.Thread(
                    target=_reindex_glossary, name="glossary-reindex", daemon=True
                ).start()
            except Exception:
                pass
        if show_message:
            n_pair = sum(
                len(self._target_rows_for_entry(e, tgt_lang))
                for e in new_data.values()
            )
            extra = ""
            if multi_row:
                extra = f"\n其中 {multi_row} 个中文有多行译法，已合并保存。"
            QMessageBox.information(
                self,
                "已保存",
                f"已写入：\n{tb.glossary_path()}\n\n"
                f"当前「{self._tgt_label()}」共 {n_pair} 条；文件总键数 {len(new_data)}。"
                f"{extra}",
            )
        self.reload_from_file()
        return True
