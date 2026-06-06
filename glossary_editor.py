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
from PyQt5.QtGui import QKeySequence, QShowEvent
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
    QStyledItemDelegate,
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


ROLE_WORD_META = Qt.UserRole + 42
ROLE_ENTRY_POS_OVERRIDE = Qt.UserRole + 43

_POS_OC_ZH: dict[str, str] = {
    "NOUN": "名词",
    "VERB": "动词",
    "INFN": "动词",
    "GRND": "动词",
    "PRTF": "分词",
    "PRTS": "分词",
    "ADJF": "形容词",
    "ADJS": "形容词",
    "ADVB": "副词",
    "NPRO": "代词",
    "NUMR": "数词",
    "PREP": "介词",
    "CONJ": "连词",
    "PRCL": "语气词",
    "INTJ": "感叹词",
}

_POS_EDIT_CHOICES = [
    "名词",
    "动词",
    "形容词",
    "副词",
    "代词",
    "数词",
    "介词",
    "连词",
    "分词",
    "语气词",
    "其它",
]

_POS_LABEL_TO_OC: dict[str, str] = {
    "名词": "NOUN",
    "动词": "VERB",
    "形容词": "ADJF",
    "副词": "ADVB",
    "代词": "NPRO",
    "数词": "NUMR",
    "介词": "PREP",
    "连词": "CONJ",
    "分词": "PRTF",
    "语气词": "PRCL",
    "其它": "OTHER",
    "其他": "OTHER",
}

_CASE_EDIT_CHOICES = [
    "—",
    "主格",
    "属格",
    "与格",
    "宾格",
    "工具格",
    "前置格",
    "呼格",
]

_NUMBER_EDIT_CHOICES = ["—", "单数", "复数"]

_CASE_ZH_TO_OC: dict[str, str] = {
    "主格": "nomn",
    "属格": "gent",
    "与格": "datv",
    "宾格": "accs",
    "工具格": "ablt",
    "前置格": "loct",
    "呼格": "voct",
}

_NUMBER_ZH_TO_OC: dict[str, str] = {
    "单数": "sing",
    "复数": "plur",
}

_OC_CASES = frozenset(_CASE_ZH_TO_OC.values())
_OC_NUMBER = frozenset(_NUMBER_ZH_TO_OC.values())
_OC_TO_CASE_ZH = {v: k for k, v in _CASE_ZH_TO_OC.items()}
_OC_TO_NUMBER_ZH = {v: k for k, v in _NUMBER_ZH_TO_OC.items()}

_ENTRY_POS_CHOICES = ("名词", "动词", "形容词", "其他")


def _pos_supports_word_columns(tgt_lang: str) -> bool:
    return (tgt_lang or "").strip().lower() in ("ru", "uk")


def _pos_oc_to_zh(pos_oc: str) -> str:
    p = (pos_oc or "").strip().upper()
    return _POS_OC_ZH.get(p, p or "—")


def _pos_zh_to_oc(label: str) -> str:
    t = (label or "").strip()
    if t in _POS_LABEL_TO_OC:
        return _POS_LABEL_TO_OC[t]
    upper = t.upper()
    if upper in _POS_OC_ZH:
        return upper
    return ""


def _bucket_to_zh(bucket: str) -> str:
    return {
        "noun": "名词",
        "verb": "动词",
        "adj": "形容词",
        "other": "其他",
    }.get((bucket or "").strip().lower(), "名词")


def _analyze_row_words(text: str, lang: str) -> list[dict[str, Any]]:
    try:
        import glossary_inflection as gi

        return list(gi.analyze_slavic_phrase(text, lang).get("words") or [])
    except Exception:
        return []


def _target_alternative_options(text: str) -> list[str]:
    try:
        import glossary_alternatives as ga

        return ga.list_all_options(text)
    except ImportError:
        t = (text or "").strip()
        return [t] if t else []


def _auto_entry_pos_zh(tgt: str, lang: str, current: str = "") -> str:
    """推断整体词性；若当前仅为默认「名词」占位则覆盖为推断结果。"""
    inferred = _bucket_to_zh(infer_pos_for_target(tgt, lang))
    cur = (current or "").strip()
    if not cur:
        return inferred
    cur_bucket = _normalize_pos(cur)
    inf_bucket = _normalize_pos(inferred)
    if cur_bucket == "noun" and inf_bucket != "noun":
        return inferred
    return _bucket_to_zh(cur_bucket)


def _words_pos_summary_or_infer(
    tgt: str, lang: str, words: list[dict[str, Any]]
) -> str:
    if words:
        summary = _words_pos_summary(words)
        if summary and summary != "—":
            return summary
    t = (tgt or "").strip()
    if not t:
        return "—"
    opts = _target_alternative_options(t)
    if len(opts) > 1:
        return _words_pos_summary_for_alternatives(opts, lang)
    pos_zh = _auto_entry_pos_zh(t, lang)
    return f"{t}({pos_zh})"


def _words_pos_summary_for_alternatives(opts: list[str], lang: str) -> str:
    if not opts:
        return "—"
    parts: list[str] = []
    for opt in opts:
        words = _analyze_row_words(opt, lang)
        if words:
            chunk = _words_pos_summary(words)
            parts.append(chunk if chunk != "—" else opt)
        else:
            pos_zh = _auto_entry_pos_zh(opt, lang)
            parts.append(f"{opt}({pos_zh})")
    return " / ".join(parts)


def _merge_words_with_overrides(
    auto_words: list[dict[str, Any]],
    overrides: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not overrides:
        return [dict(w) for w in auto_words]
    if len(overrides) != len(auto_words):
        return [dict(w) for w in auto_words]
    out: list[dict[str, Any]] = []
    for i, aw in enumerate(auto_words):
        w = dict(aw)
        ov = overrides[i]
        if not isinstance(ov, dict):
            out.append(w)
            continue
        ov_surf = (ov.get("surface") or ov.get("lemma") or "").strip().casefold()
        aw_surf = (aw.get("surface") or aw.get("lemma") or "").strip().casefold()
        if ov_surf and aw_surf and ov_surf != aw_surf:
            out.append(w)
            continue
        ov_pos = (ov.get("pos") or "").strip()
        if ov_pos:
            w["pos"] = ov_pos
        for key in ("case", "case_zh", "number", "number_zh", "grammemes"):
            if key in ov:
                w[key] = ov[key]
        out.append(w)
    return out


def _word_pos_summary_chunk(w: dict[str, Any]) -> str:
    try:
        import glossary_inflection as gi

        w = gi._enrich_word_analysis(dict(w))
    except Exception:
        w = dict(w)
    surf = (w.get("surface") or w.get("lemma") or "?").strip()
    tags: list[str] = []
    pos_label = _pos_oc_to_zh(str(w.get("pos") or ""))
    if pos_label and pos_label != "—":
        tags.append(pos_label)
    case_zh = (w.get("case_zh") or "").strip()
    if case_zh and case_zh not in ("—", "-"):
        tags.append(case_zh)
    num_zh = (w.get("number_zh") or w.get("number") or "").strip()
    if num_zh in ("sing", "plur"):
        num_zh = {"sing": "单数", "plur": "复数"}.get(num_zh, num_zh)
    if num_zh and num_zh not in ("—", "-"):
        tags.append(num_zh)
    if tags:
        return f"{surf}({'·'.join(tags)})"
    return surf


def _words_pos_summary(words: list[dict[str, Any]]) -> str:
    if not words:
        return "—"
    return "; ".join(_word_pos_summary_chunk(w) for w in words)


def _words_pos_export_detail(words: list[dict[str, Any]]) -> str:
    if not words:
        return ""
    parts: list[str] = []
    for w in words:
        surf = (w.get("surface") or w.get("lemma") or "").strip()
        lemma = (w.get("lemma") or surf).strip()
        pos_label = _pos_oc_to_zh(str(w.get("pos") or ""))
        case_zh = (w.get("case_zh") or w.get("case") or "").strip()
        num_zh = (w.get("number_zh") or w.get("number") or "").strip()
        chunk = f"{surf}|{lemma}|{pos_label}"
        if case_zh:
            chunk += f"|{case_zh}"
        if num_zh:
            chunk += f"|{num_zh}"
        parts.append(chunk)
    return " ; ".join(parts)


def _apply_words_to_target_val(
    val: Any,
    words: list[dict[str, Any]] | None,
    *,
    surface: str = "",
    lang: str = "",
) -> Any:
    if not words or not isinstance(val, dict):
        return val
    out = dict(val)
    stored_words: list[dict[str, Any]] = []
    for w in words:
        if not isinstance(w, dict):
            continue
        stored_words.append(
            {
                "surface": w.get("surface", ""),
                "lemma": w.get("lemma", ""),
                "grammemes": w.get("grammemes") or [],
                "case": w.get("case", ""),
                "case_zh": w.get("case_zh", ""),
                "number": w.get("number", ""),
                "number_zh": w.get("number_zh", ""),
                "pos": w.get("pos", ""),
                "pred_lemma": w.get("pred_lemma", "") or w.get("derive_lemma", ""),
            }
        )
    out["words"] = stored_words
    surf = (surface or "").strip()
    if not surf and stored_words and lang in ("ru", "uk"):
        try:
            import glossary_inflection as gi

            template = str(out.get("lemma") or surface or "").strip()
            if template:
                surf = gi.rebuild_phrase_surface(template, stored_words, lang).strip()
        except Exception:
            surf = ""
    if surf:
        out["surface"] = surf
    return out


class _ComboColumnDelegate(QStyledItemDelegate):
    """表格列：单击弹出下拉框编辑。"""

    def __init__(self, parent, choices: list[str]) -> None:
        super().__init__(parent)
        self._choices = list(choices)

    def createEditor(self, parent, option, index):  # noqa: ARG002
        editor = QComboBox(parent)
        editor.addItems(self._choices)
        editor.setEditable(False)
        editor.setMinimumHeight(32)
        editor.setStyleSheet(
            "QComboBox { padding: 4px 28px 4px 10px; min-height: 24px; font-size: 13px; }"
            "QComboBox::drop-down { width: 22px; }"
        )
        QTimer.singleShot(0, editor.showPopup)
        return editor

    def setEditorData(self, editor, index) -> None:
        if not isinstance(editor, QComboBox):
            return
        text = str(index.model().data(index, Qt.DisplayRole) or "").strip()
        pos = editor.findText(text)
        if pos >= 0:
            editor.setCurrentIndex(pos)
        elif text:
            editor.addItem(text)
            editor.setCurrentText(text)

    def setModelData(self, editor, model, index) -> None:
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.EditRole)


def _editable_pos_table_item(text: str, *, tooltip: str = "") -> QTableWidgetItem:
    it = _pos_table_item(text)
    it.setFlags(it.flags() | Qt.ItemIsEditable)
    if tooltip:
        it.setToolTip(tooltip)
    return it


def _make_entry_pos_item(text: str) -> QTableWidgetItem:
    return _editable_pos_table_item(
        text or "",
        tooltip="单击可修改整体词性（名词 / 动词 / 形容词 / 其他）",
    )


def _display_case_zh(w: dict[str, Any]) -> str:
    try:
        import glossary_inflection as gi

        w = gi._enrich_word_analysis(dict(w))
    except Exception:
        w = dict(w)
    case_zh = (w.get("case_zh") or "").strip()
    if case_zh:
        return case_zh
    case = (w.get("case") or "").strip()
    if case in _OC_CASES:
        return _OC_TO_CASE_ZH.get(case, case)
    return "—"


def _display_number_zh(w: dict[str, Any]) -> str:
    try:
        import glossary_inflection as gi

        w = gi._enrich_word_analysis(dict(w))
    except Exception:
        w = dict(w)
    num_zh = (w.get("number_zh") or "").strip()
    if num_zh in ("sing", "plur"):
        return {"sing": "单数", "plur": "复数"}.get(num_zh, num_zh)
    if num_zh:
        return num_zh
    number = (w.get("number") or "").strip()
    if number in _OC_NUMBER:
        return _OC_TO_NUMBER_ZH.get(number, number)
    return "—"


def _apply_case_number_to_word(
    merged: dict[str, Any],
    case_label: str,
    number_label: str,
) -> None:
    grams = [g for g in merged.get("grammemes") or [] if g not in _OC_CASES and g not in _OC_NUMBER]
    case_label = (case_label or "").strip()
    if case_label and case_label != "—":
        case_oc = _CASE_ZH_TO_OC.get(case_label, "")
        if case_oc:
            merged["case"] = case_oc
            merged["case_zh"] = case_label
            grams.append(case_oc)
        else:
            merged["case"] = case_label
            merged["case_zh"] = case_label
    else:
        merged["case"] = ""
        merged["case_zh"] = ""
    number_label = (number_label or "").strip()
    if number_label and number_label != "—":
        number_oc = _NUMBER_ZH_TO_OC.get(number_label, "")
        if number_oc:
            merged["number"] = number_oc
            merged["number_zh"] = number_label
            grams.append(number_oc)
        else:
            merged["number"] = number_label
            merged["number_zh"] = number_label
    else:
        merged["number"] = ""
        merged["number_zh"] = ""
    merged["grammemes"] = sorted(set(grams))


def _pos_table_item(text: str) -> QTableWidgetItem:
    it = QTableWidgetItem(text or "")
    it.setToolTip(text or "")
    it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    return it


class GlossaryWordPosDialog(QDialog):
    """编辑一条译文内各单词的词性。"""

    _POS_COL_WIDTH = 96
    _CASE_COL_WIDTH = 80
    _NUMBER_COL_WIDTH = 64
    _ROW_HEIGHT = 40

    def __init__(
        self,
        target_text: str,
        lang: str,
        words: list[dict[str, Any]],
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("逐词词性校对")
        self.setMinimumSize(600, 320)
        self.resize(700, 400)
        self._lang = (lang or "").strip().lower()
        self._words: list[dict[str, Any]] = [dict(w) for w in words if isinstance(w, dict)]

        hint = QLabel(
            f"译文：{target_text}\n"
            "程序已自动识别各词词性、格与单复数；如有误请单击「词性」「格」「数」列，"
            "在下拉框中选择正确项，确定后写回表格。"
        )
        hint.setWordWrap(True)

        self.table = QTableWidget(len(self._words), 5, self)
        self.table.setHorizontalHeaderLabels(["单词", "原形", "词性", "格", "数"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setEditTriggers(QAbstractItemView.CurrentChanged)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.setItemDelegateForColumn(2, _ComboColumnDelegate(self.table, _POS_EDIT_CHOICES))
        self.table.setItemDelegateForColumn(3, _ComboColumnDelegate(self.table, _CASE_EDIT_CHOICES))
        self.table.setItemDelegateForColumn(4, _ComboColumnDelegate(self.table, _NUMBER_EDIT_CHOICES))
        self.table.cellClicked.connect(self._on_edit_cell_clicked)
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        hdr.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(2, self._POS_COL_WIDTH)
        self.table.setColumnWidth(3, self._CASE_COL_WIDTH)
        self.table.setColumnWidth(4, self._NUMBER_COL_WIDTH)
        vhdr = self.table.verticalHeader()
        vhdr.setVisible(False)
        vhdr.setSectionResizeMode(QHeaderView.Fixed)
        vhdr.setDefaultSectionSize(self._ROW_HEIGHT)

        for row, w in enumerate(self._words):
            surf = (w.get("surface") or "").strip()
            lemma = (w.get("lemma") or surf).strip()
            case_zh = _display_case_zh(w)
            num_zh = _display_number_zh(w)
            pos_label = _pos_oc_to_zh(str(w.get("pos") or ""))
            if not pos_label or pos_label == "—":
                pos_label = "名词"
            self.table.setItem(row, 0, _pos_table_item(surf))
            self.table.setItem(row, 1, _pos_table_item(lemma))
            self.table.setItem(
                row,
                2,
                _editable_pos_table_item(pos_label, tooltip="单击可修改词性"),
            )
            self.table.setItem(
                row,
                3,
                _editable_pos_table_item(case_zh, tooltip="单击可修改格"),
            )
            self.table.setItem(
                row,
                4,
                _editable_pos_table_item(num_zh, tooltip="单击可修改单复数"),
            )
            self.table.setRowHeight(row, self._ROW_HEIGHT)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addWidget(self.table, 1)
        lay.addWidget(buttons)

    def _on_edit_cell_clicked(self, row: int, col: int) -> None:
        if col not in (2, 3, 4):
            return
        item = self.table.item(row, col)
        if item is not None:
            self.table.editItem(item)

    def words(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row, w in enumerate(self._words):
            merged = dict(w)
            it2 = self.table.item(row, 2)
            label = it2.text().strip() if it2 else ""
            oc = _pos_zh_to_oc(label)
            if oc and oc != "OTHER":
                merged["pos"] = oc
            elif label:
                merged["pos"] = label
            it3 = self.table.item(row, 3)
            it4 = self.table.item(row, 4)
            case_label = it3.text().strip() if it3 else "—"
            number_label = it4.text().strip() if it4 else "—"
            _apply_case_number_to_word(merged, case_label, number_label)
            out.append(merged)
        return out


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
        self.btn_copy = QPushButton("复制到剪贴板")
        self.btn_copy.clicked.connect(self.copy_table_to_clipboard)
        self.btn_word_pos = QPushButton("逐词词性…")
        self.btn_word_pos.clicked.connect(self._edit_selected_word_pos)

        row_tools = QHBoxLayout()
        row_tools.setSpacing(8)
        row_tools.addWidget(btn_bulk)
        row_tools.addWidget(btn_del)
        row_tools.addWidget(btn_clear_all)
        row_tools.addWidget(btn_import)
        row_tools.addWidget(btn_export)
        row_tools.addWidget(self.btn_copy)
        row_tools.addWidget(self.btn_word_pos)
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
                self.btn_copy,
                self.btn_word_pos,
            ):
                put.polish_widget(b)
            put.polish_widget(self.hint)
        except ImportError:
            pass

        sc_save = QShortcut(QKeySequence.Save, self)
        sc_save.activated.connect(self.save_to_file)

        self._updating_pos = False
        self._morph_pos_refresh_token = 0
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.cellClicked.connect(self._on_table_cell_clicked)

        self._update_window_title()
        self.reload_from_file()
        self._update_pos_tool_visibility()

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

    def _pos_column_count(self) -> int:
        return 4 if _pos_supports_word_columns(self._tgt_code()) else 2

    def _update_table_headers(self) -> None:
        cols = self._pos_column_count()
        if self.table.columnCount() != cols:
            self.table.setColumnCount(cols)
        headers = [f"源语（{self._src_label()}）", f"译文（{self._tgt_label()}）"]
        if cols >= 4:
            headers.extend(["整体词性", "逐词词性"])
        self.table.setHorizontalHeaderLabels(headers)
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        if cols >= 4:
            hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            hdr.setSectionResizeMode(3, QHeaderView.Stretch)
            self.table.setEditTriggers(QAbstractItemView.CurrentChanged)
            self.table.setItemDelegateForColumn(
                2,
                _ComboColumnDelegate(self.table, list(_ENTRY_POS_CHOICES)),
            )
        else:
            self.table.setItemDelegateForColumn(2, None)

    def _update_pos_tool_visibility(self) -> None:
        show = _pos_supports_word_columns(self._tgt_code())
        self.btn_copy.setVisible(True)
        self.btn_word_pos.setVisible(show)

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
                "\n俄/乌语译文可填任意词形（不必原形）；保存时将自动识别词性并规范为词典原形。"
                "\n程序会按上下文变格；若单纯变格不合适，先在本地判断语法角色，"
                "再仅对单个词联网查 bkrs 派生词与维基变格（整句不上传）。"
                "可设环境变量 ARGOS_GLOSSARY_DERIVE_ONLINE=0 关闭联网派生。"
                "\n也可在 JSON 写 ru_pred（整词）或 words[].pred_lemma（单词）。"
                "\n同一中文多种外语译法：可写多行（同一中文重复多行，每行一种外语），"
                "或在译文格用 / 、; 或换行分隔；"
                "某译法下还有用词变体时用括号（如 священник (батько/батьки)）。"
                "翻译时在全部译法中随机取一种；译文中相关词会高亮，鼠标悬停可改选。"
                "\n填写俄/乌语时，「整体词性」「逐词词性」列会自动识别词性、格与单复数；"
                "单击「整体词性」可手动修改；双击「逐词词性」或点「逐词词性…」可校对单个单词词性。"
                "可用「复制到剪贴板」或「导出」粘贴到 Google 表格。"
            )
        if self._tgt_code() == "uk":
            try:
                import glossary_inflection as gi

                if not gi.uk_morph_analyzer_available():
                    text += (
                        "\n\n乌克兰语自动变格需安装 pymorphy3-dicts-uk。"
                        "在程序目录终端运行：\n"
                        f"{gi.uk_morph_install_command()}\n"
                        "安装后请重启程序。"
                    )
            except ImportError:
                pass
        elif self._tgt_code() == "ru":
            try:
                import glossary_manager as gm
                import pymorphy_compat as pc

                if not gm.morph_analyzer_available():
                    text += (
                        "\n\n逐词词性识别需要形态分析组件（pymorphy3）。"
                        "若「逐词词性」列只有整词括号、没有格/数，请在程序目录终端运行：\n"
                        f"{pc.install_command()}\n"
                        "安装后请重启程序。"
                    )
            except ImportError:
                pass
        self.hint.setText(text)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._pos_column_count() >= 4:
            self._schedule_morph_pos_refresh()

    def _schedule_morph_pos_refresh(self, attempt: int = 0) -> None:
        """pymorphy 后台加载完成后刷新逐词词性列。"""
        if self._pos_column_count() < 4:
            return
        token = self._morph_pos_refresh_token
        try:
            import glossary_manager as gm

            morph = gm.shared_morph_analyzer()
        except Exception:
            morph = None
        if morph is not None:
            self._refresh_all_pos_columns()
            return
        if attempt >= 40:
            return

        def _retry(t: int = token, a: int = attempt + 1) -> None:
            if t != self._morph_pos_refresh_token:
                return
            self._schedule_morph_pos_refresh(a)

        QTimer.singleShot(500, _retry)

    def _refresh_all_pos_columns(self) -> None:
        if self._pos_column_count() < 4:
            return
        for row in range(self.table.rowCount()):
            if self.table._cell_text(row, 1).strip():
                self._refresh_row_pos_columns(row)

    def _on_lang_pair_changed(self) -> None:
        save_lang_pair_prefs(self._src_code(), self._tgt_code())
        self._update_window_title()
        self._update_table_headers()
        self._refresh_hint()
        self._update_pos_tool_visibility()
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
            if pos_raw:
                pos = _normalize_pos(pos_raw)
            else:
                pos = infer_pos_for_target(tgt, tgt_lang)
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
            gs.upsert_terms_bulk(entries, tgt_lang, light=True)
            gs.save()
        except OSError as e:
            QMessageBox.warning(
                self,
                "保存失败",
                f"无法写入术语库文件（请检查安装目录是否可写）：\n{e}",
            )
            return
        except Exception as e:
            QMessageBox.critical(
                self,
                "批量添加失败",
                f"保存术语时出错，请减少单次条数或检查俄/乌语拼写：\n{e}",
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.reload_from_file(defer_morph=True)
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

    def _match_target_variant(self, val: Any, tgt_show: str, lang: str) -> Any:
        show = sanitize_glossary_cell(tgt_show)
        if not show:
            return None
        if isinstance(val, str):
            cell = tb.target_cell_text({lang: val}, lang)
            if cell == show or val.strip() == show:
                return val
            return None
        if isinstance(val, dict):
            cell = tb.target_cell_text({lang: val}, lang)
            if cell == show:
                return val
            lemma = str(val.get("lemma") or "").strip()
            if lemma == show:
                return val
            return None
        if isinstance(val, list):
            for item in val:
                matched = self._match_target_variant(item, show, lang)
                if matched is not None:
                    return matched
            try:
                import glossary_alternatives as ga

                for item in val:
                    cell = tb.target_cell_text({lang: item}, lang)
                    if not cell:
                        continue
                    if cell == show:
                        return item
                    opts = ga.list_all_options(cell)
                    if show in opts:
                        return item
            except ImportError:
                pass
        return None

    def _words_and_pos_for_row(
        self, entry: Any, tgt_lang: str, tgt_show: str
    ) -> tuple[str, list[dict[str, Any]]]:
        lang = tgt_lang
        entry_pos_zh = "名词"
        words: list[dict[str, Any]] = []
        if isinstance(entry, dict):
            pos_raw = entry.get("pos")
            if isinstance(pos_raw, str) and pos_raw.strip():
                entry_pos_zh = _bucket_to_zh(_normalize_pos(pos_raw))
            val = entry.get(tgt_lang)
            matched = self._match_target_variant(val, tgt_show, lang)
            if matched is not None:
                try:
                    import glossary_inflection as gi

                    words = gi.phrase_words_from_value(matched, lang)
                except Exception:
                    words = []
        if not words and tgt_show.strip():
            words = _analyze_row_words(tgt_show, lang)
        opts = _target_alternative_options(tgt_show)
        if tgt_show.strip():
            entry_pos_zh = _auto_entry_pos_zh(tgt_show, lang, entry_pos_zh)
        return entry_pos_zh, words

    def _set_row_word_meta(self, row: int, words: list[dict[str, Any]]) -> None:
        it1 = self.table.item(row, 1)
        if it1 is None:
            return
        it1.setData(ROLE_WORD_META, {"words": [dict(w) for w in words]})

    def _row_word_meta(self, row: int) -> list[dict[str, Any]]:
        it1 = self.table.item(row, 1)
        if it1 is None:
            return []
        meta = it1.data(ROLE_WORD_META)
        if isinstance(meta, dict):
            words = meta.get("words")
            if isinstance(words, list):
                return [w for w in words if isinstance(w, dict)]
        return []

    def _refresh_row_pos_columns(self, row: int) -> None:
        if self._pos_column_count() < 4:
            return
        tgt = self.table._cell_text(row, 1)
        lang = self._tgt_code()
        if not tgt.strip():
            self._updating_pos = True
            try:
                self._set_entry_pos_item(row, "")
                self.table.setItem(row, 3, GlossaryPasteTableWidget._make_item(""))
                self._set_row_word_meta(row, [])
            finally:
                self._updating_pos = False
            return
        overrides = self._row_word_meta(row)
        alt_opts = _target_alternative_options(tgt)
        if len(alt_opts) > 1:
            words = _analyze_row_words(alt_opts[0], lang)
            words = _merge_words_with_overrides(words, overrides)
            entry_pos = self._resolve_entry_pos(row, tgt, lang)
            summary = _words_pos_summary_for_alternatives(alt_opts, lang)
            self._updating_pos = True
            try:
                self._set_entry_pos_item(row, entry_pos, locked=False)
                it3 = GlossaryPasteTableWidget._make_item(summary)
                it3.setToolTip(
                    summary + "\n\n逗号分隔的多个备选译法，翻译时随机择一。\n"
                    "双击此行可编辑第一个备选的逐词词性。"
                )
                self.table.setItem(row, 3, it3)
                self._set_row_word_meta(row, words)
            finally:
                self._updating_pos = False
            return
        auto_words = _analyze_row_words(tgt, lang)
        words = _merge_words_with_overrides(auto_words, overrides)
        try:
            import glossary_inflection as gi

            corrected = gi.rebuild_phrase_surface(tgt, words, lang).strip()
            if corrected and corrected != tgt.strip():
                tgt = corrected
                auto_words = _analyze_row_words(tgt, lang)
                words = _merge_words_with_overrides(auto_words, overrides)
        except Exception:
            pass
        entry_pos = self._resolve_entry_pos(row, tgt, lang)
        summary = _words_pos_summary_or_infer(tgt, lang, words)
        self._updating_pos = True
        try:
            self.table.setItem(row, 1, GlossaryPasteTableWidget._make_item(tgt))
            self._set_entry_pos_item(row, entry_pos)
            it3 = GlossaryPasteTableWidget._make_item(summary)
            it3.setToolTip(
                summary + "\n\n双击此行可编辑各单词词性。"
            )
            self.table.setItem(row, 3, it3)
            self._set_row_word_meta(row, words)
        finally:
            self._updating_pos = False

    def _fill_row_pos_columns(
        self,
        row: int,
        entry_pos_zh: str,
        words: list[dict[str, Any]],
    ) -> None:
        if self._pos_column_count() < 4:
            return
        summary = _words_pos_summary_or_infer(
            self.table._cell_text(row, 1), self._tgt_code(), words
        )
        self._set_entry_pos_item(row, entry_pos_zh, locked=False)
        it3 = GlossaryPasteTableWidget._make_item(summary)
        it3.setToolTip(summary + "\n\n双击此行可编辑各单词词性。")
        self.table.setItem(row, 3, it3)
        self._set_row_word_meta(row, words)

    def _entry_pos_locked(self, row: int) -> bool:
        it = self.table.item(row, 2)
        return bool(it and it.data(ROLE_ENTRY_POS_OVERRIDE))

    def _set_entry_pos_item(
        self, row: int, text: str, *, locked: bool | None = None
    ) -> None:
        if locked is None:
            locked = self._entry_pos_locked(row)
        it = _make_entry_pos_item(text)
        if locked:
            it.setData(ROLE_ENTRY_POS_OVERRIDE, True)
        self.table.setItem(row, 2, it)

    def _resolve_entry_pos(self, row: int, tgt: str, lang: str) -> str:
        if self._entry_pos_locked(row):
            return _normalize_pos(self.table._cell_text(row, 2))
        return _normalize_pos(
            _auto_entry_pos_zh(tgt, lang, self.table._cell_text(row, 2))
        )

    def _on_table_cell_clicked(self, row: int, col: int) -> None:
        if self._pos_column_count() < 4 or col != 2:
            return
        if not self.table._cell_text(row, 1).strip():
            return
        item = self.table.item(row, col)
        if item is not None:
            self.table.editItem(item)

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_pos:
            return
        if self._pos_column_count() < 4:
            return
        col = item.column()
        if col == 2:
            item.setData(ROLE_ENTRY_POS_OVERRIDE, True)
            return
        if col == 1:
            self._refresh_row_pos_columns(item.row())

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        if col == 3 and self._pos_column_count() >= 4:
            self._edit_row_word_pos(row)

    def _edit_row_word_pos(self, row: int) -> None:
        tgt = self.table._cell_text(row, 1)
        if not tgt.strip():
            QMessageBox.information(self, "逐词词性", "请先在「译文」列填写内容。")
            return
        lang = self._tgt_code()
        words = self._row_word_meta(row)
        if not words:
            words = _analyze_row_words(tgt, lang)
        dlg = GlossaryWordPosDialog(tgt, lang, words, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return
        updated = dlg.words()
        lang = self._tgt_code()
        try:
            import glossary_inflection as gi

            corrected = gi.rebuild_phrase_surface(tgt, updated, lang).strip()
            if corrected:
                tgt = corrected
                updated = _merge_words_with_overrides(
                    _analyze_row_words(tgt, lang), updated
                )
        except Exception:
            pass
        self._updating_pos = True
        try:
            self.table.setItem(row, 1, GlossaryPasteTableWidget._make_item(tgt))
            self._set_row_word_meta(row, updated)
            summary = _words_pos_summary(updated)
            it3 = GlossaryPasteTableWidget._make_item(summary)
            it3.setToolTip(summary + "\n\n双击此行可编辑各单词词性。")
            self.table.setItem(row, 3, it3)
        finally:
            self._updating_pos = False

    def _edit_selected_word_pos(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            QMessageBox.information(self, "逐词词性", "请先选中一行。")
            return
        self._edit_row_word_pos(rows[0])

    def _parse_target_with_row_meta(
        self, tgt_raw: str, tgt_lang: str, row: int
    ) -> tuple[Any, str]:
        alt_opts = _target_alternative_options(tgt_raw)
        if tgt_lang in ("ru", "uk") and len(alt_opts) > 1:
            normalized: list[Any] = []
            seen: set[str] = set()
            for opt in alt_opts:
                piece = (opt or "").strip()
                if not piece:
                    continue
                key = piece.casefold()
                if key in seen:
                    continue
                seen.add(key)
                val = tb.parse_target_cell(piece, tgt_lang)
                normalized.append(val if val else piece)
            entry_pos = self._resolve_entry_pos(row, tgt_raw, tgt_lang)
            if len(normalized) == 1:
                return normalized[0], entry_pos
            return normalized, entry_pos
        val = tb.parse_target_cell(tgt_raw, tgt_lang)
        entry_pos = _normalize_pos(self.table._cell_text(row, 2))
        if tgt_lang not in ("ru", "uk"):
            return val, entry_pos
        words = self._row_word_meta(row)
        if not words:
            words = _analyze_row_words(tgt_raw, tgt_lang)
        display = tgt_raw.strip()
        try:
            import glossary_inflection as gi

            rebuilt = gi.rebuild_phrase_surface(tgt_raw, words, tgt_lang).strip()
            if rebuilt:
                display = rebuilt
                words = _merge_words_with_overrides(
                    _analyze_row_words(display, tgt_lang), words
                )
        except Exception:
            pass
        if isinstance(val, dict):
            val = _apply_words_to_target_val(
                val, words, surface=display, lang=tgt_lang
            )
        elif words:
            try:
                import glossary_inflection as gi

                val2 = gi.normalize_for_glossary_storage(display or tgt_raw, tgt_lang)
                if isinstance(val2, dict):
                    val = _apply_words_to_target_val(
                        val2, words, surface=display, lang=tgt_lang
                    )
            except Exception:
                pass
        entry_pos = self._resolve_entry_pos(row, tgt_raw, tgt_lang)
        return val, entry_pos

    def _table_export_rows(self) -> list[list[str]]:
        cols = self._pos_column_count()
        out: list[list[str]] = []
        for r in range(self.table.rowCount()):
            src = self.table._cell_text(r, 0)
            tgt = self.table._cell_text(r, 1)
            if not src and not tgt:
                continue
            row_cells = [src, tgt]
            if cols >= 4:
                entry_pos = self.table._cell_text(r, 2)
                words = self._row_word_meta(r)
                if not words and tgt.strip():
                    words = _analyze_row_words(tgt, self._tgt_code())
                row_cells.extend(
                    [
                        entry_pos,
                        _words_pos_summary(words),
                        _words_pos_export_detail(words),
                    ]
                )
            out.append(row_cells)
        return out

    def copy_table_to_clipboard(self) -> None:
        cols = self._pos_column_count()
        headers = [
            f"源语({self._src_label()})",
            f"译文({self._tgt_label()})",
        ]
        if cols >= 4:
            headers.extend(["整体词性", "逐词词性", "逐词详情"])
        lines = ["\t".join(headers)]
        for row_cells in self._table_export_rows():
            lines.append("\t".join(row_cells))
        QApplication.clipboard().setText("\n".join(lines))
        n = max(0, len(lines) - 1)
        QMessageBox.information(
            self,
            "已复制",
            f"已复制 {n} 行到剪贴板（Tab 分隔）。\n"
            "在 Google 表格中选中 A1 后 Ctrl+V 即可粘贴。",
        )

    def reload_from_file(self, *, defer_morph: bool = False) -> None:
        self._morph_pos_refresh_token += 1
        data = tb.load_glossary()
        tgt_lang = self._tgt_code()
        cols = self._pos_column_count()
        keys = [
            k
            for k in sorted(data.keys(), key=lambda s: (len(s), s), reverse=True)
            if isinstance(k, str) and k.strip()
        ]
        display_rows: list[tuple[str, str, str, list[dict[str, Any]]]] = []
        for src in keys:
            entry = data[src]
            for tgt_show in self._target_rows_for_entry(entry, tgt_lang):
                try:
                    entry_pos, words = self._words_and_pos_for_row(
                        entry, tgt_lang, tgt_show
                    )
                except Exception:
                    entry_pos = _auto_entry_pos_zh(tgt_show, tgt_lang)
                    words = []
                display_rows.append((src, tgt_show, entry_pos, words))
        n = len(display_rows) + 1
        self._updating_pos = True
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        try:
            if self.table.columnCount() != cols:
                self.table.setColumnCount(cols)
            self._update_table_headers()
            self.table.setRowCount(n)
            for row, (src, tgt_show, entry_pos, words) in enumerate(display_rows):
                self.table.setItem(row, 0, GlossaryPasteTableWidget._make_item(src))
                self.table.setItem(
                    row, 1, GlossaryPasteTableWidget._make_item(tgt_show)
                )
                if cols >= 4:
                    self._fill_row_pos_columns(row, entry_pos, words)
            last = n - 1
            self.table.setItem(last, 0, GlossaryPasteTableWidget._make_item(""))
            self.table.setItem(last, 1, GlossaryPasteTableWidget._make_item(""))
            if cols >= 4:
                self._set_entry_pos_item(last, "", locked=False)
                self.table.setItem(last, 3, GlossaryPasteTableWidget._make_item(""))
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.blockSignals(False)
            self._updating_pos = False
        self.table._resize_rows_for_contents()
        if cols >= 4 and (defer_morph or self.isVisible()):
            self._schedule_morph_pos_refresh()

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
                cols = self._pos_column_count()
                header = [
                    f"源语({self._src_label()})",
                    f"译文({self._tgt_label()})",
                    f"src_lang={src_code}",
                    f"tgt_lang={tgt_code}",
                ]
                if cols >= 4:
                    header.extend(["整体词性", "逐词词性", "逐词详情"])
                w.writerow(header)
                for row_cells in self._table_export_rows():
                    w.writerow(row_cells)
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

        src_tgts: OrderedDict[str, list[tuple[str, int]]] = OrderedDict()

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
            for part in parts:
                src_tgts[src].append((part, r))

        multi_row = 0
        for src, tgt_rows in src_tgts.items():
            tgt_vals: list[Any] = []
            entry_pos = "noun"
            for t, row_idx in tgt_rows:
                val, ep = self._parse_target_with_row_meta(t, tgt_lang, row_idx)
                if t.strip():
                    tgt_vals.append(val)
                    entry_pos = ep
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
                merged["pos"] = entry_pos
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
