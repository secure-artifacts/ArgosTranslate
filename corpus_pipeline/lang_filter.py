"""TM / 审核队列：中文、俄语、乌克兰语筛选（无 GUI 依赖）。"""
from __future__ import annotations

LANG_OPTIONS: tuple[tuple[str, str], ...] = (
    ("", "全部"),
    ("zh", "中文"),
    ("ru", "俄语"),
    ("uk", "乌克兰语"),
)


def norm_filter_code(code: str) -> str:
    c = (code or "").strip().lower()
    if not c:
        return ""
    if c in ("zh", "zt", "cn", "zho"):
        return "zh"
    if c in ("ua", "ukr"):
        return "uk"
    if c == "rus":
        return "ru"
    return c


def pair_filter_codes(
    source_lang: str,
    target_lang: str,
) -> tuple[str | None, str | None]:
    """归一化筛选用语言码；空字符串表示不限制该侧。"""
    sl = norm_filter_code(source_lang)
    tl = norm_filter_code(target_lang)
    if sl and tl:
        try:
            from bidirectional_terminology import lookup_tm_langs

            sl, tl = lookup_tm_langs(sl, tl)
        except ImportError:
            pass
    return (sl or None), (tl or None)


def row_matches_lang_filter(
    row: dict,
    *,
    source_lang: str | None,
    target_lang: str | None,
) -> bool:
    if source_lang and norm_filter_code(str(row.get("source_lang") or "")) != source_lang:
        return False
    if target_lang and norm_filter_code(str(row.get("target_lang") or "")) != target_lang:
        return False
    return True
