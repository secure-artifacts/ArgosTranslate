"""术语合并：冲突检测、人工确认、锁定专名不可覆盖。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_pipeline.config import GLOSSARY_DIR, GLOSSARY_PENDING, ROOT


def _term_path() -> Path:
    return ROOT / "data" / "terminology" / "entities_and_terms.json"


def _is_locked(item: dict[str, Any]) -> bool:
    return bool(item.get("locked")) or item.get("priority") == "locked"


def clear_terminology_cache() -> None:
    try:
        import terminology_registry as tr

        tr._load_entities_and_terms.cache_clear()
        for fn in (
            tr._build_form_index,
            tr._build_lemma_index,
            tr._build_phrase_list,
        ):
            if hasattr(fn, "cache_clear"):
                fn.cache_clear()
    except Exception:
        pass
    try:
        import bidirectional_terminology as bt

        for fn in (
            bt._build_zh_to_slavic_index,
            bt._build_zh_to_slavic_candidates,
            bt._zh_name_entries,
        ):
            if hasattr(fn, "cache_clear"):
                fn.cache_clear()
    except Exception:
        pass
    try:
        from slavic_lemma_rank import clear_slavic_lemma_rank_cache

        clear_slavic_lemma_rank_cache()
    except Exception:
        pass


def load_extracted_glossaries() -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {"ru": [], "uk": []}
    for base in (
        GLOSSARY_DIR,
        ROOT / "data" / "corpus" / "glossary_extracted",
        ROOT / "data" / "glossary" / "international",
    ):
        if not base.is_dir():
            continue
        for p in base.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            lang = str(data.get("meta", {}).get("source_lang") or "")
            if lang not in out:
                lang = "ru" if "_ru_" in p.name else "uk" if "_uk_" in p.name else ""
            if lang not in out:
                continue
            cat = str(data.get("meta", {}).get("category") or "entities")
            merge_min = float(data.get("meta", {}).get("merge_min_confidence") or 0.72)
            for item in data.get("entries") or []:
                if not isinstance(item, dict):
                    continue
                conf = float(item.get("confidence") or 0)
                if conf < merge_min:
                    continue
                lem = str(item.get("lemma") or item.get("source") or "").strip()
                zh = str(item.get("zh") or item.get("target") or "").strip()
                if lem and zh:
                    et = str(item.get("entity_type") or "entities")
                    cat_map = {
                        "PERSON": "entities",
                        "GPE": "places",
                        "LOC": "places",
                        "ORG": "political",
                        "EVENT": "political",
                        "daily": "daily",
                    }
                    out.setdefault(lang, []).append(
                        {
                            "lemma": lem,
                            "zh": zh,
                            "_category": cat_map.get(et, cat),
                            "_source_file": p.name,
                            "_confidence": conf,
                        }
                    )
    return out


def _existing_maps(data: dict[str, Any], lang: str) -> dict[str, dict[str, Any]]:
    """lemma.lower() -> {zh, category, locked}"""
    block = data.get(lang) or {}
    found: dict[str, dict[str, Any]] = {}
    for cat in ("entities", "military", "political", "places", "daily"):
        for item in block.get(cat) or []:
            if not isinstance(item, dict):
                continue
            lem = str(item.get("lemma") or "").strip()
            if not lem:
                continue
            found[lem.lower()] = {
                "zh": str(item.get("zh") or "").strip(),
                "category": cat,
                "locked": _is_locked(item),
            }
    return found


def detect_conflicts() -> list[dict[str, Any]]:
    path = _term_path()
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    conflicts: list[dict[str, Any]] = []
    for lang, items in load_extracted_glossaries().items():
        existing = _existing_maps(data, lang)
        for it in items:
            lem = it["lemma"]
            key = lem.lower()
            zh_new = it["zh"]
            if key not in existing:
                continue
            ex = existing[key]
            if ex["locked"]:
                conflicts.append(
                    {
                        "lang": lang,
                        "lemma": lem,
                        "existing_zh": ex["zh"],
                        "proposed_zh": zh_new,
                        "category": it["_category"],
                        "reason": "locked_entry",
                        "source_file": it.get("_source_file", ""),
                    }
                )
                continue
            if ex["zh"] and ex["zh"] != zh_new:
                conflicts.append(
                    {
                        "lang": lang,
                        "lemma": lem,
                        "existing_zh": ex["zh"],
                        "proposed_zh": zh_new,
                        "category": ex["category"],
                        "reason": "zh_mismatch",
                        "source_file": it.get("_source_file", ""),
                    }
                )
    return conflicts


def write_conflicts_report() -> Path:
    GLOSSARY_PENDING.mkdir(parents=True, exist_ok=True)
    conflicts = detect_conflicts()
    path = GLOSSARY_PENDING / "conflicts.json"
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(conflicts),
        "conflicts": conflicts,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def merge_into_entities_file(
    *,
    confirm: bool = False,
    dry_run: bool = False,
) -> tuple[int, int, int]:
    """
  合并抽取术语。
  - 默认不覆盖已有条目
  - confirm=True 时仅合并非冲突项；冲突须先人工处理 conflicts.json
  - locked 条目永不覆盖
  返回 (added, skipped_conflict, skipped_locked)
    """
    path = _term_path()
    if not path.is_file():
        return 0, 0, 0

    conflict_keys = {
        (c["lang"], c["lemma"].lower())
        for c in detect_conflicts()
        if c.get("reason") == "zh_mismatch"
    }
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    added = skipped_conflict = skipped_locked = 0

    for lang, items in load_extracted_glossaries().items():
        block = data.setdefault(lang, {})
        existing = _existing_maps(data, lang)
        for it in items:
            lem = it["lemma"]
            key = lem.lower()
            cat = it.get("_category") or "entities"
            zh = it["zh"]
            if key in existing:
                ex = existing[key]
                if ex["locked"]:
                    skipped_locked += 1
                    continue
                try:
                    from corpus_pipeline.locked_glossary import is_locked_term

                    if is_locked_term(lem, lang):
                        skipped_locked += 1
                        continue
                except ImportError:
                    pass
                if ex["zh"] == zh:
                    continue
                if (lang, key) in conflict_keys and not confirm:
                    skipped_conflict += 1
                    continue
                if (lang, key) in conflict_keys:
                    skipped_conflict += 1
                    continue
            lst = block.setdefault(cat, [])
            if not isinstance(lst, list):
                lst = []
                block[cat] = lst
            lst.append(
                {
                    "lemma": lem,
                    "zh": zh,
                    "note": "corpus_auto",
                    "locked": False,
                }
            )
            existing[key] = {"zh": zh, "category": cat, "locked": False}
            zh_to = data.setdefault("zh_to", {})
            if isinstance(zh_to, dict):
                cell = zh_to.setdefault(zh, {}) if isinstance(zh_to.get(zh), dict) else {}
                if not isinstance(zh_to.get(zh), dict):
                    zh_to[zh] = cell
                prev = cell.get(lang)
                if isinstance(prev, str) and prev.strip() and prev.strip().lower() != lem.lower():
                    try:
                        from slavic_lemma_rank import pick_preferred_slavic_lemma

                        cell[lang] = pick_preferred_slavic_lemma(
                            [prev.strip(), lem], lang, zh=zh
                        )
                    except ImportError:
                        cell[lang] = lem
                elif lang not in cell or not str(cell.get(lang) or "").strip():
                    cell[lang] = lem
            added += 1

    if added and not dry_run:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        clear_terminology_cache()
    return added, skipped_conflict, skipped_locked
