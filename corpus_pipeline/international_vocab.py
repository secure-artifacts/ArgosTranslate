"""
从国际开放语料拉取日常词汇对译（Tatoeba CC BY + Wiktionary + 种子 verified）。

输出：data/glossary/international/daily_{ru|uk}_zh.json
合并：tools/ingest_international_vocab.py --apply
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from corpus_pipeline.config import ROOT

SEED_PATH = ROOT / "data" / "terminology" / "seeds" / "daily_life_zh.json"
OUT_DIR = ROOT / "data" / "glossary" / "international"

CYR = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ][А-Яа-яЁёІіЇїЄєҐґ'\-]{2,}")
SKIP_TOKENS = frozenset(
    {
        "есть", "что", "это", "более", "как", "для", "или", "нет", "ли", "на", "по",
        "из", "при", "без", "все", "ещё", "eще", "так", "там", "тут", "они", "она",
        "его", "ему", "ней", "них", "мне", "теб", "вас", "нас", "был", "была", "были",
        "лежит", "стоит", "где", "когда", "можно", "нужно", "давайте", "пожалуйста",
        "рано", "встал", "закрой", "открой", "принеси", "будь", "ласка", "никогда",
        "лежать", "стоять", "хотим", "хочу", "мой", "моя", "мои", "твою", "ваш",
        "годині", "шостій", "бачив", "мені", "кіт", "кот", "давай", "заховаймося",
    }
)
TATOEBA_LANG = {"ru": "rus", "uk": "ukr"}
SESSION = requests.Session()
SESSION.headers.update(
    {"User-Agent": "ArgosTranslateLocalGlossary/1.2 (educational; CC-BY Tatoeba)"}
)


def _load_seed() -> dict[str, Any]:
    if not SEED_PATH.is_file():
        return {"words": [], "verified": {}}
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _lemma(word: str, lang: str) -> str:
    try:
        from slavic_lemma_rank import slavic_normal_form

        return slavic_normal_form(word, lang)
    except Exception:
        return (word or "").strip()


def _is_noun(word: str, lang: str) -> bool:
    try:
        from slavic_lemma_rank import _parse_best

        p = _parse_best(word, lang)
        if p is None:
            return False
        tag = str(getattr(p, "tag", "") or "")
        if "VERB" in tag or "INFN" in tag or "PRTF" in tag or "PRTS" in tag:
            return False
        if "ADVB" in tag or "CONJ" in tag or "PREP" in tag:
            return False
        return "NOUN" in tag or "ADJF" in tag
    except Exception:
        return False


def _score_token(raw: str, lang: str) -> tuple[str, float]:
    lem = _lemma(raw, lang)
    if not lem or lem.lower() in SKIP_TOKENS:
        return "", 0.0
    if not _is_noun(raw, lang) and not _is_noun(lem, lang):
        return "", 0.0
    try:
        from slavic_lemma_rank import _pymorphy_score

        sc = _pymorphy_score(lem, lang)
    except Exception:
        sc = 0.5
    return lem, sc


def fetch_tatoeba_lemma(zh_word: str, lang: str, *, limit: int = 12) -> tuple[str, float, int]:
    """从 Tatoeba 含该词的例句中统计最可能的俄/乌 lemma。"""
    trans = TATOEBA_LANG.get(lang)
    if not trans:
        return "", 0.0, 0
    try:
        r = SESSION.get(
            "https://api.tatoeba.org/v1/sentences",
            params={
                "lang": "cmn",
                "q": f"={zh_word}",
                "sort": "relevance",
                "limit": limit,
                "showtrans:lang": trans,
                "trans:lang": trans,
            },
            timeout=25,
        )
        r.raise_for_status()
        rows = r.json().get("data") or []
    except Exception:
        return "", 0.0, 0

    counts: Counter[str] = Counter()
    scores: dict[str, float] = {}
    hit_sentences = 0
    for s in rows:
        src = str(s.get("text") or "")
        if zh_word not in src:
            continue
        hit_sentences += 1
        for tr in s.get("translations") or []:
            if tr.get("lang") != trans:
                continue
            for raw in CYR.findall(str(tr.get("text") or "")):
                lem, sc = _score_token(raw, lang)
                if not lem:
                    continue
                key = lem.lower()
                counts[key] += 1
                scores[key] = max(scores.get(key, 0.0), sc)

    if not counts:
        return "", 0.0, hit_sentences
    best_key, freq = counts.most_common(1)[0]
    if freq < 3:
        return "", 0.0, hit_sentences
    # 还原大小写：取计数最高的原始形再 lemmatize
    confidence = min(0.98, 0.45 + 0.08 * freq + 0.15 * scores.get(best_key, 0.0))
    # 找代表形
    for s in rows:
        for tr in s.get("translations") or []:
            for raw in CYR.findall(str(tr.get("text") or "")):
                if _lemma(raw, lang).lower() == best_key:
                    return _lemma(raw, lang), confidence, hit_sentences
    return best_key, confidence, hit_sentences


def resolve_word(
    zh_word: str,
    verified: dict[str, Any],
    *,
    throttle_sec: float = 0.35,
) -> dict[str, Any]:
    """单条中文词 → ru/uk lemma + 置信度 + 来源。"""
    z = (zh_word or "").strip()
    out: dict[str, Any] = {"zh": z, "ru": "", "uk": "", "confidence": 0.0, "source": []}
    if not z:
        return out

    v = verified.get(z) if isinstance(verified, dict) else None
    if isinstance(v, dict):
        if v.get("ru"):
            out["ru"] = str(v["ru"]).strip()
        if v.get("uk"):
            out["uk"] = str(v["uk"]).strip()
        out["source"].append("verified")
        out["confidence"] = 0.95
        if v.get("wrong_ru"):
            out["wrong_ru"] = list(v["wrong_ru"])
        if v.get("wrong_uk"):
            out["wrong_uk"] = list(v["wrong_uk"])

    for lang in ("ru", "uk"):
        if out.get(lang):
            continue
        lem, conf, hits = fetch_tatoeba_lemma(z, lang)
        time.sleep(throttle_sec)
        if lem:
            out[lang] = lem
            out["source"].append(f"tatoeba:{lang}:{hits}")
            out["confidence"] = max(float(out.get("confidence") or 0), conf)

    if out["ru"] or out["uk"]:
        out["confidence"] = round(float(out.get("confidence") or 0), 3)
    return out


def fetch_daily_vocab(
    *,
    words: list[str] | None = None,
    min_confidence: float = 0.55,
    throttle_sec: float = 0.35,
) -> list[dict[str, Any]]:
    seed = _load_seed()
    word_list = words or list(seed.get("words") or [])
    verified = seed.get("verified") or {}
    results: list[dict[str, Any]] = []
    for w in word_list:
        row = resolve_word(str(w).strip(), verified, throttle_sec=throttle_sec)
        if not row.get("ru") and not row.get("uk"):
            continue
        if float(row.get("confidence") or 0) < min_confidence:
            if "verified" not in row.get("source", []):
                continue
        results.append(row)
    return results


def write_glossary_files(rows: list[dict[str, Any]]) -> tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: dict[str, dict[str, Any]] = {
        "ru": {"meta": {}, "entries": []},
        "uk": {"meta": {}, "entries": []},
    }
    for lang in ("ru", "uk"):
        out[lang]["meta"] = {
            "source_lang": lang,
            "target_lang": "zh",
            "category": "daily",
            "domain": "daily_life",
            "sources": ["Tatoeba CC BY 2.0 FR", "Wiktionary", "verified"],
            "generated": ts,
            "merge_min_confidence": 0.72,
        }
    for row in rows:
        zh = str(row.get("zh") or "").strip()
        conf = float(row.get("confidence") or 0)
        for lang in ("ru", "uk"):
            lem = str(row.get(lang) or "").strip()
            if not lem:
                continue
            out[lang]["entries"].append(
                {
                    "lemma": lem,
                    "zh": zh,
                    "confidence": conf,
                    "entity_type": "daily",
                    "source": row.get("source") or [],
                }
            )
    ru_path = OUT_DIR / "daily_ru_zh.json"
    uk_path = OUT_DIR / "daily_uk_zh.json"
    ru_path.write_text(
        json.dumps(out["ru"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    uk_path.write_text(
        json.dumps(out["uk"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ru_path, uk_path


def apply_to_entities_and_terms(
    rows: list[dict[str, Any]],
    *,
    min_confidence: float = 0.72,
) -> tuple[int, int]:
    """
    写入 entities_and_terms.json 的 daily 分类与 zh_to。
    返回 (added_lemma, added_zh_to)。
    """
    from corpus_pipeline.merge_into_glossary import clear_terminology_cache

    path = ROOT / "data" / "terminology" / "entities_and_terms.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    zh_to = data.setdefault("zh_to", {})
    added_lemma = added_zh_to = 0

    for lang in ("ru", "uk"):
        block = data.setdefault(lang, {})
        daily = block.setdefault("daily", [])
        by_zh: dict[str, dict[str, Any]] = {
            str(it.get("zh") or "").strip(): it
            for it in daily
            if isinstance(it, dict) and str(it.get("zh") or "").strip()
        }

        for row in rows:
            conf = float(row.get("confidence") or 0)
            if conf < min_confidence:
                continue
            zh = str(row.get("zh") or "").strip()
            lem = str(row.get(lang) or "").strip()
            if not zh or not lem:
                continue
            item = {
                "lemma": lem,
                "zh": zh,
                "source": "international_vocab",
                "confidence": conf,
            }
            prev = by_zh.get(zh)
            if prev is None:
                daily.append(item)
                by_zh[zh] = item
                added_lemma += 1
            elif float(prev.get("confidence") or 0) <= conf:
                prev.update(item)

    for row in rows:
        conf = float(row.get("confidence") or 0)
        if conf < min_confidence:
            continue
        zh = str(row.get("zh") or "").strip()
        if not zh:
            continue
        cell = zh_to.get(zh)
        if isinstance(cell, dict) and cell.get("locked"):
            continue
        ru = str(row.get("ru") or "").strip()
        uk = str(row.get("uk") or "").strip()
        if not ru and not uk:
            continue
        new_cell: dict[str, Any] = {
            "source": "international_vocab",
            "confidence": conf,
        }
        if ru:
            new_cell["ru"] = ru
        if uk:
            new_cell["uk"] = uk
        for key in ("wrong_ru", "wrong_uk"):
            if row.get(key):
                new_cell[key] = row[key]
        if isinstance(cell, dict) and not cell.get("locked"):
            cell.update(new_cell)
            zh_to[zh] = cell
        elif zh not in zh_to:
            zh_to[zh] = new_cell
            added_zh_to += 1

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    clear_terminology_cache()
    return added_lemma, added_zh_to
