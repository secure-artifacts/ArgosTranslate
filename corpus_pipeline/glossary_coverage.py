"""术语库覆盖率与专名一致率（翻译后采样评估）。"""
from __future__ import annotations

import re

from corpus_pipeline.metrics import record_entity_consistency, record_glossary_coverage

_RU = re.compile(r"[А-Яа-яЁё][А-Яа-яЁё'\-]*")
_UK = re.compile(r"[А-Яа-яІіЇїЄєҐґ][А-Яа-яІіЇїЄєҐґ'\-]*")


def measure_slavic_to_zh(
    source_text: str,
    output_zh: str,
    source_lang: str,
) -> None:
    try:
        import terminology_registry as tr
    except ImportError:
        return
    lang = tr.normalize_source_lang(source_lang)
    if lang not in ("ru", "uk"):
        return
    index = tr._build_lemma_index(lang)
    forms = tr._build_form_index(lang)
    word_re = _UK if lang == "uk" else _RU
    tokens = word_re.findall(source_text or "")
    if not tokens:
        return
    covered = 0
    for w in tokens:
        if len(w) < 3:
            continue
        lem = tr._lemma_for_token(w, lang)
        if index.get(lem.lower()) or forms.get(w.lower()):
            covered += 1
    record_glossary_coverage(
        source_lang=lang,
        tokens_checked=len([t for t in tokens if len(t) >= 3]),
        tokens_covered=covered,
        sample_text_len=len(source_text or ""),
    )
    ru_i = tr._build_lemma_index("ru")
    uk_i = tr._build_lemma_index("uk")
    consistent = inconsistent = 0
    for key in set(ru_i) & set(uk_i):
        if ru_i[key] == uk_i[key]:
            consistent += 1
        else:
            inconsistent += 1
    if consistent or inconsistent:
        record_entity_consistency(
            source_lang=lang,
            consistent=consistent,
            inconsistent=inconsistent,
        )
