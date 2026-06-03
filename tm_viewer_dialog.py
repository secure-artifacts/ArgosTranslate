"""本地 TM（翻译记忆库）查看对话框。"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QAbstractItemView,
)

from lang_pair_filter import LangPairFilterBar
from corpus_pipeline.lang_filter import row_matches_lang_filter

_VIEW_LIMIT = 3000


def _trunc(text: str, n: int = 100) -> str:
    one = (text or "").replace("\n", " ↵ ")
    return one if len(one) <= n else one[: n - 1] + "…"


class TMViewerDialog(QDialog):
    """浏览 corpus_tm.sqlite 中已入库句对。"""

    def __init__(
        self,
        parent=None,
        *,
        source_lang: str = "",
        target_lang: str = "",
    ) -> None:
        super().__init__(parent)
        self._src_lang_in = (source_lang or "").strip()
        self._tgt_lang_in = (target_lang or "").strip()
        self.setWindowTitle("翻译记忆库（TM）")
        self.resize(1000, 580)
        layout = QVBoxLayout(self)
        try:
            from corpus_pipeline.config import TM_DB

            db_path = str(TM_DB)
        except ImportError:
            db_path = "data/corpus/tm/corpus_tm.sqlite"
        self._hint = QLabel(
            f"本机 TM 数据库：{db_path}\n"
            "翻译时若命中 TM，将优先使用下列句对（不会上传网络）。\n"
            "可在本页导入、导出或粘贴句对；翻译区「采纳为 TM」也会写入此处。"
        )
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        tools_row = QHBoxLayout()
        help_btn = QPushButton("说明")
        help_btn.setToolTip("术语库与翻译记忆（TM）分别做什么")
        help_btn.clicked.connect(self._show_help)
        import_btn = QPushButton("导入 TM")
        import_btn.setToolTip("从 JSON / CSV 合并导入句对")
        import_btn.clicked.connect(self._import_tm_file)
        batch_btn = QPushButton("批量导入")
        batch_btn.setToolTip("一次导入多个文件或文件夹；相同原文只保留首次出现")
        batch_btn.clicked.connect(self._batch_import_tm_files)
        paste_btn = QPushButton("粘贴导入")
        paste_btn.setToolTip("从 Google 表格复制两列句对（Ctrl+C），粘贴导入")
        paste_btn.clicked.connect(self._paste_import_tm)
        export_btn = QPushButton("导出 TM")
        export_btn.setToolTip("导出到 JSON / CSV（本地文件，不上传）")
        export_btn.clicked.connect(self._export_tm_file)
        tools_row.addWidget(help_btn)
        tools_row.addWidget(import_btn)
        tools_row.addWidget(batch_btn)
        tools_row.addWidget(paste_btn)
        tools_row.addWidget(export_btn)
        tools_row.addStretch()
        layout.addLayout(tools_row)

        self._lang_filter = LangPairFilterBar(
            self,
            initial_source=self._src_lang_in or "zh",
            initial_target=self._tgt_lang_in or "ru",
            filter_enabled=bool(self._src_lang_in or self._tgt_lang_in),
            checkbox_text="按语言对筛选",
        )
        self._lang_filter.connect_changed(self._reload)
        layout.addWidget(self._lang_filter)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("搜索："))
        self._search = QLineEdit()
        self._search.setPlaceholderText("原文或译文关键词…")
        self._search.textChanged.connect(self._apply_search_filter)
        filter_row.addWidget(self._search, 1)
        layout.addLayout(filter_row)

        self._count_label = QLabel("")
        layout.addWidget(self._count_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["原文", "译文", "语言对", "领域", "纯度", "置信度"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._apply_to_pane)
        layout.addWidget(self.table)

        self._all_rows: list[dict] = []
        self._reload()

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._reload)
        btn_row.addWidget(refresh_btn)
        apply_btn = QPushButton("应用到翻译区")
        apply_btn.clicked.connect(self._apply_to_pane)
        btn_row.addWidget(apply_btn)
        copy_btn = QPushButton("复制句对")
        copy_btn.clicked.connect(self._copy_pair)
        btn_row.addWidget(copy_btn)
        self._delete_reverse = QCheckBox("同时删除反向句对")
        self._delete_reverse.setChecked(True)
        btn_row.addWidget(self._delete_reverse)
        delete_btn = QPushButton("删除选中")
        delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(delete_btn)
        delete_all_btn = QPushButton("全部删除")
        delete_all_btn.clicked.connect(self._delete_all)
        btn_row.addWidget(delete_all_btn)
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _active_filter(self) -> tuple[str | None, str | None]:
        return self._lang_filter.filter_codes()

    def _load_entries(self) -> tuple[list[dict], int, bool]:
        try:
            from corpus_pipeline.tm_store import count_entries, iter_entries
        except ImportError:
            return [], 0, False

        sl, tl = self._active_filter()
        total = count_entries(source_lang=sl, target_lang=tl)
        truncated = total > _VIEW_LIMIT
        entries = iter_entries(
            source_lang=sl,
            target_lang=tl,
            limit=_VIEW_LIMIT if truncated else None,
        )
        rows = [
            {
                "source_text": e.source_text,
                "target_text": e.target_text,
                "source_lang": e.source_lang,
                "target_lang": e.target_lang,
                "domain": e.domain or "",
                "tm_purity_score": e.tm_purity_score,
                "confidence_score": e.confidence_score,
            }
            for e in entries
        ]
        return rows, total, truncated

    def _reload(self) -> None:
        self._all_rows, total, truncated = self._load_entries()
        self._fill_table(self._all_rows)
        shown = len(self._all_rows)
        parts = [f"共 {total} 条"]
        if self._lang_filter.is_active():
            parts.insert(0, f"筛选 {self._lang_filter.filter_label()}")
        if shown != total:
            parts.append(f"显示 {shown} 条")
        if truncated:
            parts.append(f"（仅显示最近 {_VIEW_LIMIT} 条，请用筛选或导出查看全部）")
        if total == 0:
            parts.append("— 库为空时可点上方「导入 TM」或翻译区「采纳为 TM」")
        self._count_label.setText(" · ".join(parts))

    def _default_lang_codes(self) -> tuple[str, str]:
        sl, tl = self._lang_filter.current_codes()
        return sl or self._src_lang_in or "zh", tl or self._tgt_lang_in or "ru"

    def _show_help(self) -> None:
        try:
            from tm_glossary_help import show_tm_glossary_help
        except ImportError:
            QMessageBox.warning(self, "说明", "说明模块未就绪。")
            return
        show_tm_glossary_help(self)

    def _export_tm_file(self) -> None:
        sl, tl = self._default_lang_codes()
        try:
            from tm_manage_actions import export_tm
        except ImportError:
            QMessageBox.warning(self, "导出 TM", "TM 操作模块未就绪。")
            return
        export_tm(self, sl, tl)

    def _import_tm_file(self) -> None:
        sl, tl = self._default_lang_codes()
        try:
            from tm_manage_actions import import_tm_file
        except ImportError:
            QMessageBox.warning(self, "导入 TM", "TM 操作模块未就绪。")
            return
        import_tm_file(self, sl, tl, on_success=self._reload)

    def _batch_import_tm_files(self) -> None:
        sl, tl = self._default_lang_codes()
        try:
            from tm_manage_actions import batch_import_tm_files
        except ImportError:
            QMessageBox.warning(self, "批量导入 TM", "TM 操作模块未就绪。")
            return
        batch_import_tm_files(self, sl, tl, on_success=self._reload)

    def _paste_import_tm(self) -> None:
        sl, tl = self._default_lang_codes()
        try:
            from tm_manage_actions import paste_import_tm
        except ImportError:
            QMessageBox.warning(self, "粘贴导入 TM", "TM 操作模块未就绪。")
            return
        paste_import_tm(self, sl, tl, on_success=self._reload)

    def _fill_table(self, rows: list[dict]) -> None:
        self.table.setRowCount(0)
        for it in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            src = it.get("source_text") or ""
            tgt = it.get("target_text") or ""
            c0 = QTableWidgetItem(_trunc(src))
            c0.setToolTip(src[:8000])
            self.table.setItem(r, 0, c0)
            c1 = QTableWidgetItem(_trunc(tgt))
            c1.setToolTip(tgt[:8000])
            self.table.setItem(r, 1, c1)
            pair = f"{it.get('source_lang', '')} → {it.get('target_lang', '')}"
            self.table.setItem(r, 2, QTableWidgetItem(pair))
            self.table.setItem(r, 3, QTableWidgetItem(it.get("domain") or "—"))
            purity = it.get("tm_purity_score")
            conf = it.get("confidence_score")
            self.table.setItem(
                r,
                4,
                QTableWidgetItem(
                    f"{float(purity):.2f}" if purity is not None else "—"
                ),
            )
            self.table.setItem(
                r,
                5,
                QTableWidgetItem(
                    f"{float(conf):.2f}" if conf is not None else "—"
                ),
            )

    def _apply_search_filter(self) -> None:
        q = (self._search.text() or "").strip().lower()
        if not q:
            self._fill_table(self._all_rows)
            self._count_label.setText(
                self._count_label.text().split(" · 搜索")[0]
            )
            return
        filtered = self._visible_rows()
        self._fill_table(filtered)
        base = self._count_label.text().split(" · 搜索")[0]
        self._count_label.setText(
            f"{base} · 搜索匹配 {len(filtered)} 条"
        )

    def _visible_rows(self) -> list[dict]:
        q = (self._search.text() or "").strip().lower()
        if not q:
            return self._all_rows
        return [
            row
            for row in self._all_rows
            if q in (row.get("source_text") or "").lower()
            or q in (row.get("target_text") or "").lower()
        ]

    def _current_row(self) -> dict | None:
        r = self.table.currentRow()
        if r < 0:
            return None
        rows = self._visible_rows()
        if r >= len(rows):
            return None
        return rows[r]

    def _selected_rows(self) -> list[dict]:
        rows = self._visible_rows()
        selected: list[dict] = []
        for idx in self.table.selectionModel().selectedRows():
            r = idx.row()
            if 0 <= r < len(rows):
                selected.append(rows[r])
        return selected

    def _delete_selected(self) -> None:
        selected = self._selected_rows()
        if not selected:
            QMessageBox.information(self, "TM", "请先选中要删除的行。")
            return
        n = len(selected)
        rev = self._delete_reverse.isChecked()
        rev_hint = "（含反向句对）" if rev else ""
        preview = _trunc(selected[0].get("source_text") or "", 60)
        extra = f"\n…等共 {n} 条" if n > 1 else ""
        reply = QMessageBox.question(
            self,
            "删除 TM",
            f"确定从本机 TM 删除 {n} 条句对{rev_hint}？\n\n"
            f"「{preview}」{extra}\n\n"
            "此操作不可撤销（不影响待审核队列）。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            from corpus_pipeline.tm_io import delete_tm
        except ImportError:
            QMessageBox.warning(self, "TM", "无法加载 TM 删除模块。")
            return
        result = delete_tm(
            entries=selected,
            delete_reverse=rev,
        )
        if not result.get("ok"):
            QMessageBox.warning(
                self,
                "TM",
                result.get("error") or "删除失败",
            )
            return
        deleted = int(result.get("deleted") or 0)
        QMessageBox.information(
            self,
            "TM",
            f"已删除 {deleted} 条（请求 {n} 条）。",
        )
        self._reload()

    def _delete_scope(self) -> tuple[str, int, str | None, str | None]:
        """返回 (描述, 条目数, source_lang, target_lang)。"""
        try:
            from corpus_pipeline.tm_store import count_entries
        except ImportError:
            return "TM", 0, None, None

        sl, tl = self._active_filter()
        if sl or tl:
            total = count_entries(source_lang=sl, target_lang=tl)
            rev = self._delete_reverse.isChecked()
            scope = self._lang_filter.filter_label()
            if rev and sl and tl:
                scope += "（含反向句对）"
            return scope, total, sl, tl

        total = count_entries()
        return "整个 TM 数据库", total, None, None

    def _delete_all(self) -> None:
        scope, total, sl, tl = self._delete_scope()
        if total <= 0:
            QMessageBox.information(self, "TM", "当前范围内没有可删除的条目。")
            return
        reply = QMessageBox.warning(
            self,
            "全部删除 TM",
            f"确定删除 {scope} 中的全部 {total} 条句对？\n\n"
            "此操作不可撤销（不影响待审核队列）。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        confirm = QMessageBox.question(
            self,
            "再次确认",
            f"最后确认：将永久删除 {total} 条 TM 句对。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            from corpus_pipeline.tm_io import delete_tm
        except ImportError:
            QMessageBox.warning(self, "TM", "无法加载 TM 删除模块。")
            return
        rev = self._delete_reverse.isChecked()
        result = delete_tm(
            source_lang=sl or "",
            target_lang=tl or "",
            delete_all=True,
            delete_reverse=rev,
        )
        if not result.get("ok"):
            QMessageBox.warning(
                self,
                "TM",
                result.get("error") or "删除失败",
            )
            return
        deleted = int(result.get("deleted") or 0)
        remaining = int(result.get("total_in_db") or 0)
        QMessageBox.information(
            self,
            "TM",
            f"已删除 {deleted} 条，库内剩余 {remaining} 条。",
        )
        self._reload()

    def _copy_pair(self) -> None:
        row = self._current_row()
        if not row:
            QMessageBox.information(self, "TM", "请先选中一行。")
            return
        src = row.get("source_text") or ""
        tgt = row.get("target_text") or ""
        QApplication.clipboard().setText(f"{src}\n---\n{tgt}")

    def _apply_to_pane(self) -> None:
        row = self._current_row()
        if not row:
            QMessageBox.information(self, "TM", "请先选中一行。")
            return
        parent = self.parent()
        if parent is None:
            self._copy_pair()
            return
        src = row.get("source_text") or ""
        tgt = row.get("target_text") or ""
        if hasattr(parent, "left_textEdit") and hasattr(parent, "right_textEdit"):
            parent.left_textEdit.setPlainText(src)
            parent.right_textEdit.setPlainText(tgt)
            if hasattr(parent, "_update_char_counts"):
                parent._update_char_counts()
            self.accept()
        else:
            self._copy_pair()


def open_tm_viewer_dialog(
    parent=None,
    *,
    source_lang: str = "",
    target_lang: str = "",
) -> None:
    dlg = TMViewerDialog(
        parent,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    dlg.exec_()
