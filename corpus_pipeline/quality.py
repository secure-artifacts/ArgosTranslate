"""语料质量过滤（含语言误判、OCR、HTML）。"""
from __future__ import annotations

import re

from corpus_pipeline.lang_detect import (
    han_ratio,
    has_ocr_noise,
    is_language_mismatch,
)

_MT_MARKERS = re.compile(
    r"baidu|google translate|machine translation|translated by|"
    r"此翻译|机器翻译|自动翻译",
    re.I,
)
_HTML_JUNK = re.compile(
    r"<[^>]{0,200}>|&nbsp;|&[a-z]{2,8};|{\s*\\|"
    r"https?://\S+\.(?:jpg|png|gif)\b",
    re.I,
)
_CYRILLIC = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_BAD_ZH = re.compile(
    r"进行了关于.+的讨论|他拥有进行工作的能力|据俄罗斯媒体报道称"
)
_REPEAT_CHAR = re.compile(r"(.)\1{6,}")


def is_noisy_pair(source: str, target: str, src_lang: str, tgt_lang: str) -> bool:
    s = (source or "").strip()
    t = (target or "").strip()
    if not s or not t:
        return True
    if len(s) < 4 or len(t) < 2:
        return True
    if _HTML_JUNK.search(s) or _HTML_JUNK.search(t):
        return True
    if has_ocr_noise(s) or has_ocr_noise(t):
        return True
    if _REPEAT_CHAR.search(s) or _REPEAT_CHAR.search(t):
        return True
    if _MT_MARKERS.search(s) or _MT_MARKERS.search(t):
        return True
    if is_language_mismatch(s, src_lang):
        return True
    sl = (src_lang or "").lower()
    tl = (tgt_lang or "").lower()
    if sl in ("ru", "uk") and not _CYRILLIC.search(s):
        return True
    if tl in ("zh", "zt", "cn") and han_ratio(t) < 0.08:
        return True
    if tl in ("zh", "zt", "cn") and _BAD_ZH.search(t):
        return True
    ratio = len(t) / max(len(s), 1)
    if ratio > 4.5 or ratio < 0.15:
        return True
    return False


def dedupe_key(source: str, target: str, src_lang: str, tgt_lang: str) -> str:
    return f"{src_lang}|{tgt_lang}|{source.strip()}|{target.strip()}"


def normalize_source_for_storage(text: str, lang: str) -> str:
    """入库前轻量归一（去多余空白、BOM）。"""
    t = (text or "").strip().lstrip("\ufeff")
    t = re.sub(r"\s+", " ", t)
    code = (lang or "").lower()
    if code in ("ru", "uk"):
        try:
            import terminology_registry as tr

            words = t.split()
            if len(words) == 1 and len(words[0]) > 3:
                return tr._lemma_for_token(words[0], code) or t
        except Exception:
            pass
    return t
