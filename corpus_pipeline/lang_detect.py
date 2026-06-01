"""俄语/乌克兰语/中文脚本检测与误判过滤。"""
from __future__ import annotations

import re

_CYR = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]")
_UK_ONLY = re.compile(r"[ІіЇїЄєҐґ]")
_RU_ONLY = re.compile(r"[ЁёЫыЭэЪъ]")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_LAT = re.compile(r"[A-Za-z]")
_OCR = re.compile(
    r"[|]{2,}|[_]{3,}|[^\S\n]{5,}|"
    r"(?:l1|0O){4,}|"
    r"[\uFFFD\u0000-\u0008\u000b\u000c\u000e-\u001f]"
)


def cyrillic_script_scores(text: str) -> tuple[float, float]:
    """返回 (uk_score, ru_score) 相对占比。"""
    t = text or ""
    if not _CYR.search(t):
        return 0.0, 0.0
    uk_hits = len(_UK_ONLY.findall(t))
    ru_hits = len(_RU_ONLY.findall(t))
    cyr = len(_CYR.findall(t))
    if cyr == 0:
        return 0.0, 0.0
    base = float(cyr)
    return uk_hits / base, ru_hits / base


def detect_cyrillic_lang(text: str) -> str:
    t = text or ""
    uk, ru = cyrillic_script_scores(t)
    cyr_n = len(_CYR.findall(t))
    if cyr_n < 15:
        return "unknown"
    if uk < 0.02 and ru < 0.02:
        # 无 Ё/Ы/І 等区分字母时（常见新闻俄语正文）
        return "ru" if cyr_n >= 40 else "mixed"
    if uk > ru * 1.15:
        return "uk"
    if ru > uk * 1.15:
        return "ru"
    return "mixed"


def is_language_mismatch(text: str, expected: str) -> bool:
    code = (expected or "").strip().lower()
    if code not in ("ru", "uk"):
        return False
    if not _CYR.search(text or ""):
        return code in ("ru", "uk")
    detected = detect_cyrillic_lang(text)
    if detected == "mixed":
        return False
    if detected == "unknown":
        return True
    return detected != code


def has_ocr_noise(text: str) -> bool:
    return bool(_OCR.search(text or ""))


def han_ratio(text: str) -> float:
    t = text or ""
    if not t:
        return 0.0
    return len(_HAN.findall(t)) / max(len(t), 1)
