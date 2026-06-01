"""HTML/编码/OCR 清洗。"""
from __future__ import annotations

import html
import re
import unicodedata

from corpus_pipeline.lang_detect import has_ocr_noise

_HTML_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(
    r"<(script|style|noscript|iframe)[^>]*>.*?</\1>",
    re.I | re.S,
)
_WS = re.compile(r"[ \t\u00a0]+")
_MULTI_NL = re.compile(r"\n{3,}")
_OCR_FIX = re.compile(r"\bl1\b", re.I)
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\ufeff]")


def normalize_unicode(text: str) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = _ZERO_WIDTH.sub("", t)
    return t.replace("\ufeff", "")


def strip_html(text: str) -> str:
    t = text or ""
    t = _SCRIPT_STYLE.sub(" ", t)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(?:p|div|h[1-6]|li|tr)\s*>", "\n", t, flags=re.I)
    t = _HTML_TAG.sub(" ", t)
    t = html.unescape(t)
    t = re.sub(r"\{[^}]{0,80}\}", " ", t)
    return t


def fix_ocr_artifacts(text: str) -> str:
    t = text or ""
    t = _OCR_FIX.sub("II", t)
    t = re.sub(r"\s+\|\s+", " ", t)
    return t


def clean_paragraph(text: str) -> str:
    t = normalize_unicode(strip_html(text))
    t = fix_ocr_artifacts(t)
    t = _WS.sub(" ", t)
    lines = [ln.strip() for ln in t.split("\n")]
    lines = [ln for ln in lines if ln and len(ln) > 1]
    t = "\n".join(lines)
    t = _MULTI_NL.sub("\n\n", t).strip()
    if has_ocr_noise(t) and len(t) < 200:
        return ""
    return t
