"""
中文 → 俄语/乌克兰语 Argos 强化：双向术语、新闻/外交句式、禁止跨轨混用。

与 slavic_to_zh_enhance 对称；不新增 UI，仅后处理链。
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

from bidirectional_terminology import (
    apply_zh_to_slavic_terminology,
    prevent_cross_track_mixing,
)
from terminology_registry import normalize_source_lang

_IDIOMS = Path(__file__).resolve().parent / "data" / "idioms" / "zh_news_slavic.json"


def zh_to_slavic_enhance_enabled() -> bool:
    v = os.environ.get("ARGOS_ZH_TO_SLAVIC_ENHANCE", "1").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    try:
        import slavic_translation_enhance as ste

        return ste.argos_slavic_enhance_enabled()
    except ImportError:
        return True


@lru_cache(maxsize=2)
def _diplomatic_items(target_lang: str) -> tuple[dict, ...]:
    if not _IDIOMS.is_file():
        return tuple()
    try:
        data = json.loads(_IDIOMS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return tuple()
    key = "zh_ru" if normalize_source_lang(target_lang) == "ru" else "zh_uk"
    return tuple(x for x in (data.get(key) or []) if isinstance(x, dict))


def apply_diplomatic_news_calques(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """整句外交/新闻 calque 修正（源文含 zh 短语时）。"""
    if not source_text or not target_text:
        return target_text
    lang = normalize_source_lang(target_lang)
    if lang not in ("ru", "uk"):
        return target_text
    src = source_text.strip()
    out = target_text
    items = sorted(
        _diplomatic_items(lang),
        key=lambda it: -len(str(it.get("zh") or "")),
    )
    for item in items:
        zh = str(item.get("zh") or "").strip()
        right = str(item.get("right") or "").strip()
        if not zh or not right or zh not in src:
            continue
        if right.lower() in out.lower():
            continue
        replaced = False
        for bad in item.get("calques") or []:
            bs = str(bad).strip()
            if bs and bs.lower() in out.lower():
                out = re.sub(re.escape(bs), right, out, flags=re.IGNORECASE)
                replaced = True
                break
        if not replaced and len(zh) >= 10 and zh in src:
            out = right
    return out


def postprocess_zh_to_slavic(
    text: str,
    target_lang: str,
    *,
    source_text: str | None = None,
) -> str:
    if not text or not zh_to_slavic_enhance_enabled():
        return text
    lang = normalize_source_lang(target_lang)
    if lang not in ("ru", "uk"):
        return text
    src = source_text or ""

    t = apply_zh_to_slavic_terminology(text, lang, source_text=src)
    t = prevent_cross_track_mixing(t, lang, source_text=src)

    try:
        import slavic_idioms as si

        if si.slavic_idiom_fix_enabled():
            t = si.apply_zh_name_transliteration_fix(src, t, lang)
    except ImportError:
        pass

    t = apply_diplomatic_news_calques(src, t, lang)

    try:
        import slavic_idioms as si

        if si.slavic_idiom_fix_enabled():
            t = si.apply_zh_source_idiom_hints(src, t, lang)
            t = si.apply_zh_colloquial_sentence_repairs(src, t, lang)
    except ImportError:
        pass

    # 母语润色：collocation → style rerank → anti-MT
    try:
        from native_fluency_pipeline import post_edit_native

        t = post_edit_native(t, lang, source_text=src)
    except ImportError:
        pass

    try:
        import slavic_idioms as si

        if si.slavic_idiom_fix_enabled():
            t = si.apply_zh_colloquial_sentence_repairs(src, t, lang)
    except ImportError:
        pass

    t = prevent_cross_track_mixing(t, lang, source_text=src)
    return t.strip() if t else t
