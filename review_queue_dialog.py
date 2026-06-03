"""用户 TM 审核队列对话框。"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QAbstractItemView,
)

from lang_pair_filter import LangPairFilterBar
from corpus_pipeline.lang_filter import row_matches_lang_filter


def _trunc(text: str, n: int = 120) -> str:
    one = (text or "").replace("\n", " ↵ ")
    return one if len(one) <= n else one[: n - 1] + "…"


def _kind_label(kind: str) -> str:
    k = (kind or "").strip()
    if k == "user_adopt":
        return "用户采纳"
    if k == "auto_low_quality":
        return "低分自动"
    return k or "—"


class ReviewQueueDialog(QDialog):
    """查看 / 批准 / 拒绝 user 审核队列（pending TM）。"""

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
        self.setWindowTitle("TM 审核队列")
        self.resize(980, 560)
        layout = QVBoxLayout(self)
        self._hint = QLabel(
            "待审核句对保存在本机 data/corpus/manual_review_queue/user/。"
            "批准后写入 gold 语料与高纯度 TM；拒绝仅标记不入库；"
            "删除则从队列中永久移除（不影响已入库 TM）。"
        )
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)
        self._lang_filter = LangPairFilterBar(
            self,
            initial_source=self._src_lang_in or "zh",
            initial_target=self._tgt_lang_in or "ru",
            filter_enabled=bool(self._src_lang_in or self._tgt_lang_in),
            checkbox_text="按语言对筛选",
        )
        self._lang_filter.connect_changed(self._reload)
        layout.addWidget(self._lang_filter)
        self._count_label = QLabel("")
        layout.addWidget(self._count_label)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["类型", "语言对", "原文", "译文", "纯度/分数", "ID"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)
        self._items: list[dict] = []
        self._all_items: list[dict] = []
        self._reload()

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._reload)
        btn_row.addWidget(refresh_btn)
        approve_btn = QPushButton("批准所选")
        approve_btn.setObjectName("PrimaryButton")
        approve_btn.clicked.connect(self._approve_selected)
        btn_row.addWidget(approve_btn)
        reject_btn = QPushButton("拒绝所选")
        reject_btn.clicked.connect(self._reject_selected)
        btn_row.addWidget(reject_btn)
        delete_btn = QPushButton("删除所选")
        delete_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(delete_btn)
        delete_all_btn = QPushButton("全部删除")
        delete_all_btn.clicked.connect(self._delete_all)
        btn_row.addWidget(delete_all_btn)
        copy_btn = QPushButton("复制 ID")
        copy_btn.clicked.connect(self._copy_id)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _reload(self) -> None:
        try:
            from corpus_pipeline.user_feedback import list_user_pending

            self._all_items = list_user_pending()
        except ImportError:
            self._all_items = []
        sl, tl = self._lang_filter.filter_codes()
        if self._lang_filter.is_active():
            self._items = [
                it
                for it in self._all_items
                if row_matches_lang_filter(it, source_lang=sl, target_lang=tl)
            ]
        else:
            self._items = list(self._all_items)
        self.table.setRowCount(0)
        for it in self._items:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(_kind_label(it.get("kind"))))
            pair = f"{it.get('source_lang', '')} → {it.get('target_lang', '')}"
            self.table.setItem(r, 1, QTableWidgetItem(pair))
            src = it.get("source_text") or ""
            tgt = it.get("target_text") or ""
            c2 = QTableWidgetItem(_trunc(src))
            c2.setToolTip(src[:8000])
            self.table.setItem(r, 2, c2)
            c3 = QTableWidgetItem(_trunc(tgt))
            c3.setToolTip(tgt[:8000])
            self.table.setItem(r, 3, c3)
            q = it.get("quality") if isinstance(it.get("quality"), dict) else {}
            purity = it.get("tm_purity_score")
            if purity is None and q:
                purity = q.get("tm_purity_score")
            qscore = q.get("quality_score") if q else None
            score_parts = []
            if purity is not None:
                score_parts.append(f"纯度 {float(purity):.2f}")
            if qscore is not None:
                score_parts.append(f"分 {float(qscore):.2f}")
            if it.get("auto_reason"):
                score_parts.append(str(it.get("auto_reason")))
            self.table.setItem(r, 4, QTableWidgetItem(" · ".join(score_parts) or "—"))
            rid = str(it.get("id") or "")
            c5 = QTableWidgetItem(rid[:16] + ("…" if len(rid) > 16 else ""))
            c5.setToolTip(rid)
            c5.setData(Qt.UserRole, rid)
            self.table.setItem(r, 5, c5)
        n = len(self._items)
        total = len(self._all_items)
        parts = [f"待审核：{n} 条"]
        if self._lang_filter.is_active() and n != total:
            parts.append(f"（全部 {total} 条 · 筛选 {self._lang_filter.filter_label()}）")
        elif self._lang_filter.is_active():
            parts.insert(0, f"筛选 {self._lang_filter.filter_label()}")
        self._count_label.setText(
            " · ".join(parts)
            + (
                "（空队列时可先「采纳为 TM」或等待低分句自动入队）"
                if n == 0
                else ""
            )
        )

    def _selected_indices(self) -> list[int]:
        rows = {idx.row() for idx in self.table.selectionModel().selectedRows()}
        return sorted(r for r in rows if 0 <= r < len(self._items))

    def _copy_id(self) -> None:
        rows = self._selected_indices()
        if len(rows) != 1:
            QMessageBox.information(self, "审核队列", "请选择一行以复制 ID。")
            return
        rid = str(self._items[rows[0]].get("id") or "")
        if rid:
            QApplication.clipboard().setText(rid)

    def _approve_selected(self) -> None:
        rows = self._selected_indices()
        if not rows:
            QMessageBox.information(self, "审核队列", "请先选择要批准的条目。")
            return
        ok = QMessageBox.question(
            self,
            "批准入 TM",
            f"确认批准 {len(rows)} 条？\n将写入 gold 语料与高纯度 TM。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ok != QMessageBox.Yes:
            return
        try:
            from corpus_pipeline.user_feedback import approve_user_item
        except ImportError:
            QMessageBox.warning(self, "审核队列", "语料模块未就绪。")
            return
        ok_n, fail = 0, 0
        msgs: list[str] = []
        for r in rows:
            item = self._items[r]
            rid = str(item.get("id") or "")
            if not rid:
                fail += 1
                continue
            try:
                res = approve_user_item(rid, reviewer="gui")
                if res.get("ok"):
                    ok_n += 1
                    msgs.append(
                        f"{rid[:12]}… TM+{res.get('tm_added', 0)}"
                    )
                else:
                    fail += 1
            except Exception as e:
                fail += 1
                msgs.append(f"{rid[:12]}… 失败: {e}")
        self._reload()
        QMessageBox.information(
            self,
            "审核队列",
            f"完成：批准 {ok_n} 条，失败 {fail} 条。"
            + ("\n" + "\n".join(msgs[:8]) if msgs else ""),
        )

    def _reject_selected(self) -> None:
        rows = self._selected_indices()
        if not rows:
            QMessageBox.information(self, "审核队列", "请先选择要拒绝的条目。")
            return
        ok = QMessageBox.question(
            self,
            "拒绝",
            f"确认拒绝 {len(rows)} 条？（不会写入 TM）",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ok != QMessageBox.Yes:
            return
        try:
            from corpus_pipeline.user_feedback import reject_user_item
        except ImportError:
            QMessageBox.warning(self, "审核队列", "语料模块未就绪。")
            return
        n = 0
        for r in rows:
            rid = str(self._items[r].get("id") or "")
            if rid and reject_user_item(rid, note="gui_reject"):
                n += 1
        self._reload()
        QMessageBox.information(self, "审核队列", f"已拒绝 {n} 条。")

    def _delete_selected(self) -> None:
        rows = self._selected_indices()
        if not rows:
            QMessageBox.information(self, "审核队列", "请先选择要删除的条目。")
            return
        n = len(rows)
        preview = _trunc(self._items[rows[0]].get("source_text") or "", 60)
        extra = f"\n…等共 {n} 条" if n > 1 else ""
        ok = QMessageBox.question(
            self,
            "删除",
            f"确定永久删除 {n} 条待审核句对？\n\n"
            f"「{preview}」{extra}\n\n"
            "此操作不可撤销，且不会写入 TM。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ok != QMessageBox.Yes:
            return
        try:
            from corpus_pipeline.user_feedback import delete_user_items
        except ImportError:
            QMessageBox.warning(self, "审核队列", "语料模块未就绪。")
            return
        ids = [str(self._items[r].get("id") or "") for r in rows]
        ids = [i for i in ids if i]
        result = delete_user_items(ids, note="gui_delete")
        self._reload()
        if not result.get("ok"):
            QMessageBox.warning(
                self,
                "审核队列",
                f"删除失败或未找到条目（请求 {result.get('requested', n)} 条）。",
            )
            return
        QMessageBox.information(
            self,
            "审核队列",
            f"已删除 {result.get('deleted', 0)} 条"
            + (
                f"（pending_tm 清理 {result.get('pending_tm_removed', 0)} 条）。"
                if result.get("pending_tm_removed")
                else "。"
            ),
        )

    def _delete_all(self) -> None:
        n = len(self._items)
        if n <= 0:
            QMessageBox.information(self, "审核队列", "当前没有待审核条目。")
            return
        reply = QMessageBox.warning(
            self,
            "全部删除",
            f"确定永久删除全部 {n} 条待审核句对？\n\n"
            "此操作不可撤销，且不会写入 TM。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        confirm = QMessageBox.question(
            self,
            "再次确认",
            f"最后确认：将永久删除 {n} 条待审核句对。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            from corpus_pipeline.user_feedback import delete_all_user_pending, delete_user_items
        except ImportError:
            QMessageBox.warning(self, "审核队列", "语料模块未就绪。")
            return
        if self._lang_filter.is_active():
            ids = [str(i.get("id") or "") for i in self._items if i.get("id")]
            result = delete_user_items(ids, note="gui_delete_all")
        else:
            result = delete_all_user_pending(note="gui_delete_all")
        self._reload()
        if not result.get("ok"):
            QMessageBox.warning(
                self,
                "审核队列",
                "删除失败或队列为空。",
            )
            return
        QMessageBox.information(
            self,
            "审核队列",
            f"已删除 {result.get('deleted', 0)} 条"
            + (
                f"（pending_tm 清理 {result.get('pending_tm_removed', 0)} 条）。"
                if result.get("pending_tm_removed")
                else "。"
            ),
        )


def open_review_queue_dialog(
    parent=None,
    *,
    source_lang: str = "",
    target_lang: str = "",
) -> None:
    dlg = ReviewQueueDialog(
        parent,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    dlg.exec_()
