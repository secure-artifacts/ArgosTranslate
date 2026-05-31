"""
俄/乌进阶形态修补：动词变位、双宾语、关系从句一致、同形异义消歧。

基于 pymorphy2（OpenCorpora）+ 规则表 slavic_grammar_rules.py。
句法启发式参考 Sussex Blok Grammar、Oxford Russian Grammar、
Wikibooks Russian Relative clauses、LearnRussian dative constructions。
"""
from __future__ import annotations

import os
import re
from typing import Any

import slavic_grammar_rules as _sgr

_gi_cache: Any = None
_gm_cache: Any = None

_APOST = r"'\u02BC\u2019\u02B9"
_RU_WORD = re.compile(
    rf"[А-Яа-яЁё{_APOST}]+(?:-[А-Яа-яЁё{_APOST}]+)*"
)
_UK_WORD = re.compile(
    rf"[А-Яа-яІіЇїЄєҐґ{_APOST}]+(?:-[А-Яа-яІіЇїЄєҐґ{_APOST}]+)*"
)

_OC_PERSON = frozenset({"1per", "2per", "3per"})
_OC_TENSE = frozenset({"pres", "past", "futr", "inf", "prtf", "prts"})
_OC_GENDER = frozenset({"masc", "femn", "neut"})
_OC_NUMBER = frozenset({"sing", "plur"})
_OC_CASES = _sgr.OC_CASES


def _gi():
    global _gi_cache
    if _gi_cache is None:
        import glossary_inflection as gi

        _gi_cache = gi
    return _gi_cache


def _gm():
    global _gm_cache
    if _gm_cache is None:
        import glossary_manager as gm

        _gm_cache = gm
    return _gm_cache


def advanced_slavic_morph_enabled() -> bool:
    v = os.environ.get("ARGOS_SLAVIC_ADVANCED_MORPH", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


def _word_re(lang: str) -> re.Pattern[str]:
    return _UK_WORD if (lang or "").strip().lower() == "uk" else _RU_WORD


def _plain(w: str) -> str:
    return (w or "").lower().replace("\u2019", "'").replace("\u02bc", "'")


def _morph(lang: str):
    code = (lang or "").strip().lower()
    if code == "uk":
        return _gi()._shared_uk_morph_analyzer()
    return _gm().shared_morph_analyzer()


def _word_spans(line: str, lang: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in _word_re(lang).finditer(line or "")]


def _rebuild(line: str, spans: list[tuple[int, int, str]], surfaces: list[str]) -> str:
    if not spans:
        return line
    out: list[str] = []
    last = 0
    for (s, e, _), surf in zip(spans, surfaces):
        out.append(line[last:s])
        out.append(surf)
        last = e
    out.append(line[last:])
    return "".join(out)


def _cap_like(before: str, after: str) -> str:
    if before and before[0].isupper() and after and after[0].islower():
        return after[0].upper() + after[1:]
    return after


def _parse_case(parse) -> str:
    try:
        if parse is not None and parse.tag.case is not None:
            return str(parse.tag.case)
    except (ValueError, AttributeError, TypeError):
        pass
    return ""


def _parse_in_sentence(
    morph,
    surface: str,
    line: str,
    start: int,
    end: int,
):
    if morph is None:
        return None
    try:
        parses = morph.parse(surface)
    except (ValueError, AttributeError, TypeError):
        return None
    if not parses:
        return None
    gm = _gm()
    if hasattr(gm, "pick_morph_parse_in_sentence"):
        return gm.pick_morph_parse_in_sentence(
            parses, surface, line, start, end
        )
    return gm.pick_morph_parse(parses, surface)


def _tag_bits(parse) -> set[str]:
    bits: set[str] = set()
    if parse is None:
        return bits
    try:
        tag = parse.tag
        for attr in ("case", "number", "gender", "person", "tense", "aspect", "mood"):
            v = getattr(tag, attr, None)
            if v is not None:
                bits.add(str(v))
    except (ValueError, AttributeError, TypeError):
        pass
    return bits


def _verb_lemma(parse) -> str:
    try:
        return (parse.normal_form or "").lower()
    except AttributeError:
        return ""


def _is_verb_token(parse) -> bool:
    return _gm().safe_parse_pos(parse) == "VERB"


def _is_finite_verb(parse) -> bool:
    if not _is_verb_token(parse):
        return False
    bits = _tag_bits(parse)
    if "inf" in bits:
        return False
    return bool(bits & (_OC_TENSE | _OC_PERSON) or "past" in bits)


def _impersonal_verbs(lang: str) -> frozenset[str]:
    if (lang or "").strip().lower() == "uk":
        return _sgr.UK_IMPERSONAL_NOM_THEME
    return _sgr.RU_IMPERSONAL_NOM_THEME


def _personal_lemmas(lang: str) -> frozenset[str]:
    if (lang or "").strip().lower() == "uk":
        return _sgr.UK_PERSONAL_PRONOUN_LEMMA
    return _sgr.RU_PERSONAL_PRONOUN_LEMMA


def _is_animate(parse) -> bool:
    return _gi()._is_animate_parse(parse)


def _is_personal_pronoun(parse, lang: str) -> bool:
    return _gi()._is_personal_pronoun_parse(parse, lang)


def _noun_likely_dative(parse, lang: str) -> bool:
    return _gi()._noun_likely_dative_object(parse, lang)


def _datv_accs_verbs(lang: str) -> frozenset[str]:
    if (lang or "").strip().lower() == "uk":
        return _sgr.UK_VERB_DATV_THEN_ACCS
    return _sgr.RU_VERB_DATV_THEN_ACCS


def _subject_agreement_grammemes(subject_parse, verb_parse, lang: str) -> set[str] | None:
    """主语→动词一致 grammemes（OpenCorpora）。"""
    if subject_parse is None or verb_parse is None:
        return None
    vbits = _tag_bits(verb_parse)
    sbits = _tag_bits(subject_parse)
    out: set[str] = set()

    if "past" in vbits or (not (vbits & {"pres", "futr"}) and "past" in sbits):
        out.add("past")
        if "plur" in sbits:
            out.add("plur")
        else:
            out.add("sing")
            g = sbits & _OC_GENDER
            if g:
                out.update(g)
            elif _gm().safe_parse_pos(subject_parse) == "NPRO":
                nf = _verb_lemma(subject_parse)
                if nf in ("она", "вона"):
                    out.add("femn")
                elif nf in ("оно", "воно"):
                    out.add("neut")
                else:
                    out.add("masc")
            else:
                out.add("masc")
        return out

    if "pres" in vbits or "futr" in vbits or not vbits & _OC_TENSE:
        tense = "futr" if "futr" in vbits else "pres"
        out.add(tense)
        if "plur" in sbits:
            out.add("plur")
        else:
            out.add("sing")
        nf = _verb_lemma(subject_parse)
        pers = sbits & _OC_PERSON
        if pers:
            out.update(pers)
        elif nf == "я":
            out.add("1per")
        elif nf in ("ты", "ти"):
            out.add("2per")
        elif nf in ("мы", "ми"):
            out.add("1per")
            out.discard("sing")
            out.add("plur")
        elif nf in ("вы", "ви"):
            out.add("2per")
            out.discard("sing")
            out.add("plur")
        else:
            out.add("3per")
        return out
    return None


def _find_subject_index(
    surfaces: list[str],
    lowers: list[str],
    verb_index: int,
    morph,
    lang: str,
) -> int | None:
    imp = _impersonal_verbs(lang)
    vps = morph.parse(lowers[verb_index])
    if vps and _verb_lemma(vps[0]) in imp:
        return None
    for j in range(verb_index - 1, max(-1, verb_index - 6), -1):
        if j < 0:
            break
        if _is_relative_pronoun(lowers[j], lang):
            break
        ps = morph.parse(lowers[j])
        if not ps:
            continue
        p = ps[0]
        pos = _gm().safe_parse_pos(p)
        if pos == "VERB" and _is_finite_verb(p):
            break
        if pos == "NPRO" and _verb_lemma(p) in _personal_lemmas(lang):
            case = _parse_case(p)
            if case in ("", "nomn"):
                return j
            continue
        if pos == "NOUN":
            case = _parse_case(p)
            if case in ("", "nomn"):
                return j
    return None


def _inflect_verb(morph, surface: str, grammemes: set[str]) -> str | None:
    if morph is None or not grammemes:
        return None
    ps = morph.parse(surface)
    if not ps:
        return None
    verbs = [p for p in ps if _gm().safe_parse_pos(p) == "VERB"]
    if not verbs:
        return None
    p = max(verbs, key=lambda x: getattr(x, "score", 0))
    tags = frozenset(g for g in grammemes if g)
    for attempt in (
        tags,
        tags | {"indc"},
        tags - _OC_CASES,
    ):
        if not attempt:
            continue
        try:
            inf = p.inflect(attempt)
            if inf is not None and getattr(inf, "word", None):
                w = inf.word
                if w.lower() != surface.lower():
                    return _cap_like(surface, w)
        except (ValueError, AttributeError, TypeError):
            continue
    return None


def _count_coordinated_subjects(
    lowers: list[str],
    verb_index: int,
    morph,
    lang: str,
) -> int:
    """并列主语（он и она / мать и отец）→ 复数谓语（Oxford Russian Grammar § agreement）。"""
    if morph is None or verb_index <= 0:
        return 0
    count = 0
    j = verb_index - 1
    while j >= 0 and verb_index - j <= 12:
        low = lowers[j]
        if low in _sgr.COORD_CONJ:
            j -= 1
            continue
        if _is_relative_pronoun(low, lang):
            break
        subconj = (
            _sgr.UK_SUBORDINATE_CONJ
            if (lang or "").strip().lower() == "uk"
            else _sgr.RU_SUBORDINATE_CONJ
        )
        if low in subconj:
            break
        ps = morph.parse(low)
        if not ps:
            if count:
                break
            j -= 1
            continue
        p = ps[0]
        pos = _gm().safe_parse_pos(p)
        if pos in ("NOUN", "NPRO"):
            if _parse_case(p) in ("", "nomn"):
                count += 1
            j -= 1
            continue
        if pos == "VERB" and _is_finite_verb(p):
            break
        if pos in ("ADJF", "ADJS", "PRTF", "PRTS"):
            j -= 1
            continue
        if count:
            break
        j -= 1
    return count


def _plural_verb_grammemes(verb_parse) -> set[str]:
    vbits = _tag_bits(verb_parse)
    if "past" in vbits or ("pres" not in vbits and "futr" not in vbits):
        return {"past", "plur"}
    tense = "futr" if "futr" in vbits else "pres"
    return {tense, "plur", "3per", "indc"}


def _fix_multiword_prep_phrases(
    surfaces: list[str],
    lowers: list[str],
    morph,
    lang: str,
) -> None:
    _gi().fix_multiword_prep_surfaces_in_place(surfaces, lowers, morph, lang)


def _fix_verb_agreement(
    surfaces: list[str],
    lowers: list[str],
    spans: list[tuple[int, int, str]],
    line: str,
    morph,
    lang: str,
) -> None:
    if morph is None:
        return
    n = len(surfaces)
    for i in range(n):
        ps = morph.parse(lowers[i])
        if not ps:
            continue
        vp = ps[0]
        if not _is_finite_verb(vp):
            continue
        if _verb_lemma(vp) in _impersonal_verbs(lang):
            continue
        coord_n = _count_coordinated_subjects(lowers, i, morph, lang)
        if coord_n >= 2:
            grams = _plural_verb_grammemes(vp)
            fixed = _inflect_verb(morph, surfaces[i], grams)
            if fixed:
                surfaces[i] = fixed
                lowers[i] = _plain(fixed)
            continue
        sj = _find_subject_index(surfaces, lowers, i, morph, lang)
        if sj is None:
            continue
        sps = morph.parse(lowers[sj])
        if not sps:
            continue
        grams = _subject_agreement_grammemes(sps[0], vp, lang)
        if not grams:
            continue
        fixed = _inflect_verb(morph, surfaces[i], grams)
        if fixed:
            surfaces[i] = fixed
            lowers[i] = _plain(fixed)


def _fix_double_object_verbs(
    surfaces: list[str],
    lowers: list[str],
    morph,
    lang: str,
) -> None:
    """双宾语：кому + что（MasterRussian / LearnRussian dative frames）。"""
    if morph is None:
        return
    verbs = _datv_accs_verbs(lang)
    n = len(surfaces)
    gi = _gi()
    for i in range(n):
        ps = morph.parse(lowers[i])
        if not ps or _gm().safe_parse_pos(ps[0]) != "VERB":
            continue
        nf = _verb_lemma(ps[0])
        if nf not in verbs:
            continue
        objects: list[tuple[int, Any]] = []
        j = i + 1
        while j < n and j <= i + 6:
            if lowers[j] in _sgr.COORD_CONJ:
                j += 1
                continue
            p = morph.parse(lowers[j])
            if not p:
                j += 1
                continue
            pr = p[0]
            pos = _gm().safe_parse_pos(pr)
            if pos not in ("NOUN", "NPRO", "ADJF"):
                if pos == "VERB":
                    break
                j += 1
                continue
            if pos == "ADJF" and j + 1 < n:
                j += 1
                continue
            pn = morph.parse(lowers[j])
            if pn:
                objects.append((j, pn[0]))
            j += 1
            if len(objects) >= 2:
                break
        if not objects:
            continue
        if len(objects) == 1:
            idx, op = objects[0]
            if _noun_likely_dative(op, lang):
                case = "datv"
            else:
                case = "accs"
                if gi._negated_verb_in_context(lowers[: idx], morph, lang):
                    case = "gent"
            cur = _parse_case(op)
            if cur in ("", "nomn") or cur != case:
                grams = gi._grammemes_for_target_case(op, case)
                fixed = gi._try_fix_word_form(morph, surfaces[idx], grams)
                if fixed.lower() != surfaces[idx].lower():
                    surfaces[idx] = fixed
            continue
        # 两个宾语：与格 + 宾格
        (i0, o0), (i1, o1) = objects[0], objects[1]
        for idx, op, case in (
            (i0, o0, "datv"),
            (i1, o1, "accs"),
        ):
            if not _noun_likely_dative(o0, lang) and idx == i0:
                case = "accs"
                if gi._negated_verb_in_context(lowers[: idx], morph, lang):
                    case = "gent"
            if idx == i1 and _noun_likely_dative(o0, lang):
                case = "accs"
                if gi._negated_verb_in_context(lowers[: idx], morph, lang):
                    case = "gent"
            cur = _parse_case(op)
            if cur in ("", "nomn") or (case == "datv" and cur != "datv"):
                grams = gi._grammemes_for_target_case(op, case)
                fixed = gi._try_fix_word_form(morph, surfaces[idx], grams)
                if fixed.lower() != surfaces[idx].lower():
                    surfaces[idx] = fixed


def _relative_forms(lang: str) -> dict[str, frozenset[str]]:
    if (lang or "").strip().lower() == "uk":
        return _sgr.UK_RELATIVE_PRONOUN_FORMS
    return _sgr.RU_RELATIVE_PRONOUN_FORMS


def _relative_nomn(lang: str) -> dict[str, str]:
    if (lang or "").strip().lower() == "uk":
        return _sgr.UK_RELATIVE_PRONOUN_NOMN
    return _sgr.RU_RELATIVE_PRONOUN_NOMN


def _gender_number_key(parse) -> str | None:
    bits = _tag_bits(parse)
    if "plur" in bits:
        return "plur"
    g = bits & _OC_GENDER
    if "femn" in g:
        return "femn"
    if "neut" in g:
        return "neut"
    if "masc" in g:
        return "masc"
    return None


def _is_relative_pronoun(low: str, lang: str) -> bool:
    forms = _relative_forms(lang)
    for pool in forms.values():
        if low in pool:
            return True
    return False


def _fix_relative_pronoun_agreement(
    surfaces: list[str],
    lowers: list[str],
    morph,
    lang: str,
) -> None:
    """
    关系代词与先行词性/数一致（Wikibooks Russian/Relative）。
    例：книга, который → книга, которая
    """
    if morph is None:
        return
    nomn_map = _relative_nomn(lang)
    rel_forms = _relative_forms(lang)
    all_rel = set()
    for pool in rel_forms.values():
        all_rel.update(pool)
    n = len(surfaces)
    for i in range(1, n):
        low = lowers[i]
        if low not in all_rel:
            continue
        ant_idx: int | None = None
        for j in range(i - 1, max(-1, i - 4), -1):
            if j < 0:
                break
            if lowers[j] in _sgr.COORD_CONJ:
                continue
            ps = morph.parse(lowers[j])
            if not ps:
                continue
            if _gm().safe_parse_pos(ps[0]) == "NOUN":
                ant_idx = j
                break
        if ant_idx is None:
            continue
        aps = morph.parse(lowers[ant_idx])
        if not aps:
            continue
        gkey = _gender_number_key(aps[0])
        if not gkey:
            continue
        cur_pool: str | None = None
        for pk, pool in rel_forms.items():
            if low in pool:
                cur_pool = pk
                break
        if cur_pool is None or cur_pool == gkey:
            continue
        cp = morph.parse(low)
        if not cp:
            continue
        src_p = cp[0]
        grams = _tag_bits(src_p) & (_OC_CASES | _OC_NUMBER | _OC_GENDER)
        grams.discard("masc")
        grams.discard("femn")
        grams.discard("neut")
        if gkey == "plur":
            grams.add("plur")
        elif gkey == "femn":
            grams.add("femn")
        elif gkey == "neut":
            grams.add("neut")
        else:
            grams.add("masc")
        if "plur" not in grams and gkey != "plur":
            grams.add("sing")
        target_lem = nomn_map.get(gkey, "")
        tp = morph.parse(target_lem)
        if not tp:
            continue
        try:
            inf = tp[0].inflect(frozenset(grams))
            if inf is not None and getattr(inf, "word", None):
                w = inf.word
                if w.lower() != low:
                    surfaces[i] = _cap_like(surfaces[i], w)
                    lowers[i] = _plain(w)
        except (ValueError, AttributeError, TypeError):
            exp = nomn_map.get(gkey)
            if exp and low in {nomn_map.get(k) for k in nomn_map}:
                surfaces[i] = _cap_like(surfaces[i], exp)
                lowers[i] = _plain(exp)


def _fix_homographs_in_sentence(
    surfaces: list[str],
    lowers: list[str],
    spans: list[tuple[int, int, str]],
    line: str,
    morph,
    lang: str,
) -> None:
    """同形异义：句中前置词/格上下文择优 parse（glossary_manager）。"""
    if morph is None:
        return
    gi = _gi()
    for i, (s, e, _w) in enumerate(spans):
        try:
            parses = morph.parse(surfaces[i])
        except (ValueError, AttributeError, TypeError):
            continue
        if len(parses) <= 1:
            continue
        p = _parse_in_sentence(morph, surfaces[i], line, s, e)
        if p is None:
            continue
        pos = _gm().safe_parse_pos(p)
        if pos not in ("NOUN", "VERB", "ADJF", "ADJS"):
            continue
        if pos == "NPRO" and _is_personal_pronoun(p, lang):
            cur_case = _parse_case(p)
            if cur_case in ("", "nomn"):
                continue
        before = " ".join(surfaces[:i])
        after = " ".join(surfaces[i + 1 :])
        code = (lang or "").strip().lower()
        if code == "ru":
            grams = gi.infer_ru_grammemes(
                before, after, p.normal_form or surfaces[i], morph=morph
            )
        else:
            grams = gi.infer_uk_grammemes(
                before, after, p.normal_form or surfaces[i], morph=morph
            )
        exp_cases = grams & _OC_CASES
        if not exp_cases:
            continue
        exp = next(iter(exp_cases))
        cur = _parse_case(p)
        if cur and cur != exp and cur not in ("", "nomn"):
            continue
        fix_grams = gi._grammemes_for_target_case(p, exp)
        fixed = gi._try_fix_word_form(morph, surfaces[i], fix_grams)
        if fixed and fixed.lower() != surfaces[i].lower():
            surfaces[i] = fixed
            lowers[i] = _plain(fixed)


def _fix_verb_prep_collocations(
    surfaces: list[str],
    lowers: list[str],
    morph,
    lang: str,
) -> None:
    """动词+介词固定搭配（Sussex / OpenRussian patterns）。"""
    if morph is None:
        return
    code = (lang or "").strip().lower()
    coll = (
        _sgr.UK_VERB_PREP_COLLOCATIONS
        if code == "uk"
        else _sgr.RU_VERB_PREP_COLLOCATIONS
    )
    gi = _gi()
    n = len(surfaces)
    for i in range(n - 1):
        ps = morph.parse(lowers[i])
        if not ps:
            continue
        nf = _verb_lemma(ps[0])
        if nf not in coll:
            continue
        prep, case = coll[nf]
        if not prep:
            continue
        if i + 1 >= n or lowers[i + 1] != prep:
            continue
        j = i + 2
        while j < n and j <= i + 5:
            if lowers[j] in _sgr.COORD_CONJ:
                j += 1
                continue
            pr = morph.parse(lowers[j])
            if not pr:
                j += 1
                continue
            pos = _gm().safe_parse_pos(pr[0])
            if pos not in ("NOUN", "ADJF", "NPRO"):
                j += 1
                continue
            cur = _parse_case(pr[0])
            if cur in ("", "nomn") or cur != case:
                grams = gi._grammemes_for_target_case(pr[0], case)
                fixed = gi._try_fix_word_form(morph, surfaces[j], grams)
                if fixed.lower() != surfaces[j].lower():
                    surfaces[j] = fixed
            if pos == "NOUN":
                break
            j += 1


def fix_sentence_advanced_slavic_morphology(sentence: str, lang: str) -> str:
    line = sentence or ""
    if not line.strip() or not advanced_slavic_morph_enabled():
        return line
    if re.search(r"GLOSSA|ＧＬＯＳＳＡ|ГЛОССА", line, re.I):
        return line
    code = (lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return line
    morph = _morph(code)
    if morph is None:
        return line
    spans = _word_spans(line, code)
    if not spans:
        return line
    surfaces = [w for _, _, w in spans]
    lowers = [_plain(w) for w in surfaces]

    _fix_homographs_in_sentence(surfaces, lowers, spans, line, morph, code)
    _fix_multiword_prep_phrases(surfaces, lowers, morph, code)
    _fix_verb_agreement(surfaces, lowers, spans, line, morph, code)
    _fix_double_object_verbs(surfaces, lowers, morph, code)
    _fix_relative_pronoun_agreement(surfaces, lowers, morph, code)
    _fix_verb_prep_collocations(surfaces, lowers, morph, code)

    line = _rebuild(line, spans, surfaces)
    # 第二遍：前述变格后再跑动词一致与多词介词
    spans = _word_spans(line, code)
    surfaces = [w for _, _, w in spans]
    lowers = [_plain(w) for w in surfaces]
    _fix_multiword_prep_phrases(surfaces, lowers, morph, code)
    _fix_verb_agreement(surfaces, lowers, spans, line, morph, code)

    return _rebuild(line, spans, surfaces)


def fix_text_advanced_slavic_morphology(text: str, lang: str) -> str:
    if not (text or "").strip():
        return text
    lines = (text or "").split("\n")
    return "\n".join(
        fix_sentence_advanced_slavic_morphology(ln, lang) for ln in lines
    )
