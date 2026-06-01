"""从对齐句对自动抽取专名/术语（分人名、地名、军事、政治）。"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from corpus_pipeline.config import GLOSSARY_DIR

_RU_PHRASE = re.compile(
    r"[А-ЯЁ][А-Яа-яЁё\-]+(?:\s+[А-ЯЁ][А-Яа-яЁё\-]+){0,3}"
)
_UK_PHRASE = re.compile(
    r"[А-ЯІЇЄҐ][А-Яа-яІіЇїЄєҐґ\-]+(?:\s+[А-ЯІЇЄҐ][А-Яа-яІіЇїЄєҐґ\-]+){0,3}"
)
_HAN_PHRASE = re.compile(r"[\u4e00-\u9fff]{2,10}")
_LATIN_ORG = re.compile(r"\b[A-Z]{2,8}\b")

_MILITARY_KW = frozenset(
    {
        "армія",
        "армия",
        "військ",
        "воен",
        "оборони",
        "обороны",
        "збро",
        "оруж",
        "ракет",
        "дрон",
        "бпла",
        "фронт",
        "бригад",
        "полк",
        "дивіз",
        "дивиз",
        "нато",
        "nato",
        "сбу",
        "гур",
        "мо",
    }
)
_POLITICAL_KW = frozenset(
    {
        "президент",
        "прем'єр",
        "премьер",
        "міністр",
        "министр",
        "парламент",
        "рада",
        "уряд",
        "правительств",
        "депутат",
        "партія",
        "партия",
        "вибор",
        "выбор",
        "дипломат",
        "посол",
        "санкц",
        "резолюц",
    }
)
_PLACE_SUFFIX = re.compile(
    r"(?:область|області|район|місто|м\.|київ|киев|львів|одес|харків|донбас|крим|crim)",
    re.I,
)
_SKIP = frozenset(
    {"Россия", "Украина", "Україна", "Президент", "Правительство", "Китай", "中国"}
)


def _cyrillic_phrases(text: str, lang: str) -> list[str]:
    pat = _UK_PHRASE if lang == "uk" else _RU_PHRASE
    return [m.group(0).strip() for m in pat.finditer(text or "")]


def _classify_phrase(phrase: str, lang: str) -> str:
    low = phrase.lower()
    if any(k in low for k in _MILITARY_KW):
        return "military"
    if any(k in low for k in _POLITICAL_KW):
        return "political"
    if _PLACE_SUFFIX.search(low):
        return "places"
    words = phrase.split()
    if len(words) >= 2 and words[0][0].isupper():
        return "names"
    if len(phrase) >= 5 and phrase[0].isupper() and " " not in phrase:
        if lang == "uk" and phrase.endswith(("ський", "ська", "ське", "ко", "енко", "ів")):
            return "names"
        if lang == "ru" and phrase.endswith(("ский", "ская", "ов", "ев", "ин", "ий")):
            return "names"
    return "entities"


def _align_phrase_candidates(
    source_text: str,
    target_text: str,
    source_lang: str,
) -> list[tuple[str, str, str]]:
    src_phrases = _cyrillic_phrases(source_text, source_lang)
    tgt_phrases = _HAN_PHRASE.findall(target_text or "")
    if not src_phrases or not tgt_phrases:
        return []
    pairs: list[tuple[str, str, str]] = []
    for sp in src_phrases:
        if sp in _SKIP or len(sp) < 3:
            continue
        cat = _classify_phrase(sp, source_lang)
        for tp in tgt_phrases:
            if len(tp) < 2:
                continue
            pairs.append((sp, tp, cat))
    return pairs[:16]


def extract_from_aligned_pairs(
    pairs: list[dict[str, Any]],
    source_lang: str,
) -> dict[str, dict[str, str]]:
    """按类别返回 {category: {lemma: zh}}。"""
    from corpus_pipeline.ner_backends import extract_named_spans

    counter: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    for row in pairs:
        src = row.get("source") or row.get("source_text") or ""
        tgt = row.get("target") or row.get("target_text") or ""
        for cy, zh, cat in _align_phrase_candidates(src, tgt, source_lang):
            counter[cat][(cy, zh)] += 1
        for m in _LATIN_ORG.finditer(src):
            abbr = m.group(0)
            if abbr in tgt:
                counter["military"][(abbr, abbr)] += 1
        tgt_phrases = _HAN_PHRASE.findall(tgt or "")
        for span in extract_named_spans(src, source_lang):
            if span in _SKIP or len(span) < 3:
                continue
            cat = _classify_phrase(span, source_lang)
            for tp in tgt_phrases:
                if len(tp) >= 2:
                    counter[cat][(span, tp)] += 1

    out: dict[str, dict[str, str]] = {}
    for cat, cnt in counter.items():
        mapping: dict[str, str] = {}
        for (cy, zh), n in cnt.most_common(400):
            if n >= 2 or (" " in cy and n >= 1) or n >= 1 and len(cy) >= 5:
                if cy not in mapping:
                    mapping[cy] = zh
        if mapping:
            out[cat] = mapping
    return out


def save_glossary_json(
    mapping: dict[str, str],
    source_lang: str,
    *,
    category: str = "entities",
    out_dir: Path | None = None,
) -> Path:
    out_dir = out_dir or GLOSSARY_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{category}_{source_lang}_zh.json"
    items = [
        {
            "lemma": cy,
            "zh": zh,
            "source": "corpus_ner",
            "category": category,
            "locked": False,
        }
        for cy, zh in sorted(mapping.items(), key=lambda x: x[0])
    ]
    payload = {
        "meta": {
            "source_lang": source_lang,
            "category": category,
            "auto_extracted": True,
        },
        "entries": items,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def save_all_categories(
    by_cat: dict[str, dict[str, str]],
    source_lang: str,
) -> list[Path]:
    paths: list[Path] = []
    for cat, mapping in by_cat.items():
        if mapping:
            paths.append(save_glossary_json(mapping, source_lang, category=cat))
    return paths
