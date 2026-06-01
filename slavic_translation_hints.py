"""
中↔俄/乌翻译强化说明（Ollama 提示词与 Argos 后处理共用数据源）。
"""
from __future__ import annotations


def is_zh_to_slavic(from_code: str, to_code: str) -> bool:
    src = (from_code or "").strip().lower()
    tgt = (to_code or "").strip().lower()
    return src in ("zh", "zt", "cn", "zho") and tgt in ("ru", "uk")


def is_slavic_target(lang_code: str) -> bool:
    return (lang_code or "").strip().lower() in ("ru", "uk")


def ollama_pair_hints(from_code: str, to_code: str) -> str:
    """供 Ollama/Qwen 使用的语言对补充说明。"""
    if is_zh_to_slavic(from_code, to_code):
        try:
            import zh_to_slavic_enhance as zts

            track_hint = zts.ollama_zh_to_slavic_system_appendix(to_code)
        except ImportError:
            track_hint = chinese_to_slavic_hint()
        return "\n".join(
            (
                track_hint,
                religious_register_hint(),
                translation_priority_hint(),
            )
        )
    tgt = (to_code or "").strip().lower()
    src = (from_code or "").strip().lower()
    if tgt in ("zh", "zt", "cn") and src in ("ru", "uk"):
        try:
            import slavic_to_zh_enhance as stz

            return stz.ollama_slavic_to_zh_system_appendix()
        except ImportError:
            return (
                "Russian/Ukrainian→Chinese: international news style; "
                "distinguish uk vs ru proper names; no word-for-word calques."
            )
    if tgt in ("zh", "zt") and src in ("ru", "uk", "en", "fr", "de", "es"):
        return (
            "When the source uses culture-specific idioms or figurative speech, "
            "render the pragmatic meaning in natural Simplified Chinese."
        )
    if src == "en" or tgt == "en":
        return (
            "English phrasal verbs, idioms, and figurative compounds require "
            "sense-based translation, not literal decomposition."
        )
    return ""


def chinese_to_slavic_hint() -> str:
    return (
        "Chinese→Slavic: chengyu, classical allusions, and poetic imagery "
        "need idiomatic target-language equivalents, not character-by-character "
        "or image-by-image calques. Pay strict attention to Russian/Ukrainian "
        "case government, adjective–noun agreement, and verb conjugation in "
        "every sentence—not only for terminology placeholders."
    )


def translation_priority_hint() -> str:
    return (
        "Priority: user glossary > military/political term DB > language rules > "
        "free translation. Never override glossary placeholders. "
        "Natural target language; no word-for-word calques; no PRC machine-translation "
        "political phrasing when international standard Chinese exists."
    )


def religious_register_hint() -> str:
    return (
        "Christian religious text (Orthodox / Catholic / Protestant): choose "
        "register by context. Orthodox: Божественная литургия, храм, Богородица, "
        "Причастие, Пасха, патриарх. Catholic: месса, папа римский, кардинал, "
        "Ватикан; still молиться (not делать молитву). Protestant: пастор, "
        "проповедь, церковь. Capitalize theonyms and fixed phrases (Слава Богу, "
        "Господи, помилуй, Иисус Христос). 福音 = Евангелие (Gospel), not "
        "'good news'."
    )
