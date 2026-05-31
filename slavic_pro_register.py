"""
书面/专业文体规范化（国际用法参考：Sussex Blok、Oxford Russian Grammar、
Chicago Manual 俄文版惯例、欧盟多语文档排版惯例）。

与形态变格互补：搭配 calque、重复词、破折号、公文套语。
"""
from __future__ import annotations

import os
import re

_GLOSSA = re.compile(r"GLOSSA|ＧＬＯＳＳＡ|ГЛОССА", re.I)

# 俄文长破折号：对话/插入语 — 两侧空格（出版惯例）
_EM_DASH_SPACED = re.compile(r"\s*—\s*")
# 错误连字符代替破折号
_HYPHEN_AS_DASH = re.compile(r"\s+-\s+(?=[А-ЯA-Z«\"])")

# 模型偶发重复词
_DUP_WORD = re.compile(
    r"\b([А-Яа-яЁёІіЇїЄєҐґ]{2,})\s+\1\b",
    re.I,
)

# 数字与单位/货币：专业排版 NBSP 已由 translation_quality 处理；此处修 common calques
_RU_PRO_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bна данный момент\b", "в настоящее время"),
    (r"\bв данный момент\b", "в настоящее время"),
    (r"\bв настоящий момент\b", "в настоящее время"),
    (r"\bв соответствии к\b", "в соответствии с"),
    (r"\bсогласно с\b", "согласно"),
    (r"\bблагодаря за\b", "благодаря"),
    (r"\bнесмотря на на\b", "несмотря на"),
    (r"\bв течении\b", "в течение"),
    (r"\bна протяжении\b", "на протяжении"),
    (r"\bв случай\b", "в случае"),
    (r"\bотносительно к\b", "относительно"),
    (r"\bкасательно к\b", "касательно"),
    (r"\bпредставляет из себя\b", "представляет собой"),
    (r"\bявляется является\b", "является"),
    (r"\bможет быть может быть\b", "может быть"),
    (r"\bthat is to say\b", "то есть"),
    (r"\bas well as\b", "а также"),
    (r"\bbased on\b", "на основе"),
    (r"\bdue to\b", "в связи с"),
    (r"\bwith regard to\b", "относительно"),
    (r"\bin terms of\b", "с точки зрения"),
    (r"\bin order to\b", "для того чтобы"),
    (r"\betc\.\b", "и т. д."),
    (r"\bi\.e\.\b", "т. е."),
    (r"\be\.g\.\b", "напр."),
)

_UK_PRO_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bна даний момент\b", "наразі"),
    (r"\bв даний момент\b", "наразі"),
    (r"\bвідповідно до до\b", "відповідно до"),
    (r"\bзгідно з з\b", "згідно з"),
    (r"\bу випадок\b", "у випадку"),
    (r"\bthat is to say\b", "тобто"),
    (r"\bas well as\b", "а також"),
    (r"\bbased on\b", "на основі"),
    (r"\bdue to\b", "у зв'язку з"),
    (r"\bin order to\b", "для того щоб"),
    (r"\betc\.\b", "тощо"),
    (r"\bi\.e\.\b", "тобто"),
    (r"\be\.g\.\b", "напр."),
)


def pro_register_fix_enabled() -> bool:
    v = os.environ.get("ARGOS_SLAVIC_PRO_REGISTER", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


def _apply_regex_pairs(text: str, pairs: tuple[tuple[str, str], ...]) -> str:
    out = text
    for pat, repl in pairs:
        out = re.sub(pat, repl, out, flags=re.I)
    return out


def _normalize_em_dash_ru(text: str) -> str:
    """出版级破折号： «—» 两侧单空格。"""
    t = _HYPHEN_AS_DASH.sub(" — ", text)
    t = _EM_DASH_SPACED.sub(" — ", t)
    t = re.sub(r" {2,}—", " —", t)
    t = re.sub(r"— {2,}", "— ", t)
    return t


def _dedupe_adjacent_words(text: str) -> str:
    prev = None
    for _ in range(3):
        nxt = _DUP_WORD.sub(r"\1", text)
        if nxt == prev:
            break
        prev = nxt
        text = nxt
    return text


def restore_frozen_professional_phrases(text: str, lang: str) -> str:
    """形态修补后恢复不可变公文套语（в настоящее время 等）。"""
    if not text:
        return text
    code = (lang or "").strip().lower()
    if code == "ru":
        pairs = (
            (r"\bв\s+настоящего\s+времени\b", "в настоящее время"),
            (r"\bв\s+настоящем\s+времени\b", "в настоящее время"),
            (r"\bв\s+данный\s+момент\b", "в настоящее время"),
            (r"\bхристос\s+воскресе\b", "Христос воскрес!"),
            (r"\bвоистину\s+воскресе\b", "Воистину воскрес!"),
            (r"\bгосподи\s+помилуй\b", "Господи, помилуй"),
            (r"\bслава\s+богу\b", "Слава Богу"),
            (r"\bотче\s+наш\b", "Отче наш"),
        )
    elif code == "uk":
        pairs = (
            (r"\bна\s+даний\s+момент\b", "наразі"),
            (r"\bв\s+даний\s+момент\b", "наразі"),
            (r"\bхристос\s+воскрес\b", "Христос воскрес!"),
            (r"\bвоістину\s+воскрес\b", "Воістину воскрес!"),
            (r"\bгосподи\s+помилуй\b", "Господи, помилуй"),
            (r"\bслава\s+богу\b", "Слава Богу"),
            (r"\bотче\s+наш\b", "Отче наш"),
        )
    else:
        return text
    out = text
    for pat, repl in pairs:
        out = re.sub(pat, repl, out, flags=re.I)
    return out


def apply_pro_register_fixes(text: str, lang: str) -> str:
    if not text or not pro_register_fix_enabled():
        return text
    if _GLOSSA.search(text):
        return text
    code = (lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return text
    t = text
    pairs = _RU_PRO_REPLACEMENTS if code == "ru" else _UK_PRO_REPLACEMENTS
    t = _apply_regex_pairs(t, pairs)
    t = _dedupe_adjacent_words(t)
    if code == "ru":
        t = _normalize_em_dash_ru(t)
    return t
