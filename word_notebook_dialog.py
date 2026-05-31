"""
生词本：按语系（俄语 / 乌克兰语）分栏查看，双击可在当前标签查词侧栏打开。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import word_lookup_store as wls

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_LANG_TABS: tuple[tuple[str, str], ...] = (
    ("ru", "俄语"),
    ("uk", "乌克兰语"),
)

_TABLE_HEADERS = ["最近查阅", "单词", "原形", "词义", "所在句（中文）"]


def _current_tab_page(host):
    tw = getattr(host, "_tab_widget", None)
    if tw is None:
        return None
    page = tw.currentWidget()
    if page is not None and hasattr(page, "_word_lookup_panel"):
        return page
    return None


class WordNotebookDialog(QDialog):
    def __init__(self, host, parent=None):
        super().__init__(parent or host)
        self._host = host
        self.setWindowTitle("生词本")
        self.resize(960, 520)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "查到词义的单词会按语系记入生词本（俄语 / 乌克兰语分开，同一单词各保留一条）。"
            "双击下表可在当前标签的查词侧栏打开已缓存释义。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._lang_tabs = QTabWidget()
        for _code, label in _LANG_TABS:
            self._lang_tabs.addTab(QWidget(), label)
        self._lang_tabs.currentChanged.connect(self._on_lang_tab_changed)
        layout.addWidget(self._lang_tabs)

        self.table = QTableWidget(0, len(_TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(_TABLE_HEADERS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self._open_in_panel)
        layout.addWidget(self.table)

        row = QHBoxLayout()
        row.addStretch()
        btn_open = QPushButton("在侧栏查看")
        btn_open.clicked.connect(self._open_in_panel)
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._delete_selected)
        btn_del_all = QPushButton("删除本栏全部")
        btn_del_all.clicked.connect(self._delete_all)
        btn_export = QPushButton("导出本栏…")
        btn_export.clicked.connect(self._export_entries)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.reload_table)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_open)
        row.addWidget(btn_del)
        row.addWidget(btn_del_all)
        row.addWidget(btn_export)
        row.addWidget(btn_refresh)
        row.addWidget(btn_close)
        layout.addLayout(row)

        self.reload_table()

    def _current_lang_code(self) -> str:
        i = self._lang_tabs.currentIndex()
        if 0 <= i < len(_LANG_TABS):
            return _LANG_TABS[i][0]
        return "ru"

    def _current_lang_label(self) -> str:
        i = self._lang_tabs.currentIndex()
        if 0 <= i < len(_LANG_TABS):
            return _LANG_TABS[i][1]
        return "俄语"

    def _on_lang_tab_changed(self, _index: int) -> None:
        self.reload_table()

    def reload_table(self) -> None:
        lang = self._current_lang_code()
        items = wls.load_entries_for_lang(lang)
        self.table.setRowCount(0)
        for it in items:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(it.get("looked_at", ""))))
            self.table.setItem(r, 1, QTableWidgetItem(str(it.get("word", ""))))
            self.table.setItem(r, 2, QTableWidgetItem(str(it.get("lemma", ""))))
            self.table.setItem(
                r, 3, QTableWidgetItem(str(it.get("meaning_preview", ""))),
            )
            sent = str(it.get("sentence_zh", ""))
            c = QTableWidgetItem(
                sent if len(sent) <= 120 else sent[:119] + "…"
            )
            c.setToolTip(sent)
            self.table.setItem(r, 4, c)
            self.table.item(r, 0).setData(Qt.UserRole, it)

        for i, (_code, base_label) in enumerate(_LANG_TABS):
            n = len(wls.load_entries_for_lang(_code))
            self._lang_tabs.setTabText(i, f"{base_label}（{n}）")

    def _selected_entry(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0:
            return None
        it = self.table.item(r, 0)
        if it is None:
            return None
        data = it.data(Qt.UserRole)
        return data if isinstance(data, dict) else None

    def _open_in_panel(self, *_) -> None:
        entry = self._selected_entry()
        if not entry:
            QMessageBox.information(self, "生词本", "请先选中一行。")
            return
        page = _current_tab_page(self._host)
        if page is None:
            QMessageBox.warning(self, "生词本", "当前没有可用的翻译标签页。")
            return
        panel = getattr(page, "_word_lookup_panel", None)
        if panel is None:
            QMessageBox.warning(self, "生词本", "查词侧栏未就绪，请稍后再试。")
            return
        if hasattr(panel, "show_from_notebook_entry"):
            panel.show_from_notebook_entry(entry)
            page.show_word_lookup_panel()
            self.accept()
        else:
            QMessageBox.warning(self, "生词本", "查词模块版本过旧，无法打开缓存。")

    def _delete_selected(self) -> None:
        entry = self._selected_entry()
        if not entry:
            QMessageBox.information(self, "生词本", "请先选中要删除的单词。")
            return
        wls.delete_entry(entry.get("lang", ""), entry.get("word", ""))
        self.reload_table()

    def _delete_all(self) -> None:
        lang = self._current_lang_code()
        label = self._current_lang_label()
        n = len(wls.load_entries_for_lang(lang))
        if n < 1:
            QMessageBox.information(
                self, "生词本", f"当前「{label}」栏没有可删除的词条。"
            )
            return
        reply = QMessageBox.question(
            self,
            "生词本",
            f"确定要删除「{label}」生词本中的全部 {n} 条词条吗？\n此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        wls.clear_entries_for_lang(lang)
        self.reload_table()
        QMessageBox.information(self, "生词本", f"已删除「{label}」的全部词条。")

    def _export_entries(self) -> None:
        lang = self._current_lang_code()
        label = self._current_lang_label()
        items = wls.load_entries_for_lang(lang)
        if not items:
            QMessageBox.information(
                self, "生词本", f"当前「{label}」栏没有可导出的词条。"
            )
            return
        default_name = (
            f"生词本_{label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        path, filt = QFileDialog.getSaveFileName(
            self,
            f"导出「{label}」生词本",
            default_name,
            "CSV 表格 (*.csv);;JSON (*.json);;文本 (*.txt);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            n = wls.export_entries(path, lang=lang)
            QMessageBox.information(
                self,
                "生词本",
                f"已导出「{label}」{n} 条到：\n{path}",
            )
        except OSError as e:
            QMessageBox.warning(self, "生词本", f"导出失败：{e}")


def open_word_notebook_dialog(host) -> None:
    dlg = WordNotebookDialog(host, host)
    dlg.setWindowFlags(dlg.windowFlags() | Qt.Window)
    dlg.show()
