"""TM 纯度评分：semantic + glossary + embedding 联合。"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from corpus_pipeline.config import ROOT
from corpus_pipeline.quality_score import score_pair


@dataclass
class TmPurityScore:
    semantic_consistency: float
    glossary_overlap: float
    embedding_similarity: float
    tm_purity_score: float
    reject_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _glossary_overlap(source: str, target: str, source_lang: str) -> float:
    p = ROOT / "data" / "glossary" / "entity_anchors_ru_zh.json"
    if not p.is_file():
        return 0.5
    try:
        anchors = json.loads(p.read_text(encoding="utf-8")).get("anchors") or []
    except (OSError, json.JSONDecodeError):
        return 0.5
    if (source_lang or "").lower() not in ("ru", "uk"):
        source, target = target, source
    src_low = (source or "").lower()
    tgt = target or ""
    hits = 0
    for anc in anchors:
        if anc.get("ru", "").lower() in src_low and anc.get("zh", "") in tgt:
            hits += 1
    if hits == 0:
        return 0.35
    return min(1.0, 0.45 + hits * 0.18)


def score_tm_purity(
    source: str,
    target: str,
    source_lang: str,
    target_lang: str,
    *,
    align_confidence: float = 0.8,
    embedding_similarity: float | None = None,
) -> TmPurityScore:
    pq = score_pair(
        source,
        target,
        source_lang,
        target_lang,
        align_confidence=align_confidence,
    )
    sem = pq.semantic_similarity
    if pq.reject_reason in ("semantic_mismatch", "entity_mismatch"):
        sem = min(sem, 0.15)

    gloss = _glossary_overlap(source, target, source_lang)
    emb = embedding_similarity
    if emb is None:
        try:
            from corpus_pipeline.bilingual_rerank import cross_lingual_similarity

            emb = cross_lingual_similarity(source[:500], target[:500])
        except Exception:
            emb = pq.named_entity_overlap

    combined = round(
        min(
            1.0,
            0.38 * sem
            + 0.22 * gloss
            + 0.28 * float(emb or 0)
            + 0.12 * pq.language_purity,
        ),
        4,
    )

    reject = ""
    if pq.reject_reason in (
        "semantic_mismatch",
        "entity_mismatch",
        "navigation_pollution",
    ):
        reject = pq.reject_reason
    elif combined < 0.52:
        reject = "low_tm_purity"

    return TmPurityScore(
        semantic_consistency=round(sem, 4),
        glossary_overlap=round(gloss, 4),
        embedding_similarity=round(float(emb or 0), 4),
        tm_purity_score=combined,
        reject_reason=reject,
    )
