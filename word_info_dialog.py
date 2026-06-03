"""
译文区点击西里尔词：在窗口右侧「查词」面板显示（不再使用弹窗）。
- 俄语：默认「单词解析」为三卡竖排；「句中词形分析」行首为 24×24 抗锯齿 PNG 图标（#0d6efd 描边），
  内嵌 data URI；源文件由 `python tools/generate_lookup_icons.py` 从矢量示意生成并写入 `lookup_icon_data.py`。
  环境变量 ARGOS_WORD_LOOKUP_VERBOSE=1 为长版。
- 乌克兰语：uk→ru 后查 bkrs.info 中文义项；变位表用 goroh.pp.ua（维基作备用）。
"""
from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path
from typing import Any

_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from PyQt5.QtCore import QEvent, QPoint, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import bkrs_parser as bp
import glossary_manager as gm
import word_lookup_store as wls
import inflection_display as idisp
import lookup_icon_data as _lk_ico_data
import terminology_bridge as tb
import wiktionary_parser as wp


def _lk_anal_icon_html(icon_key: str) -> str:
    """句中词形分析行首图标：24×24 PNG（Lucide 风格描边），内嵌 data URI 供 QTextBrowser 显示。"""
    b64 = _lk_ico_data._LK_ICO_PNG_B64.get(icon_key) or _lk_ico_data._LK_ICO_PNG_B64[
        "tag"
    ]
    uri = f"data:image/png;base64,{b64}"
    esc = html.escape(uri, quote=True)
    return (
        f'<span class="lk-ico"><img width="20" height="20" alt="" src="{esc}"/></span>'
    )


class _FetchThread(QThread):
    done = pyqtSignal(dict)

    def __init__(self, word: str, serial: int):
        super().__init__()
        self._word = word
        self._serial = serial

    def run(self):
        try:
            data = wp.get_russian_inflections(self._word)
        except Exception as e:
            data = {"source": "error", "error": str(e), "forms": []}
        try:
            bk = bp.lookup_russian_word(self._word)
            data["bkrs_lines"] = list(bk.get("definition_lines") or [])
            data["bkrs_lemma"] = bk.get("lemma") or ""
            if bk.get("error") and not data["bkrs_lines"]:
                data["bkrs_error"] = bk.get("error")
        except Exception as e:
            data["bkrs_lines"] = []
            data["bkrs_error"] = str(e)
        try:
            wp.merge_display_lemma_stress(data)
        except Exception:
            pass
        try:
            wp.merge_ru_wiki_grammar(data)
        except Exception:
            pass
        self.done.emit(data)


class _FetchThreadUk(QThread):
    done = pyqtSignal(dict)

    def __init__(self, word: str, serial: int):
        super().__init__()
        self._word = word
        self._serial = serial

    def run(self):
        try:
            data = wp.get_ukrainian_inflections(self._word)
        except Exception as e:
            data = {"source": "error", "error": str(e), "forms": []}
        if not data.get("bkrs_lines"):
            lem_ru = (
                str(data.get("lemma_ru") or data.get("bkrs_lemma") or "")
                .strip()
            )
            ru_q = str(data.get("ru_lookup_word") or "").strip()
            for ru_try in (lem_ru, ru_q):
                if not ru_try:
                    continue
                try:
                    bk = bp.lookup_russian_word(ru_try)
                    lines = list(bk.get("definition_lines") or [])
                    if lines:
                        data["bkrs_lines"] = lines
                        data["bkrs_lemma"] = (bk.get("lemma") or ru_try).strip()
                        data["bkrs_url"] = bk.get("bkrs_url") or data.get("bkrs_url") or ""
                        data["lemma_ru"] = data["bkrs_lemma"]
                        data["bkrs_error"] = None
                        break
                except Exception:
                    pass
        self.done.emit(data)


def _lookup_compact() -> bool:
    """默认简洁版面；环境变量 ARGOS_WORD_LOOKUP_VERBOSE=1 恢复详细（多义项、维基表格等）。"""
    v = os.environ.get("ARGOS_WORD_LOOKUP_VERBOSE", "").strip().lower()
    return v not in ("1", "true", "yes", "on")


def _lookup_verbose() -> bool:
    return not _lookup_compact()


_LOOKUP_DOC_STYLE = (
    "font-size:15px;line-height:1.55;"
    "font-family:'Segoe UI','Microsoft YaHei UI','Microsoft YaHei',sans-serif;"
    "color:#222;"
)


def _wrap_lookup_html(inner: str, *, compact: bool | None = None) -> str:
    """查词面板 QTextBrowser 内统一基础字号与标题间距。"""
    if compact is None:
        compact = _lookup_compact()
    inner = (inner or "").strip() or "<p></p>"
    extra = ""
    if compact:
        # 对齐参照截图（Bootstrap 系色板）：#f5f6f7 页底、#0056b3 标题、#28a745 角标、#eeeeee 分隔线
        extra = (
            ".lk-page{margin:0;padding:14px 12px 28px;background:#f5f6f7;"
            "font-family:Inter,'Segoe UI','Microsoft YaHei UI','Microsoft YaHei',system-ui,sans-serif;}"
            ".lk-card{background:#fff;border:none;border-radius:10px;"
            "box-shadow:0 2px 4px rgba(0,0,0,.075);"
            "padding:20px 22px;margin:0 0 16px;}"
            ".lk-card-wiki{margin-bottom:10px;}"
            ".lk-head-card{padding:22px 22px 20px;}"
            ".lk-word-big{font-size:34px;font-weight:700;color:#0056b3;margin:0;padding:0;line-height:1.12;"
            "letter-spacing:-0.02em;}"
            ".lk-ipa{font-size:15px;color:#6c757d;margin:6px 0 0;padding:0;line-height:1.45;}"
            ".lk-dict-table{width:100%;margin-top:20px;border-collapse:collapse;table-layout:fixed;}"
            ".lk-dict-cell{font-size:15px;color:#212529;vertical-align:middle;line-height:1.45;}"
            ".lk-dict-lab{color:#212529;font-weight:500;}"
            ".lk-zh-head{font-size:16px;line-height:1.55;color:#1a1a1a;margin:16px 0 0;padding:0;font-weight:600;}"
            ".lk-zh-head .lk-dict-lab{font-weight:600;color:#495057;margin-right:6px;}"
            ".lk-zh-head-muted{font-size:14px;line-height:1.5;color:#78909c;margin:14px 0 0;font-weight:400;}"
            ".lk-badge-cell{text-align:right;vertical-align:middle;white-space:nowrap;padding:0 0 0 14px;}"
            ".lk-lemma-a{color:#212529;font-weight:600;text-decoration:underline;text-underline-offset:3px;}"
            ".lk-badge{display:inline-block;padding:7px 14px;border-radius:999px;font-size:12px;"
            "font-weight:600;vertical-align:middle;line-height:1;letter-spacing:0.02em;}"
            ".lk-badge-ok{background:#28a745;border:none;color:#fff;}"
            ".lk-badge-miss{background:#f1f3f5;border:1px solid #adb5bd;color:#495057;"
            "font-weight:600;}"
            ".lk-badge-ok-ic{display:inline-block;width:16px;height:16px;line-height:14px;text-align:center;"
            "border-radius:50%;border:1.5px solid rgba(255,255,255,.9);font-size:11px;font-weight:700;"
            "margin-right:8px;vertical-align:middle;color:#fff;}"
            ".lk-pill-card{padding:14px 18px;}"
            "table.lk-pill-bar{border:none;border-collapse:separate;width:auto!important;max-width:100%!important;"
            "table-layout:auto!important;}"
            ".lk-anal-title{font-size:16px;font-weight:700;color:#212529;margin:0 0 12px;letter-spacing:0.02em;}"
            "table.lk-anal{width:100%;border-collapse:collapse;font-size:15px;margin:0;table-layout:fixed;}"
            "table.lk-anal td.lk-an-row{padding:13px 0;border-bottom:1px solid #eeeeee;"
            "vertical-align:middle;line-height:1.5;}"
            "table.lk-anal tr:last-child td{border-bottom:none!important;}"
            ".lk-lab-fix{display:inline-block;min-width:5em;text-align:left;}"
            ".lk-ico{display:inline-block;width:20px;height:20px;margin-right:10px;"
            "vertical-align:middle;line-height:0;}"
            ".lk-ico img{display:block;margin:0;padding:0;border:0;}"
            ".lk-ln{color:#6c757d;font-weight:400;}"
            ".lk-v{color:#212529;font-weight:600;}"
            ".lk-an-foot{margin-top:4px;padding-top:14px;font-size:14px;color:#6c757d;line-height:1.5;}"
            ".lk-an-foot a{color:#0d6efd;text-decoration:none;font-weight:500;}"
            ".lk-an-foot a:hover{text-decoration:underline;color:#0a58ca;}"
            ".lk-info-sym{color:#0d6efd;margin-right:4px;font-size:15px;font-weight:500;}"
            ".lk-ctx-tit{margin:0 0 18px;font-size:18px;font-weight:700;color:#212529;line-height:1.25;}"
            ".lk-src-ru{font-size:16px;color:#212529;line-height:1.6;font-weight:400;margin:0;}"
            ".lk-src-zh{margin:10px 0 0;font-size:14px;color:#6c757d;line-height:1.55;font-weight:400;}"
            ".lk-ctx-anal{margin:18px 0 0;font-size:15px;color:#1a1a1a;line-height:1.6;font-weight:400;}"
            ".lk-box{background:#fafafa;border:1px solid #e6e6e6;border-radius:10px;padding:12px 14px;margin:0 0 14px;}"
            ".lk-mean{font-size:17px;line-height:1.55;color:#111;margin:6px 0 14px;font-weight:600;}"
            ".lk-more{font-size:14px;line-height:1.6;color:#444;margin:0 0 12px;padding-left:12px;border-left:3px solid #cfe0f5;}"
            ".lk-caps{font-size:12px;letter-spacing:0.06em;color:#777;margin:0 0 6px;font-weight:600;}"
            ".lk-links a{display:inline-block;margin:6px 8px 0 0;padding:8px 14px;background:#e8f1fb;border-radius:8px;"
            "color:#0d47a1;text-decoration:none;font-weight:600;font-size:14px;}"
            ".lk-links a:hover{background:#d4e8fc;}"
            ".lk-foot{font-size:12px;color:#888;margin:12px 0 0;line-height:1.5;}"
            ".lk-minimal .lk-lemma{font-size:18px;font-weight:600;color:#0056b3;margin:4px 0 14px;}"
            ".lk-minimal .lk-mean{font-size:17px;line-height:1.65;color:#212529;margin:6px 0 0;font-weight:500;}"
            ".lk-minimal .lk-mean-lines{line-height:1.75;white-space:normal;}"
            ".lk-minimal .lk-src-zh{color:#212529;font-weight:400;}"
            ".lk-page,.lk-page *{user-select:text;-webkit-user-select:text;}"
            ".lk-conj-wrap{margin:8px 0 4px;overflow-x:auto;}"
            ".lk-goroh-wrap{width:100%;margin:4px 0;overflow-x:auto;min-width:0;box-sizing:border-box;}"
            "table.lk-conj{width:100%;max-width:100%;border-collapse:collapse;"
            "font-size:14px;line-height:1.45;margin:0;background:#fff;}"
            "table.lk-conj th,table.lk-conj td{border:1px solid #8eb4d8;padding:6px 8px;"
            "vertical-align:middle;text-align:center;}"
            "table.lk-conj th.lk-conj-sec{background:#4a7eb8;color:#fff;font-weight:600;"
            "font-size:14px;padding:8px;}"
            "table.lk-conj th.lk-conj-h,table.lk-conj th.lk-conj-lab{background:#e8f0fa;"
            "color:#1a3a5c;font-weight:600;text-align:left;}"
            "table.lk-conj td.lk-conj-td{color:#212529;}"
            ".lk-conj-src{font-size:12px;color:#888;margin:8px 0 0;line-height:1.4;}"
            ".lk-conj-src a{color:#0d6efd;text-decoration:none;}"
            "span.lk-conj-zh{color:#5f6368;font-weight:400;font-size:12px;margin-left:4px;}"
            "table.lk-conj th.lk-conj-sec span.lk-conj-zh{color:#e8f4ff;font-weight:500;}"
            ".lk-conj-block+.lk-conj-block{margin-top:12px;}"
            ".lk-conj-kind{font-size:12px;color:#666;margin:10px 0 4px;font-weight:600;}"
            "tr.lk-conj-row-hl th,tr.lk-conj-row-hl td{background:#fff8e1;}"
            "td.lk-conj-cell-hl,th.lk-conj-cell-hl{background:#ffe082;font-weight:700;}"
            ".lk-ctx-gram{margin:0 0 14px;padding:12px 14px;background:#f0f7ff;border-radius:8px;"
            "border:1px solid #cfe0f5;font-size:15px;line-height:1.55;color:#1a1a1a;}"
            ".lk-ctx-gram b{color:#0d47a1;}"
            "h4{font-size:14px;margin:14px 0 6px;color:#333;}"
            "ul,ol{margin:6px 0;padding-left:1.15em;}li{margin:4px 0;}"
            "a.lk-lemma-a{color:#212529!important;}a.lk-lemma-a:hover{color:#0056b3!important;}"
        )
    return (
        f'<div style="{_LOOKUP_DOC_STYLE}">'
        "<style>"
        "h4{font-size:17px;font-weight:600;margin:16px 0 8px;}"
        "ul,ol{margin:8px 0;padding-left:1.35em;}"
        "li{margin:6px 0;line-height:1.55;}"
        "code{font-size:0.95em;}"
        "a{font-size:1em;}"
        "a.lk-lemma-a{color:#111!important;}"
        "a.lk-lemma-a:hover{color:#0052d9!important;}"
        "table{table-layout:fixed;width:100%;}"
        "td{word-wrap:break-word;vertical-align:top;}"
        f"{extra}"
        "</style>"
        f"{inner}</div>"
    )


def _cyrillic_click_letters(raw: str) -> int:
    n = 0
    for c in raw:
        if "А" <= c <= "я" or c in "Ёё":
            n += 1
        elif c in "ІіЇїЄєҐґ":
            n += 1
    return n


def _lang_code_from_combo(parent, combo_attr: str) -> str | None:
    combo = getattr(parent, combo_attr, None)
    if combo is None:
        return None
    idx = combo.currentIndex()
    if idx < 0:
        return None
    if hasattr(parent, "_language_at_combo_index"):
        lang = parent._language_at_combo_index(idx)
        if lang is not None:
            return (getattr(lang, "code", None) or "").strip().lower()
        return None
    langs = getattr(parent, "languages", None) or []
    if idx >= len(langs):
        return None
    return (langs[idx].code or "").strip().lower()


def _target_output_lang_code(parent) -> str | None:
    return _lang_code_from_combo(parent, "right_language_combo")


def _source_input_lang_code(parent) -> str | None:
    return _lang_code_from_combo(parent, "left_language_combo")


# 句界：俄语译文常见标点与换行
_SENT_SPLIT_CHARS = frozenset(
    ".!?…。；;\n\r"
)  # 不含冒号，避免时间 12:30 等被误切


def sentence_bounds(full_text: str, caret: int) -> tuple[int, int]:
    """返回包含 caret 的最小「句」切片 [start, end)（半开区间）。"""
    if not full_text:
        return 0, 0
    n = len(full_text)
    caret = max(0, min(caret, n - 1 if n else 0))
    left = caret
    while left > 0 and full_text[left - 1] not in _SENT_SPLIT_CHARS:
        left -= 1
    right = caret + 1
    while right < n and full_text[right] not in _SENT_SPLIT_CHARS:
        right += 1
    if right < n and full_text[right] in ".!?…":
        right += 1
    return left, min(right, n)


def _split_text_sentences(text: str) -> list[str]:
    if not (text or "").strip():
        return []
    t = text.replace("\r\n", "\n")
    chunks: list[str] = []
    start = 0
    n = len(t)
    i = 0
    while i < n:
        if t[i] in _SENT_SPLIT_CHARS:
            piece = t[start:i].strip()
            if piece:
                chunks.append(piece)
            start = i + 1
            while start < n and t[start] in _SENT_SPLIT_CHARS:
                start += 1
            i = start
        else:
            i += 1
    tail = t[start:].strip()
    if tail:
        chunks.append(tail)
    return chunks if chunks else [text.strip()]


def _parallel_source_zh_sentence(tab, target_sentence: str) -> str:
    """中→俄/乌时，按句对齐取左侧原文对应中文句。"""
    if tab is None:
        return ""
    try:
        left = (tab.left_textEdit.toPlainText() or "").strip()
        right = (tab.right_textEdit.toPlainText() or "").strip()
    except Exception:
        return ""
    if not left:
        return ""
    if not (target_sentence or "").strip() or not right:
        return left
    left_sents = _split_text_sentences(left)
    right_sents = _split_text_sentences(right)
    tgt = target_sentence.strip()
    for i, s in enumerate(right_sents):
        s = s.strip()
        if tgt == s or tgt in s or s in tgt:
            if i < len(left_sents):
                return left_sents[i].strip()
            break
    if len(left_sents) == 1:
        return left_sents[0].strip()
    return left


def _parallel_target_zh_sentence(tab, source_sentence: str) -> str:
    """俄/乌→中时，按句对齐取右侧译文中的对应中文句。"""
    if tab is None:
        return ""
    try:
        left = (tab.left_textEdit.toPlainText() or "").strip()
        right = (tab.right_textEdit.toPlainText() or "").strip()
    except Exception:
        return ""
    if not right:
        return ""
    if not (source_sentence or "").strip() or not left:
        return right
    left_sents = _split_text_sentences(left)
    right_sents = _split_text_sentences(right)
    src = source_sentence.strip()
    for i, s in enumerate(left_sents):
        s = s.strip()
        if src == s or src in s or s in src:
            if i < len(right_sents):
                return right_sents[i].strip()
            break
    if len(right_sents) == 1:
        return right_sents[0].strip()
    return right


_NOTEBOOK_EMPTY_MEANING_MARKERS = frozenset(
    {
        "（未查到词义）",
        "(未查到词义)",
        "未查到词义",
    }
)


def lookup_meaning_should_save_to_notebook(meaning: str) -> bool:
    """生词本仅收录查到有效词义的词条。"""
    t = re.sub(r"\s+", " ", (meaning or "").strip())
    if not t:
        return False
    if t in _NOTEBOOK_EMPTY_MEANING_MARKERS:
        return False
    if "未查到词义" in t and _cjk_meaning_char_count(t) < 2:
        return False
    return True


def _word_meaning_zh_russian(data: dict, glossary: dict, clicked: str) -> str:
    bkrs = [str(x).strip() for x in (data.get("bkrs_lines") or []) if str(x).strip()]
    if bkrs:
        return "\n".join(bkrs[:24])
    zhs = gm.glossary_zh_for_russian_click(clicked, glossary)
    if zhs:
        return idisp.to_zh_cn("、".join(zhs[:4]))
    for key in ("zh_gloss_lines", "en_gloss_lines", "es_gloss_lines"):
        for ln in data.get(key) or []:
            s = _format_wiktionary_gloss_line(str(ln).strip())
            if s:
                return idisp.to_zh_cn(s)
    return "（未查到词义）"


def _first_zh_gloss_chunk(s: str) -> str:
    """从维基行里取出简短中文义项（如「知道」），避免整句例句。"""
    t = idisp.to_zh_cn((s or "").strip())
    m = re.match(r"^([\u3400-\u9fff]{1,12})", t)
    if m:
        return m.group(1)
    m = re.search(r"([\u3400-\u9fff]{2,12})", t)
    return m.group(1) if m else t


def _word_meaning_zh_ukrainian(data: dict, clicked: str) -> str:
    bkrs = [str(x).strip() for x in (data.get("bkrs_lines") or []) if str(x).strip()]
    if not bkrs:
        lem_ru = str(data.get("lemma_ru") or data.get("bkrs_lemma") or "").strip()
        if lem_ru:
            try:
                bk = bp.lookup_russian_word(lem_ru)
                bkrs = [
                    str(x).strip()
                    for x in (bk.get("definition_lines") or [])
                    if str(x).strip()
                ]
            except Exception:
                bkrs = []
    if bkrs:
        return "\n".join(bkrs[:24])
    zh_all = [str(x) for x in (data.get("zh_gloss_lines") or [])]
    pick = _pick_best_wiki_zh_gloss_for_compact(zh_all, zh_all)
    if pick:
        return _first_zh_gloss_chunk(pick)
    for ln in data.get("ru_gloss_lines") or []:
        s = _format_wiktionary_gloss_line(str(ln).strip())
        if s and _cjk_meaning_char_count(s) >= 1:
            return idisp.to_zh_cn(s)
    lem = (data.get("lemma") or "").strip()
    if lem and lem.lower() != (clicked or "").strip().lower():
        try:
            sub = wp.get_ukrainian_inflections(lem)
            sub_bk = [str(x).strip() for x in (sub.get("bkrs_lines") or []) if str(x).strip()]
            if sub_bk:
                return "\n".join(sub_bk[:16])
            zh_sub = [str(x) for x in (sub.get("zh_gloss_lines") or [])]
            pick2 = _pick_best_wiki_zh_gloss_for_compact(zh_sub, zh_sub)
            if pick2:
                return _first_zh_gloss_chunk(pick2)
        except Exception:
            pass
    return "（未查到词义）"


_RU_CONJ_SECTION_MARKERS = (
    "время",
    "наклонение",
    "причаст",
    "деепричаст",
    "склонение",
)
_RU_LABEL_ZH: dict[str, str] = {
    "настоящее время": "现在时",
    "прошедшее время": "过去时",
    "будущее время": "将来时",
    "повелительное наклонение": "命令式",
    "изъявительное наклонение": "陈述式",
    "сослагательное наклонение": "虚拟式",
    "условное наклонение": "条件式",
    "действительный залог": "主动语态",
    "страдательный залог": "被动语态",
    "ед. число": "单数",
    "мн. число": "复数",
    "единственное число": "单数",
    "множественное число": "复数",
    "1-е лицо": "第一人称",
    "2-е лицо": "第二人称",
    "3-е лицо": "第三人称",
    "м. р.": "阳性",
    "ж. р.": "阴性",
    "с. р.": "中性",
    "им.": "主格",
    "род.": "属格",
    "дат.": "与格",
    "вин.": "宾格",
    "твор.": "工具格",
    "предл.": "方位格",
    "зв.": "呼格",
    "кратк.": "短尾",
    "полн.": "全尾",
    "причастия": "分词",
    "причастие": "分词",
    "деепричастия": "副动词",
    "деепричастие": "副动词",
    "действ. наст.": "主动·现在",
    "действ. прош.": "主动·过去",
    "страд. наст.": "被动·现在",
    "страд. прош.": "被动·过去",
    "действ.": "主动",
    "страд.": "被动",
    "прош. вр.": "过去时",
    "наст.": "现在",
}
_PANEL_HTML_RU_CONJ_MARKER = "lk-conj-zh"
_RU_CYR_WORD_IN_CELL = re.compile(
    r"[А-Яа-яЁё]+(?:\u0301|\u0300|\u030f)?"
    r"(?:-[А-Яа-яЁё]+(?:\u0301|\u0300|\u030f)?)*"
)


def _is_ru_conj_section_row(row: list) -> bool:
    cells = [(c or "").strip() for c in row]
    non_empty = [c for c in cells if c]
    if not non_empty:
        return False
    if len(non_empty) == 1:
        low = non_empty[0].lower()
        return any(m in low for m in _RU_CONJ_SECTION_MARKERS)
    if cells[0] and all(not (c or "").strip() for c in cells[1:]):
        low = cells[0].lower()
        return any(m in low for m in _RU_CONJ_SECTION_MARKERS)
    return False


def _is_ru_conj_subheader_row(row: list) -> bool:
    cells = [(c or "").strip() for c in row]
    if cells and not cells[0]:
        return any(
            "число" in (c or "").lower() or "лицо" in (c or "").lower()
            for c in cells[1:]
        )
    return False


def _is_ru_conj_label_cell(cell: str) -> bool:
    """表头/语法标签格：保留 «1-е лицо»、«ед. число» 等原文，不按词切分。"""
    s = (cell or "").strip()
    if not s:
        return True
    if not re.search(r"[А-Яа-яЁё]", s):
        return True
    low = s.lower()
    if re.search(r"\d", s):
        return True
    markers = (
        "лицо",
        "число",
        " р.",
        "действ",
        "страд",
        "прош",
        "вр.",
        "время",
        "наклон",
        "залог",
        "склон",
        "причаст",
        "дееприч",
    )
    return any(m in low for m in markers)


def _ru_norm_label_key(s: str) -> str:
    return re.sub(r"[\u0301\u0300\u030f]", "", (s or "")).lower().strip()


def _ru_label_with_zh(text: str) -> str:
    raw = (text or "").strip()
    if not raw or raw in ("—", "-", "–"):
        return html.escape(raw)
    low = _ru_norm_label_key(raw)
    for ru, zh in sorted(_RU_LABEL_ZH.items(), key=lambda x: -len(x[0])):
        if low == ru or ru in low:
            return (
                f"{html.escape(raw)}"
                f' <span class="lk-conj-zh">{html.escape(zh)}</span>'
            )
    return html.escape(raw)


def _ru_conj_cell_html(cell: str, stress_map: dict[str, str]) -> str:
    raw = re.sub(r"\s*△\s*", " ", (cell or "").strip())
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return ""
    if raw in ("—", "-", "–"):
        return "—"
    if _is_ru_conj_label_cell(raw):
        return _ru_label_with_zh(raw)
    parts: list[str] = []
    pos = 0
    for m in _RU_CYR_WORD_IN_CELL.finditer(raw):
        parts.append(html.escape(raw[pos : m.start()]))
        w = m.group(0)
        parts.append(html.escape(stress_map.get(wp.ru_stress_key(w), w)))
        pos = m.end()
    parts.append(html.escape(raw[pos:]))
    joined = "".join(parts)
    if re.search(r"<br\s*/?>", raw, re.I):
        return joined.replace("\n", "<br/>")
    return joined


def _ru_case_keys_from_label(cell: str) -> set[str]:
    """俄语变格表行首标签 → OpenCorpora case tag。"""
    low = _ru_norm_label_key(cell)
    keys: set[str] = set()
    pairs = (
        ("именитель", "nomn"),
        ("им.", "nomn"),
        ("родитель", "gent"),
        ("род.", "gent"),
        ("датель", "datv"),
        ("дат.", "datv"),
        ("винитель", "accs"),
        ("вин.", "accs"),
        ("творитель", "ablt"),
        ("твор.", "ablt"),
        ("предлож", "loct"),
        ("предл.", "loct"),
        ("зватель", "voct"),
        ("зв.", "voct"),
    )
    for frag, key in pairs:
        if frag in low:
            keys.add(key)
    if low.strip() in ("р.", "р"):
        keys.add("gent")
    return keys


def _ru_conj_cell_form_keys(cell: str) -> set[str]:
    keys: set[str] = set()
    for m in _RU_CYR_WORD_IN_CELL.finditer(cell or ""):
        keys.add(wp.ru_stress_key(m.group(0)))
    return keys


def _render_ru_morfotable_html(
    rows: list[list[str]],
    stress_map: dict[str, str],
    *,
    highlight_form_keys: set[str] | None = None,
    highlight_case_keys: set[str] | None = None,
) -> str:
    parts = [
        "<table class='lk-conj' cellpadding='6' cellspacing='0'>"
    ]
    max_cols = max(len(r) for r in rows) if rows else 3
    h_forms = highlight_form_keys or set()
    h_cases = highlight_case_keys or set()
    for row in rows[:28]:
        row_case_keys: set[str] = set()
        if row:
            row_case_keys = _ru_case_keys_from_label(str(row[0] or ""))
        row_hl = bool(h_cases and row_case_keys & h_cases)
        row_attr = ' class="lk-conj-row-hl"' if row_hl else ""
        if _is_ru_conj_section_row(row):
            title = next((c for c in row if (c or "").strip()), "")
            parts.append(
                f"<tr{row_attr}><th class='lk-conj-sec' colspan='{max_cols}'>"
                f"{_ru_conj_cell_html(title, stress_map)}</th></tr>"
            )
            continue
        if _is_ru_conj_subheader_row(row):
            parts.append(f"<tr{row_attr}>")
            for c in row:
                tag = "th" if (c or "").strip() else "td"
                cls = " lk-conj-h" if tag == "th" else ""
                cell_hl = bool(h_forms & _ru_conj_cell_form_keys(c))
                if cell_hl:
                    cls += " lk-conj-cell-hl"
                parts.append(
                    f"<{tag} class='{cls.strip() or 'lk-conj-td'}'>"
                    f"{_ru_conj_cell_html(c, stress_map)}</{tag}>"
                )
            parts.append("</tr>")
            continue
        parts.append(f"<tr{row_attr}>")
        for i, c in enumerate(row):
            cell_hl = bool(h_forms & _ru_conj_cell_form_keys(c))
            hl_cls = " lk-conj-cell-hl" if cell_hl else ""
            if i == 0 and (c or "").strip():
                parts.append(
                    f"<th class='lk-conj-lab{hl_cls}'>"
                    f"{_ru_conj_cell_html(c, stress_map)}</th>"
                )
            else:
                parts.append(
                    f"<td class='lk-conj-td{hl_cls}'>"
                    f"{_ru_conj_cell_html(c, stress_map)}</td>"
                )
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def _filter_ru_inflection_tables(
    tables: list, *, lemma: str = ""
) -> list[list[list[str]]]:
    """保留词条内全部有效 morfotable（如 есть：系词变格 + 动词变位）。"""
    _ = lemma
    out: list[list[list[str]]] = []
    for tbl in tables:
        if not isinstance(tbl, list) or len(tbl) < 3:
            continue
        blob = " ".join(" ".join(r) for r in tbl[:12]).lower()
        if "ближайшее родство" in blob or "список переводов" in blob:
            continue
        if hasattr(wp, "_reject_foreign_morfotable_rows") and wp._reject_foreign_morfotable_rows(
            tbl
        ):
            continue
        out.append(tbl)
    return out


def _ru_table_kind_caption(rows: list[list[str]]) -> str:
    blob = " ".join(" ".join(r) for r in rows[:6]).lower()
    if "падеж" in blob or re.search(r"\bим\.", blob):
        return "变格表"
    if any(
        m in blob
        for m in (
            "время",
            "лицо",
            "наклонен",
            "причаст",
            "деепричаст",
            "спряжен",
        )
    ):
        return "变位表"
    return ""


def _pick_best_ru_inflection_table(
    tables: list, *, lemma: str = ""
) -> list[list[str]] | None:
    valid = _filter_ru_inflection_tables(tables, lemma=lemma)
    return valid[0] if valid else None


def _uk_panel_html_needs_conj_refresh(panel_html: str) -> bool:
    """旧版乌克兰语查词缓存无语法标签中文，需重新渲染。"""
    h = (panel_html or "").strip()
    if not h or "变位 / 变格" not in h:
        return False
    if "变位 / 变格" in h and "lk-goroh-v4" not in h:
        return True
    return "lk-goroh-zh" not in h and "lk-conj-zh" not in h


def _uk_panel_ru_lemma_stale(panel_html: str) -> bool:
    """查词面板里「俄语原形」误存为乌语或 BKRS 脏数据。"""
    h = (panel_html or "").strip()
    if not h or "俄语原形" not in h:
        return False
    try:
        import uk_lookup_bridge as ulb
    except ImportError:
        return False
    for m in re.finditer(
        r"俄语原形[^<]*</p>\s*<p class='lk-lemma'>([^<]+)</p>",
        h,
        flags=re.I,
    ):
        if ulb.looks_ukrainian(m.group(1)) or ulb.bkrs_lemma_looks_invalid(
            m.group(1)
        ):
            return True
    return False


def build_uk_goroh_section_html(data: dict, *, clicked: str = "") -> str:
    """乌克兰语变位表（goroh.pp.ua），尽量复刻官网样式与重音。"""
    import goroh_parser as gp

    clk = clicked or data.get("clicked") or ""
    gh_u = (data.get("goroh_url") or "").strip()
    block = gp.ensure_goroh_table_html(data, clicked=clk)
    if not block:
        page = ""
        try:
            import requests

            r = requests.get(
                gh_u or gp.slovozmina_url(clk),
                timeout=16,
                headers=gp._SESSION.headers,
            )
            r.raise_for_status()
            page = r.text
        except Exception:
            page = ""
        if page:
            block = gp.build_goroh_table_html(page, clicked=clk)
            if not block:
                tables = gp.parse_inflection_tables_from_html(page)
                if tables:
                    block = gp.build_goroh_table_from_rows(tables[0], clicked=clk)
    if not block:
        return ""
    src = ""
    if gh_u:
        src = (
            f"<p class='lk-conj-src'>来源：<a href='{html.escape(gh_u, quote=True)}'>"
            "Горох · Словозміна</a></p>"
        )
    return (
        "<p class='lk-caps' style='margin-top:16px'>变位 / 变格</p>"
        f"{block}{src}"
    )


def _ru_panel_html_needs_conj_refresh(panel_html: str) -> bool:
    """旧版查词缓存无俄语语法标签中文，需重新抓取渲染。"""
    h = (panel_html or "").strip()
    if not h or "变位 / 变格" not in h:
        return False
    if "lk-conj-wrap" in h and "lk-conj-block" not in h and "lk-conj" in h:
        return True
    return _PANEL_HTML_RU_CONJ_MARKER not in h


def _ru_panel_html_needs_wiki_grammar_refresh(panel_html: str) -> bool:
    """旧版查词缓存无「词性：中文（俄语）」格式说明。"""
    h = (panel_html or "").strip()
    if not h or "词义" not in h:
        return False
    if "lk-wiki-gram-v2" in h:
        return False
    if "词性：" in h and re.search(r"俄语维基\s*·\s*词性", h):
        return False
    return bool(re.search(r"俄语原形|词典原形|BKRS", h))


def _ru_panel_html_needs_lemma_stress_refresh(panel_html: str) -> bool:
    """旧版查词缓存原形未带俄语维基分音节重音（如 от-клю-ча́ть）。"""
    h = (panel_html or "").strip()
    if not h or "原形" not in h:
        return False
    m = re.search(r"<p class='lk-lemma'>([^<]+)</p>", h)
    if not m:
        return False
    lem = m.group(1)
    if any(c in lem for c in "\u0301\u0300\u030f"):
        return False
    if re.search(r"[а-яё]-[а-яё]", lem, re.I):
        return False
    return bool(re.search(r"[А-Яа-яЁё]{4,}", lem))


def build_ru_conjugation_section_html(
    data: dict,
    *,
    clicked: str = "",
    morph_detail: dict[str, Any] | None = None,
) -> str:
    """俄语维基 morfotable 变位/变格表（词条内多张表一并展示）。"""
    tables = data.get("ru_html_tables") or []
    if not isinstance(tables, list) or not tables:
        return ""
    lemma0 = (data.get("bkrs_lemma") or data.get("lemma") or "").strip()
    valid = _filter_ru_inflection_tables(tables, lemma=lemma0)
    if not valid:
        return ""
    lemma_s = (data.get("lemma_stressed") or lemma0).strip() or lemma0
    sm = wp.build_ru_wiki_stress_map(lemma_s, lemma0, tables)
    clk = (clicked or data.get("clicked") or "").strip()
    h_forms: set[str] = set()
    if clk:
        h_forms.add(wp.ru_stress_key(clk))
    h_cases: set[str] = set()
    if isinstance(morph_detail, dict):
        ck = morph_detail.get("case_key")
        if ck:
            h_cases.add(str(ck))
    blocks: list[str] = []
    multi = len(valid) > 1
    for tbl in valid:
        cap = _ru_table_kind_caption(tbl) if multi else ""
        if cap:
            blocks.append(f"<p class='lk-conj-kind'>{html.escape(cap)}</p>")
        blocks.append(
            f"<div class='lk-conj-block'>{_render_ru_morfotable_html(tbl, sm, highlight_form_keys=h_forms, highlight_case_keys=h_cases)}</div>"
        )
    ru_u = (data.get("ru_wiki_url") or "").strip()
    src = ""
    if ru_u:
        src = (
            f"<p class='lk-conj-src'>来源：<a href='{html.escape(ru_u, quote=True)}'>"
            "俄语维基词典</a> · 变位表 · "
            f"<a href='{html.escape(wp.RU_WIKI_MAIN, quote=True)}'>Викисловарь</a></p>"
        )
    note = ""
    if h_cases:
        cz = ""
        if isinstance(morph_detail, dict):
            cz = str(morph_detail.get("case_zh") or "").strip()
        if cz:
            note = (
                f"<p class='lk-foot' style='margin:0 0 8px;color:#555'>"
                f"黄色高亮：本句中该词为<b>{html.escape(cz)}</b>；加粗单元格为与点击词形一致的形式。</p>"
            )
    return (
        "<p class='lk-caps' style='margin-top:16px'>变位 / 变格（俄语维基）</p>"
        f"{note}"
        f"<div class='lk-conj-wrap'>{''.join(blocks)}{src}</div>"
    )


def build_ru_wiki_grammar_html(
    data: dict[str, Any], *, clicked: str = ""
) -> str:
    """俄语维基 / pymorphy2：词性（中俄对照）及体、性等语法属性。"""
    gram = data.get("ru_wiki_grammar")
    lines: list[str] = []
    if isinstance(gram, dict) and (gram.get("pos_zh") or gram.get("aspect_zh")):
        lines = wp.format_ru_wiki_grammar_lines(gram)
    if not lines:
        lem = (
            (data.get("bkrs_lemma") or data.get("lemma") or clicked or data.get("clicked") or "")
            .strip()
        )
        if lem:
            pm = wp.grammar_from_pymorphy(lem)
            if pm.get("pos_zh") or pm.get("aspect_zh"):
                lines = wp.format_ru_wiki_grammar_lines(pm)
                gram = pm
    if not lines:
        summary = (data.get("ru_wiki_grammar_zh") or "").strip()
        if summary:
            lines = [ln.strip() for ln in re.split(r"<br\s*/?>", summary, flags=re.I) if ln.strip()]
    if not lines:
        return ""
    src_note = ""
    if isinstance(gram, dict):
        if gram.get("source") == "pymorphy2":
            src_note = "（pymorphy2 形态分析）"
        elif gram.get("source") == "ru.wiktionary":
            src_note = "（俄语维基词典）"
    pair = (data.get("ru_wiki_grammar_pair_zh") or "").strip()
    if not pair and isinstance(gram, dict):
        pair = wp.format_ru_wiki_grammar_pair_zh(gram)
    ru_u = (data.get("ru_wiki_url") or "").strip()
    src = ""
    if ru_u:
        src = (
            f"<p class='lk-foot' style='margin-top:6px'>"
            f"<a href='{html.escape(ru_u, quote=True)}'>俄语维基词典</a>"
            f"{html.escape(src_note)} · 语法属性</p>"
        )
    elif src_note:
        src = f"<p class='lk-foot' style='margin-top:6px;color:#888'>{html.escape(src_note.strip('（）'))}</p>"
    pair_html = ""
    if pair:
        pair_html = f"<p class='lk-more' style='margin-top:8px'>{html.escape(pair)}</p>"
    body = "<br/>".join(html.escape(ln) for ln in lines)
    return (
        "<div class='lk-wiki-gram lk-wiki-gram-v2'>"
        "<p class='lk-caps'>词性与语法</p>"
        f"<p class='lk-mean lk-mean-lines'>{body}</p>"
        f"{pair_html}{src}</div>"
    )


def _enrich_morph_from_wiki_grammar(
    morph_detail: dict[str, Any], data: dict[str, Any]
) -> dict[str, Any]:
    """维基词条语法优先补全 pymorphy 未标出的体/词类（尤其动词原形）。"""
    md = dict(morph_detail) if isinstance(morph_detail, dict) else {}
    gram = data.get("ru_wiki_grammar")
    if not isinstance(gram, dict):
        return md
    if gram.get("pos") and not md.get("pos"):
        md["pos"] = gram["pos"]
    if gram.get("pos_zh") and not md.get("pos_zh"):
        md["pos_zh"] = gram["pos_zh"]
    if gram.get("aspect") and not md.get("aspect_zh"):
        az = gram.get("aspect_zh") or ""
        if az:
            md["aspect_zh"] = az
    if gram.get("gender_zh") and not md.get("gender_zh"):
        md["gender_zh"] = gram["gender_zh"]
    if gram.get("animacy_zh") and not md.get("animacy_zh"):
        md["animacy_zh"] = gram["animacy_zh"]
    if gram.get("decl_class") and not md.get("decl_class"):
        md["decl_class"] = str(gram["decl_class"]).strip()
    if not md.get("case_key") and gram.get("case"):
        ck = str(gram["case"]).strip()
        if ck:
            md["case_key"] = ck
            if not md.get("case_zh"):
                md["case_zh"] = _CASE_ZH.get(ck, ck)
    if not md.get("ok") and (gram.get("pos_zh") or gram.get("aspect_zh")):
        md["ok"] = True
    return md


def _minimal_lemma_html(
    lemma: str, clicked: str, *, caption: str = "原形"
) -> str:
    """点击变位形时显示词典原形（如 ел → есть；乌语词形旁显示俄语 bkrs 原形）。"""
    lem = (lemma or "").strip()
    clk = (clicked or "").strip()
    if not lem or not clk or lem.lower() == clk.lower():
        return ""
    return (
        f"<p class='lk-caps'>{html.escape(caption)}</p>"
        f"<p class='lk-lemma'>{html.escape(lem)}</p>"
    )


def build_minimal_lookup_html(
    word_meaning_zh: str,
    sentence_zh: str = "",
    *,
    lemma: str = "",
    clicked: str = "",
    lemma_uk: str = "",
    lemma_uk_url: str = "",
    conjugation_html: str = "",
    lemma_caption: str = "原形",
    lemma_uk_caption: str = "乌克兰语原形",
    bkrs_url: str = "",
    meaning_from_bkrs: bool = False,
    wiki_grammar_html: str = "",
    context_html: str = "",
    in_sentence_grammar_html: str = "",
) -> str:
    """仅展示：句中语法 + 原形 + 词性语法 + 词义 + 变位表（若有）。"""
    _ = sentence_zh  # 保留参数供生词本等调用方写入例句，侧栏不再展示
    uk_lem = (lemma_uk or "").strip()
    uk_block = ""
    if uk_lem:
        uk_block = _minimal_lemma_html(uk_lem, clicked, caption=lemma_uk_caption)
        if lemma_uk_url:
            uk_block += (
                f"<p class='lk-foot' style='margin-top:4px'>"
                f"<a href='{html.escape(lemma_uk_url, quote=True)}'>"
                "Горох · Словозміна</a></p>"
            )
    lemma_block = _minimal_lemma_html(lemma, clicked, caption=lemma_caption)
    ctx_block = (context_html or "").strip()
    sent_gram_block = (in_sentence_grammar_html or "").strip()
    gram_block = (wiki_grammar_html or "").strip()
    conj_block = (conjugation_html or "").strip()
    raw = (word_meaning_zh or "").strip()
    if raw:
        if "\n" in raw:
            parts = [
                html.escape(idisp.to_zh_cn(ln))
                for ln in raw.splitlines()
                if ln.strip()
            ]
            meaning_html = "<br/>".join(parts) if parts else "（未查到词义）"
        else:
            meaning_html = html.escape(idisp.to_zh_cn(raw))
    else:
        meaning_html = "（未查到词义）"
    bkrs_src = ""
    if meaning_from_bkrs and meaning_html != "（未查到词义）" and bkrs_url.strip():
        bkrs_src = (
            f"<p class='lk-foot' style='margin-top:8px'>词义来源：<a href='"
            f"{html.escape(bkrs_url or bp.BKRS_BASE, quote=True)}'>"
            "bkrs.info</a>（俄语原形）</p>"
        )
    body = (
        "<div class='lk-page lk-minimal'>"
        f"{ctx_block}"
        f"{sent_gram_block}"
        f"{uk_block}"
        f"{lemma_block}"
        f"{gram_block}"
        "<p class='lk-caps'>词义</p>"
        f"<p class='lk-mean lk-mean-lines'>{meaning_html}</p>"
        f"{bkrs_src}"
        f"{conj_block}"
        "</div>"
    )
    return _wrap_lookup_html(body, compact=True)


def highlight_word_in_sentence_html(
    sentence: str,
    rel_start: int,
    rel_end: int,
    *,
    compact: bool | None = None,
    sentence_label: str | None = None,
    wrap_lk_box: bool | None = None,
) -> str:
    """在句内高亮 [rel_start:rel_end)，各段经 HTML 转义。"""
    if compact is None:
        compact = _lookup_compact()
    if wrap_lk_box is None:
        wrap_lk_box = compact
    if rel_start < 0:
        rel_start = 0
    if rel_end < rel_start:
        rel_end = rel_start
    rel_end = min(rel_end, len(sentence))
    rel_start = min(rel_start, len(sentence))
    a = html.escape(sentence[:rel_start])
    mid = html.escape(sentence[rel_start:rel_end])
    b = html.escape(sentence[rel_end:])
    if sentence_label:
        lab = sentence_label
    elif compact:
        lab = "所在句子"
    else:
        lab = "所在句子（当前译文）"
    wrap = ""
    if compact and wrap_lk_box:
        wrap = "<div class='lk-box'>"
    if compact:
        tit = (
            f"{wrap}<p class='lk-ctx-tit'><b>{html.escape(lab)}</b></p>"
        )
        hl = (
            '<mark style="background:#fff3cd;padding:2px 6px;border-radius:4px;'
            'font-weight:600;color:#212529">'
        )
    else:
        tit = f"{wrap}<p style='margin:0 0 4px'><b>{html.escape(lab)}</b></p>"
        hl = (
            '<mark style="background:#fff3d4;padding:2px 5px;border-radius:3px;font-weight:600;color:#111">'
        )
    out = (
        f"{tit}"
        f"<p class='lk-src-ru'>{a}"
        f"{hl}{mid}</mark>{b}</p>"
    )
    if compact and wrap_lk_box:
        out += "</div>"
    return out


_CASE_ZH: dict[str, str] = {
    "nomn": "主格",
    "gent": "属格",
    "datv": "与格",
    "accs": "宾格",
    "ablt": "工具格",
    "loct": "方位格",
    "voct": "呼格",
    "gen2": "第二属格",
    "acc2": "第二宾格",
    "loc2": "第二方位格",
}


_NUM_ZH = {"sing": "单数", "plur": "复数"}
_GNDR_ZH = {"masc": "阳性", "femn": "阴性", "neut": "中性", "ms-f": "共性"}
_ANIM_ZH = {"anim": "有生命", "inan": "无生命"}
_TENSE_ZH = {"past": "过去时", "pres": "现在时", "futr": "将来时"}
_MOOD_ZH = {"indc": "直陈式", "impr": "命令式", "cond": "条件式"}
_PER_ZH = {"1per": "第一人称", "2per": "第二人称", "3per": "第三人称"}
_ASPECT_ZH = {"perf": "完成体", "impf": "未完成体"}
_POS_ZH = {
    "NOUN": "名词",
    "VERB": "动词",
    "INFN": "不定式",
    "ADJF": "形容词",
    "ADJS": "形容词短尾",
    "COMP": "比较级",
    "PRTF": "形动词",
    "PRTS": "短尾形动词",
    "NUMR": "数词",
    "ADVB": "副词",
    "NPRO": "代词",
    "PREP": "前置词",
    "CONJ": "连词",
    "PRCL": "语气词",
    "INTJ": "感叹词",
    "GRND": "副动词",
    "PRED": "谓词副词",
}


def russian_morph_detail(
    clicked: str,
    sentence: str = "",
    rel_start: int = 0,
    rel_end: int = 0,
) -> dict[str, Any]:
    """pymorphy2 对点击词形的一次解析（可结合所在句前置词等消歧），供卡片式 UI 使用。"""
    d: dict[str, Any] = {
        "ok": False,
        "ambiguous": False,
        "error": "",
        "pos": None,
        "pos_zh": "",
        "case_key": "",
        "case_zh": "",
        "number_zh": "",
        "gender_zh": "",
        "animacy_zh": "",
        "aspect_zh": "",
        "tense_zh": "",
        "mood_zh": "",
        "person_zh": "",
        "decl_class": "",
    }
    try:
        morph = gm.shared_morph_analyzer()
        if morph is None:
            d["error"] = "pymorphy2 不可用"
            return d
        plain = wp.ru_strip_stress((clicked or "").strip())
        parses = morph.parse(plain)
        if not parses:
            d["error"] = "无法识别该词形"
            return d
        p = gm.pick_morph_parse_in_sentence(
            parses, plain, sentence, rel_start, rel_end
        )
        tag = p.tag
        pos = tag.POS
        d["pos"] = pos
        if pos:
            d["pos_zh"] = _POS_ZH.get(pos, str(pos))
        if tag.case:
            d["case_key"] = str(tag.case)
            d["case_zh"] = _CASE_ZH.get(str(tag.case), str(tag.case))
        if tag.number:
            d["number_zh"] = _NUM_ZH.get(tag.number, str(tag.number))
        if tag.gender and pos == "NOUN":
            d["gender_zh"] = _GNDR_ZH.get(tag.gender, str(tag.gender))
        if tag.animacy and pos == "NOUN":
            d["animacy_zh"] = _ANIM_ZH.get(tag.animacy, str(tag.animacy))
        if tag.aspect and pos in ("VERB", "INFN", "PRTF", "PRTS", "GRND"):
            d["aspect_zh"] = _ASPECT_ZH.get(str(tag.aspect), str(tag.aspect))
        if tag.tense and pos in ("VERB", "PRTF", "PRTS"):
            d["tense_zh"] = _TENSE_ZH.get(str(tag.tense), str(tag.tense))
        if tag.mood and pos == "VERB":
            d["mood_zh"] = _MOOD_ZH.get(str(tag.mood), str(tag.mood))
        if tag.person and pos == "VERB":
            d["person_zh"] = _PER_ZH.get(str(tag.person), str(tag.person))
        d["ambiguous"] = len(parses) > 1 and (parses[0].score - parses[1].score) < 2.0
        d["ok"] = True
    except Exception as e:
        d["error"] = str(e)
    return d


def build_ru_in_sentence_grammar_html(
    morph_detail: dict[str, Any] | None,
    data: dict[str, Any] | None = None,
) -> str:
    """句中词形语法摘要：格、数、性、变格类型等。"""
    md = morph_detail if isinstance(morph_detail, dict) else {}
    if not md.get("ok") and not md.get("case_zh") and not md.get("pos_zh"):
        return ""
    bits: list[str] = []
    if md.get("pos_zh"):
        bits.append(f"词类：{md['pos_zh']}")
    if md.get("case_zh"):
        bits.append(f"<b>句中格：{html.escape(str(md['case_zh']))}</b>")
    if md.get("number_zh"):
        bits.append(f"数：{html.escape(str(md['number_zh']))}")
    if md.get("gender_zh"):
        bits.append(f"性：{html.escape(str(md['gender_zh']))}")
    if md.get("animacy_zh"):
        bits.append(f"生命性：{html.escape(str(md['animacy_zh']))}")
    if md.get("aspect_zh"):
        bits.append(f"体：{html.escape(str(md['aspect_zh']))}")
    if md.get("tense_zh"):
        bits.append(f"时：{html.escape(str(md['tense_zh']))}")
    decl = ""
    if isinstance(data, dict):
        gram = data.get("ru_wiki_grammar")
        if isinstance(gram, dict) and gram.get("decl_class"):
            decl = str(gram["decl_class"]).strip()
            md["decl_class"] = decl
    if md.get("decl_class"):
        bits.append(f"变格类型（Зализняк）：{html.escape(str(md['decl_class']))}")
    if not bits:
        return ""
    amb = ""
    if md.get("ambiguous"):
        amb = (
            "<br/><span style='color:#888;font-size:13px'>"
            "该词形词典中有多解；已结合句中前置词等选取最可能的一项。</span>"
        )
    return (
        "<div class='lk-card lk-ctx-gram'>"
        "<p class='lk-caps' style='margin-bottom:8px'>句中语法（pymorphy2 + 上下文）</p>"
        f"<p class='lk-ctx-gram' style='margin:0;padding:0;border:none;background:transparent'>"
        f"{' · '.join(bits)}{amb}</p></div>"
    )


# 语法标签：浅底 + 描边 + 深色字（圆角胶囊），避免高饱和实心块
_PILL_SOFT: tuple[tuple[str, str, str], ...] = (
    ("#e8f1ff", "#4d8dff", "#0a3d91"),  # 蓝
    ("#e6faf4", "#3cc9a8", "#0a5c45"),  # 青绿
    ("#fff3e8", "#ff9a4d", "#7a3a00"),  # 橙
    ("#f4edff", "#9575e0", "#45277a"),  # 紫
    ("#eef2f6", "#8b99a8", "#2b3035"),  # 灰
    ("#eef2f6", "#8b99a8", "#2b3035"),
)


def _pill_ru(morph_detail: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """(显示文案, 背景色, 边框色, 文字色) 列表；顺序与词类→体→时→数→人称等一致。"""
    pills: list[tuple[str, str, str, str]] = []
    ci = 0

    def add(text: str) -> None:
        nonlocal ci
        if not text or len(pills) >= 6:
            return
        bg, bd, fg = _PILL_SOFT[ci % len(_PILL_SOFT)]
        pills.append((text, bg, bd, fg))
        ci += 1

    pos = morph_detail.get("pos")
    if morph_detail.get("pos_zh"):
        add(morph_detail["pos_zh"])
    if morph_detail.get("aspect_zh"):
        add(morph_detail["aspect_zh"])
    if morph_detail.get("tense_zh"):
        add(morph_detail["tense_zh"])
    if morph_detail.get("number_zh"):
        add(morph_detail["number_zh"])
    if morph_detail.get("person_zh"):
        add(morph_detail["person_zh"])
    if morph_detail.get("case_zh"):
        add(morph_detail["case_zh"])
    if pos == "NOUN" and morph_detail.get("gender_zh"):
        add(morph_detail["gender_zh"])
    return pills[:6]


def _analysis_rows_ru(morph_detail: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(线框图标键, 标签, 值) — 与示意稿「图标 + 标签：值」一致。"""
    rows: list[tuple[str, str, str]] = []

    def add(icon: str, lab: str, val: str) -> None:
        if val:
            rows.append((icon, lab, val))

    if morph_detail.get("pos_zh"):
        add("tag", "词类倾向", morph_detail["pos_zh"])
    if morph_detail.get("aspect_zh"):
        add("layers", "体", morph_detail["aspect_zh"])
    if morph_detail.get("tense_zh"):
        add("clock", "时态", morph_detail["tense_zh"])
    if morph_detail.get("pos") == "VERB" and morph_detail.get("mood_zh"):
        if morph_detail["mood_zh"] != "直陈式":
            add("clock", "式", morph_detail["mood_zh"])
    if morph_detail.get("person_zh"):
        add("person", "人称", morph_detail["person_zh"])
    if morph_detail.get("number_zh"):
        add("grid", "数", morph_detail["number_zh"])
    if morph_detail.get("case_zh"):
        add("grid", "格", morph_detail["case_zh"])
    if morph_detail.get("gender_zh"):
        add("tag", "性", morph_detail["gender_zh"])
    if morph_detail.get("animacy_zh"):
        add("layers", "生命性", morph_detail["animacy_zh"])
    if morph_detail.get("decl_class"):
        add("book", "变格类型", morph_detail["decl_class"])
    return rows


_CJK_MEAN_RE = re.compile(r"[\u3400-\u9fff]")


def _cjk_meaning_char_count(s: str) -> int:
    """用于挑选「像汉语释义」的维基行：统计 CJK 统一汉字等。"""
    return len(_CJK_MEAN_RE.findall(s))


def _wiki_line_compact_score(s: str) -> int:
    """分数越高越适合作为头部简短中文释义（多汉字、少西里尔/拉丁干扰）。"""
    cjk = _cjk_meaning_char_count(s)
    cyr = len(re.findall(r"[А-Яа-яЁёѢѣҐґ]", s))
    lat = len(re.findall(r"[A-Za-z]", s))
    return 10 * cjk - cyr - (lat // 2)


def _zh_wiki_line_is_etymology_noise(t: str) -> bool:
    """汉语维基行中的词源、同源对照等，不作为中文释义展示。"""
    if not (t or "").strip():
        return True
    bad = (
        "同源",
        "词源",
        "詞源",
        "与包括",
        "與包括",
        "来自",
        "來自",
        "继承",
        "繼承",
        "参见",
        "參見",
        "国际音标",
        "國際音標",
        "韵部",
        "韻部",
    )
    return any(b in t for b in bad)


def _ordered_zh_gloss_candidates(
    gloss_ranked: list[str], gloss_all: list[str]
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for ln in gloss_ranked:
        if ln not in seen:
            seen.add(ln)
            ordered.append(ln)
    for ln in gloss_all:
        if ln not in seen:
            seen.add(ln)
            ordered.append(ln)
    return ordered


def _pick_best_wiki_zh_gloss_for_compact(
    gloss_ranked: list[str], gloss_all: list[str]
) -> str:
    """在维基汉语节多行中，避开词源/旧拼写等噪声，优先选汉字较多的释义行。"""
    lines = _zh_gloss_lines_for_compact(gloss_ranked, gloss_all, max_lines=1)
    return lines[0] if lines else ""


def _zh_gloss_lines_for_compact(
    gloss_ranked: list[str], gloss_all: list[str], *, max_lines: int = 3
) -> list[str]:
    """筛选后的汉语维基释义行（用于头卡中文义项）。"""
    out: list[str] = []
    seen: set[str] = set()
    scored: list[tuple[int, int, str]] = []
    for i, raw in enumerate(_ordered_zh_gloss_candidates(gloss_ranked, gloss_all)):
        t = _format_wiktionary_gloss_line(raw)
        t = re.sub(r"\s+", " ", t).strip()
        if not t or t in seen or _zh_wiki_line_is_etymology_noise(t):
            continue
        cjk = _cjk_meaning_char_count(t)
        if cjk < 2:
            continue
        seen.add(t)
        scored.append((-_wiki_line_compact_score(t), i, t))
    scored.sort()
    for _, _, t in scored[:max_lines]:
        out.append(_clip_wiki_gloss_line(t, 200))
    if out:
        return out
    for raw in _ordered_zh_gloss_candidates(gloss_ranked, gloss_all):
        t = _format_wiktionary_gloss_line(raw)
        t = re.sub(r"\s+", " ", t).strip()
        if not t or _zh_wiki_line_is_etymology_noise(t):
            continue
        if _cjk_meaning_char_count(t) >= 1:
            out.append(_clip_wiki_gloss_line(t, 200))
            if len(out) >= max_lines:
                break
    return out


def _clip_wiki_gloss_line(s: str, n: int = 280) -> str:
    t = re.sub(r"\s+", " ", (s or "").strip())
    if len(t) > n:
        return t[:n].rstrip() + "…"
    return t


def _uk_equivalents_display_html(words: list[str], uk_wiki_url: str) -> str:
    """头卡「乌克兰语对应」：词形列表，首词可链到 uk.wiktionary。"""
    ws = [str(w).strip() for w in (words or []) if str(w).strip()]
    if not ws:
        return ""
    uk_u = html.escape(uk_wiki_url or "", quote=True)
    bits: list[str] = []
    for i, w in enumerate(ws[:5]):
        ew = html.escape(w)
        if i == 0 and uk_wiki_url:
            bits.append(f'<a class="lk-lemma-a" href="{uk_u}">{ew}</a>')
        else:
            bits.append(f"<span>{ew}</span>")
    return "；".join(bits)


def _compact_ru_en_es_sense_text(data: dict) -> str:
    """紧凑头卡：英语、西班牙语维基义项各最多 2 条（换行分隔）。"""
    en = [str(x).strip() for x in (data.get("en_gloss_lines") or []) if str(x).strip()]
    es = [str(x).strip() for x in (data.get("es_gloss_lines") or []) if str(x).strip()]
    parts: list[str] = []
    for t in en[:2]:
        parts.append("EN · " + _clip_wiki_gloss_line(t, 220))
    for t in es[:2]:
        parts.append("ES · " + _clip_wiki_gloss_line(t, 220))
    return "\n".join(parts)


def _compact_russian_zh_lines(
    clicked: str,
    glossary: dict[str, Any],
    gloss_ranked: list[str],
    gloss_all: list[str],
) -> list[str]:
    """头卡「中文释义」：术语库优先，再补汉语维基释义行（已滤词源）。"""
    if not isinstance(glossary, dict):
        glossary = {}
    lines: list[str] = []
    zhs = gm.glossary_zh_for_russian_click(str(clicked).strip(), glossary)
    if zhs:
        lines.append(idisp.to_zh_cn("、".join(zhs)))
    for t in _zh_gloss_lines_for_compact(gloss_ranked, gloss_all, max_lines=3):
        if t not in lines:
            lines.append(t)
        if len(lines) >= 3:
            break
    return lines[:3]


def _compact_russian_zh_meaning(
    clicked: str,
    glossary: dict[str, Any],
    gloss_ranked: list[str],
    gloss_all: list[str],
) -> str:
    """紧凑头部「中文释义」：术语库优先，否则维基多行中择优；无则空串（由头部显示占位）。"""
    if not isinstance(glossary, dict):
        glossary = {}
    zhs = gm.glossary_zh_for_russian_click(str(clicked).strip(), glossary)
    if zhs:
        return idisp.to_zh_cn("、".join(zhs))
    pick = _pick_best_wiki_zh_gloss_for_compact(gloss_ranked, gloss_all)
    if pick:
        if len(pick) > 360:
            pick = pick[:360].rstrip() + "…"
        return pick
    return ""


def _zh_meaning_lead_tail(s: str) -> tuple[str, str]:
    """长维基句拆成首行（简明）与续段，避免第一行铺满。"""
    s = (s or "").strip()
    if not s or s.startswith("（未获取"):
        return s, ""
    if len(s) <= 52:
        return s, ""
    for sep in ("。", "；", "？", "！", "，"):
        i = s.find(sep)
        if i < 0:
            continue
        lo, hi = (15, 100) if sep == "，" else (8, 160)
        if not (lo <= i <= hi):
            continue
        lead, tail = s[: i + 1], s[i + 1 :].strip()
        if len(tail) < 8:
            return s, ""
        return lead, tail
    tail = s[50:].strip()
    if not tail:
        return s, ""
    return s[:50].rstrip() + "…", tail


def _pill_chip_td_html(text: str, bg: str, border: str, fg: str) -> str:
    """圆角胶囊：浅底、细描边、深色字（QTextBrowser 用 div 全内联样式）。"""
    st = (
        "display:inline-block;background:%s;border:1px solid %s;color:%s;"
        "font-weight:600;font-size:12px;padding:6px 14px;border-radius:999px;"
        "line-height:1.35;letter-spacing:0.02em;white-space:nowrap;overflow:hidden;"
    ) % (bg, border, fg)
    return (
        '<td valign="middle" style="padding:0;border-style:none">'
        f'<div style="{st}">{html.escape(text)}</div></td>'
    )


def build_russian_compact_anatomy_html(
    clicked: str,
    lemma: str,
    *,
    ru_wiki_url: str,
    glossary_matched: bool,
    morph_detail: dict[str, Any],
    ipa_brackets: str | None = None,
    zh_meaning_lines: list[str] | None = None,
    sense_en_es: str | None = None,
    uk_equivalent_words: list[str] | None = None,
    uk_wiki_url: str = "",
    wiki_grammar_html: str = "",
) -> str:
    """紧凑模式：头卡含中文释义、乌克兰语对应、英/西义项与形态分析。"""
    lem = html.escape(str(lemma))
    clk = html.escape(str(clicked))
    ru_u = html.escape(ru_wiki_url or "", quote=True)
    lemma_a = (
        f'<a class="lk-lemma-a" href="{ru_u}">{lem}</a>'
        if ru_wiki_url
        else f"<span class='lk-lemma-a'>{lem}</span>"
    )
    if glossary_matched:
        badge = (
            "<span class='lk-badge lk-badge-ok'>"
            '<span class="lk-badge-ok-ic">&#10003;</span>术语库匹配'
            "</span>"
        )
    else:
        badge = (
            "<span class='lk-badge lk-badge-miss'>"
            "术语库未匹配</span>"
        )

    ipa_s = (ipa_brackets or "").strip()
    ipa_block = ""
    if ipa_s:
        ipa_block = f"<p class='lk-ipa'>{html.escape(ipa_s)}</p>"

    sense_blocks: list[str] = []
    uk_html = _uk_equivalents_display_html(
        uk_equivalent_words or [], uk_wiki_url
    )
    if uk_html:
        sense_blocks.append(
            "<p class='lk-zh-head'>"
            "<span class='lk-dict-lab'>乌克兰语对应：</span>"
            f"{uk_html}</p>"
        )
    zh_lines = [str(x).strip() for x in (zh_meaning_lines or []) if str(x).strip()]
    if zh_lines:
        zbr = "<br/>".join(
            html.escape(idisp.to_zh_cn(line)) for line in zh_lines
        )
        sense_blocks.append(
            "<p class='lk-zh-head'><span class='lk-dict-lab'>中文释义：</span><br/>"
            f"{zbr}</p>"
        )
    en_es = (sense_en_es or "").strip()
    if en_es:
        ebr = "<br/>".join(
            html.escape(line.strip()) for line in en_es.split("\n") if line.strip()
        )
        sense_blocks.append(
            "<p class='lk-zh-head' style='margin-top:12px'>"
            "<span class='lk-dict-lab'>义项（英语 / 西班牙语）：</span><br/>"
            f"{ebr}</p>"
        )
    if not sense_blocks:
        sense_blocks.append(
            "<p class='lk-zh-head-muted'>"
            "未解析到中文释义、乌克兰语对应或英/西维基义项；可点击下方维基链接查看全文。"
            "</p>"
        )
    zh_mean_block = "".join(sense_blocks)

    head = (
        "<div class='lk-card lk-head-card'>"
        f'<p class="lk-word-big">{clk}</p>'
        f"{ipa_block}"
        "<table class='lk-dict-table' cellpadding='0' cellspacing='0'><tr>"
        "<td class='lk-dict-cell'>"
        "<span class='lk-dict-lab'>词典原形：</span>"
        f"{lemma_a}"
        "</td>"
        f'<td class="lk-badge-cell">{badge}</td>'
        "</tr></table>"
        f"{zh_mean_block}"
        "</div>"
    )

    gram_card = (wiki_grammar_html or "").strip()

    pills = _pill_ru(morph_detail)
    pill_html = ""
    if pills:
        cells: list[str] = []
        for text, bg, bd, fg in pills:
            cells.append(_pill_chip_td_html(text, bg, bd, fg))
        pill_html = (
            "<div class='lk-card lk-pill-card'>"
            '<table class="lk-pill-bar" cellspacing="8" cellpadding="0" border="0" '
            'style="border:none;margin:0"><tr>'
            + "".join(cells)
            + "</tr></table></div>"
        )

    rows = _analysis_rows_ru(morph_detail)
    body_rows: list[str] = []
    for icon_key, lab, val in rows:
        ico = _lk_anal_icon_html(icon_key)
        body_rows.append(
            "<tr><td class='lk-an-row'>"
            f"{ico}"
            f"<span class='lk-ln'><span class='lk-lab-fix'>{html.escape(lab)}</span>：</span>"
            f"<span class='lk-v'>{html.escape(val)}</span>"
            "</td></tr>"
        )
    if morph_detail.get("error"):
        err = html.escape(morph_detail["error"])
        body_rows.append(
            "<tr><td class='lk-an-row' style='color:#c62828'>"
            f"<span class='lk-v'>!</span> {err}</td></tr>"
        )
    elif not morph_detail.get("ok"):
        body_rows.append(
            "<tr><td class='lk-an-row' style='color:#c62828'>"
            "<span class='lk-v'>!</span> 词形无法解析</td></tr>"
        )

    foot = ""
    if ru_wiki_url:
        foot = (
            "<p class='lk-an-foot'>"
            "<span class='lk-info-sym'>&#x24D8;</span>"
            f'<a href="{ru_u}">多义词形，请参考完整词条 &gt;</a>'
            "</p>"
        )

    if not body_rows and morph_detail.get("ok") and not morph_detail.get("error"):
        body_rows.append(
            "<tr><td class='lk-an-row' style='color:#78909c'>"
            "— 本词形无格／时／人称等附加标注</td></tr>"
        )

    anal = (
        "<div class='lk-card'>"
        "<p class='lk-anal-title'>句中词形分析</p>"
        "<table class='lk-anal' cellspacing='0' cellpadding='0'>"
        + "".join(body_rows)
        + "</table>"
        + foot
        + "</div>"
    )
    return head + gram_card + pill_html + anal


def russian_in_sentence_role_zh(
    clicked: str, sentence: str, rel_start: int = 0, rel_end: int = 0
) -> str:
    """
    根据 pymorphy2 对「点击词形」的分析，结合句中前置词等上下文，用中文概括语法身份。
    """
    try:
        morph = gm.shared_morph_analyzer()
        if morph is None:
            return "词法分析：pymorphy2 不可用。"
        plain = wp.ru_strip_stress((clicked or "").strip())
        parses = morph.parse(plain)
        if not parses:
            return "词法分析：无法识别该词形。"
        p = gm.pick_morph_parse_in_sentence(
            parses, plain, sentence, rel_start, rel_end
        )
        tag = p.tag
        bits: list[str] = []
        pos = tag.POS
        if pos:
            bits.append(f"词类倾向：「{_POS_ZH.get(pos, pos)}」")
        if tag.case:
            bits.append(f"格：{_CASE_ZH.get(tag.case, tag.case)}")
        if tag.number:
            bits.append(_NUM_ZH.get(tag.number, tag.number))
        if tag.gender and pos == "NOUN":
            bits.append(_GNDR_ZH.get(tag.gender, tag.gender))
        if tag.animacy and pos == "NOUN":
            bits.append(_ANIM_ZH.get(tag.animacy, tag.animacy))
        if tag.aspect and pos in ("VERB", "INFN", "PRTF", "PRTS", "GRND"):
            bits.append(
                "体：" + _ASPECT_ZH.get(str(tag.aspect), str(tag.aspect))
            )
        if tag.tense and pos in ("VERB", "PRTF", "PRTS"):
            bits.append(
                "时：" + _TENSE_ZH.get(str(tag.tense), str(tag.tense))
            )
        if tag.mood and pos == "VERB":
            bits.append("式：" + _MOOD_ZH.get(str(tag.mood), str(tag.mood)))
        if tag.person and pos == "VERB":
            bits.append("人称：" + _PER_ZH.get(str(tag.person), str(tag.person)))
        amb = ""
        if len(parses) > 1 and (parses[0].score - parses[1].score) < 2.0:
            amb = "（该词形词典中有多解，已结合句中上下文选取；若不合句意请对照下方变格表。）"
        tail = " ".join(bits) if bits else str(tag)
        return f"在本句中（据词形）：{tail}{amb}"
    except Exception as e:
        return f"词法分析不可用：{e}"


def _gloss_pos_hint_score(line: str, pos: str | None) -> int:
    """维基释义行里若出现与词类一致的中文提示，则提高排序权重。"""
    if not pos or not line:
        return 0
    s = line
    score = 0
    if pos == "NOUN":
        if re.search(r"[名名]詞|名词", s):
            score += 3
        if re.search(r"動詞|动词", s):
            score -= 2
    elif pos in ("VERB", "INFN", "GRND", "PRTF", "PRTS"):
        if re.search(r"動詞|动词", s):
            score += 3
        if re.search(r"[名名]詞|名词", s) and "名物化" not in s:
            score -= 1
    elif pos in ("ADJF", "ADJS", "COMP"):
        if re.search(r"形容|形詞|形动词", s):
            score += 3
    elif pos == "ADVB":
        if "副" in s:
            score += 2
    return score


def rank_gloss_lines_for_pos(lines: list[str], pos: str | None) -> list[str]:
    if not lines or not pos:
        return list(lines)
    scored = [(-_gloss_pos_hint_score(ln, pos), i, ln) for i, ln in enumerate(lines)]
    scored.sort()
    return [ln for _, _, ln in scored]


def _format_wiktionary_gloss_line(ln: str) -> str:
    """去掉汉语维基释义行里的拉丁转写括号后再转简体（与缓存规范化一致）。"""
    s = idisp.strip_wiktionary_latin_transliteration_parens(str(ln))
    return idisp.to_zh_cn(s)


def build_russian_sentence_context_html(
    sentence: str | None,
    rel_start: int,
    rel_end: int,
    clicked: str,
    *,
    source_zh_hint: str = "",
    ru_stress_map: dict[str, str] | None = None,
) -> str:
    """句中上下文辅助信息（不展示「所在句子」及其高亮标注）。"""
    _ = (source_zh_hint, ru_stress_map)
    if not sentence or not sentence.strip():
        return ""
    role_p = ""
    try:
        role = russian_in_sentence_role_zh(
            clicked, sentence, rel_start, rel_end
        )
        if role:
            if len(role) > 420:
                role = role[:419].rstrip() + "…"
            role_p = (
                "<p class='lk-ctx-anal'>"
                f"{html.escape(idisp.to_zh_cn(role))}</p>"
            )
    except Exception:
        pass
    if not role_p.strip():
        return ""
    if _lookup_compact():
        return f"<div class='lk-card'>{role_p}</div>"
    return f"<div style='margin-top:6px'>{role_p}</div>"


def build_ukrainian_sentence_context_html(
    sentence: str | None, rel_start: int, rel_end: int, clicked: str
) -> str:
    _ = (sentence, rel_start, rel_end, clicked)
    if not sentence or not sentence.strip():
        return ""
    note = (
        "<p style='color:#555;font-size:14px;line-height:1.55'>乌克兰语：本版未内置形态库，"
        "义项无法按格/体自动筛选；请结合句意从下列汉语维基释义中判断。</p>"
    )
    if _lookup_compact():
        note = "<p style='color:#666;font-size:13px'>乌：义项未按形态筛选，请结合句意。</p>"
    return note


def _tables_to_html(
    tbls: list,
    title: str,
    *,
    cell_display=None,
    max_tables: int | None = None,
) -> list[str]:
    """cell_display: 若为可调用对象，则对每个单元格文本做展示转换（如去拉丁转写、简体化）。"""
    out: list[str] = []
    if not tbls:
        return out
    limit = 6 if max_tables is None else max(0, max_tables)
    if limit == 0:
        return out
    out.append(f"<h4>{html.escape(idisp.to_zh_cn(title))}</h4>")
    for tbl in tbls[:limit]:
        out.append(
            "<table border='1' cellpadding='8' cellspacing='0' "
            "style='border-collapse:collapse;margin-bottom:12px;font-size:15px;line-height:1.45;'>"
        )
        for row in tbl[:22]:
            out.append("<tr>")
            for c in row[:14]:
                t = str(c)
                if cell_display is not None:
                    t = cell_display(t)
                out.append(f"<td>{html.escape(t)}</td>")
            out.append("</tr>")
        out.append("</table>")
    return out


def russian_meta_labels(clicked_word: str, glossary: dict) -> tuple[str, str]:
    zhs = gm.glossary_zh_for_russian_click(clicked_word, glossary)
    zh_line = "、".join(zhs) if zhs else "（术语库中未匹配到对应中文，可检查词形或扩充术语表）"
    zh_line = idisp.to_zh_cn(zh_line)
    morph_line = ""
    try:
        morph = gm.shared_morph_analyzer()
        if morph is None:
            morph_line = "词法分析：pymorphy2 不可用。"
        else:
            p = morph.parse(clicked_word.strip())
            if not p:
                morph_line = "词法分析：无法识别该词形。"
            else:
                morph_line = "词法分析：" + idisp.opencorpora_tag_string_to_zh(str(p[0].tag))
    except Exception as e:
        morph_line = f"词法分析不可用：{e}"
    if _lookup_compact():
        zh_prefix = "术语："
        morph_line = morph_line.replace("词法分析：", "词法：", 1)
        if len(morph_line) > 88:
            morph_line = morph_line[:88].rstrip() + "…"
    else:
        zh_prefix = "术语库对应中文："
    return zh_prefix + zh_line, morph_line


def build_russian_word_info_html(
    data: dict,
    clicked_fallback: str,
    *,
    context_html: str = "",
    pos_hint: str | None = None,
    morph_detail: dict[str, Any] | None = None,
    glossary_matched: bool = False,
    glossary: dict[str, Any] | None = None,
) -> str:
    cp = _lookup_compact()
    lemma = data.get("lemma") or clicked_fallback
    clicked = data.get("clicked") or clicked_fallback
    clicked_disp = str(data.get("clicked_stressed") or clicked)
    lemma_disp = str(data.get("lemma_stressed") or lemma)
    raw_zh = data.get("zh_gloss_lines") or []
    gloss = [str(x).strip() for x in raw_zh if str(x).strip()]
    gloss_ranked = rank_gloss_lines_for_pos(gloss, pos_hint)
    zh_gl = _zh_gloss_lines_for_compact(gloss_ranked, gloss, max_lines=4)
    en_gl = [str(x).strip() for x in (data.get("en_gloss_lines") or []) if str(x).strip()]
    es_gl = [str(x).strip() for x in (data.get("es_gloss_lines") or []) if str(x).strip()]
    uk_words = [
        str(x).strip() for x in (data.get("uk_equivalent_words") or []) if str(x).strip()
    ]
    zh_u = data.get("zh_wiki_url") or ""
    ru_u = data.get("ru_wiki_url") or ""
    uk_u = data.get("uk_wiki_url") or ""
    en_u = data.get("en_wiki_url") or ""
    es_u = data.get("es_wiki_url") or ""
    main_u = data.get("ru_wiktionary_main_url") or wp.RU_WIKI_MAIN

    if cp:
        parts: list[str] = ["<div class='lk-page'>"]
        md = morph_detail if isinstance(morph_detail, dict) else None
        if md is None:
            md = russian_morph_detail(str(clicked))
        md = _enrich_morph_from_wiki_grammar(md, data)
        ipa = (data.get("ipa_brackets") or "").strip() or None
        gram_html = build_ru_wiki_grammar_html(data, clicked=str(clicked))
        try:
            zh_lines = _compact_russian_zh_lines(
                str(clicked), glossary or {}, gloss_ranked, gloss
            )
            sense_txt = _compact_ru_en_es_sense_text(data)
            parts.append(
                build_russian_compact_anatomy_html(
                    clicked_disp,
                    lemma_disp,
                    ru_wiki_url=ru_u,
                    glossary_matched=glossary_matched,
                    morph_detail=md,
                    ipa_brackets=ipa,
                    zh_meaning_lines=zh_lines,
                    sense_en_es=sense_txt,
                    uk_equivalent_words=uk_words,
                    uk_wiki_url=uk_u,
                    wiki_grammar_html=gram_html,
                )
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            parts.append(
                "<div class='lk-card' style='border-color:#ffcdd2;background:#fff8f8'>"
                "<p style='margin:0;color:#b71c1c'><b>查词界面渲染出错</b>："
                f"{html.escape(str(e))}</p>"
                "<p style='margin:8px 0 0;font-size:13px;color:#555'>"
                "请从命令行重新启动程序查看完整报错，或向开发者反馈。</p></div>"
            )
        err_card: list[str] = []
        if data.get("error"):
            err_card.append(
                "<p style='margin:0;color:#b71c1c'><b>错误</b>："
                f"{html.escape(str(data['error']))}</p>"
            )
        for k in ("zh_fetch_error", "ru_fetch_error", "en_fetch_error", "es_fetch_error"):
            if data.get(k):
                err_card.append(
                    f"<p style='margin:6px 0 0;font-size:13px;color:#c62828'>"
                    f"{html.escape(k)}：{html.escape(str(data[k]))}</p>"
                )
        if err_card:
            parts.append(
                "<div class='lk-card' style='border-color:#ffcdd2;background:#fff8f8'>"
                + "".join(err_card)
                + "</div>"
            )

        # 与示意稿一致：单词头 → 语法标签 → 词形分析 → 变格表 → 维基摘录等
        if context_html:
            parts.append(context_html)
        conj_sec = build_ru_conjugation_section_html(
            data,
            clicked=str(clicked),
            morph_detail=md,
        )
        if conj_sec:
            parts.append(f"<div class='lk-card'>{conj_sec}</div>")

        parts.append("<div class='lk-card lk-card-wiki'>")
        parts.append("<p class='lk-caps'>汉语维基 · 中文义项</p>")
        if zh_gl:
            for i, ln in enumerate(zh_gl[:4]):
                cls = "lk-mean" if i == 0 else "lk-more"
                parts.append(
                    f"<p class='{cls}'>{html.escape(idisp.to_zh_cn(ln))}</p>"
                )
        else:
            parts.append(
                "<p style='color:#757575;font-size:14px;margin:4px 0 0'>"
                "<i>未解析到汉语维基「俄语」节中文释义（已跳过词源段）。</i></p>"
            )
        parts.append("<p class='lk-caps' style='margin-top:12px'>乌克兰语对应</p>")
        if uk_words:
            parts.append(
                f"<p class='lk-mean'>{_uk_equivalents_display_html(uk_words, uk_u)}</p>"
            )
            parts.append(
                "<p class='lk-more' style='color:#666;font-size:13px'>"
                "来源：俄语维基词条内「Украинский uk」翻译行；可与乌语维基对照。</p>"
            )
        else:
            parts.append(
                "<p style='color:#757575;font-size:14px;margin:4px 0 0'>"
                "<i>未解析到乌克兰语对应词（该词条可能无乌语翻译表）。</i></p>"
            )
        parts.append("<p class='lk-caps' style='margin-top:12px'>英语 / 西班牙语维基 · 义项摘录</p>")
        if en_gl:
            parts.append(
                f"<p class='lk-mean'>{html.escape(_clip_wiki_gloss_line(en_gl[0], 320))}</p>"
            )
            if len(en_gl) > 1:
                parts.append(
                    f"<p class='lk-more'>{html.escape(_clip_wiki_gloss_line(en_gl[1], 320))}</p>"
                )
        if es_gl:
            parts.append(
                f"<p class='lk-mean' style='margin-top:10px'>"
                f"{html.escape(_clip_wiki_gloss_line(es_gl[0], 320))}</p>"
            )
            if len(es_gl) > 1:
                parts.append(
                    f"<p class='lk-more'>{html.escape(_clip_wiki_gloss_line(es_gl[1], 320))}</p>"
                )
        if not en_gl and not es_gl:
            parts.append(
                "<p style='color:#757575;font-size:14px;margin:4px 0 0'>"
                "<i>未解析到英语或西班牙语维基「俄语」节义项（可能无该节或抓取失败）。</i></p>"
            )
        parts.append("<p class='lk-caps' style='margin-top:12px'>查全文</p>")
        lk: list[str] = []
        if zh_u:
            lk.append(f'<a href="{html.escape(zh_u, quote=True)}">汉语维基</a>')
        if uk_u:
            lk.append(f'<a href="{html.escape(uk_u, quote=True)}">乌克兰语维基</a>')
        if en_u:
            lk.append(f'<a href="{html.escape(en_u, quote=True)}">英语维基</a>')
        if es_u:
            lk.append(f'<a href="{html.escape(es_u, quote=True)}">西班牙语维基</a>')
        if ru_u:
            lk.append(f'<a href="{html.escape(ru_u, quote=True)}">俄语维基</a>')
        if not lk:
            lk.append(f'<a href="{html.escape(main_u, quote=True)}">俄语维基词典</a>')
        parts.append("<div class='lk-links'>" + "".join(lk) + "</div>")
        parts.append(
            "<p class='lk-foot'>变格表与更多义项见网页；侧栏长版请设 "
            "<code>ARGOS_WORD_LOOKUP_VERBOSE=1</code> 后重启。</p>"
        )
        parts.append("</div>")

        tbl_cap = 0
        zht = data.get("zh_html_tables") or []
        rut = data.get("ru_html_tables") or []
        parts.extend(
            _tables_to_html(
                zht,
                "汉语维基 · 「俄语」节表格节选（多为变格表；以网页为准）",
                cell_display=idisp.declension_cell_display,
                max_tables=tbl_cap,
            )
        )
        parts.extend(
            _tables_to_html(
                rut,
                "俄语维基 · 「Русский」节表格节选（多为变格表；以网页为准）",
                cell_display=idisp.declension_cell_display,
                max_tables=tbl_cap,
            )
        )
        if not zht and not rut:
            fb = data.get("html_tables") or []
            parts.extend(
                _tables_to_html(
                    fb,
                    "维基节选表格（以网页为准）",
                    cell_display=idisp.declension_cell_display,
                    max_tables=tbl_cap,
                )
            )
        parts.append("</div>")
        return "\n".join(parts)

    parts: list[str] = []
    if context_html:
        parts.append(context_html)
        parts.append(
            "<hr style='border:none;border-top:1px solid #ccc;margin:12px 0'/>"
        )

    parts.append(
        f"<p><b>点击形式</b>：<code>{html.escape(clicked_disp)}</code>　"
        f"<b>词典形</b>：<code>{html.escape(lemma_disp)}</code></p>"
    )

    src = data.get("source", "")
    if (
        data.get("error")
        or data.get("zh_fetch_error")
        or data.get("ru_fetch_error")
        or data.get("en_fetch_error")
        or data.get("es_fetch_error")
    ):
        parts.append(f"<p><b>抓取状态</b>：{html.escape(str(src))}</p>")
    if data.get("error"):
        parts.append(f"<p style='color:#a00'>{html.escape(str(data['error']))}</p>")
    for k in ("zh_fetch_error", "ru_fetch_error", "en_fetch_error", "es_fetch_error"):
        if data.get(k):
            parts.append(
                f"<p style='color:#666;font-size:14px'>{html.escape(k)}：{html.escape(str(data[k]))}</p>"
            )

    if uk_words:
        parts.append(
            "<div style='border-left:3px solid #7b1fa2;padding:10px 12px;margin-bottom:12px;"
            "background:#f6eef8;font-size:15px;line-height:1.55'>"
            "<b>乌克兰语对应</b>："
            f"{_uk_equivalents_display_html(uk_words, uk_u)}</div>"
        )
    zh_lead_lines = _compact_russian_zh_lines(
        str(clicked), glossary or {}, gloss_ranked, gloss
    )
    if zh_lead_lines:
        parts.append(
            "<div style='border-left:3px solid #2e7d32;padding:10px 12px;margin-bottom:12px;"
            "background:#eef7ee;font-size:15px;line-height:1.55'>"
            "<b>中文释义（术语库 / 汉语维基）</b><br/>"
            f"{html.escape('；'.join(zh_lead_lines[:3]))}</div>"
        )
    lead = ""
    if en_gl:
        lead = _clip_wiki_gloss_line(en_gl[0], 360)
    elif es_gl:
        lead = _clip_wiki_gloss_line(es_gl[0], 360)
    if lead:
        parts.append(
            "<div style='border-left:3px solid #2d6cb5;padding:10px 12px;margin-bottom:12px;"
            "background:#eef5fc;font-size:15px;line-height:1.55'>"
            "<b>义项摘录（英语 / 西班牙语维基「俄语」节）</b><br/>"
            f"{html.escape(lead)}</div>"
        )
    if gloss_ranked:
        parts.append("<h4>汉语维基词典 · 「俄语」义项（节选，已滤词源）</h4><ul>")
        shown: set[str] = set()
        for ln in gloss_ranked[:12]:
            t = _format_wiktionary_gloss_line(ln)
            if _zh_wiki_line_is_etymology_noise(t):
                continue
            if t in shown:
                continue
            shown.add(t)
            parts.append(f"<li>{html.escape(t)}</li>")
        parts.append("</ul>")
    if en_gl or es_gl:
        if en_gl:
            parts.append("<h4>英语维基 · Russian</h4><ul>")
            for ln in en_gl[:12]:
                parts.append(f"<li>{html.escape(_clip_wiki_gloss_line(ln, 420))}</li>")
            parts.append("</ul>")
        if es_gl:
            parts.append("<h4>西班牙语维基 · Ruso</h4><ul>")
            for ln in es_gl[:12]:
                parts.append(f"<li>{html.escape(_clip_wiki_gloss_line(ln, 420))}</li>")
            parts.append("</ul>")
    else:
        parts.append(
            "<p><i>未解析到英语或西班牙语维基「俄语」节义项（可能无该节或标题不同）。</i></p>"
        )

    parts.append("<p>")
    link_bits: list[str] = []
    if zh_u:
        link_bits.append(
            f'<a href="{html.escape(zh_u, quote=True)}">在浏览器打开 · 汉语维基词条</a>'
        )
    if uk_u:
        link_bits.append(
            f'<a href="{html.escape(uk_u, quote=True)}">在浏览器打开 · 乌克兰语维基词条</a>'
        )
    if en_u:
        link_bits.append(
            f'<a href="{html.escape(en_u, quote=True)}">在浏览器打开 · 英语维基词条</a>'
        )
    if es_u:
        link_bits.append(
            f'<a href="{html.escape(es_u, quote=True)}">在浏览器打开 · 西班牙语维基词条</a>'
        )
    if ru_u:
        link_bits.append(
            f'<a href="{html.escape(ru_u, quote=True)}">在浏览器打开 · 俄语维基词条</a>'
        )
    parts.append("　|　".join(link_bits))
    parts.append("</p>")
    parts.append(
        "<p style='color:#555;font-size:14px;line-height:1.55'>"
        "<b>变位／变格</b>：俄语的人称、时态、格等语法形式，以下方 <b>pymorphy2</b> 生成的「词形一览」为准。"
        "维基里的表格有时是<strong>同根词、派生词列举</strong>，不是动词变位表；此类表已尽量自动隐藏。"
        f'体例说明见 <a href="{html.escape(main_u, quote=True)}">俄语维基词典</a>。</p>'
    )

    forms = data.get("forms") or []
    pm = data.get("pymorphy2") or {}
    if forms:
        parts.append(
            "<h4>变位／词形一览（pymorphy2：格、数、体、人称、时态等）</h4>"
            "<ul style='list-style-position:outside;'>"
        )
        for f in forms[:36]:
            w = html.escape(str(f.get("word", "")))
            tzh = idisp.opencorpora_tag_string_to_zh(str(f.get("tag", "")))
            parts.append(
                "<li style='margin-bottom:10px;'>"
                f'<div style="margin:0 0 2px 0;"><code>{w}</code></div>'
                f'<div style="color:#444;">{html.escape(tzh)}</div>'
                "</li>"
            )
        parts.append("</ul>")
    elif pm.get("error"):
        parts.append(f"<p>{html.escape(str(pm['error']))}</p>")

    zht = data.get("zh_html_tables") or []
    rut = data.get("ru_html_tables") or []
    parts.extend(
        _tables_to_html(
            zht,
            "汉语维基 · 「俄语」节表格节选（多为变格表；以网页为准）",
            cell_display=idisp.declension_cell_display,
            max_tables=None,
        )
    )
    parts.extend(
        _tables_to_html(
            rut,
            "俄语维基 · 「Русский」节表格节选（多为变格表；以网页为准）",
            cell_display=idisp.declension_cell_display,
            max_tables=None,
        )
    )
    if not zht and not rut:
        fallback = data.get("html_tables") or []
        parts.extend(
            _tables_to_html(
                fallback,
                "维基节选表格（以网页为准）",
                cell_display=idisp.declension_cell_display,
                max_tables=None,
            )
        )
        if not fallback:
            parts.append(
                "<p><i>未解析到维基表格；完整变格/派生信息请点击上方链接在浏览器中查看。</i></p>"
            )

    return "\n".join(parts)


def ukrainian_meta_labels() -> tuple[str, str]:
    if _lookup_compact():
        return (
            "术语：中↔俄术语库不覆盖乌语；汉语维基 + 俄语维基（乌克兰语节）+ Горох 供参考。",
            "词形：Горох；释义见汉语维基，若无则见俄语维基摘录。",
        )
    return (
        "词义：乌克兰语先译成俄语，再查 bkrs.info（与俄语查词相同）。",
        "变位：Горох（goroh.pp.ua）「Словозміна」；维基义项仅作备用。",
    )


def build_ukrainian_word_info_html(
    data: dict,
    clicked_fallback: str,
    *,
    context_html: str = "",
) -> str:
    cp = _lookup_compact()
    parts: list[str] = []
    if context_html:
        parts.append(context_html)
        if cp:
            parts.append("<div style='height:10px'></div>")
        else:
            parts.append(
                "<hr style='border:none;border-top:1px solid #ccc;margin:12px 0'/>"
            )

    lemma = data.get("lemma") or clicked_fallback
    clicked = data.get("clicked") or clicked_fallback
    if cp:
        parts.append(
            "<p class='lk-caps'>查询形（与顶部所选词可能不同）</p>"
            f"<p style='margin:0 0 4px'><code style='font-size:16px'>{html.escape(str(lemma))}</code></p>"
        )
    else:
        parts.append(
            f"<p><b>点击形式</b>：<code>{html.escape(clicked)}</code>　"
            f"<b>查询形</b>：<code>{html.escape(str(lemma))}</code></p>"
        )

    src = data.get("source", "")
    if (
        not cp
        or data.get("error")
        or data.get("zh_fetch_error")
        or data.get("goroh_fetch_error")
        or data.get("ru_fetch_error")
    ):
        parts.append(f"<p><b>抓取状态</b>：{html.escape(str(src))}</p>")
    if data.get("error"):
        parts.append(f"<p style='color:#a00'>{html.escape(str(data['error']))}</p>")
    for k in ("zh_fetch_error", "goroh_fetch_error", "ru_fetch_error"):
        if data.get(k):
            parts.append(
                f"<p style='color:#666;font-size:14px'>{html.escape(k)}：{html.escape(str(data[k]))}</p>"
            )

    bkrs_g = list(data.get("bkrs_lines") or [])
    zh_g = list(data.get("zh_gloss_lines") or [])
    ru_g = list(data.get("ru_gloss_lines") or [])
    zh_u = data.get("zh_wiki_url") or ""
    uk_u = data.get("uk_wiki_url") or ""
    ru_u = data.get("ru_wiki_url") or ""
    ru_idx = data.get("ru_wikt_uk_index_url") or getattr(
        wp, "RU_WIKT_UKRAINIAN_INDEX_URL", ""
    )
    gh_u = data.get("goroh_url") or ""
    gh_lem_u = data.get("goroh_lemma_url") or gh_u
    goroh_lem = (data.get("goroh_lemma") or "").strip()
    bk_u = data.get("bkrs_url") or ""

    if goroh_lem and cp:
        parts.append("<p class='lk-caps'>乌克兰语原形（Горох）</p>")
        parts.append(f"<p class='lk-mean'>{html.escape(goroh_lem)}</p>")
        if gh_lem_u:
            parts.append(
                f"<p class='lk-foot'><a href='{html.escape(gh_lem_u, quote=True)}'>"
                "在 Горох 打开原形 · Словозміна</a></p>"
            )

    if bkrs_g:
        if cp:
            parts.append("<p class='lk-caps'>词义（大БКРС · 经俄语对应词）</p>")
            for i, ln in enumerate(bkrs_g[:8]):
                cls = "lk-mean" if i == 0 else "lk-more"
                parts.append(f"<p class='{cls}'>{html.escape(ln)}</p>")
            ru_q = (data.get("ru_lookup_word") or "").strip()
            lem_ru = (data.get("bkrs_lemma") or "").strip()
            if ru_q or lem_ru:
                note = []
                if ru_q:
                    note.append(f"俄语对应：{ru_q}")
                if lem_ru and lem_ru.lower() != ru_q.lower():
                    note.append(f"BKRS 原形：{lem_ru}")
                parts.append(
                    f"<p class='lk-foot'>{html.escape('；'.join(note))}</p>"
                )
        else:
            parts.append("<h4>大БКРС（bkrs.info）· 中文义项</h4><ul>")
            for ln in bkrs_g[:16]:
                parts.append(f"<li>{html.escape(ln)}</li>")
            parts.append("</ul>")

    primary = ""
    secondary = ""
    secondary_from_ru = False
    if zh_g and not bkrs_g:
        primary = _format_wiktionary_gloss_line(zh_g[0])
        if len(zh_g) > 1:
            secondary = _format_wiktionary_gloss_line(zh_g[1])
        elif ru_g:
            secondary = _format_wiktionary_gloss_line(ru_g[0])
            secondary_from_ru = True
    elif ru_g:
        primary = _format_wiktionary_gloss_line(ru_g[0])
        if len(ru_g) > 1:
            secondary = _format_wiktionary_gloss_line(ru_g[1])

    if (primary or secondary) and not bkrs_g:
        if cp:
            cap = "主释义"
            if primary and not zh_g and ru_g:
                cap = "主释义（俄语维基·乌克兰语节）"
            if primary:
                parts.append(f"<p class='lk-caps'>{html.escape(cap)}</p>")
                parts.append(f"<p class='lk-mean'>{html.escape(primary)}</p>")
            if secondary:
                if secondary_from_ru:
                    parts.append(
                        "<p class='lk-caps' style='margin-top:4px'>俄语维基摘录</p>"
                    )
                parts.append(f"<p class='lk-more'>{html.escape(secondary)}</p>")
        else:
            if zh_g:
                parts.append(
                    "<div style='border-left:3px solid #2d6cb5;padding:10px 12px;margin-bottom:12px;"
                    "background:#eef5fc;font-size:15px;line-height:1.55'>"
                    "<b>首条义项（未按乌克兰语形态筛选，请结合上句判断）</b><br/>"
                    f"{html.escape(_format_wiktionary_gloss_line(zh_g[0]))}</div>"
                )
                parts.append("<h4>汉语维基词典 · 「乌克兰语」义项（节选）</h4><ul>")
                for ln in zh_g[:12]:
                    parts.append(
                        f"<li>{html.escape(_format_wiktionary_gloss_line(ln))}</li>"
                    )
                parts.append("</ul>")
            if ru_g:
                parts.append(
                    "<h4>俄语维基词典 · 「乌克兰语」相关节义项（节选）</h4><ul>"
                )
                for ln in ru_g[:12]:
                    parts.append(
                        f"<li>{html.escape(_format_wiktionary_gloss_line(ln))}</li>"
                    )
                parts.append("</ul>")
    elif not bkrs_g:
        parts.append(
            "<p><i>未解析到 BKRS 中文义项，也未找到维基「乌克兰语」节摘录。</i></p>"
        )

    if cp:
        parts.append("<p class='lk-caps' style='margin-top:4px'>查全文</p>")
        lk: list[str] = []
        if bk_u:
            lk.append(f'<a href="{html.escape(bk_u, quote=True)}">大БКРС</a>')
        if gh_u:
            lk.append(f'<a href="{html.escape(gh_u, quote=True)}">Горох</a>')
        if zh_u:
            lk.append(f'<a href="{html.escape(zh_u, quote=True)}">汉语维基</a>')
        if ru_u:
            lk.append(f'<a href="{html.escape(ru_u, quote=True)}">俄语维基词条</a>')
        if ru_idx:
            lk.append(
                f'<a href="{html.escape(ru_idx, quote=True)}">俄语维基·乌语索引</a>'
            )
        if uk_u:
            lk.append(f'<a href="{html.escape(uk_u, quote=True)}">乌语维基</a>')
        if not lk:
            lk.append('<a href="https://goroh.pp.ua/">Горох（主页）</a>')
        parts.append("<div class='lk-links'>" + "".join(lk) + "</div>")
        parts.append(
            "<p class='lk-foot'>变格表与更多义项：用上面链接在浏览器打开。"
            "侧栏长版（含维基节选表格）：设置 <code>ARGOS_WORD_LOOKUP_VERBOSE=1</code> 后重启。</p>"
        )
    else:
        parts.append("<p>")
        if gh_u:
            parts.append(
                f'<a href="{html.escape(gh_u, quote=True)}">在浏览器打开 · Горох Словозміна</a>'
            )
        if gh_u and (zh_u or ru_u):
            parts.append("　|　")
        if zh_u:
            parts.append(
                f'<a href="{html.escape(zh_u, quote=True)}">在浏览器打开 · 汉语维基词条</a>'
            )
        if zh_u and ru_u:
            parts.append("　|　")
        if ru_u:
            parts.append(
                f'<a href="{html.escape(ru_u, quote=True)}">在浏览器打开 · 俄语维基词条</a>'
            )
        if ru_u and ru_idx:
            parts.append("　|　")
        if ru_idx:
            parts.append(
                f'<a href="{html.escape(ru_idx, quote=True)}">俄语维基 · 乌克兰语索引</a>'
            )
        if (ru_idx or ru_u) and uk_u:
            parts.append("　|　")
        if uk_u:
            parts.append(
                f'<a href="{html.escape(uk_u, quote=True)}">在浏览器打开 · 乌克兰语维基词条</a>'
            )
        parts.append("</p>")
        parts.append(
            "<p style='color:#555;font-size:14px;line-height:1.5'>变格表体例与 <a href=\"https://goroh.pp.ua/\">Горох</a> "
            "网站「Словозміна」一致；俄语维基体例见俄语维基词典。</p>"
        )

    tbl_cap = 0 if cp else None
    ght = data.get("goroh_tables") or []
    parts.extend(
        _tables_to_html(
            ght,
            "Горох（goroh.pp.ua）· Словозміна 变格表（节选，词形仅西里尔文）",
            cell_display=idisp.declension_cell_display,
            max_tables=tbl_cap,
        )
    )
    if not ght and not cp:
        parts.append(
            "<p><i>未从 Горох 解析到变格表，可点击上方链接在浏览器中查看。</i></p>"
        )

    zht = data.get("zh_html_tables") or []
    parts.extend(
        _tables_to_html(
            zht,
            "汉语维基词典 · 「乌克兰语」变格表（节选，若有，简体表头、词形仅西里尔文）",
            cell_display=idisp.declension_cell_display,
            max_tables=tbl_cap,
        )
    )

    rut = data.get("ru_html_tables") or []
    parts.extend(
        _tables_to_html(
            rut,
            "俄语维基词典 · 「乌克兰语」节变格表（节选，若有）",
            cell_display=idisp.declension_cell_display,
            max_tables=tbl_cap,
        )
    )

    return "\n".join(parts)


class WordLookupPanel(QWidget):
    """主窗口右侧：点击译文中的词后在此显示释义与变格（不弹窗）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WordLookupPanel")
        self.setMinimumWidth(260)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self._head = QLabel("查词")
        self._head.setObjectName("WordLookupHead")
        self._head.setWordWrap(True)
        self._zh_label = QLabel("")
        self._zh_label.setObjectName("MetaLabel")
        self._zh_label.setWordWrap(True)
        self._zh_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._morph_label = QLabel("")
        self._morph_label.setObjectName("MetaLabel")
        self._morph_label.setWordWrap(True)
        self._morph_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self._browser = QTextBrowser()
        self._browser.setObjectName("WordLookupBrowser")
        self._browser.setOpenExternalLinks(True)
        self._browser.setReadOnly(True)
        self._browser.setTextInteractionFlags(
            Qt.TextSelectableByMouse
            | Qt.TextSelectableByKeyboard
            | Qt.LinksAccessibleByMouse
        )
        self._browser.setFocusPolicy(Qt.StrongFocus)
        self._browser.setContextMenuPolicy(Qt.DefaultContextMenu)
        self._browser.setPlaceholderText("")
        self._browser.setLineWrapMode(QTextEdit.WidgetWidth)
        self._browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._browser.setMinimumHeight(260)
        self._browser.clear()
        self._browser.viewport().installEventFilter(self)

        self._btn_close = QPushButton("关闭")
        self._btn_close.setObjectName("TextAction")
        self._btn_close.setToolTip("关闭单词解析面板")
        self._btn_close.clicked.connect(self.close_panel)

        head_row = QHBoxLayout()
        head_row.setContentsMargins(0, 0, 0, 0)
        head_row.addWidget(self._head, 1)
        head_row.addWidget(self._btn_close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(10)
        lay.addLayout(head_row)
        lay.addWidget(self._zh_label)
        lay.addWidget(self._morph_label)
        lay.addWidget(self._browser, 1)

        self._thread: QThread | None = None
        self._word: str = ""
        self._ru_fetch_serial: int = 0
        self._uk_fetch_serial: int = 0
        self._ru_context_html: str = ""
        self._ru_sentence: str = ""
        self._ru_rel_s: int = 0
        self._ru_rel_e: int = 0
        self._ru_pos_hint: str | None = None
        self._ru_morph_detail: dict[str, Any] = {}
        self._ru_glossary_hit: bool = False
        self._ru_glossary: dict[str, Any] = {}
        self._ru_source_zh: str = ""
        self._uk_context_html: str = ""

        try:
            from portable_ui_theme import polish_widget

            polish_widget(self._browser)
        except ImportError:
            pass

        self.setVisible(False)
        self._show_idle_hint()

    def _sync_browser_text_width(self) -> None:
        """QTextDocument 默认按内容缩排；同步视口宽度后 HTML 表可铺满侧栏。"""
        vp = self._browser.viewport()
        w = max(vp.width() - 6, 220)
        doc = self._browser.document()
        if doc is not None and int(doc.textWidth()) != int(w):
            doc.setTextWidth(float(w))

    def _set_browser_html(self, html: str) -> None:
        self._browser.setHtml(html)
        QTimer.singleShot(0, self._sync_browser_text_width)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._browser.viewport() and event.type() == QEvent.Resize:
            self._sync_browser_text_width()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_browser_text_width()

    def _tab_page(self):
        page = getattr(self, "_translation_tab_page", None)
        if page is not None and hasattr(page, "show_word_lookup_panel"):
            return page
        p = self.parent()
        while p is not None:
            if hasattr(p, "show_word_lookup_panel"):
                return p
            p = p.parent()
        return None

    def reveal(self) -> None:
        """点击译文中的词时展开右侧独立查词栏（不压缩译文区）。"""
        page = self._tab_page()
        if page is not None:
            page.show_word_lookup_panel()
        else:
            self.setVisible(True)

    def close_panel(self) -> None:
        """关闭查词侧栏（可再次点击译文中的词打开）。"""
        self._cancel_thread()
        page = self._tab_page()
        if page is not None:
            page.hide_word_lookup_panel()
        else:
            self.setVisible(False)

    def _cancel_thread(self) -> None:
        """请求停止后台查词；不阻塞 UI，避免连续点击其他词时侧栏无反应。"""
        t = self._thread
        self._thread = None
        if t is not None and t.isRunning():
            t.requestInterruption()

    def show_from_notebook_entry(self, entry: dict) -> None:
        """生词本双击：直接展示已缓存的查词 HTML。"""
        self.reveal()
        word = str(entry.get("word") or "").strip()
        self._word = word
        self._head.setText(f"「{word}」" if word else "单词解析")
        self._cancel_thread()
        self._zh_label.hide()
        self._morph_label.hide()
        html = str(entry.get("panel_html") or "").strip()
        if html:
            self._set_browser_html(html)
        else:
            self._set_browser_html(
                _wrap_lookup_html("<p>（该条记录无缓存内容，请重新点击译文中的词）</p>", compact=True)
            )

    def _show_cached_lookup(self, lang: str, clicked_word: str) -> bool:
        entry = wls.get_entry(lang, clicked_word)
        if not entry or not str(entry.get("panel_html") or "").strip():
            return False
        panel_html = str(entry.get("panel_html") or "")
        if lang == "ru" and _ru_panel_html_needs_conj_refresh(panel_html):
            return False
        if lang == "ru" and _ru_panel_html_needs_lemma_stress_refresh(panel_html):
            return False
        if lang == "ru" and _ru_panel_html_needs_wiki_grammar_refresh(panel_html):
            return False
        if lang == "uk" and _uk_panel_html_needs_conj_refresh(panel_html):
            return False
        if lang == "uk" and _uk_panel_ru_lemma_stale(panel_html):
            return False
        self.show_from_notebook_entry(entry)
        wls.touch_entry(lang, clicked_word)
        return True

    def _save_lookup_to_notebook(
        self,
        lang: str,
        *,
        lemma: str,
        meaning: str,
        sentence_zh: str,
        panel_html: str,
    ) -> None:
        if not lookup_meaning_should_save_to_notebook(meaning):
            return
        try:
            wls.upsert_entry(
                lang=lang,
                word=self._word,
                lemma=lemma,
                meaning=meaning,
                sentence_zh=sentence_zh,
                panel_html=panel_html,
            )
        except Exception:
            pass

    def _show_idle_hint(self) -> None:
        self._head.setText("单词解析")
        self._zh_label.setText("")
        self._morph_label.setText("")
        self._zh_label.hide()
        self._morph_label.hide()
        self._set_browser_html(
            _wrap_lookup_html(
                "<p style='color:#666'>在<strong>原文或译文</strong>中单击俄语/乌克兰语单词，"
                "显示词义与对应中文句。</p>",
                compact=True,
            )
        )

    def show_russian(
        self,
        clicked_word: str,
        glossary: dict,
        *,
        sentence: str = "",
        rel_start: int = 0,
        rel_end: int = 0,
        clicked_in_source: bool = False,
    ) -> None:
        self.reveal()
        self._word = clicked_word
        self._head.setText(f"「{clicked_word}」")
        self._zh_label.hide()
        self._morph_label.hide()
        if self._show_cached_lookup("ru", clicked_word):
            self._cancel_thread()
            return
        self._cancel_thread()
        self._ru_morph_detail = russian_morph_detail(
            clicked_word,
            sentence,
            rel_start,
            rel_end,
        )
        self._ru_glossary_hit = bool(
            gm.glossary_zh_for_russian_click(clicked_word, glossary)
        )
        self._ru_glossary = glossary if isinstance(glossary, dict) else {}
        self._ru_clicked_in_source = bool(clicked_in_source)
        tab = self._tab_page()
        hint_zh = ""
        if tab is not None:
            try:
                if clicked_in_source:
                    hint_zh = tab.right_textEdit.toPlainText() or ""
                else:
                    hint_zh = tab.left_textEdit.toPlainText() or ""
            except Exception:
                pass
        self._ru_source_zh = hint_zh

        self._ru_sentence = sentence
        self._ru_rel_s = rel_start
        self._ru_rel_e = rel_end
        self._ru_context_html = ""

        self._ru_pos_hint = None
        try:
            morph = gm.shared_morph_analyzer()
            if morph is not None:
                ps = morph.parse(clicked_word.strip())
                if ps:
                    self._ru_pos_hint = ps[0].tag.POS
        except Exception:
            pass
        self._set_browser_html(
            _wrap_lookup_html("<p style='color:#888'>正在查询词义…</p>", compact=True)
        )

        self._ru_fetch_serial += 1
        serial = self._ru_fetch_serial
        th = _FetchThread(clicked_word, serial)
        self._thread = th
        th.done.connect(self._on_russian_data)
        th.start()

    @pyqtSlot(dict)
    def _on_russian_data(self, data: dict) -> None:
        try:
            self._apply_russian_data(data)
        except Exception as e:
            self._show_lookup_error(e)

    def _apply_russian_data(self, data: dict) -> None:
        th = self.sender()
        if th is not self._thread or not isinstance(th, _FetchThread):
            return
        if th._serial != self._ru_fetch_serial:
            return
        if _lookup_verbose():
            self._ru_morph_detail = _enrich_morph_from_wiki_grammar(
                russian_morph_detail(
                    self._word,
                    self._ru_sentence,
                    self._ru_rel_s,
                    self._ru_rel_e,
                ),
                data,
            )
            lemma0 = str(data.get("lemma") or self._word)
            lemma_s = str(data.get("lemma_stressed") or lemma0)
            sm = wp.build_ru_wiki_stress_map(lemma_s, lemma0, data.get("ru_html_tables"))
            cs = str(data.get("clicked_stressed") or self._word)
            sm[wp.ru_stress_key(self._word)] = cs
            ctx = ""
            if self._ru_sentence.strip():
                ctx = build_russian_sentence_context_html(
                    self._ru_sentence,
                    self._ru_rel_s,
                    self._ru_rel_e,
                    self._word,
                    source_zh_hint=self._ru_source_zh,
                    ru_stress_map=sm,
                )
            self._set_browser_html(
                _wrap_lookup_html(
                    build_russian_word_info_html(
                        data,
                        self._word,
                        context_html=ctx,
                        pos_hint=self._ru_pos_hint,
                        morph_detail=self._ru_morph_detail,
                        glossary_matched=self._ru_glossary_hit,
                        glossary=self._ru_glossary,
                    )
                )
            )
            return
        tab = self._tab_page()
        if getattr(self, "_ru_clicked_in_source", False):
            sent_zh = _parallel_target_zh_sentence(tab, self._ru_sentence)
        else:
            sent_zh = _parallel_source_zh_sentence(tab, self._ru_sentence)
        if not sent_zh.strip():
            sent_zh = (self._ru_source_zh or "").strip()
        md = _enrich_morph_from_wiki_grammar(
            russian_morph_detail(
                self._word,
                self._ru_sentence,
                self._ru_rel_s,
                self._ru_rel_e,
            ),
            data,
        )
        ctx_html = ""
        if self._ru_sentence.strip():
            lemma0 = str(data.get("lemma") or self._word)
            lemma_s = str(data.get("lemma_stressed") or lemma0)
            sm = wp.build_ru_wiki_stress_map(
                lemma_s, lemma0, data.get("ru_html_tables")
            )
            sm[wp.ru_stress_key(self._word)] = str(
                data.get("clicked_stressed") or self._word
            )
            ctx_html = build_russian_sentence_context_html(
                self._ru_sentence,
                self._ru_rel_s,
                self._ru_rel_e,
                self._word,
                source_zh_hint=sent_zh,
                ru_stress_map=sm,
            )
        sent_gram_html = build_ru_in_sentence_grammar_html(md, data)
        meaning = _word_meaning_zh_russian(data, self._ru_glossary, self._word)
        lemma = str(
            data.get("bkrs_lemma")
            or data.get("lemma")
            or data.get("lemma_stressed")
            or ""
        ).strip()
        conj_html = build_ru_conjugation_section_html(
            data,
            clicked=self._word,
            morph_detail=md,
        )
        gram_html = build_ru_wiki_grammar_html(data, clicked=self._word)
        html = build_minimal_lookup_html(
            meaning,
            lemma=lemma,
            clicked=self._word,
            conjugation_html=conj_html,
            wiki_grammar_html=gram_html,
            context_html=ctx_html,
            in_sentence_grammar_html=sent_gram_html,
        )
        self._set_browser_html(html)
        self._save_lookup_to_notebook(
            "ru",
            lemma=lemma,
            meaning=meaning,
            sentence_zh=sent_zh,
            panel_html=html,
        )

    def _show_lookup_error(self, err: BaseException) -> None:
        msg = html.escape(str(err) or type(err).__name__)
        self._set_browser_html(
            _wrap_lookup_html(
                f"<p style='color:#b00020'>查词时出错：{msg}</p>",
                compact=True,
            )
        )

    def show_ukrainian(
        self,
        clicked_word: str,
        glossary: dict,
        *,
        sentence: str = "",
        rel_start: int = 0,
        rel_end: int = 0,
        clicked_in_source: bool = False,
    ) -> None:
        self.reveal()
        self._word = clicked_word
        self._head.setText(f"「{clicked_word}」")
        self._zh_label.hide()
        self._morph_label.hide()
        _ = glossary
        self._uk_clicked_in_source = bool(clicked_in_source)
        if self._show_cached_lookup("uk", clicked_word):
            self._cancel_thread()
            return
        self._cancel_thread()
        self._uk_sentence = sentence
        self._uk_rel_s = rel_start
        self._uk_rel_e = rel_end
        self._set_browser_html(
            _wrap_lookup_html("<p style='color:#888'>正在查询词义…</p>", compact=True)
        )

        self._uk_fetch_serial += 1
        serial = self._uk_fetch_serial
        th = _FetchThreadUk(clicked_word, serial)
        self._thread = th
        th.done.connect(self._on_ukrainian_data)
        th.start()

    @pyqtSlot(dict)
    def _on_ukrainian_data(self, data: dict) -> None:
        try:
            self._apply_ukrainian_data(data)
        except Exception as e:
            self._show_lookup_error(e)

    def _apply_ukrainian_data(self, data: dict) -> None:
        th = self.sender()
        if th is not self._thread or not isinstance(th, _FetchThreadUk):
            return
        if th._serial != self._uk_fetch_serial:
            return
        if _lookup_verbose():
            ctx = (
                build_ukrainian_sentence_context_html(
                    self._uk_sentence,
                    self._uk_rel_s,
                    self._uk_rel_e,
                    self._word,
                )
                if self._uk_sentence.strip()
                else ""
            )
            self._set_browser_html(
                _wrap_lookup_html(
                    build_ukrainian_word_info_html(
                        data, self._word, context_html=ctx
                    )
                )
            )
            return
        tab = self._tab_page()
        if getattr(self, "_uk_clicked_in_source", False):
            sent_zh = _parallel_target_zh_sentence(tab, self._uk_sentence)
        else:
            sent_zh = _parallel_source_zh_sentence(tab, self._uk_sentence)
        meaning = _word_meaning_zh_ukrainian(data, self._word)
        lemma_uk = str(data.get("goroh_lemma") or data.get("lemma") or "").strip()
        lemma_ru = (
            str(data.get("bkrs_lemma") or data.get("lemma_ru") or "").strip()
        )
        conj_html = build_uk_goroh_section_html(data, clicked=self._word)
        gram_html = ""
        if lemma_ru:
            gram_data = {
                "ru_wiki_grammar": data.get("ru_wiki_grammar"),
                "ru_wiki_grammar_zh": data.get("ru_wiki_grammar_zh"),
                "ru_wiki_grammar_pair_zh": data.get("ru_wiki_grammar_pair_zh"),
                "ru_wiki_url": wp._wiki_index_url("ru", lemma_ru),
            }
            if not gram_data.get("ru_wiki_grammar_zh"):
                try:
                    wp.merge_ru_wiki_grammar(gram_data)
                except Exception:
                    pass
            gram_html = build_ru_wiki_grammar_html(gram_data, clicked=self._word)
        html = build_minimal_lookup_html(
            meaning,
            lemma=lemma_ru,
            lemma_uk=lemma_uk,
            lemma_uk_url=str(data.get("goroh_lemma_url") or data.get("goroh_url") or ""),
            clicked=self._word,
            conjugation_html=conj_html,
            wiki_grammar_html=gram_html,
            lemma_caption="俄语原形（BKRS）",
            bkrs_url=str(data.get("bkrs_url") or ""),
            meaning_from_bkrs=bool(data.get("bkrs_lines")),
        )
        self._set_browser_html(html)
        self._save_lookup_to_notebook(
            "uk",
            lemma=lemma_uk or lemma_ru or str(data.get("lemma") or "").strip(),
            meaning=meaning,
            sentence_zh=sent_zh,
            panel_html=html,
        )


class ClickableTranslationTextEdit(QTextEdit):
    """左键单击选中词：原文或译文中的西里尔词均在侧栏查词。"""

    def __init__(self, parent_window, *, role: str = "target"):
        super().__init__()
        self._parent_window = parent_window
        self._lookup_role = role if role in ("source", "target") else "target"
        self._pending_lookup_bounds: tuple[int, int] | None = None

    def _viewport_point_from_event(self, event) -> QPoint:
        vp = self.viewport()
        return vp.mapFrom(self, event.pos())

    def _word_rect_in_viewport(self, start: int, end: int):
        """词形在 viewport 中的像素矩形（QTextEdit.cursorRect 为控件坐标）。"""
        if end <= start:
            return None
        tc = self.textCursor()
        tc.setPosition(start)
        r0 = self.cursorRect(tc)
        tc.setPosition(end - 1)
        r1 = self.cursorRect(tc)
        r = r0.united(r1)
        vp = self.viewport()
        tl = vp.mapFrom(self, r.topLeft())
        br = vp.mapFrom(self, r.bottomRight())
        return tl, br

    def _block_for_viewport_point(self, pt: QPoint):
        """按 Y 坐标找文本块；避免点击行下方空白时 cursor 落到行尾。"""
        doc = self.document()
        best_block = None
        best_dy = 10**9
        for i in range(doc.blockCount()):
            block = doc.findBlockByNumber(i)
            if not block.isValid():
                continue
            cur = QTextCursor(block)
            r_top = self.cursorRect(cur)
            cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.MoveAnchor)
            r_bot = self.cursorRect(cur)
            top = min(r_top.top(), r_bot.top()) - 3
            bottom = max(r_top.bottom(), r_bot.bottom()) + 5
            if top <= pt.y() <= bottom:
                return block
            cy = (top + bottom) // 2
            dy = abs(pt.y() - cy)
            if dy < best_dy:
                best_dy = dy
                best_block = block
        return best_block

    def _pick_cyrillic_word_bounds_at_click(self, event) -> tuple[int, int] | None:
        """
        仅用视口像素选词，不用 cursorForPosition 的字符索引（高框点行下方会偏到行尾/别词）。
        """
        full = self.toPlainText()
        if not full:
            return None
        pt = self._viewport_point_from_event(event)
        block = self._block_for_viewport_point(pt)
        if block is None or not block.isValid():
            return None

        line_start = block.position()
        line_end = min(line_start + block.length() - 1, len(full))
        line_text = full[line_start:line_end]

        containing: list[tuple[int, int, float]] = []
        nearest: tuple[int, int, float] | None = None

        for m in wp._CYR_WORD_IN_TEXT.finditer(line_text):
            w0 = line_start + m.start()
            w1 = line_start + m.end()
            rect = self._word_rect_in_viewport(w0, w1)
            if rect is None:
                continue
            tl, br = rect
            if br.x() <= tl.x():
                continue
            hit_x0, hit_y0 = tl.x() - 3, tl.y() - 5
            hit_x1, hit_y1 = br.x() + 3, br.y() + 5
            cx = (tl.x() + br.x()) // 2
            cy = (tl.y() + br.y()) // 2
            in_hit = hit_x0 <= pt.x() <= hit_x1 and hit_y0 <= pt.y() <= hit_y1
            dist = abs(pt.x() - cx) + max(0, abs(pt.y() - cy) - (br.y() - tl.y())) * 2
            if in_hit:
                containing.append((w0, w1, dist))
            elif nearest is None or dist < nearest[2]:
                nearest = (w0, w1, dist)

        if containing:
            w0, w1, _ = min(containing, key=lambda x: x[2])
            return w0, w1

        if nearest is not None:
            w0, w1, dist = nearest
            rect = self._word_rect_in_viewport(w0, w1)
            if rect is not None:
                tl, br = rect
                width = max(br.x() - tl.x(), 8)
                if dist <= max(width * 2.5, 28):
                    return w0, w1
        return None

    def _run_word_lookup(self, w0: int, w1: int) -> None:
        full = self.toPlainText()
        if w0 >= w1:
            return
        raw = full[w0:w1].replace("\u2029", " ").strip()
        if not raw or _cyrillic_click_letters(raw) < 1:
            return
        mid = (w0 + w1) // 2 if full else 0
        s0, s1 = sentence_bounds(full, mid)
        sentence = full[s0:s1]
        rel_s, rel_e = w0 - s0, w1 - s0

        glossary = tb.load_glossary()
        tab = self._parent_window
        if self._lookup_role == "source":
            code = _source_input_lang_code(tab)
            in_source = True
        else:
            code = _target_output_lang_code(tab)
            in_source = False
        panel = getattr(tab, "_word_lookup_panel", None)
        if panel is None:
            return
        if code not in ("ru", "uk"):
            return
        kw = dict(
            sentence=sentence,
            rel_start=rel_s,
            rel_end=rel_e,
            clicked_in_source=in_source,
        )
        if code == "uk":
            panel.show_ukrainian(raw, glossary, **kw)
        else:
            panel.show_russian(raw, glossary, **kw)

    def mousePressEvent(self, event):
        """在 Qt 移动光标之前按像素定词，避免 release 后索引错位。"""
        if event.button() == Qt.LeftButton:
            self._pending_lookup_bounds = self._pick_cyrillic_word_bounds_at_click(
                event
            )
        else:
            self._pending_lookup_bounds = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton:
            return
        bounds = self._pending_lookup_bounds
        self._pending_lookup_bounds = None
        if bounds is None:
            return
        self._run_word_lookup(bounds[0], bounds[1])

    def keyPressEvent(self, event):
        if self._lookup_role == "source":
            from translation_source_edit import is_paste_plain_shortcut, paste_plain_into_text_edit

            if is_paste_plain_shortcut(event):
                paste_plain_into_text_edit(self)
                return
        elif self._lookup_role == "target":
            from translation_source_edit import (
                is_paste_plain_shortcut,
                is_paste_shortcut,
                paste_plain_into_text_edit,
            )

            if is_paste_plain_shortcut(event) or is_paste_shortcut(event):
                paste_plain_into_text_edit(self, for_target=True)
                return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:
        if self._lookup_role == "target":
            from translation_source_edit import insert_plain_from_mime

            if insert_plain_from_mime(self, source, for_target=True):
                return
        super().insertFromMimeData(source)
