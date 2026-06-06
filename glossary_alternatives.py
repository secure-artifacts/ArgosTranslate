"""
术语库解析：
- 源语（中文）/ ; 分隔 → 多种中文说法对应同一外语（翻译时任一侧均匹配）；
- 目标语单元格 / ; 换行、逗号（仅短词备选） 与括号 () → 多种外语译法（翻译时随机择一，可悬停改选）。
"""
from __future__ import annotations

import random
import re
from typing import Any, Iterable

_TOP_SEP = frozenset({"/", ";", "；", "\n"})
_COMMA_ALT_SEP = frozenset({",", "，"})
_SOURCE_ALIAS_SEP = frozenset({"/", ";", "；"})
_PAREN_SUFFIX = re.compile(r"^(.*?)\(([^()]+)\)\s*$")


def _split_at_seps(text: str, seps: frozenset[str]) -> list[str]:
    """按给定分隔符拆分，忽略括号内的分隔符。"""
    t = (text or "").strip()
    if not t:
        return []
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in t:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch in seps and depth == 0:
            seg = "".join(buf).strip()
            if seg:
                parts.append(seg)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts if parts else [t]


def split_top_level(text: str) -> list[str]:
    """目标语：按 / ; 换行拆分；短词逗号备选亦拆分（忽略括号内的分隔符）。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    parts = _split_at_seps(text, _TOP_SEP)
    if len(parts) > 1:
        return parts
    comma_parts = _split_at_seps(text, _COMMA_ALT_SEP)
    if len(comma_parts) > 1 and _looks_like_word_alternatives(comma_parts):
        return comma_parts
    return parts if parts else ([text.strip()] if text.strip() else [])


def _looks_like_word_alternatives(parts: list[str]) -> bool:
    """逗号分隔的若干单词 → 译法备选，而非短语或句子。"""
    if len(parts) < 2:
        return False
    for part in parts:
        t = (part or "").strip()
        if not t:
            return False
        words = re.findall(r"[А-Яа-яЁёA-Za-z\-']+", t)
        if len(words) != 1:
            return False
        if re.sub(r"\s+", "", t).casefold() != words[0].casefold():
            return False
    return True


def split_source_aliases(text: str) -> list[str]:
    """源语（中文）多别名：/ 或 ; 分隔，共用同一外语译法。"""
    return _split_at_seps(text, _SOURCE_ALIAS_SEP)


def list_source_aliases(source_key: str) -> list[str]:
    """术语库 JSON 键中的全部可匹配中文片段（去重、保序）。"""
    key = (source_key or "").strip()
    if not key:
        return []
    parts = split_source_aliases(key)
    if len(parts) <= 1:
        return [key]
    return _dedupe_options(parts)


def expand_segment(segment: str) -> list[str]:
    """展开单段：无括号则原样；有 (a/b) 则与段首词组合。"""
    seg = (segment or "").strip()
    if not seg:
        return []
    m = _PAREN_SUFFIX.match(seg)
    if not m:
        return [seg]
    base = m.group(1).strip()
    inners = split_top_level(m.group(2))
    out: list[str] = []
    for inner in inners:
        inner = inner.strip()
        if not inner:
            continue
        out.append(f"{base} {inner}".strip() if base else inner)
    return out or [seg]


def list_all_options(raw: str) -> list[str]:
    """术语库一行内的全部可选译法（去重、保序）。"""
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    has_top_sep = any(c in text for c in _TOP_SEP)
    has_paren = "(" in text
    if not has_top_sep and not has_paren:
        comma_parts = _split_at_seps(text, _COMMA_ALT_SEP)
        if len(comma_parts) > 1 and _looks_like_word_alternatives(comma_parts):
            return _dedupe_options([p.strip() for p in comma_parts])
        return [text]
    opts: list[str] = []
    seen: set[str] = set()
    for seg in split_top_level(text):
        for opt in expand_segment(seg):
            key = opt.casefold()
            if key not in seen:
                seen.add(key)
                opts.append(opt)
    return opts or [text]


def _dedupe_options(opts: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for opt in opts:
        t = (opt or "").strip()
        if not t:
            continue
        key = t.casefold()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _option_strings_from_stored_value(val: Any) -> list[str]:
    """从 JSON 字段（字符串 / 列表 / 结构化 dict）提取可展示的原文行。"""
    if val is None:
        return []
    if isinstance(val, list):
        rows: list[str] = []
        for item in val:
            rows.extend(_option_strings_from_stored_value(item))
        return rows
    if isinstance(val, dict):
        s = str(val.get("surface") or val.get("lemma") or "").strip()
        return [s] if s else []
    s = str(val).strip()
    return [s] if s else []


def stored_rows_as_strings(val: Any) -> list[str]:
    """JSON 中一条目标语字段（字符串 / 列表 / dict）对应的各行原文。"""
    return _option_strings_from_stored_value(val)


def list_options_from_entry(entry: Any, lang_code: str) -> list[str]:
    """合并「多行外语 + 单元格内 / ; ()」后的全部译法选项。"""
    code = (lang_code or "").strip().lower()
    if entry is None:
        return []
    opts: list[str] = []
    if isinstance(entry, str):
        opts.extend(list_all_options(entry))
        return _dedupe_options(opts)
    if not isinstance(entry, dict):
        s = str(entry).strip()
        return list_all_options(s) if s else []
    val = None
    for k, v in entry.items():
        if isinstance(k, str) and k.strip().lower() == code:
            val = v
            break
    if val is None:
        val = entry.get("default")
    if isinstance(val, list):
        for row in _option_strings_from_stored_value(val):
            opts.extend(list_all_options(row))
    else:
        for row in _option_strings_from_stored_value(val):
            opts.extend(list_all_options(row))
    return _dedupe_options(opts)


def pick_default(raw: str) -> str:
    """兼容：取第一个完整选项。"""
    opts = list_all_options(raw)
    return opts[0] if opts else (raw or "").strip()


def pick_random(options: list[str]) -> tuple[str, int]:
    """从全部译法选项中随机择一，返回 (选项, 下标)。"""
    opts = _dedupe_options(list(options or []))
    if not opts:
        return "", 0
    idx = random.randrange(len(opts))
    return opts[idx], idx


def pick_for_translation(entry: Any, lang_code: str) -> tuple[str, list[str], int]:
    """翻译时随机选一；返回 (选中项, 全部选项, 下标)。"""
    opts = list_options_from_entry(entry, lang_code)
    if not opts:
        return "", [], 0
    chosen, idx = pick_random(opts)
    return chosen, opts, idx


_ROLE_POS_ORDER: dict[str, tuple[str, ...]] = {
    "object": ("noun", "other", "verb", "adj"),
    "predicate": ("verb", "adj", "noun", "other"),
    "modifier": ("adj", "noun", "other", "verb"),
    "adverb": ("adj", "other", "noun", "verb"),
}


def _pos_bucket_for_option(opt: str, lang_code: str) -> str:
    try:
        from glossary_manager import infer_pos_for_target

        return infer_pos_for_target(opt, lang_code)
    except ImportError:
        return "noun"


def pos_bucket_for_option(opt: str, lang_code: str) -> str:
    return _pos_bucket_for_option(opt, lang_code)


def pos_bucket_changed(old_opt: str, new_opt: str, lang_code: str) -> bool:
    return _pos_bucket_for_option(old_opt, lang_code) != _pos_bucket_for_option(
        new_opt, lang_code
    )


def pick_option_for_role(
    options: list[str],
    lang_code: str,
    role: str,
) -> tuple[str, int]:
    """按语法角色从备选译法中择一（优先匹配词性，同词性再随机）。"""
    opts = _dedupe_options(list(options or []))
    if not opts:
        return "", 0
    order = _ROLE_POS_ORDER.get((role or "").strip().lower(), _ROLE_POS_ORDER["object"])
    code = (lang_code or "").strip().lower()
    for bucket in order:
        matched = [o for o in opts if _pos_bucket_for_option(o, code) == bucket]
        if not matched:
            continue
        chosen = matched[0]
        for o in opts:
            if o in matched:
                chosen = o
                break
        return chosen, opts.index(chosen)
    chosen, idx = pick_random(opts)
    return chosen, idx


def pick_for_translation_by_role(
    entry: Any,
    lang_code: str,
    role: str,
) -> tuple[str, list[str], int]:
    """翻译时按中文/句法角色选择最匹配词性的译法。"""
    opts = list_options_from_entry(entry, lang_code)
    if not opts:
        return "", [], 0
    chosen, idx = pick_option_for_role(opts, lang_code, role)
    return chosen, opts, idx


def chosen_index(raw: str, chosen: str) -> int:
    """当前选中的选项在 list_all_options 中的下标。"""
    opts = list_all_options(raw)
    key = (chosen or "").strip().casefold()
    for i, opt in enumerate(opts):
        if opt.casefold() == key:
            return i
    return 0


def has_multiple_options(raw: str) -> bool:
    return len(list_all_options(raw)) > 1


def entry_has_multiple_options(entry: Any, lang_code: str) -> bool:
    return len(list_options_from_entry(entry, lang_code)) > 1


def inflect_option(
    option: str,
    lang: str,
    context_before: str,
    context_after: str,
    *,
    fixed_grammemes: Iterable[str] | None = None,
    pos_hint: str | None = None,
    words: list | None = None,
) -> str:
    """将选项原形按上下文变格（俄/乌）。"""
    code = (lang or "").strip().lower()
    opt = (option or "").strip()
    if not opt:
        return ""
    if code not in ("ru", "uk"):
        return opt
    try:
        import glossary_inflection as gi
    except ImportError:
        return opt
    use_words: list | None = None
    try:
        phrase = gi.analyze_slavic_phrase(opt, code)
        parsed = phrase.get("words") if isinstance(phrase.get("words"), list) else None
        if parsed:
            use_words = parsed
    except Exception:
        use_words = None
    if use_words is None and isinstance(words, list) and words:
        first = words[0] if isinstance(words[0], dict) else {}
        if (first.get("lemma") or "").strip().casefold() == opt.casefold():
            use_words = words
    return gi.inflect_glossary_term(
        opt,
        code,
        context_before,
        context_after,
        fixed_grammemes=list(fixed_grammemes) if fixed_grammemes else None,
        pos_hint=pos_hint,
        words=use_words,
    )
