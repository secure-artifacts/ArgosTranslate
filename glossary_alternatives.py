"""
术语库目标语单元格：解析 /、; 与括号 () 中的多义选项；
同一中文多行外语条目合并后同样视为多义。

规则：
- 顶层用 / 或 ; 分隔多种译法（任选其一）；
- 某段末尾可带 (a/b) 表示该译法下的词形/用词变体；
- 同时出现时：先按 / 或 ; 拆成主选项，再展开括号内变体；
- 翻译时在全部选项中随机择一（用户可在译文区悬停改选）。
"""
from __future__ import annotations

import random
import re
from typing import Any, Iterable

_TOP_SEP = frozenset({"/", ";", "；"})
_PAREN_SUFFIX = re.compile(r"^(.*?)\(([^()]+)\)\s*$")


def split_top_level(text: str) -> list[str]:
    """按 / ; 拆分，忽略括号内的分隔符。"""
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
        elif ch in _TOP_SEP and depth == 0:
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
    text = (raw or "").strip()
    if not text:
        return []
    if not any(c in text for c in _TOP_SEP) and "(" not in text:
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
    return gi.inflect_glossary_term(
        opt,
        code,
        context_before,
        context_after,
        fixed_grammemes=list(fixed_grammemes) if fixed_grammemes else None,
        pos_hint=pos_hint,
        words=words if isinstance(words, list) else None,
    )
