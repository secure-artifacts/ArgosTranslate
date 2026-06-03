"""从 Google 表格 / Excel 复制粘贴导入 TM。"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class TMPasteImportDialog(QDialog):
    """粘贴表格文本（TSV）批量导入 TM。"""

    def __init__(
        self,
        parent=None,
        *,
        source_lang: str = "",
        target_lang: str = "",
        initial_text: str = "",
    ) -> None:
        super().__init__(parent)
        self._sl = (source_lang or "").strip()
        self._tl = (target_lang or "").strip()
        self._result: dict | None = None
        self.setWindowTitle("粘贴导入 TM")
        self.resize(720, 480)
        layout = QVBoxLayout(self)
        pair = f"{self._sl} → {self._tl}" if self._sl and self._tl else "当前语言对"
        hint = QLabel(
            "从 Google 表格选中句对区域并复制（Ctrl+C），在此粘贴。\n"
            "支持两列「原文\\t译文」，或带表头（source_text / target_text / 原文 / 译文）。\n"
            f"缺省语言对：{pair}（可在表格中另加语言列覆盖）"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._edit = QPlainTextEdit()
        self._edit.setPlaceholderText(
            "示例：\n原文\t译文\n你好\tПривет\n谢谢\tСпасибо"
        )
        if initial_text:
            self._edit.setPlainText(initial_text)
        layout.addWidget(self._edit, 1)
        btn_row = QHBoxLayout()
        paste_btn = QPushButton("从剪贴板粘贴")
        paste_btn.clicked.connect(self._paste_clipboard)
        btn_row.addWidget(paste_btn)
        btn_row.addStretch()
        import_btn = QPushButton("导入")
        import_btn.setObjectName("PrimaryButton")
        import_btn.clicked.connect(self._do_import)
        btn_row.addWidget(import_btn)
        close_btn = QPushButton("取消")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _paste_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if text:
            self._edit.setPlainText(text)

    def _do_import(self) -> None:
        text = self._edit.toPlainText()
        if not (text or "").strip():
            QMessageBox.information(self, "粘贴导入 TM", "请先粘贴表格内容。")
            return
        try:
            from corpus_pipeline.tm_io import import_tm_from_table_text
        except ImportError:
            QMessageBox.warning(self, "粘贴导入 TM", "TM 模块未就绪。")
            return
        preview_rows = text.strip().splitlines()
        n_lines = len([ln for ln in preview_rows if ln.strip()])
        reply = QMessageBox.question(
            self,
            "粘贴导入 TM",
            f"将导入约 {n_lines} 行表格数据到本机 TM。\n"
            "相同原文会跳过重复。\n\n是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        result = import_tm_from_table_text(
            text,
            default_source_lang=self._sl,
            default_target_lang=self._tl,
            quality_gate=False,
            bidirectional=True,
        )
        if not result.get("ok"):
            QMessageBox.warning(
                self,
                "粘贴导入 TM",
                result.get("reason") or "未能解析有效句对（需至少两列：原文、译文）",
            )
            return
        self._result = result
        self.accept()

    def result_data(self) -> dict | None:
        return self._result


def open_tm_paste_import_dialog(
    parent=None,
    *,
    source_lang: str = "",
    target_lang: str = "",
    initial_text: str = "",
) -> dict | None:
    dlg = TMPasteImportDialog(
        parent,
        source_lang=source_lang,
        target_lang=target_lang,
        initial_text=initial_text,
    )
    if dlg.exec_() != QDialog.Accepted:
        return None
    return dlg.result_data()
