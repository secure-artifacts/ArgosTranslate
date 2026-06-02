"""
术语优先级注册表（专名 > 军事 > 政治 > 语言规则 > 模型）。

俄/乌→中文：按源语分轨（uk 不得套用 ru 专名，如 Олександр≠亚历山大）。
查词前对词形做 lemma 归一（pymorphy2 / 乌语词典）。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
_TERM_DIR = _ROOT / "data" / "terminology"

_TERM_CATEGORIES = ("political", "military", "entities", "daily", "places")
_RU_WORD = re.compile(
    r"[А-Яа-яЁё][А-Яа-яЁё'\u02BC\u2019\u02B9\-]*"
)
_UK_WORD = re.compile(
    r"[А-Яа-яІіЇїЄєҐґ][А-Яа-яІіЇїЄєҐґ'\u02BC\u2019\u02B9\-]*"
)


def normalize_source_lang(code: str) -> str:
    c = (code or "").strip().lower()
    if c in ("uk", "ua", "ukr"):
        return "uk"
    if c in ("ru", "rus"):
        return "ru"
    return c


def _data_path(name: str) -> Path:
    return _TERM_DIR / name


@lru_cache(maxsize=1)
def _load_entities_and_terms() -> dict[str, Any]:
    p = _data_path("entities_and_terms.json")
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _fallback_lemma(token: str, lang: str) -> str:
    """无 pymorphy 时的保守词尾剥离（专名/术语）。"""
    w = (token or "").strip()
    if len(w) < 4:
        return w
    lang = normalize_source_lang(lang)
    suffixes_ru = (
        "ского",
        "скому",
        "ским",
        "ском",
        "ами",
        "ах",
        "ях",
        "ам",
        "ом",
        "ем",
        "ой",
        "ей",
        "ию",
        "ия",
        "ию",
        "ов",
        "ев",
        "ах",
        "у",
        "а",
        "е",
        "ы",
        "и",
        "ю",
    )
    suffixes_uk = suffixes_ru + ("і", "ї", "є", "ів", "ям", "ями")
    for suf in suffixes_uk if lang == "uk" else suffixes_ru:
        if w.endswith(suf) and len(w) > len(suf) + 2:
            return w[: -len(suf)]
    return w


def _lemma_for_token(token: str, lang: str) -> str:
    w = (token or "").strip()
    if not w or not w[0].isalpha():
        return w
    lang = normalize_source_lang(lang)
    try:
        if lang == "ru":
            import glossary_inflection as gi

            m = gi._morph_ru()
            if m is None:
                return w
            parses = m.parse(w)
            if parses:
                return (parses[0].normal_form or w).strip()
        if lang == "uk":
            import glossary_inflection as gi

            m = gi._shared_uk_morph_analyzer()
            if m is None:
                return w
            parses = m.parse(w)
            if parses:
                return (parses[0].normal_form or w).strip()
    except Exception:
        pass
    return _fallback_lemma(w, lang)


@lru_cache(maxsize=4)
def _build_form_index(lang: str) -> dict[str, str]:
    """变格形式.lower() -> zh"""
    lang = normalize_source_lang(lang)
    if lang not in ("ru", "uk"):
        return {}
    data = _load_entities_and_terms()
    block = data.get(lang) or {}
    index: dict[str, str] = {}
    for category in _TERM_CATEGORIES:
        for item in block.get(category) or []:
            if not isinstance(item, dict):
                continue
            zh = str(item.get("zh") or "").strip()
            lem = str(item.get("lemma") or "").strip()
            if not zh:
                continue
            if lem:
                index[lem.lower()] = zh
            for f in item.get("forms") or []:
                fs = str(f).strip()
                if fs:
                    index[fs.lower()] = zh
    return index


@lru_cache(maxsize=4)
def _build_lemma_index(lang: str) -> dict[str, str]:
    """lemma.lower() -> zh（后加载覆盖先加载：entities > military > political）。"""
    lang = normalize_source_lang(lang)
    if lang not in ("ru", "uk"):
        return {}
    data = _load_entities_and_terms()
    block = data.get(lang) or {}
    index: dict[str, str] = {}
    for category in _TERM_CATEGORIES:
        items = block.get(category) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            lem = str(item.get("lemma") or "").strip()
            zh = str(item.get("zh") or "").strip()
            if lem and zh:
                index[lem.lower()] = zh
    return index


@lru_cache(maxsize=4)
def _build_phrase_list(lang: str) -> list[tuple[str, str]]:
    """多词专名，按 lemma 长度降序。"""
    lang = normalize_source_lang(lang)
    if lang not in ("ru", "uk"):
        return []
    data = _load_entities_and_terms()
    block = data.get(lang) or {}
    phrases: list[tuple[str, str]] = []
    for category in _TERM_CATEGORIES:
        for item in block.get(category) or []:
            if not isinstance(item, dict):
                continue
            lem = str(item.get("lemma") or "").strip()
            zh = str(item.get("zh") or "").strip()
            if lem and zh and " " in lem:
                phrases.append((lem, zh))
    phrases.sort(key=lambda x: -len(x[0]))
    return phrases


def _user_glossary_zh_pairs(source_lang: str) -> list[tuple[str, str]]:
    """用户术语库：外语 lemma → 中文（仅匹配源语方向 ru/uk→zh 的条目）。"""
    pairs: list[tuple[str, str]] = []
    try:
        import terminology_bridge as tb

        g = tb.load_glossary()
    except Exception:
        return pairs
    if not isinstance(g, dict):
        return pairs
    lang = normalize_source_lang(source_lang)
    for _key, entry in g.items():
        if not isinstance(entry, dict):
            continue
        zh = str(entry.get("zh") or entry.get("source") or "").strip()
        if not zh:
            continue
        for code in ("ru", "uk"):
            if code != lang:
                continue
            cell = entry.get(code)
            if isinstance(cell, str) and cell.strip():
                pairs.append((cell.strip(), zh))
            elif isinstance(cell, dict):
                lem = str(cell.get("lemma") or "").strip()
                if lem:
                    pairs.append((lem, zh))
    pairs.sort(key=lambda x: -len(x[0]))
    return pairs


def apply_priority_terminology_to_zh(
    text: str,
    source_lang: str,
    *,
    source_text: str | None = None,
) -> str:
    """
    将俄/乌译文中的专名/术语替换为标准中文（优先级：用户术语库 > 内置实体 > 军事 > 政治）。
    """
    if not (text or "").strip():
        return text
    lang = normalize_source_lang(source_lang)
    if lang not in ("ru", "uk"):
        return text

    out = text
    # 1) 用户术语库（最高）
    for foreign, zh in _user_glossary_zh_pairs(lang):
        if foreign in out:
            out = re.sub(
                re.escape(foreign),
                zh,
                out,
                flags=re.IGNORECASE,
            )

    # 2) 多词短语
    for phrase, zh in _build_phrase_list(lang):
        if phrase in out:
            out = out.replace(phrase, zh)

    index = _build_lemma_index(lang)
    forms = _build_form_index(lang)
    word_re = _UK_WORD if lang == "uk" else _RU_WORD

    def _repl(m: re.Match[str]) -> str:
        w = m.group(0)
        zh = forms.get(w.lower())
        if zh:
            return zh
        lem = _lemma_for_token(w, lang)
        zh = index.get(lem.lower()) or index.get(w.lower())
        if zh:
            return zh
        return w

    out = word_re.sub(_repl, out)
    return out


def cross_lang_conflicts() -> list[tuple[str, str, str]]:
    """俄/乌同概念不同中文译名（用于 QA，不自动混用）。"""
    ru_i = _build_lemma_index("ru")
    uk_i = _build_lemma_index("uk")
    out: list[tuple[str, str, str]] = []
    for key in set(ru_i) & set(uk_i):
        if ru_i[key] != uk_i[key]:
            out.append((key, ru_i[key], uk_i[key]))
    return out
