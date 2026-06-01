"""
俄/乌 → 中文 Argos 强化：术语优先级、分轨专名、lemma 查词、新闻体中文后处理。
"""
from __future__ import annotations

import os
import re

from terminology_registry import apply_priority_terminology_to_zh, normalize_source_lang


def slavic_to_zh_enhance_enabled() -> bool:
    v = os.environ.get("ARGOS_SLAVIC_TO_ZH_ENHANCE", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


# 去除机器翻译腔 / 直译句式（国际新闻体）
_ZH_STYLE_PATTERNS: list[tuple[str, str]] = [
    (r"进行了关于(.+?)的讨论", r"讨论了\1"),
    (r"进行了(.+?)的讨论", r"讨论了\1"),
    (r"他拥有进行工作的能力", r"他有工作能力"),
    (r"她拥有进行工作的能力", r"她有工作能力"),
    (r"拥有(.+?)的能力", r"具备\1能力"),
    (r"在(.+?)的情况下", r"在\1情况下"),
    (r"被进行了", r"被"),
    (r"对于(.+?)的问题", r"关于\1的问题"),
    (r"关于这个问题的问题", r"关于这个问题"),
    (r"乌克兰的安全局", r"乌克兰安全局"),
    (r"俄罗斯联邦", r"俄罗斯"),
    (r"，，+", r"，"),
    (r"。。+", r"。"),
]


# 禁止把乌语专名按俄语习惯译（后验：源为 uk 时替换错译）
_UK_NAME_OVERRIDES: list[tuple[str, str, str]] = [
    (r"亚历山大", "奥列克桑德尔", r"Олександр|олександр"),
    (r"弗拉基米尔", "沃洛德米尔", r"Володимир|володимир"),
    (r"尼古拉", "米科拉", r"Микола|микола"),
    (r"谢尔盖", "谢尔希", r"Сергій|сергій"),
    (r"德米特里", "德米特罗", r"Дмитро|дмитро"),
    (r"玛丽亚", "玛丽娅", r"Марія|марія"),
]


def _detect_source_has_ukrainian_markers(source_text: str) -> bool:
    if not source_text:
        return False
    return bool(re.search(r"[іїєґІЇЄҐ]", source_text))


def polish_zh_news_style(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return text
    for pat, repl in _ZH_STYLE_PATTERNS:
        t = re.sub(pat, repl, t)
    lines = [re.sub(r" +", " ", ln).strip() for ln in t.split("\n")]
    return "\n".join(lines)


def fix_uk_source_name_mistranslation(
    text: str,
    source_text: str,
    source_lang: str,
) -> str:
    """源语为乌克兰语时，纠正按俄语习惯误用的中文人名/地名。"""
    if normalize_source_lang(source_lang) != "uk":
        if not _detect_source_has_ukrainian_markers(source_text):
            return text
    src = source_text or ""
    out = text
    for wrong_zh, right_zh, cyr_pat in _UK_NAME_OVERRIDES:
        if wrong_zh not in out:
            continue
        if re.search(cyr_pat, src, re.I):
            out = out.replace(wrong_zh, right_zh)
    return out


def check_terminology_consistency(
    text: str,
    source_lang: str,
) -> str:
    """同一中文译名重复检查：合并明显重复实体表述。"""
    t = text or ""
    t = re.sub(r"(泽连斯基)(?:总统)?\1", r"\1", t)
    t = re.sub(r"(普京)(?:总统)?\1", r"\1", t)
    return t


def postprocess_slavic_to_zh(
    text: str,
    source_lang: str,
    *,
    source_text: str | None = None,
) -> str:
    if not text or not slavic_to_zh_enhance_enabled():
        return text
    lang = normalize_source_lang(source_lang)
    if lang not in ("ru", "uk"):
        return text

    src = source_text or text
    t = text

    try:
        import translation_quality as tq

        if hasattr(tq, "sanitize_llm_translation_output"):
            t = tq.sanitize_llm_translation_output(t)
    except ImportError:
        pass

    t = apply_priority_terminology_to_zh(t, lang, source_text=src)
    t = fix_uk_source_name_mistranslation(t, src, lang)
    t = polish_zh_news_style(t)
    t = check_terminology_consistency(t, lang)

    try:
        import translation_quality as tq

        if hasattr(tq, "normalize_zh_for_mt"):
            t = tq.normalize_zh_for_mt(t)
    except ImportError:
        pass

    return t.strip() if t else t


def ollama_slavic_to_zh_system_appendix() -> str:
    """Ollama 俄/乌→中补充说明（与内置术语库一致）。"""
    return (
        "Russian/Ukrainian→Chinese: Use international news Chinese (UN/EU style), "
        "not mainland machine-translation phrasing. "
        "NEVER confuse Ukrainian and Russian proper names "
        "(Олександр→奥列克桑德尔, Александр→亚历山大; "
        "Зеленський/Путін vs Зеленский/Путин). "
        "Military terms: бригада→旅, батальон/батальйон→营, БПЛА→无人机. "
        "Split long sentences; natural Chinese word order; no word-for-word calques. "
        "Output only final Chinese, no notes or pinyin."
    )
