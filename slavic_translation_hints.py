"""
中↔俄/乌翻译强化说明（Argos 后处理与术语数据）。
"""
from __future__ import annotations


def is_zh_to_slavic(from_code: str, to_code: str) -> bool:
    src = (from_code or "").strip().lower()
    tgt = (to_code or "").strip().lower()
    return src in ("zh", "zt", "cn", "zho") and tgt in ("ru", "uk")


def is_slavic_target(lang_code: str) -> bool:
    return (lang_code or "").strip().lower() in ("ru", "uk")


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
