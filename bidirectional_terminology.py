"""
双向术语：ru/uk↔zh 统一索引、中文专名反查、zh→俄/乌输出校正。

优先级：用户术语库 > locked 内置 > entities > military > political > 语言规则
同一中文对应多个俄/乌词时，按 slavic_lemma_rank 选当地人更常用的形。
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from slavic_lemma_rank import pick_preferred_slavic_lemma
from terminology_registry import (
    _load_entities_and_terms,
    normalize_source_lang,
)

_HAN = re.compile(r"[\u4e00-\u9fff]{2,12}")


def normalize_target_lang(code: str) -> str:
    return normalize_source_lang(code)


@lru_cache(maxsize=1)
def _zh_name_entries() -> dict[str, dict[str, Any]]:
    try:
        import slavic_idioms as si

        return dict(si._zh_name_map())
    except Exception:
        return {}


def _is_locked(item: dict[str, Any]) -> bool:
    return bool(item.get("locked")) or item.get("priority") == "locked"


def _add_zh_candidate(
    bucket: dict[str, list[tuple[str, dict[str, Any] | None, int]]],
    zh: str,
    lemma: str,
    *,
    meta: dict[str, Any] | None = None,
    list_index: int,
) -> None:
    z = (zh or "").strip()
    lem = (lemma or "").strip()
    if not z or not lem:
        return
    for prev, _, _ in bucket.get(z, []):
        if prev.lower() == lem.lower():
            return
    bucket.setdefault(z, []).append((lem, meta, list_index))


@lru_cache(maxsize=2)
def _build_zh_to_slavic_candidates(
    target_lang: str,
) -> dict[str, list[tuple[str, dict[str, Any] | None, int]]]:
    """中文 → 候选俄/乌词（含 metadata 与源表顺序）。"""
    lang = normalize_target_lang(target_lang)
    bucket: dict[str, list[tuple[str, dict[str, Any] | None, int]]] = {}
    if lang not in ("ru", "uk"):
        return bucket

    data = _load_entities_and_terms()
    block = data.get(lang) or {}
    idx = 0
    for category in ("entities", "places", "military", "political", "daily"):
        for item in block.get(category) or []:
            if not isinstance(item, dict):
                continue
            zh = str(item.get("zh") or "").strip()
            lem = str(item.get("lemma") or "").strip()
            if zh and lem:
                _add_zh_candidate(bucket, zh, lem, meta=item, list_index=idx)
                idx += 1

    zh_to = data.get("zh_to") or {}
    if isinstance(zh_to, dict):
        for zh, cell in zh_to.items():
            if not isinstance(cell, dict):
                continue
            meta = cell if _is_locked(cell) else {"usage_rank": 5}
            val = cell.get(lang)
            if isinstance(val, str) and val.strip():
                _add_zh_candidate(
                    bucket, str(zh).strip(), val.strip(), meta=meta, list_index=idx
                )
                idx += 1
            elif isinstance(val, dict):
                lem = str(val.get("lemma") or "").strip()
                if lem:
                    _add_zh_candidate(
                        bucket,
                        str(zh).strip(),
                        lem,
                        meta={**cell, **val},
                        list_index=idx,
                    )
                    idx += 1

    for zh, entry in _zh_name_entries().items():
        lem = str(entry.get(lang) or "").strip()
        if lem:
            _add_zh_candidate(
                bucket, zh, lem, meta={"usage_rank": 8}, list_index=idx
            )
            idx += 1

    try:
        import terminology_bridge as tb

        g = tb.load_glossary()
        for _k, entry in (g or {}).items():
            if not isinstance(entry, dict):
                continue
            zh = str(entry.get("zh") or entry.get("source") or "").strip()
            if not zh:
                continue
            meta = {"usage_rank": 20}
            cell = entry.get(lang)
            if isinstance(cell, str) and cell.strip():
                _add_zh_candidate(bucket, zh, cell.strip(), meta=meta, list_index=idx)
                idx += 1
            elif isinstance(cell, dict):
                lem = str(cell.get("lemma") or "").strip()
                if lem:
                    _add_zh_candidate(bucket, zh, lem, meta=meta, list_index=idx)
                    idx += 1
    except Exception:
        pass
    return bucket


@lru_cache(maxsize=2)
def _build_zh_to_slavic_index(target_lang: str) -> dict[str, str]:
    """中文词/短语 → 目标语优选 lemma（仅 target_lang 轨）。"""
    lang = normalize_target_lang(target_lang)
    out: dict[str, str] = {}
    for zh, rows in _build_zh_to_slavic_candidates(lang).items():
        cands = [r[0] for r in rows]
        metas = [r[1] for r in rows]
        pick = pick_preferred_slavic_lemma(cands, lang, zh=zh, metas=metas)
        if pick:
            out[zh] = pick
    return out


def zh_to_slavic_alternatives(zh: str, target_lang: str) -> list[str]:
    """某中文义项的全部俄/乌候选（已去重）。"""
    z = (zh or "").strip()
    if not z:
        return []
    rows = _build_zh_to_slavic_candidates(target_lang).get(z, [])
    out: list[str] = []
    seen: set[str] = set()
    for lem, _, _ in rows:
        key = lem.lower()
        if key not in seen:
            seen.add(key)
            out.append(lem)
    return out


@lru_cache(maxsize=2)
def _build_slavic_to_zh_by_lang(source_lang: str) -> dict[str, str]:
    from terminology_registry import _build_lemma_index

    return _build_lemma_index(source_lang)


def resolve_zh_to_slavic(zh: str, target_lang: str) -> str | None:
    """中文专名/术语 → 正确俄/乌拼写（禁止跨轨混用）。"""
    z = (zh or "").strip()
    if not z:
        return None
    return _build_zh_to_slavic_index(target_lang).get(z)


def resolve_zh_pair(zh: str) -> dict[str, str]:
    """返回 {'ru': ..., 'uk': ...}（若存在）。"""
    return {
        "ru": resolve_zh_to_slavic(zh, "ru") or "",
        "uk": resolve_zh_to_slavic(zh, "uk") or "",
    }


def _wrong_forms_for_zh(zh: str, target_lang: str) -> list[str]:
    lang = normalize_target_lang(target_lang)
    correct = resolve_zh_to_slavic(zh, lang) or ""
    wrong: list[str] = []
    for alt in zh_to_slavic_alternatives(zh, lang):
        if alt and alt != correct and alt.lower() != correct.lower():
            wrong.append(alt)
    entry = _zh_name_entries().get(zh) or {}
    key = "wrong_ru" if lang == "ru" else "wrong_uk"
    wrong.extend(str(x).strip() for x in (entry.get(key) or []) if str(x).strip())
    data = _load_entities_and_terms()
    zh_cell = (data.get("zh_to") or {}).get(zh)
    if isinstance(zh_cell, dict):
        wrong.extend(
            str(x).strip()
            for x in (zh_cell.get(key) or [])
            if str(x).strip()
        )
    other = "uk" if lang == "ru" else "ru"
    other_lem = resolve_zh_to_slavic(zh, other)
    if other_lem and correct and other_lem != correct:
        wrong.append(other_lem)
    seen: set[str] = set()
    out: list[str] = []
    for w in wrong:
        k = w.lower()
        if k not in seen and k != correct.lower():
            seen.add(k)
            out.append(w)
    return out


def apply_zh_to_slavic_terminology(
    text: str,
    target_lang: str,
    *,
    source_text: str | None = None,
) -> str:
    """
    源文含某中文专名时，将译文中的错写/另一轨/低频同义词替换为优选形。
    """
    if not (text or "").strip():
        return text
    lang = normalize_target_lang(target_lang)
    if lang not in ("ru", "uk"):
        return text
    src = source_text or ""
    if not src.strip():
        return text

    out = text
    index = _build_zh_to_slavic_index(lang)
    for zh in sorted(index.keys(), key=len, reverse=True):
        if zh not in src:
            continue
        correct = index[zh]
        if not correct:
            continue
        for wrong in _wrong_forms_for_zh(zh, lang):
            if wrong and wrong != correct:
                out = re.sub(re.escape(wrong), correct, out, flags=re.IGNORECASE)
    return out


def prevent_cross_track_mixing(
    text: str,
    target_lang: str,
    *,
    source_text: str | None = None,
) -> str:
    """uk 目标时替换误用的俄语专名形；ru 目标时替换误用的乌语专名形。"""
    lang = normalize_target_lang(target_lang)
    if lang not in ("ru", "uk"):
        return text
    src = source_text or ""
    out = text
    other = "uk" if lang == "ru" else "ru"
    idx = _build_zh_to_slavic_index(lang)
    other_idx = _build_zh_to_slavic_index(other)
    for zh in sorted(idx.keys(), key=len, reverse=True):
        if zh not in src:
            continue
        correct = idx.get(zh)
        wrong = other_idx.get(zh)
        if correct and wrong and wrong != correct and wrong in out:
            out = re.sub(re.escape(wrong), correct, out)
    return out


def lookup_tm_langs(from_code: str, to_code: str) -> tuple[str, str]:
    """TM 查询用语言码归一。"""
    src = (from_code or "").strip().lower()
    tgt = (to_code or "").strip().lower()
    if src in ("zh", "zt", "cn", "zho"):
        src = "zh"
    if tgt in ("zh", "zt", "cn", "zho"):
        tgt = "zh"
    if src in ("ua", "ukr"):
        src = "uk"
    if tgt in ("ua", "ukr"):
        tgt = "uk"
    if src == "rus":
        src = "ru"
    if tgt == "rus":
        tgt = "ru"
    return src, tgt


def is_bidirectional_pair(from_code: str, to_code: str) -> bool:
    src, tgt = lookup_tm_langs(from_code, to_code)
    return (src in ("ru", "uk") and tgt == "zh") or (
        src == "zh" and tgt in ("ru", "uk")
    )
