"""专名抽取：Natasha / spaCy / Stanza + 类型标注 + 规则回退。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

_RU_PHRASE = re.compile(
    r"[А-ЯЁ][А-Яа-яЁё\-]+(?:\s+[А-ЯЁ][А-Яа-яЁё\-]+){0,3}"
)
_COUNTRIES_RU = frozenset(
    {
        "Россия",
        "России",
        "Украина",
        "Украины",
        "Україна",
        "Китай",
        "Китая",
        "США",
        "Израиль",
        "Палестина",
        "Сирия",
        "Иран",
        "Германия",
        "Франция",
        "Польша",
        "Турция",
        "Беларусь",
        "ООН",
        "НАТО",
        "ЕС",
    }
)
_ORG_ABBR = re.compile(
    r"\b(?:ООН|НАТО|ЕС|СБУ|МИД|ЮНЕСКО|ВОЗ|МАГАТЭ)\b",
    re.I,
)

_ALLOWED_TYPES = frozenset({"PERSON", "GPE", "ORG", "LOC", "EVENT"})


@dataclass(frozen=True)
class TypedEntity:
    text: str
    entity_type: str
    backend: str = "pattern"


def _map_type(label: str) -> str:
    m = {
        "PER": "PERSON",
        "PERSON": "PERSON",
        "LOC": "LOC",
        "GPE": "GPE",
        "ORG": "ORG",
        "EVENT": "EVENT",
    }
    return m.get((label or "").upper(), "")


def _from_natasha(text: str) -> list[TypedEntity]:
    try:
        from natasha import Doc, NewsEmbedding, NewsMorphTagger, NewsNERTagger, Segmenter

        emb = NewsEmbedding()
        seg = Segmenter(emb)
        morph = NewsMorphTagger(emb)
        ner = NewsNERTagger(emb)
        doc = Doc(text[:8000])
        doc.segment(seg)
        doc.tag_morph(morph)
        doc.tag_ner(ner)
        out: list[TypedEntity] = []
        for span in doc.spans:
            et = _map_type(span.type or "")
            if et not in _ALLOWED_TYPES:
                continue
            s = (span.text or "").strip()
            if len(s) >= 2:
                out.append(TypedEntity(s, et, "natasha"))
        return out
    except Exception:
        return []


def _from_spacy_ru(text: str) -> list[TypedEntity]:
    try:
        import spacy

        nlp = spacy.load("ru_core_news_sm")
        doc = nlp(text[:8000])
        out: list[TypedEntity] = []
        for ent in doc.ents:
            et = _map_type(ent.label_ or "")
            if et not in _ALLOWED_TYPES:
                continue
            s = ent.text.strip()
            if len(s) >= 2:
                out.append(TypedEntity(s, et, "spacy"))
        return out
    except Exception:
        return []


def _from_stanza_uk(text: str) -> list[TypedEntity]:
    try:
        import stanza

        nlp = stanza.Pipeline("uk", processors="tokenize,ner", verbose=False)
        doc = nlp(text[:6000])
        out: list[TypedEntity] = []
        for sent in doc.sentences:
            for ent in sent.ents:
                et = _map_type(ent.type or "")
                if et not in _ALLOWED_TYPES:
                    continue
                s = (ent.text or "").strip()
                if len(s) >= 2:
                    out.append(TypedEntity(s, et, "stanza"))
        return out
    except Exception:
        return []


def _pattern_fallback(text: str, lang: str) -> list[TypedEntity]:
    out: list[TypedEntity] = []
    for c in _COUNTRIES_RU:
        if c in (text or ""):
            et = "GPE" if c in ("ООН", "НАТО", "ЕС", "США") else "GPE"
            if c in ("ООН", "НАТО", "ЕС"):
                et = "ORG"
            out.append(TypedEntity(c, et, "pattern"))
    for m in _ORG_ABBR.finditer(text or ""):
        out.append(TypedEntity(m.group(0).strip(), "ORG", "pattern"))
    for m in _RU_PHRASE.finditer(text or ""):
        s = m.group(0).strip()
        if len(s) < 4 or " " not in s:
            continue
        if s[0].isupper():
            out.append(TypedEntity(s, "PERSON", "pattern"))
    return out


def extract_typed_entities(text: str, lang: str) -> list[TypedEntity]:
    lang = (lang or "ru").lower()
    if lang not in ("ru", "uk"):
        return []
    seen: set[tuple[str, str]] = set()
    merged: list[TypedEntity] = []

    def add(items: Iterable[TypedEntity]) -> None:
        for it in items:
            key = (it.text.lower(), it.entity_type)
            if key in seen:
                continue
            seen.add(key)
            merged.append(it)

    if lang == "ru":
        add(_from_natasha(text))
        add(_from_spacy_ru(text))
    if lang == "uk":
        add(_from_stanza_uk(text))
    add(_pattern_fallback(text, lang))
    return merged[:60]
