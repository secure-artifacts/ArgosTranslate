"""语料质量综合评分 corpus_quality_score → TM 准入 / quarantine。"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher

from corpus_pipeline.config import CORPUS_QUALITY_MIN
from corpus_pipeline.lang_detect import (
    cyrillic_script_scores,
    detect_cyrillic_lang,
    han_ratio,
    has_ocr_noise,
)
from corpus_pipeline.quality import _HTML_JUNK

_LATIN_ORG = re.compile(r"\b[A-Z]{2,8}\b")
_NAV_MARKERS = re.compile(
    r"Toggle navigation|Submit Search|Указатель|网址索引|"
    r"Search the United Nations|multilingual",
    re.I,
)

_LAT = re.compile(r"[A-Za-z]{3,}")
_HAN_PHRASE = re.compile(r"[\u4e00-\u9fff]{2,8}")
_CYR_PHRASE = re.compile(
    r"[А-ЯЁ][А-Яа-яЁё\-]+(?:\s+[А-ЯЁ][А-Яа-яЁё\-]+){0,2}"
)
_NUM = re.compile(r"\d{2,}")


@dataclass
class PairQuality:
    language_purity: float
    semantic_similarity: float
    named_entity_overlap: float
    sentence_length_ratio: float
    html_noise_ratio: float
    corpus_quality_score: float
    reject_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _language_purity(source: str, target: str, src_lang: str, tgt_lang: str) -> float:
    sl = (src_lang or "").lower()
    tl = (tgt_lang or "").lower()
    scores: list[float] = []
    if sl in ("ru", "uk"):
        det = detect_cyrillic_lang(source)
        cyr = len(re.findall(r"[А-Яа-яЁёІіЇїЄєҐґ]", source))
        lat = len(_LAT.findall(source))
        if lat > cyr * 2 and cyr < 30:
            scores.append(0.15)
        elif det == sl:
            scores.append(1.0)
        elif det == "mixed":
            scores.append(0.75)
        elif det == "unknown":
            scores.append(0.2 if cyr < 20 else 0.45)
        else:
            scores.append(0.25)
    if tl in ("zh", "zt", "cn"):
        hr = han_ratio(target)
        scores.append(min(1.0, hr / 0.12) if hr >= 0.08 else hr * 5)
    return sum(scores) / max(len(scores), 1)


def _semantic_similarity(source: str, target: str) -> float:
    """跨语言粗略语义：数字/拉丁缩写/长度结构。"""
    s, t = (source or "").strip(), (target or "").strip()
    if not s or not t:
        return 0.0
    nums_s = set(_NUM.findall(s))
    nums_t = set(_NUM.findall(t))
    num_overlap = len(nums_s & nums_t) / max(len(nums_s | nums_t), 1)
    lat_s = {x.upper() for x in _LATIN_ORG.findall(s)}
    lat_t = {x.upper() for x in _LATIN_ORG.findall(t)}
    lat_overlap = len(lat_s & lat_t) / max(len(lat_s | lat_t), 1)
    char_ratio = SequenceMatcher(
        None, re.sub(r"\s+", "", s[:200]), re.sub(r"\s+", "", t[:200])
    ).ratio()
    return min(1.0, 0.35 * num_overlap + 0.25 * lat_overlap + 0.4 * char_ratio * 0.3)


def _entity_overlap(source: str, target: str) -> float:
    han = set(_HAN_PHRASE.findall(target or ""))
    cyr = set(_CYR_PHRASE.findall(source or ""))
    if not han or not cyr:
        return 0.5
    hits = 0
    for h in han:
        if len(h) < 2:
            continue
        for c in cyr:
            if len(c) < 4:
                continue
            if h[:1] in target and c[:3].lower() in (source or "").lower():
                hits += 1
                break
    return min(1.0, 0.4 + hits / max(min(len(han), 8), 1) * 0.15)


def _length_ratio_score(source: str, target: str) -> float:
    ls = max(len(re.sub(r"\s+", "", source or "")), 1)
    lt = max(len(re.sub(r"\s+", "", target or "")), 1)
    r = ls / lt if ls > lt else lt / ls
    if r <= 1.8:
        return 1.0
    if r <= 2.8:
        return 0.7
    if r <= 4.0:
        return 0.35
    return 0.1


def _html_noise_ratio(source: str, target: str) -> float:
    combined = (source or "") + (target or "")
    if not combined:
        return 0.0
    hits = len(_HTML_JUNK.findall(combined))
    return min(1.0, hits / max(len(combined) / 80, 1))


def score_pair(
    source: str,
    target: str,
    source_lang: str,
    target_lang: str,
    *,
    align_confidence: float = 0.8,
) -> PairQuality:
    lang_p = _language_purity(source, target, source_lang, target_lang)
    sem = _semantic_similarity(source, target)
    ent = _entity_overlap(source, target)
    lr = _length_ratio_score(source, target)
    html_n = _html_noise_ratio(source, target)

    det = detect_cyrillic_lang(source) if (source_lang or "").lower() in ("ru", "uk") else "ok"
    lat_n = len(_LAT.findall(source or ""))
    cyr_n = len(re.findall(r"[А-Яа-яЁё]", source or ""))

    reject = ""
    if _NAV_MARKERS.search(source) or _NAV_MARKERS.search(target):
        reject = "navigation_pollution"
    elif has_ocr_noise(source) or has_ocr_noise(target):
        reject = "ocr_noise"
    elif html_n > 0.35:
        reject = "html_noise"
    elif (source_lang or "").lower() == "ru" and det == "unknown" and cyr_n < 25:
        reject = "language_unknown"
    elif lat_n > cyr_n * 2.5 and cyr_n < 40:
        reject = "english_heavy"
    elif lang_p < 0.35:
        reject = "low_language_purity"
    elif ent < 0.25 and sem < 0.18:
        reject = "entity_mismatch"
    elif sem < 0.08 and ent < 0.35:
        reject = "semantic_mismatch"

    combined = (
        0.30 * lang_p
        + 0.22 * sem
        + 0.18 * ent
        + 0.18 * lr
        + 0.12 * (1.0 - html_n)
    )
    combined = combined * 0.85 + 0.15 * float(align_confidence)
    combined = round(min(1.0, max(0.0, combined)), 4)

    min_score = float(os.environ.get("CORPUS_QUALITY_MIN", str(CORPUS_QUALITY_MIN)))
    if not reject and combined < min_score:
        reject = "low_corpus_quality_score"

    return PairQuality(
        language_purity=round(lang_p, 4),
        semantic_similarity=round(sem, 4),
        named_entity_overlap=round(ent, 4),
        sentence_length_ratio=round(lr, 4),
        html_noise_ratio=round(html_n, 4),
        corpus_quality_score=combined,
        reject_reason=reject,
    )


def passes_quality(
    source: str,
    target: str,
    source_lang: str,
    target_lang: str,
    *,
    align_confidence: float = 0.8,
) -> tuple[bool, PairQuality]:
    q = score_pair(
        source, target, source_lang, target_lang, align_confidence=align_confidence
    )
    return (not q.reject_reason, q)
