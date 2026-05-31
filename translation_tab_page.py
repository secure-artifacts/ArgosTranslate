"""
多标签翻译页：每个标签独立的语言对、原文/译文、语音设备与翻译任务。
"""
from __future__ import annotations

import copy
from functools import partial
from typing import Any, TYPE_CHECKING

from PyQt5.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEventLoop,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from argostranslategui.gui import GUIWindow

_SESSION_TEXT_LIMIT = 500_000
# 查词侧栏：默认宽度与可拖动范围（QSplitter，不挤压左侧翻译区）
WORD_LOOKUP_PANEL_DEFAULT_WIDTH = 440
WORD_LOOKUP_PANEL_MIN_WIDTH = 280
WORD_LOOKUP_TRANSLATION_MIN_WIDTH = 520
# 本软件常用语言：下拉框置顶、加粗并放大（与 host.languages 下标映射见 _lang_combo_order）
_PRIORITY_LANG_CODES = frozenset({"zh", "zt", "ru", "uk"})
_PRIORITY_LANG_ORDER = ("zh", "zt", "ru", "uk")
_PRIORITY_LANG_FONT_PT_DELTA = 2


def _is_zh_family_code(code: str) -> bool:
    c = (code or "").strip().lower().replace("_", "-")
    return bool(c) and (c.startswith("zh") or c in ("zt", "jy", "cn", "tw"))


def _resolve_translation(input_language, output_language, languages: list):
    """
    选择翻译链。Ollama 模式下使用 Qwen 2.5；否则走 Argos 语言包。
    中→乌在 Argos 模式下仍优先经俄语；Ollama 模式下可直译。
    """
    if input_language is None or output_language is None:
        return None
    try:
        import ollama_translate as ot

        if ot.use_ollama_backend():
            return ot.make_translation(input_language.code, output_language.code)
    except ImportError:
        pass
    except ValueError:
        return None
    src = (input_language.code or "").strip().lower()
    tgt = (output_language.code or "").strip().lower()
    if _is_zh_family_code(src) and tgt == "uk":
        lang_by_code = {l.code: l for l in languages if getattr(l, "code", None)}
        ru = lang_by_code.get("ru")
        uk = lang_by_code.get("uk")
        if ru is not None and uk is not None:
            t_zh_ru = input_language.get_translation(ru)
            t_ru_uk = ru.get_translation(uk)
            if t_zh_ru is not None and t_ru_uk is not None:
                from argostranslate.translate import CompositeTranslation

                return CompositeTranslation(t_zh_ru, t_ru_uk)
    return input_language.get_translation(output_language)


def _ordered_language_indices(languages: list) -> list[int]:
    rank = {c: i for i, c in enumerate(_PRIORITY_LANG_ORDER)}
    pri: list[tuple[int, int]] = []
    rest: list[int] = []
    for i, lang in enumerate(languages):
        code = (getattr(lang, "code", None) or "").strip().lower()
        if code in rank:
            pri.append((rank[code], i))
        else:
            rest.append(i)
    pri.sort(key=lambda x: x[0])
    return [i for _, i in pri] + rest


def _is_priority_lang_code(code: str | None) -> bool:
    return (code or "").strip().lower() in _PRIORITY_LANG_CODES


def _priority_lang_font(base: QFont) -> QFont:
    f = QFont(base)
    f.setBold(True)
    pt = f.pointSize()
    if pt > 0:
        f.setPointSize(pt + _PRIORITY_LANG_FONT_PT_DELTA)
    elif f.pixelSize() > 0:
        f.setPixelSize(int(f.pixelSize() * 1.12) + 2)
    return f


def _normal_lang_font(base: QFont) -> QFont:
    f = QFont(base)
    f.setBold(False)
    return f


def _trim_session_text(s: str) -> str:
    if len(s) <= _SESSION_TEXT_LIMIT:
        return s
    return s[:_SESSION_TEXT_LIMIT] + "\n\n[… 超出保存上限，部分内容未写入会话文件 …]"


class TranslationTabPage(QWidget):
    """单个翻译标签：独立输入设置，不与其他标签共享语音会话或翻译队列。"""

    def __init__(
        self,
        host: GUIWindow,
        tab_serial: int,
        *,
        speech_prefs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._host = host
        self.tab_serial = tab_serial
        self._speech_prefs: dict[str, Any] = {}
        self._init_speech_prefs(speech_prefs)

        self.worker_thread = None
        self.queued_translation = None
        self._offline_speech_worker = None
        self._vosk_download_worker = None
        self._vosk_download_pending_lang: str | None = None
        self._speech_was_paused_by_tab_switch = False
        self._speech_committed = ""
        self._speech_live_partial = ""
        self._speech_translate_debounce = QTimer(self)
        self._speech_translate_debounce.setSingleShot(True)
        self._speech_translate_debounce.setInterval(450)
        self._speech_translate_debounce.timeout.connect(
            self._translate_after_speech_update
        )
        self._btn_offline_speech = None
        self._speech_input_combo = None
        self._speech_output_combo = None
        self._speech_channels_combo = None
        self._speech_audio_bar = None
        self._speech_settings_panel = None
        self._btn_speech_settings = None
        self._left_col_layout = None
        self._src_footer_layout = None
        self._word_lookup_panel = None
        self._lookup_slot = None
        self._translation_pair = None
        self._main_splitter = None
        self._lookup_panel_open = False
        self._lookup_panel_width = WORD_LOOKUP_PANEL_DEFAULT_WIDTH
        self._word_lookup_upgraded = False
        self._restore_left_code = ""
        self._restore_right_code = ""
        self._lang_combo_order: list[int] = []
        self._lang_combo_base_font: QFont | None = None

        root = host._portable_root
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        lang_bar = QFrame()
        lang_bar.setObjectName("LangBar")
        lang_row = QHBoxLayout(lang_bar)
        lang_row.setContentsMargins(12, 8, 12, 8)
        self.left_language_combo = QComboBox()
        self.language_swap_button = QPushButton("↔")
        self.right_language_combo = QComboBox()
        self.left_language_combo.currentIndexChanged.connect(self._on_lang_combo_changed)
        self.right_language_combo.currentIndexChanged.connect(self._on_lang_combo_changed)
        self.language_swap_button.clicked.connect(self.swap_languages_button_clicked)
        self._populate_lang_row(lang_row)
        layout.addWidget(lang_bar)

        self.left_textEdit = QTextEdit()
        from argostranslategui.gui import _fast_startup_enabled

        if root is not None and _fast_startup_enabled():
            _src_ph = "在此输入要翻译的原文"
        else:
            _src_ph = "在此输入要翻译的原文（支持大段文字；极长单行会自动按语义切块后翻译）"
            if root is not None:
                try:
                    import ollama_translate as ot

                    if ot.use_ollama_backend():
                        _src_ph = (
                            "在此输入要翻译的原文（支持大段文字）。"
                            "引擎：Ollama + Qwen 2.5 本地推理，数据不上传。"
                            "固定译法请写入「术语库」。"
                        )
                    else:
                        _src_ph = (
                            "在此输入要翻译的原文（支持大段文字）。合同/法律类：务必人工校对；"
                            "固定译法请写入「术语库」。精译参数见 data\\config\\argos-translate\\settings.json。"
                        )
                except ImportError:
                    _src_ph = (
                        "在此输入要翻译的原文（支持大段文字）。合同/法律类：务必人工校对；"
                        "固定译法请写入「术语库」。精译参数见 data\\config\\argos-translate\\settings.json。"
                    )
        self.left_textEdit.setPlaceholderText(_src_ph)
        self._translate_debounce = QTimer(self)
        self._translate_debounce.setSingleShot(True)
        self._translate_debounce.setInterval(200)
        self._translate_debounce.timeout.connect(self.translate)
        self.left_textEdit.textChanged.connect(self._update_char_counts)
        self.left_textEdit.textChanged.connect(self._schedule_translate_debounce)

        self.right_textEdit = QTextEdit()
        if root is not None and _fast_startup_enabled():
            _tgt_ph = "译文"
        else:
            _tgt_ph = "译文将显示在此处"
            if root is not None:
                try:
                    import ollama_translate as ot

                    if ot.use_ollama_backend():
                        _tgt_ph = (
                            "译文将显示在此处。\n"
                            f"引擎：Ollama + {ot.model_name()}（100% 本地，首次翻译可能较慢）。"
                        )
                    else:
                        _tgt_ph = (
                            "译文将显示在此处。\n"
                            "说明：离线模型会压缩语气；可调 settings.json 中的 ARGOS_BEAM_SIZE（如 8～12，更慢）。"
                        )
                except ImportError:
                    _tgt_ph = (
                        "译文将显示在此处。\n"
                        "说明：离线模型会压缩语气；可调 settings.json 中的 ARGOS_BEAM_SIZE（如 8～12，更慢）。"
                    )
        self.right_textEdit.setPlaceholderText(_tgt_ph)
        self.right_textEdit.textChanged.connect(self._update_char_counts)

        self._src_count_label = QLabel("0 字符")
        self._src_count_label.setObjectName("CharCount")
        self._tgt_count_label = QLabel("0 字符")
        self._tgt_count_label.setObjectName("CharCount")
        btn_clear_src = QPushButton("清空")
        btn_clear_src.setObjectName("TextAction")
        btn_clear_src.clicked.connect(self._clear_source_text)
        btn_clear_tgt = QPushButton("清空")
        btn_clear_tgt.setObjectName("TextAction")
        btn_clear_tgt.clicked.connect(self._clear_target_text)
        btn_copy_tgt = QPushButton("复制译文")
        btn_copy_tgt.setObjectName("TextAction")
        btn_copy_tgt.clicked.connect(self._copy_target_text)

        left_col = QWidget()
        left_col_layout = QVBoxLayout(left_col)
        left_col_layout.setContentsMargins(0, 0, 0, 0)
        left_col_layout.setSpacing(8)
        left_col_layout.addWidget(self.left_textEdit)
        self._left_col_layout = left_col_layout
        src_footer = QHBoxLayout()
        src_footer.addWidget(self._src_count_label)
        src_footer.addStretch()
        src_footer.addWidget(btn_clear_src)
        self._src_footer_layout = src_footer
        left_col_layout.addLayout(src_footer)
        if root is not None and _fast_startup_enabled():
            QTimer.singleShot(900, self._deferred_init_speech_controls)
        elif root is not None:
            self._init_speech_controls()

        right_col = QWidget()
        right_col_layout = QVBoxLayout(right_col)
        right_col_layout.setContentsMargins(0, 0, 0, 0)
        right_col_layout.setSpacing(8)
        right_col_layout.addWidget(self.right_textEdit)
        tgt_footer = QHBoxLayout()
        tgt_footer.addWidget(self._tgt_count_label)
        tgt_footer.addStretch()
        tgt_footer.addWidget(btn_copy_tgt)
        tgt_footer.addWidget(btn_clear_tgt)
        right_col_layout.addLayout(tgt_footer)

        self._translation_pair = QWidget()
        tp_l = QHBoxLayout(self._translation_pair)
        tp_l.setContentsMargins(0, 0, 0, 0)
        tp_l.setSpacing(12)
        tp_l.addWidget(left_col, 1)
        tp_l.addWidget(right_col, 1)

        self._lookup_slot = QWidget()
        self._lookup_slot.setObjectName("WordLookupSlot")
        slot_l = QVBoxLayout(self._lookup_slot)
        slot_l.setContentsMargins(0, 0, 0, 0)
        slot_l.setSpacing(0)

        self._main_splitter = QSplitter(Qt.Horizontal)
        self._main_splitter.setObjectName("TranslationSplitter")
        self._main_splitter.setChildrenCollapsible(False)
        self._main_splitter.setHandleWidth(10)
        self._main_splitter.addWidget(self._translation_pair)
        self._main_splitter.addWidget(self._lookup_slot)
        self._main_splitter.setStretchFactor(0, 1)
        self._main_splitter.setStretchFactor(1, 0)
        self._main_splitter.setSizes([10000, 0])
        self._main_splitter.splitterMoved.connect(self._on_lookup_splitter_moved)

        from argostranslategui.gui import _import_word_info_module

        if root is not None:
            wi_mod = _import_word_info_module()
            if wi_mod is not None and hasattr(wi_mod, "WordLookupPanel"):
                self._attach_word_lookup_panel(wi_mod.WordLookupPanel(self))
        layout.addWidget(self._main_splitter, 1)

        self.language_swap_button.setObjectName("SwapButton")
        self.left_textEdit.setMinimumHeight(200)
        self.right_textEdit.setMinimumHeight(200)
        self._update_char_counts()

    def _attach_word_lookup_panel(self, panel: QWidget) -> None:
        """查词侧栏放入 QSplitter，可拖动调宽，左侧翻译区宽度由分隔条保证。"""
        if self._word_lookup_panel is not None:
            return
        self._word_lookup_panel = panel
        panel._translation_tab_page = self
        lay = self._lookup_slot.layout()
        if lay is not None:
            lay.addWidget(panel)
        panel.setVisible(False)
        self._lookup_slot.setMinimumWidth(0)
        self._lookup_slot.setMaximumWidth(16777215)

    def _splitter_total_width(self) -> int:
        if self._main_splitter is None:
            return 1
        w = self._main_splitter.width()
        if w > 0:
            return w
        sizes = self._main_splitter.sizes()
        return max(sum(sizes), 1)

    def _set_lookup_splitter_width(self, lookup_w: int) -> None:
        if self._main_splitter is None:
            return
        total = self._splitter_total_width()
        lookup_w = max(0, min(int(lookup_w), total - WORD_LOOKUP_TRANSLATION_MIN_WIDTH))
        if lookup_w > 0:
            lookup_w = max(lookup_w, WORD_LOOKUP_PANEL_MIN_WIDTH)
        self._main_splitter.setSizes([max(1, total - lookup_w), lookup_w])

    def _on_lookup_splitter_moved(self, _pos: int, index: int) -> None:
        if index != 1 or self._main_splitter is None:
            return
        sizes = self._main_splitter.sizes()
        if len(sizes) >= 2 and sizes[1] >= WORD_LOOKUP_PANEL_MIN_WIDTH:
            self._lookup_panel_width = sizes[1]

    def show_word_lookup_panel(self) -> None:
        if self._word_lookup_panel is None or self._lookup_slot is None:
            return
        self._lookup_panel_open = True
        self._word_lookup_panel.setVisible(True)
        self._lookup_slot.show()
        w = max(WORD_LOOKUP_PANEL_MIN_WIDTH, int(self._lookup_panel_width))
        self._set_lookup_splitter_width(w)

    def hide_word_lookup_panel(self) -> None:
        if self._word_lookup_panel is None or self._lookup_slot is None:
            return
        if self._main_splitter is not None:
            sizes = self._main_splitter.sizes()
            if len(sizes) >= 2 and sizes[1] >= WORD_LOOKUP_PANEL_MIN_WIDTH:
                self._lookup_panel_width = sizes[1]
            total = max(sum(sizes), self._splitter_total_width())
            self._main_splitter.setSizes([total, 0])
        self._word_lookup_panel.setVisible(False)
        self._lookup_panel_open = False

    @property
    def languages(self) -> list:
        return getattr(self._host, "languages", None) or []

    def _language_at_combo_index(self, combo_idx: int):
        langs = self.languages
        order = self._lang_combo_order or list(range(len(langs)))
        if combo_idx < 0 or combo_idx >= len(order) or not langs:
            return langs[0] if langs else None
        return langs[order[combo_idx]]

    def _combo_index_for_lang_index(self, lang_idx: int) -> int:
        order = self._lang_combo_order or list(range(len(self.languages)))
        try:
            return order.index(lang_idx)
        except ValueError:
            return 0

    def _lang_combo_base(self) -> QFont:
        if self._lang_combo_base_font is None:
            self._lang_combo_base_font = QFont(self.left_language_combo.font())
        return QFont(self._lang_combo_base_font)

    def _update_language_combo_display_font(self, combo: QComboBox) -> None:
        lang = self._language_at_combo_index(combo.currentIndex())
        base = self._lang_combo_base()
        if lang is not None and _is_priority_lang_code(getattr(lang, "code", None)):
            combo.setFont(_priority_lang_font(base))
        else:
            combo.setFont(_normal_lang_font(base))

    def _fill_language_combo(self, combo: QComboBox) -> None:
        from argostranslategui.gui import _lang_combo_label_zh

        langs = self.languages
        self._lang_combo_order = _ordered_language_indices(langs)
        if self._lang_combo_base_font is None:
            self._lang_combo_base_font = QFont(combo.font())
        base = self._lang_combo_base()
        combo.clear()
        for pos, lang_i in enumerate(self._lang_combo_order):
            lang = langs[lang_i]
            combo.addItem(_lang_combo_label_zh(lang))
            if _is_priority_lang_code(getattr(lang, "code", None)):
                combo.setItemData(pos, _priority_lang_font(base), Qt.FontRole)
            else:
                combo.setItemData(pos, _normal_lang_font(base), Qt.FontRole)
        self._update_language_combo_display_font(combo)

    def _init_speech_prefs(self, speech_prefs: dict[str, Any] | None) -> None:
        from argostranslategui.gui import _import_offline_speech_module

        sm = _import_offline_speech_module()
        if speech_prefs and isinstance(speech_prefs, dict):
            base = sm.default_audio_prefs() if sm else {}
            self._speech_prefs = {**base, **copy.deepcopy(speech_prefs)}
        elif sm is not None:
            self._speech_prefs = copy.deepcopy(sm.load_audio_prefs())
        else:
            self._speech_prefs = {}

    def default_tab_title(self) -> str:
        return f"翻译 {self.tab_serial}"

    def to_session_dict(self) -> dict[str, Any]:
        li = self.left_language_combo.currentIndex()
        ri = self.right_language_combo.currentIndex()
        L = self._language_at_combo_index(li)
        R = self._language_at_combo_index(ri)
        lc = (getattr(L, "code", None) or "").strip().lower() if L else ""
        rc = (getattr(R, "code", None) or "").strip().lower() if R else ""
        return {
            "source_text": _trim_session_text(self.left_textEdit.toPlainText()),
            "target_text": _trim_session_text(self.right_textEdit.toPlainText()),
            "left_lang_code": lc,
            "right_lang_code": rc,
            "speech_prefs": copy.deepcopy(self._get_speech_audio_prefs()),
        }

    def apply_session_state(self, state: dict[str, Any]) -> None:
        self._restore_left_code = str(state.get("left_lang_code") or "").strip().lower()
        self._restore_right_code = str(state.get("right_lang_code") or "").strip().lower()
        src = state.get("source_text") or ""
        tgt = state.get("target_text") or ""
        if isinstance(tgt, str) and (
            "[当前语言对" in tgt
            or "WinError 1114" in tgt
            or "c10.dll" in tgt.lower()
        ):
            tgt = ""
        self.left_textEdit.blockSignals(True)
        self.left_textEdit.setPlainText(src if isinstance(src, str) else "")
        self.left_textEdit.blockSignals(False)
        self.right_textEdit.blockSignals(True)
        self.right_textEdit.setPlainText(tgt if isinstance(tgt, str) else "")
        self.right_textEdit.blockSignals(False)
        sp = state.get("speech_prefs")
        if isinstance(sp, dict):
            self._speech_prefs = copy.deepcopy(sp)
        self._update_char_counts()

    def apply_restored_language_codes(self) -> None:
        if not self._restore_left_code and not self._restore_right_code:
            return
        self.apply_language_codes(self._restore_left_code, self._restore_right_code)

    def apply_language_codes(self, src_code: str, tgt_code: str) -> None:
        if not self.languages:
            return
        from argostranslategui.gui import _lang_index_first_matching_code

        src = (src_code or "").strip().lower()
        tgt = (tgt_code or "").strip().lower()
        if not src and not tgt:
            return
        self.left_language_combo.blockSignals(True)
        self.right_language_combo.blockSignals(True)
        if src:
            i = _lang_index_first_matching_code(self.languages, (src,))
            if i is not None:
                self.left_language_combo.setCurrentIndex(
                    self._combo_index_for_lang_index(i)
                )
        if tgt:
            i = _lang_index_first_matching_code(self.languages, (tgt,))
            if i is not None:
                self.right_language_combo.setCurrentIndex(
                    self._combo_index_for_lang_index(i)
                )
        self.left_language_combo.blockSignals(False)
        self.right_language_combo.blockSignals(False)
        self.refresh_tab_title()

    def refresh_tab_title(self) -> None:
        langs = self.languages
        li = self.left_language_combo.currentIndex()
        ri = self.right_language_combo.currentIndex()
        if not langs or li < 0 or ri < 0:
            title = self.default_tab_title()
        else:
            from argostranslategui.gui import _lang_combo_label_zh

            L = self._language_at_combo_index(li)
            R = self._language_at_combo_index(ri)
            if L is None or R is None:
                title = self.default_tab_title()
            else:
                title = (
                    f"{_lang_combo_label_zh(L)} → {_lang_combo_label_zh(R)}"
                )
        tw = self._host._tab_widget
        idx = tw.indexOf(self)
        if idx >= 0:
            tw.setTabText(idx, title)

    def _schedule_translate_debounce(self) -> None:
        try:
            import argos_inference_tuning as ait

            ms = ait.debounce_ms_for_text(self.left_textEdit.toPlainText())
        except Exception:
            ms = 200
        self._translate_debounce.setInterval(ms)
        self._translate_debounce.start()

    def _warmup_current_language_pair(self) -> None:
        if not self.languages:
            return
        li = self.left_language_combo.currentIndex()
        ri = self.right_language_combo.currentIndex()
        if li < 0 or ri < 0:
            return
        L = self._language_at_combo_index(li)
        R = self._language_at_combo_index(ri)
        if L is None or R is None:
            return
        fc = (L.code or "").strip().lower()
        tc = (R.code or "").strip().lower()
        if fc not in ("ru", "uk") and tc not in ("ru", "uk"):
            return

        def _run() -> None:
            try:
                import argos_inference_tuning as ait

                ait.warmup_translation(fc, tc)
            except Exception:
                pass

        from PyQt5.QtCore import QThreadPool, QRunnable

        class _Job(QRunnable):
            def run(self) -> None:
                _run()

        QThreadPool.globalInstance().start(_Job())

    def _on_lang_combo_changed(self, _index: int = 0) -> None:
        sender = self.sender()
        if sender in (self.left_language_combo, self.right_language_combo):
            self._update_language_combo_display_font(sender)
        self.refresh_tab_title()
        self._maybe_upgrade_word_lookup_text_edits()
        self._warmup_current_language_pair()
        self.translate()

    def shutdown(self) -> None:
        self._stop_speech_worker(wait_ms=3000)
        if self.worker_thread is not None and self.worker_thread.isRunning():
            self.worker_thread.wait(2000)

    def on_tab_deactivated(self) -> None:
        w = self._offline_speech_worker
        if w is not None and w.isRunning() and w.is_recording_allowed():
            w.pause_recording()
            self._speech_was_paused_by_tab_switch = True
            if self._btn_offline_speech is not None:
                self._btn_offline_speech.setText("语音继续")

    def on_tab_activated(self) -> None:
        if not self._speech_was_paused_by_tab_switch:
            return
        w = self._offline_speech_worker
        if w is not None and w.isRunning():
            w.resume_recording()
            if self._btn_offline_speech is not None:
                self._btn_offline_speech.setText("语音暂停")
        self._speech_was_paused_by_tab_switch = False

    def _populate_lang_row(self, row: QHBoxLayout) -> None:
        row.addStretch()
        row.addWidget(self.left_language_combo)
        row.addStretch()
        row.addWidget(self.language_swap_button)
        row.addStretch()
        row.addWidget(self.right_language_combo)
        row.addStretch()

    def apply_language_combos(self, *, run_translate: bool = True) -> None:
        from argostranslategui.gui import _lang_index_first_matching_code

        self.left_language_combo.blockSignals(True)
        self.right_language_combo.blockSignals(True)
        self._fill_language_combo(self.left_language_combo)
        self._fill_language_combo(self.right_language_combo)
        n = len(self.languages)
        if n == 0:
            self.left_language_combo.blockSignals(False)
            self.right_language_combo.blockSignals(False)
            self.right_textEdit.setPlaceholderText("未检测到语言包，请先安装语言包。")
            self.refresh_tab_title()
            return
        self.right_textEdit.setPlaceholderText("译文将显示在此处。")
        src_i = _lang_index_first_matching_code(self.languages, ("zh", "zt"))
        tgt_i = _lang_index_first_matching_code(self.languages, ("ru",))
        if src_i is not None:
            self.left_language_combo.setCurrentIndex(
                self._combo_index_for_lang_index(src_i)
            )
        else:
            self.left_language_combo.setCurrentIndex(0)
        left_cur = self.left_language_combo.currentIndex()
        if tgt_i is not None:
            tgt_combo = self._combo_index_for_lang_index(tgt_i)
            if tgt_combo != left_cur:
                self.right_language_combo.setCurrentIndex(tgt_combo)
        elif n > 1:
            for j in range(len(self._lang_combo_order)):
                if j != left_cur:
                    self.right_language_combo.setCurrentIndex(j)
                    break
        else:
            self.right_language_combo.setCurrentIndex(0)
        self.left_language_combo.blockSignals(False)
        self.right_language_combo.blockSignals(False)
        self.apply_restored_language_codes()
        self._update_language_combo_display_font(self.left_language_combo)
        self._update_language_combo_display_font(self.right_language_combo)
        self.refresh_tab_title()
        self._maybe_upgrade_word_lookup_text_edits()
        if run_translate:
            self.translate()

    def finish_session_restore(self) -> None:
        """语言包与语音控件就绪后，刷新设备下拉并套用已保存的语言码。"""
        self.apply_restored_language_codes()
        host = self._host
        if host is not None and not getattr(host, "_languages_lightweight", False):
            try:
                import startup_warmup as sw

                sw.schedule_from_tab(self)
            except Exception:
                self._warmup_current_language_pair()
        elif host is not None and getattr(host, "_languages_lightweight", False):
            self.right_textEdit.setPlaceholderText(
                "翻译引擎仍在加载，首次翻译可能需等待数秒…"
            )
        if self._speech_input_combo is not None:
            sm = None
            from argostranslategui.gui import _import_offline_speech_module

            sm = _import_offline_speech_module()
            if sm is not None:
                self._refresh_speech_audio_combos(sm)
        self.refresh_tab_title()
        self._update_char_counts()

    def _deferred_init_speech_controls(self) -> None:
        self._init_speech_controls()

    def _toggle_speech_settings_panel(self) -> None:
        panel = self._speech_settings_panel
        btn = self._btn_speech_settings
        if panel is None or btn is None:
            return
        show = not panel.isVisible()
        panel.setVisible(show)
        btn.setText("收起设置" if show else "声音设置")

    def _init_speech_controls(self) -> None:
        if self._speech_settings_panel is not None:
            return
        from argostranslategui.gui import _import_offline_speech_module

        sm = _import_offline_speech_module()
        if self._host._portable_root is None or sm is None:
            return
        self._btn_offline_speech = QPushButton("语音开始")
        self._btn_offline_speech.setObjectName("TextAction")
        self._btn_offline_speech.setToolTip(getattr(sm, "BUTTON_TOOLTIP", ""))
        self._btn_offline_speech.clicked.connect(self._toggle_offline_speech_session)
        self._btn_speech_settings = QPushButton("声音设置")
        self._btn_speech_settings.setObjectName("TextAction")
        self._btn_speech_settings.setToolTip(
            "展开/收起：麦克风输入、播放输出、声道与刷新设备"
        )
        self._btn_speech_settings.clicked.connect(self._toggle_speech_settings_panel)
        self._speech_input_combo = QComboBox()
        self._speech_input_combo.setMinimumWidth(180)
        self._speech_output_combo = QComboBox()
        self._speech_output_combo.setMinimumWidth(180)
        self._speech_channels_combo = QComboBox()
        self._speech_channels_combo.addItem("立体声", 2)
        self._speech_channels_combo.addItem("单声道", 1)
        btn_refresh = QPushButton("刷新设备")
        btn_refresh.setObjectName("TextAction")
        btn_refresh.clicked.connect(partial(self._refresh_speech_audio_combos, sm))
        for combo in (
            self._speech_input_combo,
            self._speech_output_combo,
            self._speech_channels_combo,
        ):
            combo.currentIndexChanged.connect(self._on_speech_audio_changed)
        self._speech_settings_panel = QWidget()
        self._speech_settings_panel.setObjectName("SpeechSettingsPanel")
        panel_l = QVBoxLayout(self._speech_settings_panel)
        panel_l.setContentsMargins(8, 8, 8, 8)
        panel_l.setSpacing(6)
        row_in = QHBoxLayout()
        row_in.addWidget(QLabel("输入"))
        row_in.addWidget(self._speech_input_combo, 1)
        row_out = QHBoxLayout()
        row_out.addWidget(QLabel("输出"))
        row_out.addWidget(self._speech_output_combo, 1)
        row_ch = QHBoxLayout()
        row_ch.addWidget(QLabel("声道"))
        row_ch.addWidget(self._speech_channels_combo)
        row_ch.addWidget(btn_refresh)
        row_ch.addStretch()
        panel_l.addLayout(row_in)
        panel_l.addLayout(row_out)
        panel_l.addLayout(row_ch)
        self._speech_settings_panel.setVisible(False)
        self._speech_audio_bar = panel_l
        if self._left_col_layout is not None:
            self._left_col_layout.insertWidget(1, self._speech_settings_panel)
        if self._src_footer_layout is not None:
            self._src_footer_layout.insertWidget(1, self._btn_speech_settings)
            self._src_footer_layout.insertWidget(2, self._btn_offline_speech)
        for combo in (self._speech_input_combo, self._speech_output_combo):
            combo.blockSignals(True)
            combo.addItem("（正在加载设备…）", {"index": None, "name": ""})
            combo.blockSignals(False)
        QTimer.singleShot(80, partial(self._refresh_speech_audio_combos, sm))
        if self._restore_left_code or self._restore_right_code or self._speech_prefs:
            QTimer.singleShot(200, self.finish_session_restore)

    def _lang_pair_needs_word_lookup(self) -> bool:
        for combo in (self.left_language_combo, self.right_language_combo):
            lang = self._language_at_combo_index(combo.currentIndex())
            if lang is None:
                continue
            code = (getattr(lang, "code", "") or "").strip().lower()
            if code in ("ru", "uk"):
                return True
        return False

    def _word_lookup_text_edits_ready(self) -> bool:
        return (
            self.left_textEdit.__class__.__name__ == "ClickableTranslationTextEdit"
            and self.right_textEdit.__class__.__name__ == "ClickableTranslationTextEdit"
        )

    def _replace_text_edit_with_clickable(
        self, attr: str, *, role: str, wi_mod
    ) -> None:
        old = getattr(self, attr)
        if old.__class__.__name__ == "ClickableTranslationTextEdit":
            return
        new = wi_mod.ClickableTranslationTextEdit(self, role=role)
        new.setPlainText(old.toPlainText())
        new.setPlaceholderText(old.placeholderText())
        new.setMinimumHeight(old.minimumHeight())
        if attr == "left_textEdit":
            new.textChanged.connect(self._update_char_counts)
            new.textChanged.connect(self._schedule_translate_debounce)
        else:
            new.textChanged.connect(self._update_char_counts)
        parent = old.parentWidget()
        if parent is not None and parent.layout() is not None:
            lay = parent.layout()
            for i in range(lay.count()):
                item = lay.itemAt(i)
                if item is not None and item.widget() is old:
                    lay.replaceWidget(old, new)
                    break
        old.deleteLater()
        setattr(self, attr, new)

    def _upgrade_word_lookup_text_edits(self) -> None:
        from argostranslategui.gui import _import_word_info_module

        wi_mod = _import_word_info_module()
        if wi_mod is None:
            return
        self._replace_text_edit_with_clickable(
            "left_textEdit", role="source", wi_mod=wi_mod
        )
        self._replace_text_edit_with_clickable(
            "right_textEdit", role="target", wi_mod=wi_mod
        )
        if self._word_lookup_panel is None and hasattr(wi_mod, "WordLookupPanel"):
            self._attach_word_lookup_panel(wi_mod.WordLookupPanel(self))

    def _upgrade_right_text_edit_word_info(self) -> None:
        """兼容旧调用：升级为原文+译文均可点击查词。"""
        self._upgrade_word_lookup_text_edits()

    def _maybe_upgrade_word_lookup_text_edits(self) -> None:
        if self._word_lookup_text_edits_ready():
            self._word_lookup_upgraded = True
            return
        if not self._lang_pair_needs_word_lookup():
            return
        self._upgrade_word_lookup_text_edits()
        self._word_lookup_upgraded = True

    def _update_char_counts(self) -> None:
        self._src_count_label.setText(f"{len(self.left_textEdit.toPlainText())} 字符")
        self._tgt_count_label.setText(f"{len(self.right_textEdit.toPlainText())} 字符")

    def _clear_source_text(self) -> None:
        self._snapshot_translation_history_if_voice_session()
        self.left_textEdit.blockSignals(True)
        self.left_textEdit.setPlainText("")
        self.left_textEdit.blockSignals(False)
        self._update_char_counts()
        self.translate()

    def _clear_target_text(self) -> None:
        self.right_textEdit.blockSignals(True)
        self.right_textEdit.setPlainText("")
        self.right_textEdit.blockSignals(False)
        self._update_char_counts()

    def _cancel_pending_translation(self) -> None:
        """原文已空或需重置时：停止去抖定时器并丢弃排队/进行中的译稿回写。"""
        self._translate_debounce.stop()
        self.worker_thread = None
        self.queued_translation = None

    def _copy_target_text(self) -> None:
        from PyQt5.QtWidgets import QApplication

        QApplication.clipboard().setText(self.right_textEdit.toPlainText())

    def swap_languages_button_clicked(self) -> None:
        self._pulse_swap_button()
        li = self.left_language_combo.currentIndex()
        self.left_language_combo.setCurrentIndex(self.right_language_combo.currentIndex())
        self.right_language_combo.setCurrentIndex(li)
        self._update_language_combo_display_font(self.left_language_combo)
        self._update_language_combo_display_font(self.right_language_combo)
        self.refresh_tab_title()

    def _app_window_title(self) -> str:
        try:
            from app_version import APP_NAME

            return APP_NAME
        except ImportError:
            return "本地翻译器（俄乌）"

    def _translation_model_loading_pending(
        self, translation, host: "GUIWindow | None"
    ) -> bool:
        """翻译路由尚未就绪，需要等待语言包或加载 CT2 模型。"""
        try:
            import ollama_translate as ot

            if ot.use_ollama_backend():
                return False
        except ImportError:
            pass
        if translation is not None:
            return False
        if host is None:
            return False
        worker = getattr(host, "_lang_load_worker", None)
        if worker is not None and worker.isRunning():
            return True
        if getattr(host, "_languages_lightweight", False):
            return True
        return callable(getattr(host, "try_reload_full_languages", None))

    def _wait_host_language_worker(self, host: "GUIWindow") -> None:
        worker = getattr(host, "_lang_load_worker", None)
        if worker is None or not worker.isRunning():
            return
        while worker.isRunning():
            QApplication.processEvents(QEventLoop.AllEvents, 80)
            worker.wait(100)

    def _show_model_loading_dialog(self, work) -> Any:
        """模态提示「正在加载翻译模型」，避免译文区误显示「正在翻译…」。"""
        dlg = QProgressDialog(
            "正在加载翻译模型，请稍候…\n\n"
            "首次启动或语言包较大时可能需要十几秒，完成后将自动开始翻译。",
            None,
            0,
            0,
            self,
        )
        dlg.setWindowTitle(self._app_window_title())
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setAutoClose(True)
        dlg.setAutoReset(True)
        dlg.setMinimumWidth(360)
        dlg.show()
        QApplication.processEvents(QEventLoop.AllEvents, 50)
        try:
            return work()
        finally:
            dlg.close()
            QApplication.processEvents(QEventLoop.AllEvents, 30)

    def _ensure_translation_engine_ready(
        self,
        input_language,
        output_language,
    ):
        """必要时弹窗加载模型；返回 (input_language, output_language, translation)。"""
        try:
            import ollama_translate as ot

            if ot.use_ollama_backend():
                if input_language is None or output_language is None:
                    return input_language, output_language, None
                return (
                    input_language,
                    output_language,
                    _resolve_translation(
                        input_language, output_language, self.languages
                    ),
                )
        except ImportError:
            pass
        host = self._host
        translation = _resolve_translation(
            input_language, output_language, self.languages
        )
        if not self._translation_model_loading_pending(translation, host):
            return input_language, output_language, translation
        if host is None:
            return input_language, output_language, translation

        def _load() -> None:
            self._wait_host_language_worker(host)
            reload_fn = getattr(host, "try_reload_full_languages", None)
            if not callable(reload_fn):
                return
            if getattr(host, "_languages_lightweight", False):
                reload_fn()
                return
            li = self.left_language_combo.currentIndex()
            ri = self.right_language_combo.currentIndex()
            L = self._language_at_combo_index(li)
            R = self._language_at_combo_index(ri)
            if L is not None and R is not None and L.get_translation(R) is None:
                reload_fn()

        self._show_model_loading_dialog(_load)
        input_language = self._language_at_combo_index(
            self.left_language_combo.currentIndex()
        )
        output_language = self._language_at_combo_index(
            self.right_language_combo.currentIndex()
        )
        if input_language is None or output_language is None:
            return input_language, output_language, None
        translation = _resolve_translation(
            input_language, output_language, self.languages
        )
        return input_language, output_language, translation

    def _pulse_swap_button(self) -> None:
        btn = self.language_swap_button
        eff = QGraphicsOpacityEffect(btn)
        btn.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(1.0)
        anim.setKeyValueAt(0.45, 0.55)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.start(QAbstractAnimation.DeleteWhenStopped)

    def translate(self) -> None:
        from argostranslategui.gui import (
            TranslationThread,
            _get_terminology_bridge,
            _import_bulk_text_module,
            _import_translation_quality_module,
            _is_zh_family_source,
        )
        from argostranslate.utils import error

        if len(self.languages) < 1:
            return
        input_text_raw = self.left_textEdit.toPlainText()
        if not (input_text_raw or "").strip():
            self._cancel_pending_translation()
            self._clear_target_text()
            return
        input_language = self._language_at_combo_index(
            self.left_language_combo.currentIndex()
        )
        output_language = self._language_at_combo_index(
            self.right_language_combo.currentIndex()
        )
        tb = _get_terminology_bridge()
        try:
            import ollama_translate as ot

            use_llm = ot.use_ollama_backend()
        except ImportError:
            use_llm = False
        tq = _import_translation_quality_module()
        if tq is not None and hasattr(tq, "sanitize_source_text"):
            input_text_raw = tq.sanitize_source_text(
                input_text_raw, for_llm=use_llm
            )
        zh_family = (
            tb.is_chinese_source_language(input_language.code)
            if tb is not None and hasattr(tb, "is_chinese_source_language")
            else _is_zh_family_source(input_language.code)
        )
        tgt_code = (output_language.code or "").strip().lower()
        if zh_family:
            if tq is not None:
                if use_llm:
                    input_text_raw = tq.normalize_zh_for_mt(input_text_raw)
                elif tgt_code in ("ru", "uk") and hasattr(
                    tq, "prepare_zh_for_cyrillic_target"
                ):
                    input_text_raw = tq.prepare_zh_for_cyrillic_target(
                        input_text_raw, tgt_code
                    )
                else:
                    input_text_raw = tq.normalize_zh_for_mt(input_text_raw)
            bm = _import_bulk_text_module()
            if bm is not None:
                input_text_raw = bm.prepare_long_translation_input(
                    input_text_raw, for_llm=use_llm
                )
        elif use_llm:
            bm = _import_bulk_text_module()
            if bm is not None:
                input_text_raw = bm.prepare_long_translation_input(
                    input_text_raw, for_llm=True
                )
        input_language, output_language, translation = (
            self._ensure_translation_engine_ready(
                input_language, output_language
            )
        )
        try:
            import argos_inference_tuning as ait

            ait.apply_for_input(input_text_raw)
        except Exception:
            pass
        if not translation:
            try:
                import ollama_translate as ot

                if ot.use_ollama_backend():
                    hint = ot.ollama_error_hint()
                    hint += "\n\n请点击顶部「下载引擎」或菜单「下载翻译引擎…」完成安装。"
                    self.update_right_textEdit(hint)
                    error("Ollama 翻译引擎未就绪。")
                    return
            except ImportError:
                pass
            lw = getattr(self._host, "_languages_lightweight", False)
            err = getattr(self._host, "_lang_load_full_error", "") or ""
            if lw:
                self.update_right_textEdit(
                    "翻译引擎未就绪，无法翻译。\n"
                    "请完全退出程序（结束 pythonw.exe）后重新运行 run_gui.bat。"
                )
                handle = getattr(self._host, "_handle_torch_engine_failure", None)
                if callable(handle) and err:
                    QTimer.singleShot(0, lambda: handle(err, from_retry=True))
            else:
                hint = "[当前语言对没有可用的翻译模型]"
                if err:
                    hint += "\n\n（翻译引擎报错，请见弹窗说明。）"
                self.update_right_textEdit(hint)
                handle = getattr(self._host, "_handle_torch_engine_failure", None)
                if callable(handle) and err:
                    QTimer.singleShot(0, lambda: handle(err))
            error("当前语言对没有可用的翻译模型。")
            return
        use_glossary = (
            tb is not None
            and hasattr(tb, "should_apply_glossary")
            and tb.should_apply_glossary(
                input_language.code, output_language.code
            )
        )
        progress_slot: list = []

        if use_glossary:

            def bound() -> str:
                cb = progress_slot[0] if progress_slot else None
                return tb.apply_glossary(
                    translation,
                    input_text_raw,
                    input_language.code,
                    output_language.code,
                    on_progress=cb,
                )

        else:
            prep = input_text_raw
            if tb is not None:
                prep = tb.prepare_engine_input(input_text_raw)
            else:
                bm = _import_bulk_text_module()
                if bm is not None:
                    prep = bm.prepare_long_translation_input(
                        input_text_raw, for_llm=use_llm
                    )
            if use_llm:

                def bound() -> str:
                    cb = progress_slot[0] if progress_slot else None
                    if cb is not None:
                        return translation.translate(prep, on_progress=cb)
                    return translation.translate(prep)

            else:
                bound = partial(translation.translate, prep)
        self._show_translating_status("正在翻译…")
        new_worker = TranslationThread(bound, True)
        if use_llm:
            progress_slot.append(new_worker.send_text_update.emit)
        new_worker.send_text_update.connect(self.update_right_textEdit)
        new_worker.finished.connect(self.handle_worker_thread_finished)
        if self.worker_thread is None:
            self.worker_thread = new_worker
            self.worker_thread.start()
        else:
            self.queued_translation = new_worker

    def _show_translating_status(self, message: str = "正在翻译…") -> None:
        """译文区立即显示状态，避免长文本或排队时长时间无反馈。"""
        msg = (message or "正在翻译…").strip() or "正在翻译…"
        self.right_textEdit.blockSignals(True)
        self.right_textEdit.setPlainText(msg)
        self.right_textEdit.blockSignals(False)
        self._update_char_counts()

    def update_right_textEdit(self, text: str) -> None:
        from argostranslategui.gui import _import_translation_quality_module

        if not (self.left_textEdit.toPlainText() or "").strip():
            return
        t = text or ""
        tq = _import_translation_quality_module()
        try:
            import ollama_translate as ot

            if ot.use_ollama_backend() and tq is not None and hasattr(
                tq, "sanitize_llm_translation_output"
            ):
                t = tq.sanitize_llm_translation_output(t)
        except ImportError:
            pass
        if tq is not None:
            R = self._language_at_combo_index(self.right_language_combo.currentIndex())
            if R is not None:
                code = (R.code or "").strip().lower()
                if code in ("ru", "uk"):
                    L = self._language_at_combo_index(
                        self.left_language_combo.currentIndex()
                    )
                    src_code = (L.code or "").strip().lower() if L else ""
                    src_plain = self.left_textEdit.toPlainText() or ""
                    if hasattr(tq, "postprocess_translation_target"):
                        t = tq.postprocess_translation_target(
                            t, code, source_text=src_plain, source_lang_code=src_code
                        )
                    else:
                        t = tq.touchup_cyrillic_target_spacing(t)
        self.right_textEdit.setPlainText(t)
        self._update_char_counts()
        self._maybe_show_uk_morph_install_notice()

    def _maybe_show_uk_morph_install_notice(self) -> None:
        """术语乌语变格缺词典时，在主线程弹出一次性安装说明。"""
        try:
            import glossary_inflection as gi
        except ImportError:
            return
        msg = gi.consume_uk_morph_install_notice()
        if not msg:
            return
        QMessageBox.information(
            self,
            "乌克兰语变格词典",
            msg,
        )

    def handle_worker_thread_finished(self) -> None:
        self.worker_thread = None
        self._maybe_show_uk_morph_install_notice()
        if self.queued_translation is not None:
            self.worker_thread = self.queued_translation
            self.worker_thread.start()
            self.queued_translation = None

    def _speech_combo_device_data(self, combo: QComboBox) -> tuple[Any, str]:
        raw = combo.currentData()
        if isinstance(raw, dict):
            return raw.get("index"), str(raw.get("name") or "")
        return raw, combo.currentText() if combo.currentIndex() >= 0 else ""

    def _get_speech_audio_prefs(self) -> dict[str, Any]:
        if self._speech_input_combo is None:
            return copy.deepcopy(self._speech_prefs)
        ch = self._speech_channels_combo.currentData()
        inp_idx, inp_name = self._speech_combo_device_data(self._speech_input_combo)
        out_idx, out_name = self._speech_combo_device_data(self._speech_output_combo)
        return {
            "input_device": inp_idx,
            "output_device": out_idx,
            "input_device_name": inp_name,
            "output_device_name": out_name,
            "channels": 2 if int(ch or 1) >= 2 else 1,
        }

    def _on_speech_audio_changed(self, _index: int = 0) -> None:
        self._speech_prefs = self._get_speech_audio_prefs()

    def _refresh_speech_audio_combos(self, sm=None) -> None:
        if sm is None:
            from argostranslategui.gui import _import_offline_speech_module

            sm = _import_offline_speech_module()
        if sm is None or self._speech_input_combo is None:
            return
        prefs = self._speech_prefs
        inputs, outputs = sm.list_audio_devices()

        def _fill(combo: QComboBox, items: list, idx_key: str, name_key: str) -> None:
            combo.blockSignals(True)
            combo.clear()
            want_name = str(prefs.get(name_key) or "").strip()
            want_idx = prefs.get(idx_key)
            pick = 0
            for i, it in enumerate(items):
                payload = {
                    "index": it["index"],
                    "name": it.get("name") or it.get("label") or "",
                }
                combo.addItem(it["label"], payload)
                if want_name and (
                    payload["name"] == want_name or it.get("label") == want_name
                ):
                    pick = i
                elif want_idx is not None and it["index"] == want_idx:
                    pick = i
            combo.setCurrentIndex(pick)
            combo.blockSignals(False)

        _fill(self._speech_input_combo, inputs, "input_device", "input_device_name")
        _fill(self._speech_output_combo, outputs, "output_device", "output_device_name")
        self._speech_channels_combo.blockSignals(True)
        ch = 2 if int(prefs.get("channels") or 1) >= 2 else 1
        self._speech_channels_combo.setCurrentIndex(0 if ch >= 2 else 1)
        self._speech_channels_combo.blockSignals(False)
        self._speech_prefs = self._get_speech_audio_prefs()

    def _stop_speech_worker(self, wait_ms: int = 5000) -> None:
        w = self._offline_speech_worker
        if w is not None and w.isRunning():
            w.request_stop()
            w.wait(wait_ms)
        self._offline_speech_worker = None
        if self._btn_offline_speech is not None:
            self._btn_offline_speech.setText("语音开始")

    def _begin_offline_speech_session(self, code: str) -> None:
        from argostranslategui.gui import _import_offline_speech_module

        sm = _import_offline_speech_module()
        if sm is None or self._btn_offline_speech is None:
            return
        self._host._pause_other_tabs_speech(self)
        prefs = self._get_speech_audio_prefs()
        self._speech_prefs = dict(prefs)
        mic_err = sm.check_microphone_available(prefs)
        if mic_err:
            QMessageBox.warning(self, "离线语音", mic_err)
            return
        if not self._host._offline_speech_intro_shown:
            QMessageBox.information(
                self,
                "离线语音",
                "每个标签页可使用不同的输入/输出设备，互不干扰。\n"
                "切换标签时，其他页的语音会自动暂停；回到该标签可点「语音继续」。\n\n"
                "点「确定」后边说边识别、边翻译（类似谷歌翻译，本机完成）。\n"
                "· 左侧灰色部分为正在说的内容，句末会固定下来；\n"
                "· 右侧随识别自动更新译文（俄语/乌克兰语/中文）。",
            )
            self._host._offline_speech_intro_shown = True
        self._speech_committed = self.left_textEdit.toPlainText().strip()
        self._speech_live_partial = ""
        self._stop_speech_worker(wait_ms=2000)
        worker_cls = getattr(
            sm, "StreamingOfflineSpeechSessionWorker", sm.OfflineSpeechSessionWorker
        )
        self._offline_speech_worker = worker_cls(code, prefs)
        if hasattr(self._offline_speech_worker, "partial_text"):
            self._offline_speech_worker.partial_text.connect(
                self._on_offline_speech_partial
            )
        if hasattr(self._offline_speech_worker, "final_text"):
            self._offline_speech_worker.final_text.connect(self._on_offline_speech_final)
        elif hasattr(self._offline_speech_worker, "result_text"):
            self._offline_speech_worker.result_text.connect(self._on_offline_speech_final)
        self._offline_speech_worker.error_msg.connect(self._on_offline_speech_error)
        self._offline_speech_worker.status_msg.connect(self._on_offline_speech_status)
        self._offline_speech_worker.finished.connect(self._on_offline_speech_worker_finished)
        self._update_speech_source_display()
        self._btn_offline_speech.setText("正在启动…")
        self._offline_speech_worker.resume_recording()
        self._offline_speech_worker.start()
        self._speech_was_paused_by_tab_switch = False

    def _toggle_offline_speech_session(self) -> None:
        from argostranslategui.gui import _import_offline_speech_module

        sm = _import_offline_speech_module()
        if sm is None or self._btn_offline_speech is None:
            return
        idx = self.left_language_combo.currentIndex()
        lang = self._language_at_combo_index(idx)
        if lang is None:
            QMessageBox.warning(self, "离线语音", "请先选择源语言。")
            return
        code = (lang.code or "zh").strip().lower()
        w = self._offline_speech_worker
        if w is not None and w.isRunning():
            if w.is_recording_allowed():
                w.pause_recording()
                self._btn_offline_speech.setText("语音继续")
            else:
                self._host._pause_other_tabs_speech(self)
                w.resume_recording()
                self._btn_offline_speech.setText("语音暂停")
            return
        if not sm.is_model_installed(code):
            r = QMessageBox.question(
                self,
                "离线语音",
                sm.describe_setup(code) + "\n\n是否现在自动下载？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if r != QMessageBox.Yes:
                return
            self._start_vosk_model_download(code)
            return
        self._begin_offline_speech_session(code)

    def _start_vosk_model_download(self, code: str) -> None:
        from argostranslategui.gui import _import_offline_speech_module

        sm = _import_offline_speech_module()
        if sm is None:
            return
        if self._vosk_download_worker is not None and self._vosk_download_worker.isRunning():
            QMessageBox.information(self, "离线语音", "模型正在下载，请稍候。")
            return
        self._vosk_download_pending_lang = code
        if self._btn_offline_speech is not None:
            self._btn_offline_speech.setEnabled(False)
            self._btn_offline_speech.setText("下载模型…")
        self._vosk_download_worker = sm.VoskModelDownloadWorker(code)
        self._vosk_download_worker.progress.connect(self._on_vosk_download_progress)
        self._vosk_download_worker.finished_ok.connect(self._on_vosk_download_ok)
        self._vosk_download_worker.failed.connect(self._on_vosk_download_failed)
        self._vosk_download_worker.finished.connect(self._on_vosk_download_thread_finished)
        self._vosk_download_worker.start()

    def _on_vosk_download_progress(self, msg: str) -> None:
        if self._btn_offline_speech is not None and (msg or "").strip():
            t = (msg or "").strip()
            self._btn_offline_speech.setText(t[:24] + ("…" if len(t) > 24 else ""))

    def _on_vosk_download_ok(self) -> None:
        code = self._vosk_download_pending_lang or "zh"
        self._begin_offline_speech_session(code)

    def _on_vosk_download_failed(self, msg: str) -> None:
        QMessageBox.warning(self, "离线语音", msg or "模型下载失败")

    def _on_vosk_download_thread_finished(self) -> None:
        self._vosk_download_worker = None
        self._vosk_download_pending_lang = None
        if self._btn_offline_speech is not None:
            self._btn_offline_speech.setEnabled(True)
            w = self._offline_speech_worker
            if w is not None and w.isRunning():
                self._btn_offline_speech.setText(
                    "语音暂停" if w.is_recording_allowed() else "语音继续"
                )
            else:
                self._btn_offline_speech.setText("语音开始")

    def _on_offline_speech_worker_finished(self) -> None:
        if self._speech_live_partial:
            t = self._speech_live_partial.strip()
            if t:
                if self._speech_committed:
                    self._speech_committed = self._speech_committed + "\n" + t
                else:
                    self._speech_committed = t
            self._speech_live_partial = ""
            self._update_speech_source_display()
            self._schedule_speech_translate()
        if self._btn_offline_speech is not None:
            self._btn_offline_speech.setText("语音开始")
        self._offline_speech_worker = None

    def _on_offline_speech_status(self, msg: str) -> None:
        if self._btn_offline_speech is None:
            return
        w = self._offline_speech_worker
        if w is None or not w.isRunning():
            return
        t = (msg or "").strip()
        if not t:
            return
        if t == "语音暂停" and w.is_recording_allowed():
            self._btn_offline_speech.setText("语音暂停")
            return
        self._btn_offline_speech.setText(t[:22] + ("…" if len(t) > 22 else ""))

    def _compose_speech_source_text(self) -> str:
        if self._speech_committed and self._speech_live_partial:
            return self._speech_committed + " " + self._speech_live_partial
        if self._speech_committed:
            return self._speech_committed
        return self._speech_live_partial

    def _update_speech_source_display(self) -> None:
        text = self._compose_speech_source_text()
        self.left_textEdit.blockSignals(True)
        self.left_textEdit.setPlainText(text)
        self.left_textEdit.blockSignals(False)
        self._update_char_counts()

    def _schedule_speech_translate(self) -> None:
        if self._offline_speech_worker is None or not self._offline_speech_worker.isRunning():
            return
        self._speech_translate_debounce.start()

    def _translate_after_speech_update(self) -> None:
        plain = self._compose_speech_source_text()
        if not plain.strip():
            return
        self.translate()

    def _on_offline_speech_partial(self, partial: str) -> None:
        self._speech_live_partial = (partial or "").strip()
        self._update_speech_source_display()
        self._schedule_speech_translate()

    def _on_offline_speech_final(self, text: str) -> None:
        t = (text or "").strip()
        if t:
            if self._speech_committed:
                self._speech_committed = self._speech_committed + "\n" + t
            else:
                self._speech_committed = t
        self._speech_live_partial = ""
        self._update_speech_source_display()
        self._schedule_speech_translate()

    def _on_offline_speech_done(self, text: str) -> None:
        self._on_offline_speech_final(text)

    def _on_offline_speech_error(self, msg: str) -> None:
        QMessageBox.warning(self, "离线语音", msg)

    def _current_translation_lang_meta(self) -> tuple[str, str, str, str]:
        from argostranslategui.gui import _lang_combo_label_zh

        li = self.left_language_combo.currentIndex()
        ri = self.right_language_combo.currentIndex()
        L = self._language_at_combo_index(li)
        R = self._language_at_combo_index(ri)
        if L is None or R is None:
            return "", "", "", ""
        return (
            (getattr(L, "code", None) or "").strip(),
            (getattr(R, "code", None) or "").strip(),
            _lang_combo_label_zh(L),
            _lang_combo_label_zh(R),
        )

    def _snapshot_translation_history_if_voice_session(self) -> None:
        w = self._offline_speech_worker
        if w is None or not w.isRunning():
            return
        src = self.left_textEdit.toPlainText()
        tgt = self.right_textEdit.toPlainText()
        if not src.strip() and not tgt.strip():
            return
        from argostranslategui.gui import _import_translation_history_module

        mod = _import_translation_history_module()
        if mod is None:
            return
        code_l, code_r, lab_l, lab_r = self._current_translation_lang_meta()
        try:
            mod.append_record(src, tgt, code_l, code_r, lab_l, lab_r)
        except OSError:
            pass
