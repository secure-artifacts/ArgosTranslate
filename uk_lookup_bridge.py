"""
乌克兰语查词：先 uk→ru 直译，再按俄语词形查询大БКРС（bkrs.info）。
变位形优先用 Goroh 不定式（或规则推测）再译成俄语，避免把乌语词形直接送进 BKRS。
"""
from __future__ import annotations

import json
import re

from terminology_bridge import portable_root

_CACHE_PATH = portable_root() / "data" / "cache" / "uk_ru_bkrs_bridge_v2.json"
_RU_CYR = re.compile(r"[А-Яа-яЁё]+(?:\u0301|\u0300|\u030f)?")
_UK_MARKERS = re.compile(r"[іїєґІЇЄҐ]")
_STRESS = re.compile(r"[\u0301\u0300\u030f]")
_CACHE: dict[str, str] = {}
_LOADED = False

# 乌语不定式 → 俄语不定式（与 translation_quality._RU_UK_VERB_OVERRIDE 互补）
_UK_RU_VERB_OVERRIDE: dict[str, str] = {
    "увімкнути": "включить",
    "увімкнуть": "включить",
    "вимкнути": "выключить",
    "вимкнуть": "выключить",
    "відключити": "отключить",
    "підключити": "подключить",
    "відкрити": "открыть",
    "закрити": "закрыть",
    "увійти": "войти",
}


def _strip_stress(s: str) -> str:
    return _STRESS.sub("", (s or "").strip())


def looks_ukrainian(word: str) -> bool:
    return bool(_UK_MARKERS.search(word or ""))


def looks_russian_for_bkrs(word: str) -> bool:
    w = (word or "").strip()
    if not w or looks_ukrainian(w):
        return False
    return bool(_RU_CYR.search(w))


def bkrs_lemma_looks_invalid(lemma: str) -> bool:
    lem = (lemma or "").strip()
    if not lem:
        return True
    if looks_ukrainian(lem):
        return True
    if not _RU_CYR.search(lem):
        return True
    low = lem.lower()
    # BKRS 误把乌语词形当词条时的脏「原形」
    if re.search(r"ув[іi]?мкн", low):
        return True
    return False


def _load_cache() -> None:
    global _CACHE, _LOADED
    if _LOADED:
        return
    _LOADED = True
    if _CACHE_PATH.is_file():
        try:
            with open(_CACHE_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                _CACHE = {
                    str(k): str(v)
                    for k, v in raw.items()
                    if looks_russian_for_bkrs(str(v))
                }
        except (OSError, json.JSONDecodeError):
            _CACHE = {}


def _save_cache() -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CACHE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_CACHE, f, ensure_ascii=False, indent=2)
    tmp.replace(_CACHE_PATH)


def _verb_override_table() -> dict[str, str]:
    out = dict(_UK_RU_VERB_OVERRIDE)
    try:
        import translation_quality as tq

        for ru, uk in tq._RU_UK_VERB_OVERRIDE.items():
            out.setdefault(_strip_stress(uk).lower(), ru)
    except Exception:
        pass
    return out


def _uk_infinitive_candidates(surface: str, uk_lemma: str | None = None) -> list[str]:
    clean = _strip_stress((surface or "").strip())
    lemma = _strip_stress((uk_lemma or "").strip())
    seen: set[str] = set()
    out: list[str] = []

    def add(w: str) -> None:
        k = _strip_stress(w).lower()
        if not k or k in seen:
            return
        seen.add(k)
        out.append(_strip_stress(w))

    if lemma:
        add(lemma)
    if clean:
        add(clean)
    try:
        from wiktionary_parser import _uk_infinitive_guess

        guess = _uk_infinitive_guess(clean)
        if guess:
            add(guess)
    except Exception:
        pass
    return out


def _first_russian_token(text: str) -> str:
    m = _RU_CYR.search((text or "").strip())
    return m.group(0) if m else ""


def _argos_uk_to_ru(uk_text: str) -> str:
    clean = (uk_text or "").strip()
    if not clean:
        return ""
    try:
        import argostranslate.translate as tr

        tr.get_installed_languages.cache_clear()
        by_code = {l.code: l for l in tr.get_installed_languages()}
        uk = by_code.get("uk")
        ru = by_code.get("ru")
        if uk is not None and ru is not None:
            trans = uk.get_translation(ru)
            if trans is not None:
                return (trans.translate(clean) or "").strip()
    except Exception:
        pass
    return ""


def uk_to_russian_for_bkrs(uk_word: str, *, uk_lemma: str | None = None) -> str:
    """将乌克兰语词形译为俄语词形，供 bkrs.info 查询。"""
    overrides = _verb_override_table()
    _load_cache()

    for cand in _uk_infinitive_candidates(uk_word, uk_lemma):
        low = cand.lower()
        if low in overrides:
            token = overrides[low]
            _CACHE[low] = token
            try:
                _save_cache()
            except OSError:
                pass
            return token
        if low in _CACHE:
            return _CACHE[low]

    for cand in _uk_infinitive_candidates(uk_word, uk_lemma):
        low = cand.lower()
        ru_out = _argos_uk_to_ru(cand)
        token = _first_russian_token(ru_out)
        if looks_russian_for_bkrs(token):
            _CACHE[low] = token
            try:
                _save_cache()
            except OSError:
                pass
            return token

    return ""


def fetch_bkrs_for_ukrainian(
    uk_surface: str,
    *,
    uk_lemma: str | None = None,
    timeout: float = 14.0,
) -> dict:
    """uk 表面形式 → ru → bkrs 释义（优先用乌语不定式译俄语）。"""
    import bkrs_parser as bp

    clean = (uk_surface or "").strip()
    ru_word = uk_to_russian_for_bkrs(clean, uk_lemma=uk_lemma)
    out: dict = {
        "ru_lookup_word": ru_word,
        "bkrs_lines": [],
        "bkrs_lemma": "",
        "bkrs_url": "",
        "bkrs_error": None,
    }
    if not ru_word:
        out["bkrs_error"] = "无法得到俄语对应词"
        return out
    try:
        bk = bp.lookup_russian_word(ru_word, timeout=timeout)
        out["bkrs_lines"] = list(bk.get("definition_lines") or [])
        out["bkrs_lemma"] = (bk.get("lemma") or "").strip()
        out["bkrs_url"] = bk.get("bkrs_url") or bp.BKRS_BASE
        if bk.get("error") and not out["bkrs_lines"]:
            out["bkrs_error"] = bk.get("error")
    except Exception as e:
        out["bkrs_error"] = str(e)

    if (
        uk_lemma
        and (
            not out["bkrs_lines"]
            or bkrs_lemma_looks_invalid(out.get("bkrs_lemma") or "")
            or looks_ukrainian(out.get("ru_lookup_word") or "")
        )
    ):
        ru2 = uk_to_russian_for_bkrs(uk_lemma)
        if ru2 and ru2 != ru_word:
            try:
                bk2 = bp.lookup_russian_word(ru2, timeout=timeout)
                lines2 = list(bk2.get("definition_lines") or [])
                lem2 = (bk2.get("lemma") or "").strip()
                if lines2 and not bkrs_lemma_looks_invalid(lem2):
                    out["ru_lookup_word"] = ru2
                    out["bkrs_lines"] = lines2
                    out["bkrs_lemma"] = lem2
                    out["bkrs_url"] = bk2.get("bkrs_url") or bp.BKRS_BASE
                    out["bkrs_error"] = None
            except Exception:
                pass
    return out


def bkrs_pack_needs_retry(pack: dict, *, uk_lemma: str | None = None) -> bool:
    if not uk_lemma:
        return False
    if looks_ukrainian(pack.get("ru_lookup_word") or ""):
        return True
    if bkrs_lemma_looks_invalid(pack.get("bkrs_lemma") or ""):
        return True
    if not pack.get("bkrs_lines"):
        return True
    return False
