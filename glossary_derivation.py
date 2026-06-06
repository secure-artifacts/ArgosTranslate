"""
术语派生词：句子在本地分析；联网仅查询单个词条。

- 派生候选：bkrs.info「ссылки с / слова с / сателлиты」
- 词性与变格：优先本地 pymorphy2；必要时仅对选中的单个词查 ru.wiktionary
"""
from __future__ import annotations

import os
import re
from typing import Any

_RU_WORD = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")

_ROLE_POS: dict[str, frozenset[str]] = {
    "predicate": frozenset({"ADJF", "ADJS", "PRTS", "PRTF", "VERB", "INFN"}),
    "modifier": frozenset({"ADJF", "ADJS", "PRTF", "PRTS"}),
    "adverb": frozenset({"ADVB"}),
    "object": frozenset({"NOUN", "NUMR", "NPRO"}),
}

_POS_HINT = {
    "ADJF": "adj",
    "ADJS": "adj",
    "PRTF": "adj",
    "PRTS": "adj",
    "VERB": "verb",
    "INFN": "verb",
    "ADVB": "adv",
    "NOUN": "noun",
    "NUMR": "noun",
    "NPRO": "noun",
}


def online_derivation_enabled() -> bool:
    v = (os.environ.get("ARGOS_GLOSSARY_DERIVE_ONLINE") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _gm():
    import glossary_manager as gm

    return gm


def _morph_for_lang(lang: str):
    code = (lang or "").strip().lower()
    if code == "uk":
        import glossary_inflection as gi

        return gi._morph_for_lang(code)
    return _gm().shared_morph_analyzer()


def _bkrs_query_lemma(surface: str, lang: str) -> str:
    import bkrs_parser as bp

    clean = bp.assert_single_word_query(surface)
    code = (lang or "").strip().lower()
    if code == "uk":
        try:
            import uk_lookup_bridge as ulb

            ru = (ulb.uk_to_russian_for_bkrs(clean) or "").strip()
            if ru:
                return bp.assert_single_word_query(ru)
        except Exception:
            pass
    return clean


def fetch_bkrs_derivatives_single_word(surface: str, lang: str) -> list[str]:
    """联网：仅提交单个词到 bkrs.info。"""
    if not online_derivation_enabled():
        return []
    try:
        import bkrs_parser as bp

        query = _bkrs_query_lemma(surface, lang)
        pack = bp.lookup_russian_derivatives(query)
        return list(pack.get("derivatives") or [])
    except Exception:
        return []


def _parse_pos(surface: str, morph, lang: str) -> str:
    if morph is None:
        return ""
    gm = _gm()
    parses = morph.parse(surface)
    if not parses:
        return ""
    p = (
        gm.pick_morph_parse(parses, surface)
        if hasattr(gm, "pick_morph_parse")
        else parses[0]
    )
    return gm.safe_parse_pos(p) if hasattr(gm, "safe_parse_pos") else ""


def _stem_overlap(base: str, cand: str) -> int:
    a = (base or "").casefold()
    b = (cand or "").casefold()
    if not a or not b:
        return 0
    limit = min(len(a), len(b), 8)
    for n in range(limit, 2, -1):
        if a[:n] == b[:n]:
            return n
    return 0


def _score_derivative(
    candidate: str,
    base: str,
    role: str,
    morph,
) -> float:
    pos = _parse_pos(candidate, morph, "")
    want = _ROLE_POS.get(role) or _ROLE_POS["object"]
    if not pos:
        return -1.0
    score = 0.0
    if pos in want:
        score += 10.0
        if pos in ("ADJF", "ADJS") and role in ("predicate", "modifier"):
            score += 6.0
        if pos == "ADVB" and role == "adverb":
            score += 6.0
        if pos in ("VERB", "INFN") and role in ("predicate", "modifier"):
            score += 1.0
    elif role in ("predicate", "modifier") and pos in ("NOUN",):
        score -= 3.0
    score += _stem_overlap(base, candidate)
    if candidate.casefold() == base.casefold():
        score -= 5.0
    if len(candidate) > len(base) + 8:
        score -= 2.0
    return score


def pick_derivative_for_role(
    lemma: str,
    role: str,
    lang: str,
    *,
    extra_candidates: list[str] | None = None,
) -> tuple[str, str | None] | None:
    """
    本地根据语法角色从派生候选中选一个词形（lemma, pos_hint）。
    候选来自 bkrs（单词联网）与 extra_candidates；评分仅用本地 morph。
    """
    base = (lemma or "").strip()
    code = (lang or "").strip().lower()
    if not base or code not in ("ru", "uk"):
        return None
    if role not in ("predicate", "modifier", "adverb"):
        return None

    morph = _morph_for_lang(code)
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(w: str) -> None:
        w = (w or "").strip()
        if not w or not _RU_WORD.fullmatch(w):
            return
        k = w.casefold()
        if k in seen:
            return
        seen.add(k)
        candidates.append(w)

    for w in extra_candidates or []:
        _add(w)
    if role in ("predicate", "modifier"):
        try:
            import glossary_inflection as gi

            sug = gi.suggest_predicate_adjective(base, code)
            if sug:
                _add(sug)
        except Exception:
            pass
    for w in fetch_bkrs_derivatives_single_word(base, code):
        _add(w)

    if not candidates:
        return None

    best_word = ""
    best_score = -1.0
    best_pos = ""
    for cand in candidates:
        sc = _score_derivative(cand, base, role, morph)
        if sc > best_score:
            best_score = sc
            best_word = cand
            best_pos = _parse_pos(cand, morph, code)

    if not best_word or best_score < 5.0:
        return None
    hint = _POS_HINT.get(best_pos)
    return best_word, hint


def inflect_single_word_online_safe(
    surface: str,
    grammemes: set[str],
    lang: str,
    *,
    pos_hint: str | None = None,
) -> str | None:
    """
    变格单个词：先本地 pymorphy2；失败且允许联网时，仅将该词提交 wiktionary。
    """
    word = (surface or "").strip()
    code = (lang or "").strip().lower()
    if not word or code not in ("ru", "uk"):
        return None

    import glossary_inflection as gi

    morph = gi._morph_for_lang(code)
    got = gi._inflect_with_morph(morph, word, grammemes, pos_hint=pos_hint)
    if got:
        return got
    if not online_derivation_enabled() or code != "ru":
        return None
    try:
        import bkrs_parser as bp
        import wiktionary_parser as wp

        query = bp.assert_single_word_query(word)
        wi = wp.get_russian_inflections(query, timeout=12.0)
        lemma = (wi.get("lemma") or query).strip() or query
        got2 = gi._inflect_with_morph(morph, lemma, grammemes, pos_hint=pos_hint)
        if got2:
            return got2
        forms = wi.get("forms") or []
        if isinstance(forms, list):
            for item in forms:
                if not isinstance(item, dict):
                    continue
                form = str(item.get("form") or item.get("word") or "").strip()
                if not form:
                    continue
                if gi._surface_matches_grammemes(morph, form, grammemes):
                    return form
    except Exception:
        return None
    return None
