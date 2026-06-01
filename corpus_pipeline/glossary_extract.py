"""提纯版 glossary 抽取：黑名单、实体类型、双语共现、置信度。"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from corpus_pipeline.config import GLOSSARY_DIR, ROOT
from corpus_pipeline.ner_backends import TypedEntity, extract_typed_entities

_HAN_ENT = re.compile(r"[\u4e00-\u9fff]{2,8}")
_ALLOWED_TYPES = frozenset({"PERSON", "GPE", "ORG", "LOC", "EVENT"})
_GLOSSARY_MIN_CONFIDENCE = 0.55
_MERGE_MIN_CONFIDENCE = 0.72
_ZH_FRAGMENT_BLOCK = re.compile(
    r"^(?:他|她|它|这|那|说|表示|指出|强调|认为|记者|能力|还是|然而|目前|实现|规定|危机|和平|日|的|了|在|与|及)$"
)


@dataclass
class GlossaryCandidate:
    source: str
    target: str
    entity_type: str
    confidence: float
    sources_count: int = 1
    domains: list[str] = field(default_factory=list)

    def to_entry_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "entity_type": self.entity_type,
            "confidence": round(self.confidence, 4),
            "sources_count": self.sources_count,
            "domains": sorted(set(self.domains)),
            "lemma": self.source,
            "zh": self.target,
            "locked": False,
        }


def _load_blacklist() -> tuple[set[str], set[str]]:
    p = ROOT / "data" / "glossary" / "stopword_blacklist.json"
    zh: set[str] = set()
    ru: set[str] = set()
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            zh = {str(x).strip() for x in data.get("zh") or [] if str(x).strip()}
            ru = {str(x).strip().lower() for x in data.get("ru") or [] if str(x).strip()}
        except (OSError, json.JSONDecodeError):
            pass
    return zh, ru


def _is_blacklisted(text: str, lang: str, zh_bl: set[str], ru_bl: set[str]) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if lang == "zh" or lang == "cn":
        if t in zh_bl:
            return True
        for b in zh_bl:
            if len(b) >= 3 and b in t:
                return True
    if lang in ("ru", "uk"):
        low = t.lower()
        if low in ru_bl:
            return True
        for b in ru_bl:
            if len(b) >= 4 and b in low:
                return True
    if re.match(r"^(?:第.+届|点击|更多|了解|搜索|菜单)", t):
        return True
    if t.lower() in ("english", "中文", "русский", "multilingual", "menu"):
        return True
    return False


def _load_entity_anchors() -> list[dict[str, str]]:
    p = ROOT / "data" / "glossary" / "entity_anchors_ru_zh.json"
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return list(data.get("anchors") or [])
    except (OSError, json.JSONDecodeError):
        return []


def _anchor_match(ru_text: str, zh_text: str, entity_type: str) -> bool:
    ru_low = (ru_text or "").lower()
    for anc in _load_entity_anchors():
        if anc.get("entity_type") != entity_type:
            continue
        if anc["ru"].lower() in ru_low and anc["zh"] == zh_text:
            return True
    return False


def _entity_cross_validation(
    ru_text: str,
    zh_text: str,
    entity_type: str,
    *,
    sources_count: int,
) -> float:
    """锚点表 + 类型一致 + 多文档重复 → 提升置信度。"""
    bonus = 0.0
    if _anchor_match(ru_text, zh_text, entity_type):
        bonus += 0.28
    if sources_count >= 3:
        bonus += 0.15
    elif sources_count >= 2:
        bonus += 0.10
    if entity_type in ("ORG", "GPE") and len(zh_text) >= 2 and len(ru_text) >= 2:
        bonus += 0.05
    if _ZH_FRAGMENT_BLOCK.match(zh_text.strip()):
        return -1.0
    if len(zh_text) <= 1 and entity_type != "GPE":
        return -1.0
    return bonus


def _zh_entities_from_sentence(sentence: str, zh_bl: set[str]) -> list[TypedEntity]:
    out: list[TypedEntity] = []
    for m in _HAN_ENT.findall(sentence or ""):
        if _is_blacklisted(m, "zh", zh_bl, set()):
            continue
        if len(m) < 2 or len(m) > 6:
            continue
        et = "GPE" if m.endswith(("国", "市", "省", "州")) else "PERSON"
        if m in ("联合国", "安理会", "大会", "秘书处", "北约", "欧盟"):
            et = "ORG"
        out.append(TypedEntity(m, et, "zh_heuristic"))
    return out


def _pair_overlap_score(ru_ent: TypedEntity, zh_ent: TypedEntity, sentence_ru: str, sentence_zh: str) -> float:
    """同句内双语实体共现强度。"""
    if ru_ent.entity_type != zh_ent.entity_type and ru_ent.entity_type not in ("ORG", "GPE") and zh_ent.entity_type not in ("ORG", "GPE"):
        if not (ru_ent.entity_type == "PERSON" and zh_ent.entity_type == "PERSON"):
            return 0.0
    if ru_ent.text not in sentence_ru or zh_ent.text not in sentence_zh:
        return 0.0
    base = 0.55
    if ru_ent.backend in ("natasha", "spacy", "stanza"):
        base += 0.15
    if zh_ent.backend == "zh_heuristic" and len(zh_ent.text) >= 2:
        base += 0.05
  # ORG/GPE short forms
    if ru_ent.entity_type in ("ORG", "GPE") and len(ru_ent.text) <= 6:
        base += 0.1
    if len(ru_ent.text) >= 4 and len(zh_ent.text) >= 2:
        base += 0.1
    return min(1.0, base)


def extract_glossary_from_pairs(
    pairs: list[dict[str, Any]],
    source_lang: str,
    *,
    default_domain: str = "un",
) -> list[GlossaryCandidate]:
    zh_bl, ru_bl = _load_blacklist()
    accum: dict[tuple[str, str, str], GlossaryCandidate] = {}

    for row in pairs:
        if float(row.get("pair_confidence") or 1.0) < 0.80:
            continue
        src = row.get("source") or row.get("source_text") or ""
        tgt = row.get("target") or row.get("target_text") or ""
        domain = str(row.get("domain") or default_domain)
        if not src.strip() or not tgt.strip():
            continue
        if row.get("quality_reject") in (
            "semantic_mismatch",
            "entity_mismatch",
        ):
            continue

        ru_ents = [
            e
            for e in extract_typed_entities(src, source_lang)
            if e.entity_type in _ALLOWED_TYPES
            and not _is_blacklisted(e.text, source_lang, zh_bl, ru_bl)
        ]
        zh_ents = _zh_entities_from_sentence(tgt, zh_bl)

        for re_ent in ru_ents:
            for zh_ent in zh_ents:
                ov = _pair_overlap_score(re_ent, zh_ent, src, tgt)
                if ov < 0.5:
                    continue
                if _is_blacklisted(zh_ent.text, "zh", zh_bl, ru_bl):
                    continue
                key = (re_ent.text, zh_ent.text, re_ent.entity_type)
                if key in accum:
                    c = accum[key]
                    c.sources_count += 1
                    c.confidence = min(1.0, c.confidence + 0.06)
                    if domain not in c.domains:
                        c.domains.append(domain)
                else:
                    accum[key] = GlossaryCandidate(
                        source=re_ent.text,
                        target=zh_ent.text,
                        entity_type=re_ent.entity_type,
                        confidence=ov,
                        sources_count=1,
                        domains=[domain],
                    )

    out: list[GlossaryCandidate] = []
    for c in accum.values():
        if c.sources_count >= 2:
            c.confidence = min(1.0, c.confidence + 0.12)
        elif c.sources_count == 1 and c.confidence < 0.62:
            continue
        cross = _entity_cross_validation(
            c.source, c.target, c.entity_type, sources_count=c.sources_count
        )
        if cross < 0:
            continue
        c.confidence = min(1.0, c.confidence + cross)
        if _anchor_match(c.source, c.target, c.entity_type):
            c.confidence = max(c.confidence, 0.82)
        if c.confidence < _GLOSSARY_MIN_CONFIDENCE:
            continue
        if _is_blacklisted(c.source, source_lang, zh_bl, ru_bl):
            continue
        if _is_blacklisted(c.target, "zh", zh_bl, ru_bl):
            continue
        if c.entity_type in ("ORG", "GPE") and len(c.target) < 2:
            continue
        if len(c.source) >= 4 and len(c.target) <= 2 and not _anchor_match(
            c.source, c.target, c.entity_type
        ):
            continue
        out.append(c)
    out.sort(key=lambda x: (-x.confidence, -x.sources_count))
    return out


def save_glossary_candidates(
    candidates: list[GlossaryCandidate],
    source_lang: str,
    *,
    out_dir: Path | None = None,
) -> Path:
    out_dir = out_dir or GLOSSARY_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"entities_{source_lang}_zh.json"
    existing: dict[tuple[str, str, str], dict] = {}
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            for item in old.get("entries") or []:
                key = (
                    str(item.get("source") or ""),
                    str(item.get("target") or ""),
                    str(item.get("entity_type") or ""),
                )
                existing[key] = item
        except (OSError, json.JSONDecodeError):
            pass

    for c in candidates:
        key = (c.source, c.target, c.entity_type)
        new = c.to_entry_dict()
        if key in existing:
            old = existing[key]
            new["sources_count"] = int(old.get("sources_count") or 1) + c.sources_count
            new["confidence"] = round(
                max(float(old.get("confidence") or 0), c.confidence), 4
            )
            domains = set(old.get("domains") or []) | set(c.domains)
            new["domains"] = sorted(domains)
        existing[key] = new

    merged = list(existing.values())
    merged.sort(key=lambda x: (-float(x.get("confidence") or 0), -int(x.get("sources_count") or 0)))
    by_type: dict[str, list] = defaultdict(list)
    for item in merged:
        by_type[str(item.get("entity_type") or "OTHER")].append(item)
    payload = {
        "meta": {
            "source_lang": source_lang,
            "auto_extracted": True,
            "min_confidence": _GLOSSARY_MIN_CONFIDENCE,
            "merge_min_confidence": _MERGE_MIN_CONFIDENCE,
            "entry_count": len(merged),
        },
        "entries": merged,
        "by_entity_type": {k: v for k, v in by_type.items()},
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def count_high_confidence_glossary(min_confidence: float = 0.72) -> int:
    total = 0
    if not GLOSSARY_DIR.is_dir():
        return 0
    for p in GLOSSARY_DIR.glob("entities_*_zh.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in data.get("entries") or []:
            if float(item.get("confidence") or 0) >= min_confidence:
                total += 1
    return total
