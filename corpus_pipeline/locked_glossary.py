"""锁定术语表：人工确认、多来源一致，禁止自动覆盖。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from corpus_pipeline.config import LOCKED_GLOSSARY_DIR, ROOT


def locked_file(lang: str) -> Path:
    LOCKED_GLOSSARY_DIR.mkdir(parents=True, exist_ok=True)
    return LOCKED_GLOSSARY_DIR / f"locked_{lang}_zh.json"


def load_locked(lang: str) -> list[dict[str, Any]]:
    p = locked_file(lang)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return list(data.get("entries") or [])
    except (OSError, json.JSONDecodeError):
        return []


def is_locked_term(source: str, lang: str) -> bool:
    low = (source or "").strip().lower()
    for e in load_locked(lang):
        lem = str(e.get("lemma") or e.get("source") or "").strip().lower()
        if lem and lem == low:
            return True
    return False


def add_locked_entry(
    *,
    source: str,
    target: str,
    lang: str,
    entity_type: str = "ORG",
    sources_count: int = 1,
    domains: list[str] | None = None,
    note: str = "",
) -> Path:
    p = locked_file(lang)
    entries = load_locked(lang)
    key = (source.strip(), target.strip())
    for e in entries:
        if (e.get("source") or e.get("lemma")) == source.strip():
            e.update(
                {
                    "target": target.strip(),
                    "zh": target.strip(),
                    "entity_type": entity_type,
                    "locked": True,
                    "sources_count": max(int(e.get("sources_count") or 1), sources_count),
                    "domains": sorted(set((e.get("domains") or []) + (domains or []))),
                    "note": note or e.get("note", ""),
                }
            )
            break
    else:
        entries.append(
            {
                "source": source.strip(),
                "target": target.strip(),
                "lemma": source.strip(),
                "zh": target.strip(),
                "entity_type": entity_type,
                "confidence": 1.0,
                "sources_count": sources_count,
                "domains": sorted(set(domains or [])),
                "locked": True,
                "note": note,
            }
        )
    payload = {
        "meta": {"source_lang": lang, "locked": True, "entry_count": len(entries)},
        "entries": entries,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def merge_locked_into_registry() -> int:
    """将 locked 条目同步到 entities_and_terms（仅新增，不覆盖已有 locked）。"""
    from corpus_pipeline.merge_into_glossary import clear_terminology_cache

    term_path = ROOT / "data" / "terminology" / "entities_and_terms.json"
    if not term_path.is_file():
        return 0
    data = json.loads(term_path.read_text(encoding="utf-8"))
    added = 0
    for lang in ("ru", "uk"):
        cat_key = "entities"
        bucket = data.setdefault(lang, {}).setdefault(cat_key, [])
        existing = {
            str(x.get("lemma") or "").strip().lower(): x for x in bucket if isinstance(x, dict)
        }
        for e in load_locked(lang):
            lem = str(e.get("lemma") or e.get("source") or "").strip()
            zh = str(e.get("zh") or e.get("target") or "").strip()
            if not lem or not zh:
                continue
            if lem.lower() in existing:
                if existing[lem.lower()].get("locked"):
                    continue
                existing[lem.lower()]["zh"] = zh
                existing[lem.lower()]["locked"] = True
                existing[lem.lower()]["priority"] = "locked"
            else:
                bucket.append({"lemma": lem, "zh": zh, "locked": True, "priority": "locked"})
                added += 1
    term_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clear_terminology_cache()
    return added
