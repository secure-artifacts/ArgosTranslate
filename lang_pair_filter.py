"""TM / 审核队列：语言对筛选 UI。"""
from __future__ import annotations

from PyQt5.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QWidget

from corpus_pipeline.lang_filter import LANG_OPTIONS, norm_filter_code, pair_filter_codes


def _fill_lang_combo(combo: QComboBox, selected: str) -> None:
    combo.clear()
    sel = norm_filter_code(selected)
    pick = 0
    for i, (code, label) in enumerate(LANG_OPTIONS):
        combo.addItem(label, code)
        if code == sel:
            pick = i
    combo.setCurrentIndex(pick)


class LangPairFilterBar(QWidget):
    """源语 / 目标语下拉 + 是否启用筛选。"""

    def __init__(
        self,
        parent=None,
        *,
        initial_source: str = "",
        initial_target: str = "",
        filter_enabled: bool = True,
        checkbox_text: str = "按语言对筛选",
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._filter_check = QCheckBox(checkbox_text)
        self._filter_check.setChecked(filter_enabled)
        layout.addWidget(self._filter_check)
        layout.addWidget(QLabel("源语："))
        self._source_combo = QComboBox()
        _fill_lang_combo(self._source_combo, initial_source or "zh")
        layout.addWidget(self._source_combo)
        layout.addWidget(QLabel("目标语："))
        self._target_combo = QComboBox()
        _fill_lang_combo(self._target_combo, initial_target or "ru")
        layout.addWidget(self._target_combo)
        layout.addStretch()

    def connect_changed(self, callback) -> None:
        self._filter_check.stateChanged.connect(lambda _: callback())
        self._source_combo.currentIndexChanged.connect(lambda _: callback())
        self._target_combo.currentIndexChanged.connect(lambda _: callback())

    def is_active(self) -> bool:
        return self._filter_check.isChecked()

    def current_codes(self) -> tuple[str, str]:
        return (
            str(self._source_combo.currentData() or ""),
            str(self._target_combo.currentData() or ""),
        )

    def filter_codes(self) -> tuple[str | None, str | None]:
        if not self.is_active():
            return None, None
        return pair_filter_codes(*self.current_codes())

    def filter_label(self) -> str:
        if not self.is_active():
            return "全部语言"
        sl, tl = self.filter_codes()
        parts = []
        if sl:
            parts.append(sl)
        else:
            parts.append("*")
        parts.append("→")
        if tl:
            parts.append(tl)
        else:
            parts.append("*")
        return " ".join(parts)
