"""
术语占位符还原时的俄语/乌克兰语变格（结合译文中占位符前后上下文 + pymorphy2）。
"""
from __future__ import annotations

import re
from typing import Any

import slavic_grammar_rules as _sgr

# 勿在模块顶层 import glossary_manager：terminology_bridge ↔ glossary_manager 会循环导入。
_gm_cache: Any = None


def _gm():
    global _gm_cache
    if _gm_cache is None:
        import glossary_manager as gm

        _gm_cache = gm
    return _gm_cache


def _ru_prep_governs() -> dict[str, tuple[str, ...]]:
    return getattr(_gm(), "_RU_PREP_GOVERNS", {})


def _morph_ru():
    return _gm().shared_morph_analyzer()

# 乌语数词 П'ять 等含撇号；允许多种 Unicode 撇号
_APOSTrophe = r"'\u02BC\u2019\u02B9"
_RU_WORD = re.compile(
    rf"[А-Яа-яЁё{_APOSTrophe}]+(?:-[А-Яа-яЁё{_APOSTrophe}]+)*"
)
_UK_WORD = re.compile(
    rf"[А-Яа-яІіЇїЄєҐґ{_APOSTrophe}]+(?:-[А-Яа-яІіЇїЄєҐґ{_APOSTrophe}]+)*"
)

_OC_CASES = frozenset(
    {"nomn", "gent", "datv", "accs", "ablt", "loct", "voct"}
)
_OC_GENDER = frozenset({"masc", "femn", "neut"})
_OC_NUMBER = frozenset({"sing", "plur"})

# 规则数据来自 slavic_grammar_rules.py（Sussex / ukrainianlanguage.org.uk 等）
_RU_GENTIVE_HEAD = _sgr.RU_GENTIVE_HEAD
_RU_GENTIVE_PLURAL_HEAD = _sgr.RU_GENTIVE_PLURAL_HEAD
_RU_MOTION_OR_PLACE_VERBS = _sgr.RU_MOTION_OR_PLACE_VERBS
_UK_MOTION_OR_PLACE_VERBS = _sgr.UK_MOTION_OR_PLACE_VERBS
_RU_STATIC_LOCATION_VERBS = _sgr.RU_STATIC_LOCATION_VERBS
_UK_STATIC_LOCATION_VERBS = _sgr.UK_STATIC_LOCATION_VERBS
_RU_VERB_DATIVE = _sgr.RU_VERB_DATIVE
_RU_VERB_GENITIVE = _sgr.RU_VERB_GENITIVE
_RU_VERB_INSTRUMENTAL = _sgr.RU_VERB_INSTRUMENTAL
_RU_IMPERSONAL_NOM_THEME = _sgr.RU_IMPERSONAL_NOM_THEME
_UK_VERB_DATIVE = _sgr.UK_VERB_DATIVE
_UK_VERB_GENITIVE = _sgr.UK_VERB_GENITIVE
_UK_VERB_INSTRUMENTAL = _sgr.UK_VERB_INSTRUMENTAL
_UK_IMPERSONAL_NOM_THEME = _sgr.UK_IMPERSONAL_NOM_THEME
_UK_GENTIVE_HEAD = _sgr.UK_GENTIVE_HEAD
_UK_GENTIVE_PLURAL_HEAD = _sgr.UK_GENTIVE_PLURAL_HEAD
_UK_PREP_GOVERNS = _sgr.UK_PREP_GOVERNS

_uk_morph_singleton: Any | bool = False
_uk_install_warn_pending = False


def uk_morph_analyzer_available() -> bool:
    """是否已安装 pymorphy2-dicts-uk 并可加载乌克兰语 MorphAnalyzer。"""
    return _shared_uk_morph_analyzer() is not None


def uk_morph_install_command() -> str:
    """供用户复制执行的 pip 命令（使用当前解释器）。"""
    import sys

    return f'"{sys.executable}" -m pip install pymorphy2-dicts-uk'


def uk_morph_install_message() -> str:
    """乌克兰语变格词典缺失时的说明（中文）。"""
    cmd = uk_morph_install_command()
    return (
        "乌克兰语术语自动变格需要额外安装词典包 pymorphy2-dicts-uk。\n\n"
        "未安装时，术语库中的乌语词条将以原形插入，格变化可能不正确。\n\n"
        "请在程序目录打开终端（与 run_gui.bat 同级），运行：\n\n"
        f"{cmd}\n\n"
        "安装完成后请完全退出并重新启动翻译程序。"
    )


def request_uk_morph_install_notice() -> None:
    """后台线程可调用：标记主界面稍后弹出安装提示（每会话一次）。"""
    global _uk_install_warn_pending
    if uk_morph_analyzer_available():
        return
    _uk_install_warn_pending = True


def consume_uk_morph_install_notice() -> str | None:
    """主线程取回并清除待显示的安装提示；无则返回 None。"""
    global _uk_install_warn_pending
    if not _uk_install_warn_pending or uk_morph_analyzer_available():
        _uk_install_warn_pending = False
        return None
    _uk_install_warn_pending = False
    return uk_morph_install_message()


def _plain_surface(surface: str) -> str:
    return re.sub(r"[\u0301\u0300\u030f]", "", (surface or "").strip()).lower()


def _ru_tokens(text: str, *, max_n: int = 8) -> list[str]:
    return [_plain_surface(w) for w in _RU_WORD.findall(text or "")][-max_n:]


def _uk_tokens(text: str, *, max_n: int = 8) -> list[str]:
    return [_plain_surface(w) for w in _UK_WORD.findall(text or "")][-max_n:]


def _shared_uk_morph_analyzer() -> Any | None:
    global _uk_morph_singleton
    if _uk_morph_singleton is not False:
        return _uk_morph_singleton
    try:
        from pymorphy2 import MorphAnalyzer

        _uk_morph_singleton = MorphAnalyzer(lang="uk")
        _uk_morph_singleton.parse("тест")
    except Exception:
        _uk_morph_singleton = None
    return _uk_morph_singleton


_CASE_ZH: dict[str, str] = {
    "nomn": "主格",
    "gent": "属格",
    "datv": "与格",
    "accs": "宾格",
    "ablt": "工具格",
    "loct": "前置格",
    "voct": "呼格",
}


def _word_re(lang: str) -> re.Pattern[str]:
    return _UK_WORD if (lang or "").strip().lower() == "uk" else _RU_WORD


def _morph_for_lang(lang: str):
    code = (lang or "").strip().lower()
    if code == "uk":
        return _shared_uk_morph_analyzer()
    return _morph_ru()


def _cap_like(surface: str, lemma: str) -> str:
    if not lemma:
        return lemma
    if surface and surface[0].isupper() and lemma[0].islower():
        return lemma[0].upper() + lemma[1:]
    return lemma


def _iter_phrase_tokens(text: str, lang: str):
    """按序产出 ('gap', 非词片段) / ('word', 西里尔词)。"""
    last = 0
    for m in _word_re(lang).finditer(text or ""):
        if m.start() > last:
            yield ("gap", text[last : m.start()])
        yield ("word", m.group(0))
        last = m.end()
    if last < len(text or ""):
        yield ("gap", text[last:])


def analyze_slavic_word(
    surface: str,
    morph,
    *,
    pos_hint: str | None = None,
) -> dict[str, Any]:
    """单词：识别词典原形与 OpenCorpora grammemes（含格）。"""
    surf = (surface or "").strip()
    empty: dict[str, Any] = {
        "surface": surf,
        "lemma": surf,
        "grammemes": [],
        "pos": "",
        "case": "",
        "case_zh": "",
    }
    if not surf or morph is None:
        return empty
    gm = _gm()
    parses = morph.parse(surf)
    if not parses:
        return empty
    p = (
        gm.pick_morph_parse(parses, surf)
        if hasattr(gm, "pick_morph_parse")
        else parses[0]
    )
    grams = sorted(_tag_grammemes(p.tag))
    lemma = _cap_like(surf, (p.normal_form or surf).strip())
    pos = gm.safe_parse_pos(p) if hasattr(gm, "safe_parse_pos") else ""
    case = ""
    for g in grams:
        if g in _OC_CASES:
            case = g
            break
    return {
        "surface": surf,
        "lemma": lemma,
        "grammemes": grams,
        "pos": pos or (pos_hint or ""),
        "case": case,
        "case_zh": _CASE_ZH.get(case, case),
    }


def analyze_slavic_phrase(text: str, lang: str) -> dict[str, Any]:
    """
    短语内逐词分析：无论用户输入的是否为原形，均识别各词格并规范为 lemma 序列。
    """
    raw = (text or "").strip()
    code = (lang or "").strip().lower()
    out: dict[str, Any] = {
        "surface": raw,
        "lemma": raw,
        "words": [],
    }
    if not raw:
        return out
    morph = _morph_for_lang(code)
    if morph is None:
        return out
    words: list[dict[str, Any]] = []
    lemma_parts: list[str] = []
    for kind, chunk in _iter_phrase_tokens(raw, code):
        if kind == "gap":
            lemma_parts.append(chunk)
            continue
        w = analyze_slavic_word(chunk, morph)
        words.append(w)
        lemma_parts.append(w["lemma"])
    out["words"] = words
    out["lemma"] = "".join(lemma_parts)
    _harmonize_phrase_word_cases(words)
    return out


def _harmonize_phrase_word_cases(words: list[dict[str, Any]]) -> None:
    """短语内形容词/名词格一致：以核心名词的格为准。"""
    if not words:
        return
    head_case = ""
    for w in reversed(words):
        if w.get("pos") == "NOUN" and w.get("case"):
            head_case = str(w["case"])
            break
    if not head_case:
        for w in reversed(words):
            if w.get("case"):
                head_case = str(w["case"])
                break
    if not head_case:
        return
    for w in words:
        if w.get("pos") not in ("ADJF", "ADJS", "PRTF", "PRTS"):
            continue
        if w.get("case") == head_case:
            continue
        w["case"] = head_case
        w["case_zh"] = _CASE_ZH.get(head_case, head_case)
        grams = [g for g in w.get("grammemes") or [] if g not in _OC_CASES]
        grams.append(head_case)
        w["grammemes"] = sorted(set(grams))


def normalize_for_glossary_storage(raw: str, lang: str) -> Any:
    """
    保存术语时：识别各词格，写入 lemma + 逐词分析（俄/乌）。
    已是主格且单词时仍存为字符串以兼容旧格式。
    """
    text = (raw or "").strip()
    if not text:
        return ""
    code = (lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return text
    if text.startswith("{") and text.endswith("}"):
        try:
            import json

            obj = json.loads(text)
            if isinstance(obj, dict) and obj.get("lemma"):
                return obj
        except json.JSONDecodeError:
            pass
    analysis = analyze_slavic_phrase(text, code)
    words = analysis.get("words") or []
    if not words:
        return text
    lemma = str(analysis.get("lemma") or text).strip()
    if len(words) == 1:
        w = words[0]
        grams = set(w.get("grammemes") or [])
        if (w.get("surface") or "").lower() == (w.get("lemma") or "").lower():
            if not (grams & _OC_CASES) or "nomn" in grams:
                return lemma
    return {
        "lemma": lemma,
        "words": [
            {
                "surface": w.get("surface", ""),
                "lemma": w.get("lemma", ""),
                "grammemes": w.get("grammemes") or [],
                "case": w.get("case", ""),
                "case_zh": w.get("case_zh", ""),
            }
            for w in words
        ],
    }


def phrase_words_from_value(val: Any, lang: str) -> list[dict[str, Any]]:
    """从 JSON 字段或字符串读取逐词分析。"""
    if isinstance(val, dict):
        words = val.get("words")
        if isinstance(words, list) and words:
            return [w for w in words if isinstance(w, dict)]
        lemma = str(val.get("lemma") or "").strip()
        if lemma:
            return analyze_slavic_phrase(lemma, lang).get("words") or []
    if isinstance(val, str) and val.strip():
        return analyze_slavic_phrase(val.strip(), lang).get("words") or []
    return []


def term_lemma_from_entry(entry: Any, to_code: str) -> str:
    return (extract_term_meta(entry, to_code).get("lemma") or "").strip()


def extract_term_meta(entry: Any, to_code: str) -> dict[str, Any]:
    """从术语条目提取原形、逐词分析、可选固定 grammemes。"""
    code = (to_code or "").strip().lower()
    meta: dict[str, Any] = {
        "lemma": "",
        "fixed_grammemes": None,
        "pos": None,
        "words": [],
        "surface": "",
    }
    if entry is None:
        return meta
    if isinstance(entry, str):
        meta["surface"] = entry.strip()
        if code in ("ru", "uk") and entry.strip():
            analysis = analyze_slavic_phrase(entry.strip(), code)
            meta["lemma"] = str(analysis.get("lemma") or entry.strip())
            meta["words"] = analysis.get("words") or []
        else:
            meta["lemma"] = entry.strip()
        return meta
    if not isinstance(entry, dict):
        meta["lemma"] = str(entry).strip()
        return meta

    val = None
    for k, v in entry.items():
        if isinstance(k, str) and k.strip().lower() == code:
            val = v
            break

    if isinstance(val, str):
        meta["surface"] = val.strip()
        if code in ("ru", "uk"):
            analysis = analyze_slavic_phrase(val.strip(), code)
            meta["lemma"] = str(analysis.get("lemma") or val.strip())
            meta["words"] = analysis.get("words") or []
        else:
            meta["lemma"] = val.strip()
    elif isinstance(val, dict):
        meta["surface"] = str(val.get("surface") or val.get("lemma") or "").strip()
        meta["lemma"] = str(val.get("lemma") or meta["surface"]).strip()
        meta["words"] = phrase_words_from_value(val, code)
        grams = val.get("grammemes") or val.get("gram")
        if isinstance(grams, str):
            grams = [g.strip() for g in grams.replace(",", " ").split() if g.strip()]
        if isinstance(grams, list) and grams:
            meta["fixed_grammemes"] = [str(g) for g in grams if g]
    elif code in ("ru", "uk") and entry.get("lemma"):
        val_d = entry
        meta["lemma"] = str(val_d.get("lemma") or "").strip()
        meta["words"] = phrase_words_from_value(val_d, code)
        grams = val_d.get("grammemes") or val_d.get("gram")
        if isinstance(grams, str):
            grams = [g.strip() for g in grams.replace(",", " ").split() if g.strip()]
        if isinstance(grams, list) and grams:
            meta["fixed_grammemes"] = [str(g) for g in grams if g]

    pos = entry.get("pos")
    if isinstance(pos, str) and pos.strip():
        meta["pos"] = pos.strip().lower()
    if not meta["lemma"] and meta["surface"]:
        meta["lemma"] = meta["surface"]
    return meta


def _tag_grammemes(tag) -> set[str]:
    out: set[str] = set()
    if tag is None:
        return out
    for attr in ("case", "number", "gender", "person", "tense", "aspect", "mood"):
        try:
            v = getattr(tag, attr, None)
        except (ValueError, AttributeError, TypeError):
            v = None
        if v is not None:
            out.add(str(v))
    return out


def _pick_parse_for_lemma(morph, lemma: str, pos_hint: str | None = None):
    if morph is None:
        return None
    gm = _gm()
    parses = morph.parse(lemma)
    if not parses:
        return None
    if hasattr(gm, "pick_morph_parse"):
        return gm.pick_morph_parse(parses, lemma)
    if pos_hint == "verb":
        verbs = [
            p for p in parses if gm.safe_parse_pos(p) == "VERB"
        ]
        if verbs:
            return max(verbs, key=lambda p: p.score)
    if pos_hint == "noun":
        nouns = [
            p for p in parses if gm.safe_parse_pos(p) == "NOUN"
        ]
        if nouns:
            return max(nouns, key=lambda p: p.score)
    return parses[0]


def _is_motion_or_placement_verb(tok: str, morph) -> bool:
    if tok in _RU_MOTION_OR_PLACE_VERBS or tok in _UK_MOTION_OR_PLACE_VERBS:
        return True
    if morph is None:
        return False
    ps = morph.parse(tok)
    if not ps:
        return False
    try:
        nf = (ps[0].normal_form or "").lower()
    except (AttributeError, IndexError):
        return False
    return nf in _RU_MOTION_OR_PLACE_VERBS or nf in _UK_MOTION_OR_PLACE_VERBS


def _static_location_verbs(lang: str) -> frozenset[str]:
    if (lang or "").strip().lower() == "uk":
        return _UK_STATIC_LOCATION_VERBS
    return _RU_STATIC_LOCATION_VERBS


def _is_static_location_verb(tok: str, morph, lang: str) -> bool:
    static = _static_location_verbs(lang)
    if tok in static:
        return True
    if morph is None:
        return False
    ps = morph.parse(tok)
    if not ps:
        return False
    try:
        nf = (ps[0].normal_form or "").lower()
    except (AttributeError, IndexError):
        return False
    return nf in static


def _norm_prep_case(case: str, lang: str) -> str:
    """乌克兰语规则表用 inst，OpenCorpora 用 ablt。"""
    if (lang or "").strip().lower() == "uk" and case == "inst":
        return "ablt"
    return case


def _verb_lemma(parse) -> str:
    try:
        return (parse.normal_form or "").lower()
    except AttributeError:
        return ""


def _verb_object_case(parse, lang: str) -> str | None:
    """动词支配的后续名词/补语格；None 表示不强制变格（如 нравиться）。"""
    nf = _verb_lemma(parse)
    if not nf:
        return "accs"
    code = (lang or "").strip().lower()
    if code == "uk":
        if nf in _UK_IMPERSONAL_NOM_THEME:
            return None
        if nf in _UK_VERB_DATIVE:
            return "datv"
        if nf in _UK_VERB_GENITIVE:
            return "gent"
        if nf in _UK_VERB_INSTRUMENTAL:
            return "ablt"
        if nf in _sgr.UK_VERB_REFLEXIVE_INSTR:
            return "ablt"
    else:
        if nf in _RU_IMPERSONAL_NOM_THEME:
            return None
        if nf in _RU_VERB_DATIVE:
            return "datv"
        if nf in _RU_VERB_GENITIVE:
            return "gent"
        if nf in _RU_VERB_INSTRUMENTAL:
            return "ablt"
        if nf in _sgr.RU_VERB_REFLEXIVE_INSTR:
            return "ablt"
    return "accs"


def _disambig_s_z_case(tokens_before: list[str], morph, lang: str) -> str:
    """с/з/із：from → gent，with → ablt（Sussex §2.1b）。"""
    code = (lang or "").strip().lower()
    verbs = (
        _sgr.UK_VERB_WITH_Z_GENT if code == "uk" else _sgr.RU_VERB_WITH_S_GENT
    )
    for tok in reversed(tokens_before[-4:]):
        if tok in verbs:
            return "gent"
        if morph is None:
            continue
        ps = morph.parse(tok)
        if ps and _verb_lemma(ps[0]) in verbs:
            return "gent"
    return "ablt"


def _disambig_za_case(tokens_before: list[str], morph, lang: str) -> str:
    """за：感谢/报酬→accs；静态在…后→ablt；趋向→accs（Sussex §3.2–3.4）。"""
    code = (lang or "").strip().lower()
    heads = _sgr.UK_ZA_ACCS_HEAD if code == "uk" else _sgr.RU_ZA_ACCS_HEAD
    for tok in reversed(tokens_before[-3:]):
        if tok in heads:
            return "accs"
        if morph is None:
            continue
        ps = morph.parse(tok)
        if ps and _verb_lemma(ps[0]) in heads:
            return "accs"
    for tok in reversed(tokens_before[-4:]):
        if _is_motion_or_placement_verb(tok, morph):
            return "accs"
        if _is_static_location_verb(tok, morph, lang):
            return "ablt"
    return "accs"


def _token_lemma_in_set(tok: str, morph, verb_set: frozenset[str]) -> bool:
    if tok in verb_set:
        return True
    if morph is None:
        return False
    ps = morph.parse(tok)
    if not ps:
        return False
    return _verb_lemma(ps[0]) in verb_set


def _disambig_na_case(tokens_before: list[str], morph, lang: str) -> str:
    """на + ACC after ответить/вказати etc.; else location/motion."""
    code = (lang or "").strip().lower()
    verbs = (
        _sgr.UK_VERB_GOVERNS_NA_ACCS
        if code == "uk"
        else _sgr.RU_VERB_GOVERNS_NA_ACCS
    )
    for tok in reversed(tokens_before[-4:]):
        if _token_lemma_in_set(tok, morph, verbs):
            return "accs"
    return _disambig_locative_accusative("на", tokens_before, morph, lang=code)


def _disambig_v_case(tokens_before: list[str], morph, lang: str) -> str:
    """в + ACC after играть/верить; else location/motion."""
    code = (lang or "").strip().lower()
    verbs = (
        _sgr.UK_VERB_GOVERNS_V_ACCS
        if code == "uk"
        else _sgr.RU_VERB_GOVERNS_V_ACCS
    )
    for tok in reversed(tokens_before[-4:]):
        if _token_lemma_in_set(tok, morph, verbs):
            return "accs"
    return _disambig_locative_accusative("в", tokens_before, morph, lang=code)


def _disambig_o_case(tokens_before: list[str], morph, lang: str) -> str:
    """о + ACC (against) vs loct (about)."""
    code = (lang or "").strip().lower()
    verbs_acc = (
        _sgr.UK_VERB_GOVERNS_O_ACCS
        if code == "uk"
        else _sgr.RU_VERB_GOVERNS_O_ACCS
    )
    verbs_loc = (
        _sgr.UK_VERB_GOVERNS_O_LOCT
        if code == "uk"
        else _sgr.RU_VERB_GOVERNS_O_LOCT
    )
    for tok in reversed(tokens_before[-4:]):
        if _token_lemma_in_set(tok, morph, verbs_acc):
            return "accs"
    for tok in reversed(tokens_before[-4:]):
        if _token_lemma_in_set(tok, morph, verbs_loc):
            return "loct"
    return "loct"


def _negated_verb_in_context(tokens_before: list[str], morph, lang: str) -> bool:
    """не/ні + 动词 → 宾语常作属格（Ukrainian 14.7）。"""
    if not tokens_before or morph is None:
        return False
    code = (lang or "").strip().lower()
    imp = _UK_IMPERSONAL_NOM_THEME if code == "uk" else _RU_IMPERSONAL_NOM_THEME
    for i, tok in enumerate(tokens_before):
        if tok not in _sgr.NEGATION_MARKERS and not tok.startswith("не"):
            continue
        for vtok in tokens_before[i + 1 : i + 6]:
            ps = morph.parse(vtok)
            if not ps:
                continue
            if _gm().safe_parse_pos(ps[0]) != "VERB":
                continue
            if _verb_lemma(ps[0]) in imp:
                return False
            return True
    return False


def _normalize_num_token(tok: str) -> str:
    return (tok or "").replace("'", "").replace("'", "").replace("`", "")


def _token_lookup_keys(tok: str) -> tuple[str, ...]:
    """数词/触发词查表键（大小写、撇号变体）。"""
    raw = (tok or "").strip()
    if not raw:
        return ()
    plain = _plain_surface(raw)
    norm = _normalize_num_token(plain)
    out: list[str] = []
    for k in (raw, plain, norm):
        if k and k not in out:
            out.append(k)
    return tuple(out)


def _token_in_frozenset(tok: str, pool: frozenset[str]) -> bool:
    return any(k in pool for k in _token_lookup_keys(tok))


def _is_animate_parse(parse) -> bool:
    try:
        if parse is not None and parse.tag is not None:
            if "anim" in parse.tag:
                return True
            if "inan" in parse.tag:
                return False
    except (ValueError, AttributeError, TypeError):
        pass
    return False


def _animate_accs_as_gent_enabled(lang: str) -> bool:
    code = (lang or "").strip().lower()
    if code == "uk":
        return _sgr.UK_ANIMATE_ACCS_AS_GENT
    if code == "ru":
        return _sgr.RU_ANIMATE_ACCS_AS_GENT
    return False


def _transitive_accs_verb_in_context(
    tokens_before: list[str], morph, lang: str
) -> bool:
    """上文近期是否有及物动词（宾格支配）。"""
    if morph is None or not tokens_before:
        return False
    for tok in reversed(tokens_before[-4:]):
        ps = morph.parse(tok)
        if not ps:
            continue
        if _gm().safe_parse_pos(ps[0]) != "VERB":
            continue
        if _verb_object_case(ps[0], lang) == "accs":
            return True
    return False


def _impersonal_theme_verbs(lang: str) -> frozenset[str]:
    code = (lang or "").strip().lower()
    if code == "uk":
        return _UK_IMPERSONAL_NOM_THEME
    return _RU_IMPERSONAL_NOM_THEME


def _personal_pronoun_lemmas(lang: str) -> frozenset[str]:
    code = (lang or "").strip().lower()
    if code == "uk":
        return _sgr.UK_PERSONAL_PRONOUN_LEMMA
    return _sgr.RU_PERSONAL_PRONOUN_LEMMA


def _reflexive_pronoun_surfaces(lang: str) -> frozenset[str]:
    code = (lang or "").strip().lower()
    if code == "uk":
        return _sgr.UK_REFLEXIVE_PRONOUN
    return _sgr.RU_REFLEXIVE_PRONOUN


def _token_is_impersonal_verb(tok: str, morph, lang: str) -> bool:
    if morph is None or not tok:
        return False
    ps = morph.parse(tok)
    if not ps:
        return False
    imp = _impersonal_theme_verbs(lang)
    for p in ps:
        if _gm().safe_parse_pos(p) == "VERB" and _verb_lemma(p) in imp:
            return True
    return False


def _is_personal_pronoun_parse(parse, lang: str) -> bool:
    if parse is None:
        return False
    if _gm().safe_parse_pos(parse) != "NPRO":
        return False
    try:
        nf = (parse.normal_form or "").lower()
    except AttributeError:
        return False
    return nf in _personal_pronoun_lemmas(lang)


def _infer_case_from_context_after(
    tokens_after: list[str],
    morph,
    lang: str,
) -> str | None:
    if not tokens_after or morph is None:
        return None
    for k, tok in enumerate(tokens_after[:4]):
        if _token_is_impersonal_verb(tok, morph, lang):
            if k == 0:
                return "datv"
            break
    return None


def _infer_impersonal_theme_nomn(
    tokens_before: list[str],
    tokens_after: list[str],
    morph,
    lang: str,
) -> str | None:
    if morph is None:
        return None
    for tok in reversed(tokens_before[-3:]):
        if _token_is_impersonal_verb(tok, morph, lang):
            return "nomn"
    for k, tok in enumerate(tokens_after[:4]):
        if not _token_is_impersonal_verb(tok, morph, lang):
            continue
        if k == 0:
            return "nomn"
        prev = tokens_after[k - 1]
        ps = morph.parse(prev)
        if ps and _is_personal_pronoun_parse(ps[0], lang):
            return "nomn"
        break
    return None


def _apply_context_after_infer(
    chosen_case: str | None,
    tokens_before: list[str],
    tokens_after: list[str],
    morph,
    lang: str,
    *,
    lemma: str = "",
) -> str | None:
    if chosen_case is not None:
        return chosen_case
    aft = _infer_case_from_context_after(tokens_after, morph, lang)
    if aft == "datv" and morph is not None and (lemma or "").strip():
        ps = morph.parse(lemma.strip())
        if ps and _is_personal_pronoun_parse(ps[0], lang):
            return "datv"
    return _infer_impersonal_theme_nomn(tokens_before, tokens_after, morph, lang)


def _fix_impersonal_constructions(
    surfaces: list[str],
    lowers: list[str],
    morph,
    lang: str,
) -> None:
    if morph is None:
        return
    n = len(surfaces)
    for i in range(n):
        if not _token_is_impersonal_verb(lowers[i], morph, lang):
            continue
        if i > 0:
            p = _parse_surface(morph, surfaces[i - 1])
            if p is not None and _is_personal_pronoun_parse(p, lang):
                grams = _grammemes_for_target_case(p, "datv")
                fixed = _try_fix_word_form(morph, surfaces[i - 1], grams)
                if fixed.lower() != surfaces[i - 1].lower():
                    surfaces[i - 1] = fixed
        if i + 1 < n:
            p = _parse_surface(morph, surfaces[i + 1])
            if p is not None and _is_personal_pronoun_parse(p, lang):
                grams = _grammemes_for_target_case(p, "datv")
                fixed = _try_fix_word_form(morph, surfaces[i + 1], grams)
                if fixed.lower() != surfaces[i + 1].lower():
                    surfaces[i + 1] = fixed
        j = i + 1
        while j < n and j <= i + 3:
            if lowers[j] in _sgr.COORD_CONJ:
                j += 1
                continue
            p = _parse_surface(morph, surfaces[j])
            if p is None:
                break
            pos = _gm().safe_parse_pos(p)
            if pos == "NPRO" and _is_personal_pronoun_parse(p, lang):
                j += 1
                continue
            if pos in ("NOUN", "ADJF", "PRTF"):
                cur = _parse_case_tag(p)
                if cur not in ("", "nomn"):
                    grams = _grammemes_for_target_case(p, "nomn")
                    fixed = _try_fix_word_form(morph, surfaces[j], grams)
                    if fixed.lower() != surfaces[j].lower():
                        surfaces[j] = fixed
                break
            break


def _fix_reflexive_pronoun_case(
    surfaces: list[str],
    lowers: list[str],
    morph,
    lang: str,
) -> None:
    if morph is None:
        return
    refl = _reflexive_pronoun_surfaces(lang)
    reflexive_verbs = (
        _sgr.UK_VERB_REFLEXIVE_INSTR
        if (lang or "").strip().lower() == "uk"
        else _sgr.RU_VERB_REFLEXIVE_INSTR
    )
    for i, low in enumerate(lowers):
        if low not in refl:
            continue
        for tok in reversed(lowers[max(0, i - 4) : i]):
            ps = morph.parse(tok)
            if not ps:
                continue
            if _gm().safe_parse_pos(ps[0]) != "VERB":
                continue
            if _verb_lemma(ps[0]) in reflexive_verbs:
                p = _parse_surface(morph, surfaces[i])
                if p is None:
                    break
                grams = _grammemes_for_target_case(p, "ablt")
                fixed = _try_fix_word_form(morph, surfaces[i], grams)
                if fixed.lower() != surfaces[i].lower():
                    surfaces[i] = fixed
                break


def _prep_immediately_before_noun(lowers: list[str], j: int, lang: str) -> bool:
    """名词紧挨前置词时，格由前置词决定，动词不再覆盖。"""
    if j <= 0:
        return False
    return lowers[j - 1] in _prep_map(lang)


def _noun_likely_dative_object(parse, lang: str) -> bool:
    """与格宾语：人称代词或有生命指人名词（писать кому vs писать письмо）。"""
    if parse is None:
        return False
    pos = _gm().safe_parse_pos(parse)
    if pos == "NPRO":
        return _is_personal_pronoun_parse(parse, lang)
    if pos == "NOUN":
        return _is_animate_parse(parse)
    return False


def _resolve_verb_object_case_for_noun(
    verb_parse,
    noun_parse,
    tokens_before: list[str],
    morph,
    lang: str,
    *,
    lowers: list[str] | None = None,
    noun_index: int | None = None,
) -> str | None:
    """
    动词支配格：前置词短语优先；与格动词+无生命宾语→宾格；
    否定句宾格→属格；有生命宾格→属格词形。
    """
    if (
        lowers is not None
        and noun_index is not None
        and _prep_immediately_before_noun(lowers, noun_index, lang)
    ):
        return None
    verb_case = _verb_object_case(verb_parse, lang)
    if not verb_case:
        return None
    if verb_case == "datv" and not _noun_likely_dative_object(noun_parse, lang):
        verb_case = "accs"
    if verb_case == "accs" and _negated_verb_in_context(
        tokens_before, morph, lang
    ):
        verb_case = "gent"
    return _effective_object_case(
        verb_case, noun_parse, tokens_before, morph, lang
    )


def _fix_verb_governed_phrase(
    surfaces: list[str],
    lowers: list[str],
    morph,
    lang: str,
) -> None:
    if morph is None:
        return
    n = len(surfaces)
    for j in range(n):
        pn = _parse_surface(morph, surfaces[j])
        if pn is None or _gm().safe_parse_pos(pn) != "NOUN":
            continue
        verb_case: str | None = None
        for tok in reversed(lowers[max(0, j - 5) : j]):
            ps = morph.parse(tok)
            if not ps:
                continue
            if _gm().safe_parse_pos(ps[0]) != "VERB":
                continue
            verb_case = _resolve_verb_object_case_for_noun(
                ps[0],
                pn,
                lowers[:j],
                morph,
                lang,
                lowers=lowers,
                noun_index=j,
            )
            break
        if not verb_case or verb_case == "nomn":
            continue
        target = _agreement_grammemes_from_head(pn)
        if not (target & _OC_CASES):
            target = set(target) | {verb_case}
        else:
            target = (target - _OC_CASES) | {verb_case}
        for k in range(max(0, j - 2), j + 1):
            pa = _parse_surface(morph, surfaces[k])
            if pa is None:
                continue
            if _gm().safe_parse_pos(pa) not in ("ADJF", "ADJS", "PRTF", "PRTS"):
                continue
            fixed = _try_fix_word_form(morph, surfaces[k], target)
            if fixed.lower() != surfaces[k].lower():
                surfaces[k] = fixed
        cur = _parse_case_tag(pn)
        if cur in ("", "nomn") or cur != verb_case:
            fixed = _try_fix_word_form(morph, surfaces[j], target)
            if fixed.lower() != surfaces[j].lower():
                surfaces[j] = fixed


def _effective_object_case(
    case: str,
    parse,
    tokens_before: list[str],
    morph,
    lang: str,
) -> str:
    """有生命宾语：俄/乌及物宾格采用属格词形（含复数 студентов）。"""
    if (
        case == "accs"
        and _animate_accs_as_gent_enabled(lang)
        and _is_animate_parse(parse)
        and _transitive_accs_verb_in_context(tokens_before, morph, lang)
    ):
        return "gent"
    return case


def _numeral_one_lemma(parse) -> bool:
    try:
        nf = (parse.normal_form or "").lower()
    except AttributeError:
        return False
    return nf in ("один", "одна", "одне", "одно")


def _is_numeral_one_token(parse, surface: str) -> bool:
    low = _plain_surface(surface)
    norm = _normalize_num_token(low)
    if low in _sgr.NUMERAL_ONE_HEADS or norm in _sgr.NUMERAL_ONE_HEADS:
        return True
    if parse is None:
        return False
    return _numeral_one_lemma(parse)


def _infer_numeral_one_agreement(
    tokens_before: list[str],
    morph,
    lang: str,
) -> tuple[str | None, set[str]]:
    """один/одна/одне … → 名词与数词同格、同数、性随搭配。"""
    if not tokens_before or morph is None:
        return None, set()
    head = tokens_before[-1]
    norm = _normalize_num_token(head)
    if head not in _sgr.NUMERAL_ONE_HEADS and norm not in _sgr.NUMERAL_ONE_HEADS:
        ps = morph.parse(head)
        if not ps or not any(
            _gm().safe_parse_pos(p) == "NUMR" and _numeral_one_lemma(p) for p in ps
        ):
            return None, set()
    else:
        ps = morph.parse(head)
    grams: set[str] = {"sing"}
    chosen: str | None = None
    for p in ps or []:
        if _gm().safe_parse_pos(p) != "NUMR" and head not in _sgr.NUMERAL_ONE_HEADS:
            if not _numeral_one_lemma(p):
                continue
        tg = _tag_grammemes(p.tag)
        case_bits = tg & _OC_CASES
        if case_bits:
            chosen = next(iter(case_bits))
        if chosen:
            break
    if chosen is None:
        chosen = "nomn"
    return chosen, grams


def _infer_misc_case_rules(
    chosen_case: str | None,
    grams: set[str],
    tokens_before: list[str],
    morph,
    lang: str,
) -> tuple[str | None, set[str]]:
    """数词、否定、部分属格、比较结构等无前置词时的格推断。"""
    if chosen_case is not None:
        return chosen_case, grams
    if tokens_before:
        head = tokens_before[-1]
        if _token_in_frozenset(head, _sgr.COMPARISON_THAN_MARKERS):
            return "nomn", set(grams) | {"sing"}
        if _token_in_frozenset(head, _sgr.COMPARISON_GENITIVE_HEADS):
            g = set(grams)
            g.add("sing")
            return "gent", g
        if _token_in_frozenset(head, _sgr.PARTITIVE_GENTIVE_HEADS):
            g = set(grams)
            g.add("sing")
            return "gent", g
        one_case, one_grams = _infer_numeral_one_agreement(
            tokens_before, morph, lang
        )
        if one_case is not None:
            return one_case, set(grams) | one_grams
        if _token_in_frozenset(head, _sgr.NUMERAL_GENTIVE_SINGULAR_HEADS):
            return "gent", set(grams) | {"sing"}
        if _token_in_frozenset(head, _sgr.NUMERAL_GENTIVE_PLURAL_HEADS):
            return "gent", set(grams) | {"plur"}
        if _token_in_frozenset(head, _sgr.NUMERAL_GENTIVE_HEADS):
            return "gent", set(grams)
    if _negated_verb_in_context(tokens_before, morph, lang):
        return "gent", grams
    return chosen_case, grams


def _disambig_position_prep(
    prep: str,
    tokens_before: list[str],
    morph,
    lang: str,
) -> str:
    """под/над/перед/між：静态→ablt，趋向→accs（Sussex; Ukrainian 16.5）。"""
    for tok in reversed(tokens_before[-4:]):
        if _is_motion_or_placement_verb(tok, morph):
            return "accs"
        if _is_static_location_verb(tok, morph, lang):
            return "ablt"
    if prep in ("под", "подо", "під", "попід"):
        return "accs" if _is_motion_or_placement_verb(
            tokens_before[-1] if tokens_before else "", morph
        ) else "ablt"
    return "ablt"


def _resolve_multi_case_prep(
    prep: str,
    tokens_before: list[str],
    morph,
    lang: str,
    cases: tuple[str, ...],
) -> str:
    code = (lang or "").strip().lower()
    if prep in ("в", "во"):
        return _disambig_v_case(tokens_before, morph, code)
    if prep == "на":
        return _disambig_na_case(tokens_before, morph, code)
    if prep == "у":
        if not tokens_before:
            return "gent"
        return _disambig_locative_accusative(prep, tokens_before, morph, lang=code)
    if prep in ("о", "об", "обо"):
        return _disambig_o_case(tokens_before, morph, code)
    if prep in ("с", "со", "з", "із", "зі"):
        return _disambig_s_z_case(tokens_before, morph, code)
    if prep == "за":
        return _disambig_za_case(tokens_before, morph, code)
    if prep in _sgr.RU_POSITION_PREPS or prep in _sgr.UK_POSITION_PREPS:
        return _disambig_position_prep(prep, tokens_before, morph, code)
    if prep == "по":
        return _norm_prep_case(cases[0], code)
    return _norm_prep_case(cases[0], code)


def _skip_u_prep_for_existential(tokens_before: list[str], lang: str) -> bool:
    """у/в … + есть/є 存在句：宾语用主格，不因 у 取属格。"""
    exist = "є" if (lang or "").strip().lower() == "uk" else "есть"
    if exist not in tokens_before:
        return False
    prep = "у" if (lang or "").strip().lower() == "uk" else "у"
    if prep not in tokens_before:
        return False
    try:
        return tokens_before.index(exist) > tokens_before.index(prep)
    except ValueError:
        return False


def _disambig_locative_accusative(
    prep: str,
    tokens_before: list[str],
    morph,
    *,
    lang: str = "ru",
) -> str:
    """в/на/у 等：趋向（куда）→ accs，位置/状态 → loct。"""
    if morph is None or not tokens_before:
        return "loct"
    content = [t for t in tokens_before if t != prep]
    for tok in reversed(content[-4:]):
        if _is_motion_or_placement_verb(tok, morph):
            return "accs"
        if _is_static_location_verb(tok, morph, lang):
            return "loct"
        ps = morph.parse(tok)
        if not ps:
            continue
        p = ps[0]
        pos = _gm().safe_parse_pos(p)
        if pos == "VERB":
            try:
                if p.tag and "perf" in p.tag and _is_motion_or_placement_verb(
                    tok, morph
                ):
                    return "accs"
            except (ValueError, AttributeError, TypeError):
                pass
    return "loct"


def _prep_governs_for_lang(lang: str) -> dict[str, tuple[str, ...]]:
    code = (lang or "").strip().lower()
    if code == "uk":
        return _UK_PREP_GOVERNS
    return _ru_prep_governs()


def _existential_u_pattern(tokens: list[str], lang: str) -> bool:
    """句中含 у … + есть/є 存在结构。"""
    exist = "є" if (lang or "").strip().lower() == "uk" else "есть"
    return "у" in tokens and exist in tokens and _skip_u_prep_for_existential(tokens, lang)


def _skip_u_prep_for_possession(tokens_before: list[str], lang: str) -> bool:
    """у/в + 属格代词 + 所有物：不因 у 变方位/属格（Sussex §2.1a）。"""
    if not tokens_before:
        return False
    code = (lang or "").strip().lower()
    poss = (
        _sgr.UK_U_POSSESSIVE_PRONOUN
        if code == "uk"
        else _sgr.RU_U_POSSESSIVE_PRONOUN
    )
    preps = ("у", "в") if code == "uk" else ("у",)
    for prep in preps:
        if prep not in tokens_before:
            continue
        try:
            idx = tokens_before.index(prep)
        except ValueError:
            continue
        if idx + 1 < len(tokens_before) and tokens_before[idx + 1] in poss:
            return len(tokens_before) > idx + 1
    return False


def _infer_prep_case(
    tok: str,
    tokens_before: list[str],
    morph,
    lang: str,
) -> str | None:
    pmap = _prep_governs_for_lang(lang)
    cases = pmap.get(tok)
    if not cases:
        return None
    if tok in ("у", "в") and (
        _skip_u_prep_for_existential(tokens_before, lang)
        or _skip_u_prep_for_possession(tokens_before, lang)
    ):
        return None
    if len(cases) == 1:
        return _norm_prep_case(cases[0], lang)
    return _resolve_multi_case_prep(tok, tokens_before, morph, lang, cases)


def _agreement_grammemes_from_head(parse) -> set[str]:
    """从名词/中心词提取形容词/代词应一致的 grammemes。"""
    grams: set[str] = set()
    try:
        tag = parse.tag
        if tag.case is not None:
            grams.add(str(tag.case))
        if tag.number is not None:
            grams.add(str(tag.number))
        if tag.gender is not None:
            grams.add(str(tag.gender))
    except (ValueError, AttributeError, TypeError):
        pass
    if not (grams & _OC_NUMBER):
        grams.add("sing")
    return grams


def _infer_adjacent_prep_case(
    tokens_before: list[str],
    morph,
    lang: str,
) -> str | None:
    """仅紧邻名词的前置词短语（в новой комнате），避免句首 distant prep 覆盖 нет/много。"""
    if not tokens_before:
        return None
    pmap = _prep_map(lang)
    head = tokens_before[-1]
    if head in pmap:
        return _expected_case_after_prep(
            head, tokens_before[:-1], morph, lang
        )
    if len(tokens_before) >= 2:
        prev = tokens_before[-2]
        if prev in pmap and morph is not None:
            ps = morph.parse(head)
            if ps and _gm().safe_parse_pos(ps[0]) in (
                "ADJF",
                "ADJS",
                "PRTF",
                "PRTS",
            ):
                return _expected_case_after_prep(
                    prev, tokens_before[:-2], morph, lang
                )
    mw = _infer_multiword_prep_case(tokens_before, lang)
    if mw:
        return mw
    return None


def _multiword_prep_patterns(lang: str) -> tuple[tuple[tuple[str, ...], str], ...]:
    code = (lang or "").strip().lower()
    if code == "uk":
        return _sgr.UK_MULTI_PREP_PATTERNS
    return _sgr.RU_MULTI_PREP_PATTERNS


def _infer_multiword_prep_case(
    tokens_before: list[str],
    lang: str,
) -> str | None:
    """公文多词介词：в соответствии с → INST；на основе → GEN（Sussex / AlphaDictionary）。"""
    if not tokens_before:
        return None
    for pat, case in reversed(_multiword_prep_patterns(lang)):
        plen = len(pat)
        if len(tokens_before) < plen:
            continue
        tail = tuple(tokens_before[-plen:])
        if tail == pat:
            if case == "inf":
                return None
            return case
    return None


def fix_multiword_prep_surfaces_in_place(
    surfaces: list[str],
    lowers: list[str],
    morph,
    lang: str,
) -> None:
    """书面多词介词短语 + 名词格（в соответствии с / на основе …）。"""
    if morph is None:
        return
    n = len(surfaces)
    for pat, case in _multiword_prep_patterns(lang):
        if case == "inf":
            continue
        plen = len(pat)
        for i in range(n - plen):
            if tuple(lowers[i : i + plen]) != pat:
                continue
            j = i + plen
            while j < n and j <= i + plen + 4:
                if lowers[j] in _sgr.COORD_CONJ:
                    j += 1
                    continue
                pr = morph.parse(lowers[j])
                if not pr:
                    j += 1
                    continue
                head_p = pr[0]
                pos = _gm().safe_parse_pos(head_p)
                if pos not in ("NOUN", "ADJF", "NPRO"):
                    noun_ps = [
                        p for p in pr if _gm().safe_parse_pos(p) == "NOUN"
                    ]
                    if noun_ps:
                        head_p = max(noun_ps, key=lambda x: getattr(x, "score", 0))
                        pos = "NOUN"
                    else:
                        j += 1
                        continue
                cur = _parse_case_tag(head_p)
                if cur in ("", "nomn") or cur != case:
                    grams = _grammemes_for_target_case(head_p, case)
                    fixed = _try_fix_word_form(morph, surfaces[j], grams)
                    if fixed.lower() != surfaces[j].lower():
                        surfaces[j] = fixed
                        lowers[j] = _plain_surface(fixed)
                if pos == "NOUN":
                    break
                j += 1


def _infer_immediate_gentive_head(
    tokens_before: list[str],
    lang: str,
) -> tuple[str | None, set[str]]:
    """紧邻属格触发词（нет/много/немного …）。"""
    grams: set[str] = set()
    if not tokens_before:
        return None, grams
    head = tokens_before[-1]
    code = (lang or "").strip().lower()
    gent_heads = (
        _UK_GENTIVE_HEAD if code == "uk" else _RU_GENTIVE_HEAD
    )
    if _token_in_frozenset(head, gent_heads) or _token_in_frozenset(
        head, _sgr.PARTITIVE_GENTIVE_HEADS
    ):
        plural_heads = (
            _UK_GENTIVE_PLURAL_HEAD if code == "uk" else _RU_GENTIVE_PLURAL_HEAD
        )
        if _token_in_frozenset(head, plural_heads):
            grams.add("plur")
        return "gent", grams
    return None, grams


def infer_ru_grammemes(
    context_before: str,
    context_after: str,
    lemma: str,
    *,
    morph=None,
) -> set[str]:
    """根据占位符前后俄文上下文推断 OpenCorpora grammemes。"""
    if morph is None:
        morph = _morph_ru()
    grams: set[str] = set()
    before = context_before or ""
    after = context_after or ""
    tokens_before = _ru_tokens(before)
    tokens_after = _ru_tokens(after)
    chosen_case: str | None = None

    # 1) 紧邻属格触发词（нет/много — 优先于 distant 前置词）
    chosen_case, gent_grams = _infer_immediate_gentive_head(tokens_before, "ru")
    grams.update(gent_grams)

    # 2) 紧邻前置词短语（в новой комнате）
    if chosen_case is None:
        chosen_case = _infer_adjacent_prep_case(tokens_before, morph, "ru")

    chosen_case, grams = _infer_misc_case_rules(
        chosen_case, grams, tokens_before, morph, "ru"
    )

    # 3) 动词后宾语/补语格（优先于误用主格的形容词）
    if chosen_case is None and morph is not None:
        for tok in reversed(tokens_before[-4:]):
            if tok in _ru_prep_governs() or tok in _RU_GENTIVE_HEAD:
                continue
            if tok in _sgr.EXISTENTIAL_MARKERS:
                continue
            ps = morph.parse(tok)
            if not ps:
                continue
            if _gm().safe_parse_pos(ps[0]) == "VERB":
                np = (
                    _pick_parse_for_lemma(morph, (lemma or "").strip())
                    if (lemma or "").strip()
                    else None
                )
                vc = _resolve_verb_object_case_for_noun(
                    ps[0], np, tokens_before, morph, "ru"
                )
                if vc:
                    chosen_case = vc
                    break

    chosen_case = _apply_context_after_infer(
        chosen_case, tokens_before, tokens_after, morph, "ru", lemma=lemma
    )

    # 4) 形容词/分词：继承数、性；无前置词时继承非主格
    if morph is not None and tokens_before:
        for tok in reversed(tokens_before[-4:]):
            if tok in _ru_prep_governs():
                continue
            ps = morph.parse(tok)
            if not ps:
                continue
            best = ps[0]
            pos = _gm().safe_parse_pos(best)
            if pos not in ("ADJF", "ADJS", "PRTF", "PRTS", "NUMR"):
                continue
            tg = _tag_grammemes(best.tag)
            if pos == "NUMR" and _numeral_one_lemma(best):
                if chosen_case is None:
                    case_bits = tg & _OC_CASES
                    if case_bits:
                        c = next(iter(case_bits))
                        if c != "nomn":
                            chosen_case = c
                num_bits = tg & _OC_NUMBER
                if num_bits:
                    grams.update(num_bits)
                break
            if (
                pos == "ADJF"
                and _numeral_one_lemma(best)
                and tok in _sgr.NUMERAL_ONE_HEADS
            ):
                if chosen_case is None:
                    case_bits = tg & _OC_CASES
                    if case_bits:
                        c = next(iter(case_bits))
                        if c != "nomn":
                            chosen_case = c
                num_bits = tg & _OC_NUMBER
                if num_bits:
                    grams.update(num_bits)
                break
            if chosen_case is None:
                case_bits = tg & _OC_CASES
                if case_bits:
                    c = next(iter(case_bits))
                    if c != "nomn":
                        chosen_case = c
            num_bits = tg & _OC_NUMBER
            if num_bits:
                grams.update(num_bits)
            gen_bits = tg & _OC_GENDER
            if gen_bits:
                grams.update(gen_bits)
            break

    if chosen_case:
        grams.add(chosen_case)

    # 3b) 有生命宾语 → 属格词形（俄/乌，术语还原时有 lemma）
    if chosen_case == "accs" and morph is not None and (lemma or "").strip():
        np = _pick_parse_for_lemma(morph, lemma.strip())
        if np is not None:
            chosen_case = _effective_object_case(
                chosen_case, np, tokens_before, morph, "ru"
            )
            grams.discard("accs")
            grams.add(chosen_case)

    # 5) 复数线索（仅看占位符之前，避免「… GLOSSA … много книг」误判）
    if morph is not None:
        for tok in tokens_before[-3:]:
            ps = morph.parse(tok)
            if not ps:
                continue
            if _gm().safe_parse_pos(ps[0]) not in ("NOUN", "NUMR", "ADJF"):
                continue
            try:
                if ps[0].tag and "plur" in ps[0].tag:
                    grams.add("plur")
                    break
            except (ValueError, AttributeError, TypeError):
                pass

    # 6) 默认单数
    if not (grams & _OC_NUMBER):
        grams.add("sing")

    return grams


def infer_uk_grammemes(
    context_before: str,
    context_after: str,
    lemma: str,
    *,
    morph=None,
) -> set[str]:
    """乌克兰语变格推断（有 pymorphy2-dicts-uk 时精度更高）。"""
    if morph is None:
        morph = _shared_uk_morph_analyzer()
    grams: set[str] = set()
    tokens_before = _uk_tokens(context_before or "")
    tokens_after = _uk_tokens(context_after or "")
    chosen_case: str | None = None

    # 1) 紧邻属格触发词
    chosen_case, gent_grams = _infer_immediate_gentive_head(tokens_before, "uk")
    grams.update(gent_grams)

    # 2) 紧邻前置词短语
    if chosen_case is None:
        chosen_case = _infer_adjacent_prep_case(tokens_before, morph, "uk")

    chosen_case, grams = _infer_misc_case_rules(
        chosen_case, grams, tokens_before, morph, "uk"
    )

    # 3) 动词后宾语/补语
    if chosen_case is None and morph is not None:
        for tok in reversed(tokens_before[-4:]):
            if tok in _UK_PREP_GOVERNS or tok in _UK_GENTIVE_HEAD:
                continue
            if tok in _sgr.EXISTENTIAL_MARKERS:
                continue
            ps = morph.parse(tok)
            if not ps:
                continue
            if _gm().safe_parse_pos(ps[0]) == "VERB":
                np = (
                    _pick_parse_for_lemma(morph, (lemma or "").strip())
                    if (lemma or "").strip()
                    else None
                )
                vc = _resolve_verb_object_case_for_noun(
                    ps[0], np, tokens_before, morph, "uk"
                )
                if vc:
                    chosen_case = vc
                    break

    chosen_case = _apply_context_after_infer(
        chosen_case, tokens_before, tokens_after, morph, "uk", lemma=lemma
    )

    # 4) 形容词/分词（非主格）
    if morph is not None and tokens_before:
        for tok in reversed(tokens_before[-4:]):
            if tok in _UK_PREP_GOVERNS:
                continue
            ps = morph.parse(tok)
            if not ps:
                continue
            best = ps[0]
            pos = _gm().safe_parse_pos(best)
            if pos not in ("ADJF", "ADJS", "PRTF", "PRTS", "NUMR"):
                continue
            tg = _tag_grammemes(best.tag)
            if pos == "NUMR" and _numeral_one_lemma(best):
                if chosen_case is None:
                    case_bits = tg & _OC_CASES
                    if case_bits:
                        c = next(iter(case_bits))
                        if c != "nomn":
                            chosen_case = c
                grams.update(tg & _OC_NUMBER)
                break
            if chosen_case is None:
                case_bits = tg & _OC_CASES
                if case_bits:
                    c = next(iter(case_bits))
                    if c != "nomn":
                        chosen_case = c
            grams.update(tg & (_OC_NUMBER | _OC_GENDER))
            break

    if chosen_case:
        grams.add(chosen_case)

    if (
        chosen_case == "accs"
        and morph is not None
        and (lemma or "").strip()
    ):
        np = _pick_parse_for_lemma(morph, lemma.strip())
        if np is not None:
            chosen_case = _effective_object_case(
                chosen_case, np, tokens_before, morph, "uk"
            )
            grams.discard("accs")
            grams.add(chosen_case)

    if morph is not None:
        for tok in tokens_before[-3:]:
            ps = morph.parse(tok)
            if not ps:
                continue
            if _gm().safe_parse_pos(ps[0]) not in ("NOUN", "NUMR", "ADJF"):
                continue
            try:
                if ps[0].tag and "plur" in ps[0].tag:
                    grams.add("plur")
                    break
            except (ValueError, AttributeError, TypeError):
                pass

    if not (grams & _OC_NUMBER):
        grams.add("sing")
    return grams


def _numeral_one_lemma_for_gender(gender: str) -> str:
    if gender == "femn":
        return "одна"
    if gender == "neut":
        return "одно"
    return "один"


def _inflect_numeral_one_to_match(
    morph,
    surface: str,
    target: set[str],
) -> str | None:
    """один/одна/одне 与后接名词性数格一致。"""
    if morph is None:
        return None
    gender_bits = target & _OC_GENDER
    if not gender_bits:
        return None
    gender = next(iter(gender_bits))
    case_bits = target & _OC_CASES
    case = next(iter(case_bits), "nomn")
    number_bits = target & _OC_NUMBER
    grams = {case, gender} | (number_bits or {"sing"})
    lemma = _numeral_one_lemma_for_gender(gender)
    fixed = _inflect_with_morph(morph, lemma, grams)
    if fixed:
        return _cap_like(surface, fixed)
    return None


def _lexeme_forms_for_case(
    morph,
    surface: str,
    case: str,
    *,
    number: str | None = None,
) -> list[str]:
    """同形异义词素表中符合目标格的所有词形（用于乌语属格 -а/-у 择优）。"""
    if morph is None or not case:
        return []
    seen: set[str] = set()
    out: list[str] = []
    seeds = {surface.strip()}
    p0 = _parse_surface(morph, surface)
    anchor_nf = (p0.normal_form or "").lower() if p0 is not None else ""
    if p0 is not None and p0.normal_form:
        seeds.add(p0.normal_form)
    for seed in seeds:
        if not seed:
            continue
        try:
            parses = morph.parse(seed)
        except (ValueError, AttributeError, TypeError):
            continue
        for pr in parses:
            if _gm().safe_parse_pos(pr) != "NOUN":
                continue
            lex = getattr(pr, "lexeme", None)
            if not lex:
                continue
            for form in lex:
                try:
                    if str(form.tag.case) != case:
                        continue
                    if number and form.tag.number is not None:
                        if str(form.tag.number) != number:
                            continue
                    w = form.word
                    if w and w not in seen:
                        seen.add(w)
                        out.append(w)
                except (ValueError, AttributeError, TypeError):
                    continue
    return out


def _surface_matches_grammemes(
    morph,
    surface: str,
    grammemes: set[str],
) -> bool:
    """词形是否已是目标格/数的有效变位（避免同形异义误改，如姓氏 котов）。"""
    if morph is None or not surface.strip():
        return False
    exp_case = next((g for g in grammemes if g in _OC_CASES), None)
    if not exp_case:
        return False
    num = next((g for g in grammemes if g in _OC_NUMBER), None)
    low = surface.lower()
    alts = _lexeme_forms_for_case(morph, surface, exp_case, number=num)
    if low in {a.lower() for a in alts}:
        return True
    p = _parse_surface(morph, surface)
    if p is not None and _parse_case_tag(p) == exp_case:
        try:
            if num is None or (p.tag.number is not None and str(p.tag.number) == num):
                return True
        except (ValueError, AttributeError, TypeError):
            return True
    return False


def _prefer_gent_form(
    forms: list[str],
    *,
    prefer_standard: bool,
    number: str | None = None,
) -> str | None:
    if not forms:
        return None
    if not prefer_standard and number != "plur":
        return forms[0]
    if number == "plur" or any(w.endswith(("ок", "ек", "ів", "ей")) for w in forms):
        for w in forms:
            lw = w.lower()
            if lw.endswith(("ок", "ек", "ів", "ей")):
                return w
    for w in forms:
        lw = w.lower()
        if lw.endswith(("а", "я", "и", "ів", "ей", "ок", "ек")):
            return w
    for w in forms:
        lw = w.lower()
        if not lw.endswith(("у", "ю")):
            return w
    return forms[0]


def _inflect_with_morph(
    morph,
    lemma: str,
    grammemes: set[str],
    *,
    pos_hint: str | None = None,
    prefer_standard_gent: bool = False,
) -> str | None:
    if morph is None or not (lemma or "").strip():
        return None
    p = _pick_parse_for_lemma(morph, lemma.strip(), pos_hint)
    if p is None:
        return None
    tags = frozenset(g for g in grammemes if g)
    if not tags:
        return None
    case_only = frozenset(g for g in grammemes if g in _OC_CASES)
    target_case = next(iter(case_only), None) if len(case_only) == 1 else None
    number_hint = next((g for g in grammemes if g in _OC_NUMBER), None)

    if target_case == "gent" and number_hint:
        alts = _lexeme_forms_for_case(
            morph, lemma, target_case, number=number_hint
        )
        if alts:
            pref = _prefer_gent_form(
                alts,
                prefer_standard=True,
                number=number_hint,
            )
            if pref:
                return pref
            return alts[0]

    try:
        inf = p.inflect(tags)
        if inf is not None and getattr(inf, "word", None):
            if target_case == "gent" and prefer_standard_gent:
                alts = _lexeme_forms_for_case(
                    morph, lemma, "gent", number=number_hint
                )
                pref = _prefer_gent_form(
                    alts, prefer_standard=True, number=number_hint
                )
                if pref:
                    return pref
            return inf.word
    except (ValueError, AttributeError, TypeError):
        pass

    gender_only = frozenset(g for g in grammemes if g in _OC_GENDER)
    number_only = frozenset(g for g in grammemes if g in _OC_NUMBER)
    if case_only:
        attempts: list[frozenset[str]] = []
        if "plur" in number_only:
            attempts.append(case_only | number_only)
        attempts.extend(
            [
                case_only | gender_only | number_only,
                case_only | gender_only,
                case_only | number_only,
                case_only,
            ]
        )
        seen: set[frozenset[str]] = set()
        for attempt in attempts:
            if not attempt or attempt in seen:
                continue
            seen.add(attempt)
            try:
                inf = p.inflect(attempt)
                if inf is not None and getattr(inf, "word", None):
                    if target_case == "gent" and prefer_standard_gent:
                        num = next((g for g in attempt if g in _OC_NUMBER), None)
                        alts = _lexeme_forms_for_case(
                            morph, lemma, "gent", number=num
                        )
                        pref = _prefer_gent_form(
                            alts, prefer_standard=True, number=num
                        )
                        if pref:
                            return pref
                    return inf.word
            except (ValueError, AttributeError, TypeError):
                continue
    if target_case:
        alts = _lexeme_forms_for_case(
            morph, lemma, target_case, number=number_hint
        )
        if target_case == "gent":
            pref = _prefer_gent_form(
                alts, prefer_standard=prefer_standard_gent, number=number_hint
            )
            if pref:
                return pref
        elif alts:
            return alts[0]
    return None


def _inflect_phrase_lemma(
    phrase_lemma: str,
    word_lemmas: list[str],
    morph,
    grammemes: set[str],
    lang: str,
    *,
    pos_hint: str | None = None,
) -> str:
    """多词术语：各词使用同一套句法 grammemes（格/数一致）分别变格。"""
    it = iter(word_lemmas)
    parts: list[str] = []
    for kind, chunk in _iter_phrase_tokens(phrase_lemma, lang):
        if kind == "gap":
            parts.append(chunk)
            continue
        wl = next(it, chunk)
        got = _inflect_with_morph(morph, wl, grammemes, pos_hint=pos_hint)
        parts.append(got if got else wl)
    return "".join(parts)


def _apply_capitalization(before: str, word: str) -> str:
    if not word:
        return word
    stripped = (before or "").rstrip()
    if not stripped or stripped.endswith((".", "!", "?", "…", ":", ";", "\n")):
        if word[0].islower():
            return word[0].upper() + word[1:]
    return word


def inflect_glossary_term(
    lemma: str,
    lang_code: str,
    context_before: str,
    context_after: str,
    *,
    fixed_grammemes: list[str] | None = None,
    pos_hint: str | None = None,
    words: list[dict[str, Any]] | None = None,
) -> str:
    """
    将术语原形按上下文变格；无形态库或无法变格时返回原形。
    words：术语库逐词分析（各词 lemma）；多词时各词同格变位。
    """
    lem = (lemma or "").strip()
    if not lem:
        return lem
    code = (lang_code or "").strip().lower()

    if code not in ("ru", "uk"):
        return lem

    if fixed_grammemes:
        grams = set(fixed_grammemes)
    elif code == "ru":
        grams = infer_ru_grammemes(context_before, context_after, lem)
    else:
        grams = infer_uk_grammemes(context_before, context_after, lem)

    if code == "uk":
        morph = _shared_uk_morph_analyzer()
        if morph is None:
            request_uk_morph_install_notice()
            return _apply_capitalization(context_before, lem)
    else:
        morph = _morph_ru()

    word_lemmas: list[str] = []
    if words:
        word_lemmas = [
            str(w.get("lemma") or w.get("surface") or "").strip()
            for w in words
            if isinstance(w, dict)
            and str(w.get("lemma") or w.get("surface") or "").strip()
        ]
    cyr_in_lemma = _word_re(code).findall(lem)
    if len(word_lemmas) > 1 or (len(word_lemmas) == 1 and len(cyr_in_lemma) > 1):
        if len(word_lemmas) < len(cyr_in_lemma):
            word_lemmas = cyr_in_lemma
        inflected = _inflect_phrase_lemma(
            lem, word_lemmas, morph, grams, code, pos_hint=pos_hint
        )
    else:
        target = word_lemmas[0] if word_lemmas else lem
        inflected = _inflect_with_morph(morph, target, grams, pos_hint=pos_hint)

    result = inflected if inflected else lem
    return _apply_capitalization(context_before, result)


# --- 整句译文：前置词/一致关系变格修补 ---

def _prep_single_case_set(lang: str) -> frozenset[str]:
    code = (lang or "").strip().lower()
    if code == "uk":
        return _sgr.UK_PREP_SINGLE_CASE
    return _sgr.RU_PREP_SINGLE_CASE



def _prep_map(lang: str) -> dict[str, tuple[str, ...]]:
    code = (lang or "").strip().lower()
    if code == "uk":
        return _UK_PREP_GOVERNS
    return _ru_prep_governs()


def _word_spans(line: str, lang: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group(0)) for m in _word_re(lang).finditer(line or "")]


def _rebuild_line(line: str, spans: list[tuple[int, int, str]], surfaces: list[str]) -> str:
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


def _parse_surface(morph, surface: str):
    if morph is None:
        return None
    ps = morph.parse(surface)
    if not ps:
        return None
    gm = _gm()
    if hasattr(gm, "pick_morph_parse"):
        return gm.pick_morph_parse(ps, surface)
    return ps[0]


def _pick_noun_parse_for_context(
    morph,
    surface: str,
    tokens_before: list[str],
    lang: str,
):
    """多义名词：及物宾格上下文优先有生命 parse（коты → anim plur）。"""
    if morph is None:
        return None
    try:
        parses = morph.parse(surface)
    except (ValueError, AttributeError, TypeError):
        return _parse_surface(morph, surface)
    nouns = [p for p in parses if _gm().safe_parse_pos(p) == "NOUN"]
    if not nouns:
        return _parse_surface(morph, surface)
    if _transitive_accs_verb_in_context(tokens_before, morph, lang):
        anim = [p for p in nouns if _is_animate_parse(p)]
        if anim:
            return max(anim, key=lambda p: getattr(p, "score", 0))
    if hasattr(_gm(), "pick_morph_parse"):
        return _gm().pick_morph_parse(nouns, surface)
    return max(nouns, key=lambda p: getattr(p, "score", 0))


def _number_from_noun_lexeme(morph, surface: str, case: str) -> str | None:
    """同形词形在词素表中的数（котов → plur）。"""
    if morph is None:
        return None
    low = (surface or "").lower()
    for pr in morph.parse(surface):
        if _gm().safe_parse_pos(pr) != "NOUN":
            continue
        lex = getattr(pr, "lexeme", None)
        if not lex:
            continue
        for form in lex:
            if (form.word or "").lower() != low:
                continue
            try:
                if case and str(form.tag.case) != case:
                    continue
                if form.tag.number is not None:
                    return str(form.tag.number)
            except (ValueError, AttributeError, TypeError):
                continue
    return None


def _grammemes_for_target_case(
    parse,
    case: str,
) -> set[str]:
    grams: set[str] = {case}
    try:
        tag = parse.tag
        if tag.number is not None:
            grams.add(str(tag.number))
        else:
            grams.add("sing")
        if tag.gender is not None:
            grams.add(str(tag.gender))
    except (ValueError, AttributeError, TypeError):
        grams.add("sing")
    return grams


def _should_fix_to_case(
    prep: str,
    current: str,
    expected: str,
    lang: str = "ru",
    *,
    tokens_before: list[str] | None = None,
    morph=None,
) -> bool:
    if not expected or not current or current == expected:
        return False
    if current == "nomn":
        return True
    if prep in _prep_single_case_set(lang):
        return True
    if (
        prep in _sgr.MULTI_CASE_MOTION_PREPS
        and tokens_before is not None
        and morph is not None
        and current in ("loct", "accs")
        and expected in ("loct", "accs")
    ):
        resolved = _expected_case_after_prep(
            prep, tokens_before, morph, lang
        )
        if resolved == expected:
            return True
    return False


def _expected_case_after_prep(
    prep: str,
    tokens_before: list[str],
    morph,
    lang: str,
) -> str | None:
    pmap = _prep_map(lang)
    cases = pmap.get(prep)
    if not cases:
        return None
    if len(cases) == 1:
        return _norm_prep_case(cases[0], lang)
    return _resolve_multi_case_prep(prep, tokens_before, morph, lang, cases)


def _parse_case_tag(parse) -> str:
    try:
        if parse is not None and parse.tag.case is not None:
            return str(parse.tag.case)
    except (ValueError, AttributeError, TypeError):
        pass
    return ""


def _context_infer_should_fix(
    cur_case: str,
    exp_case: str,
    tokens_before: list[str],
    morph,
    lang: str,
) -> bool:
    """是否应根据句法推断修正当前词形（不限于主格）。"""
    if not exp_case or not cur_case or cur_case == exp_case:
        return False
    if cur_case in ("", "nomn"):
        return True
    # 否定谓语 + 属格：宾格/主格宾语 → 属格（俄/乌 partial genitive）
    if exp_case == "nomn" and cur_case not in ("", "nomn"):
        if tokens_before and tokens_before[-1] in _sgr.COMPARISON_THAN_MARKERS:
            return True
    if exp_case == "gent" and cur_case in ("", "nomn", "accs"):
        if tokens_before and tokens_before[-1] in _sgr.COMPARISON_GENITIVE_HEADS:
            return True
    if exp_case == "gent" and cur_case == "accs":
        if _negated_verb_in_context(tokens_before, morph, lang):
            return True
        head = tokens_before[-1] if tokens_before else ""
        norm = _normalize_num_token(head)
        if (
            head in _sgr.NUMERAL_GENTIVE_HEADS
            or norm in _sgr.NUMERAL_GENTIVE_HEADS
            or head in _RU_GENTIVE_HEAD
            or head in _UK_GENTIVE_HEAD
            or head in _sgr.PARTITIVE_GENTIVE_HEADS
        ):
            return True
    if (
        exp_case in ("loct", "accs")
        and cur_case in ("loct", "accs")
        and exp_case != cur_case
    ):
        for tok in reversed(tokens_before[-5:]):
            if tok in _sgr.MULTI_CASE_MOTION_PREPS:
                return True
    if exp_case == "datv" and cur_case in ("", "nomn", "accs"):
        if tokens_before and _token_is_impersonal_verb(
            tokens_before[-1], morph, lang
        ):
            return True
        return False
    if (
        cur_case == "gent"
        and exp_case in ("datv", "ablt", "accs")
        and _negated_verb_in_context(tokens_before, morph, lang)
    ):
        return False
    if cur_case in ("loct", "accs") and exp_case == "ablt":
        return False
    return False


def _fix_word_from_context_infer(
    surfaces: list[str],
    index: int,
    morph,
    lang: str,
) -> None:
    """据句法规则推断格并修补明显错误的词形（主格、否定下误用宾格等）。"""
    pos_hint_parse = _parse_surface(morph, surfaces[index])
    if pos_hint_parse is None:
        return
    pos = _gm().safe_parse_pos(pos_hint_parse)
    if pos not in ("NOUN", "ADJF", "ADJS", "PRTF", "PRTS", "NUMR", "NPRO"):
        return
    before_ctx = " ".join(surfaces[:index])
    after_ctx = " ".join(surfaces[index + 1 :])
    code = (lang or "").strip().lower()
    tokens_before = _uk_tokens(before_ctx) if code == "uk" else _ru_tokens(before_ctx)
    if pos == "NOUN":
        p = _pick_noun_parse_for_context(
            morph, surfaces[index], tokens_before, code
        )
    else:
        p = pos_hint_parse
    if p is None:
        return
    cur_case = _parse_case_tag(p)
    if code == "ru":
        grams = infer_ru_grammemes(
            before_ctx, after_ctx, surfaces[index], morph=morph
        )
    elif code == "uk":
        grams = infer_uk_grammemes(
            before_ctx, after_ctx, surfaces[index], morph=morph
        )
    else:
        return
    exp_cases = grams & _OC_CASES
    if not exp_cases:
        return
    exp = next(iter(exp_cases))
    exp = _effective_object_case(exp, p, tokens_before, morph, code)
    if exp == "nomn":
        if _context_infer_should_fix(cur_case, exp, tokens_before, morph, code):
            fix_grams = _grammemes_for_target_case(p, "nomn")
            fix_grams.difference_update(_OC_NUMBER)
            fix_grams.update(grams & _OC_GENDER)
            if not (fix_grams & _OC_NUMBER):
                fix_grams.add("sing")
            surfaces[index] = _try_fix_word_form(morph, surfaces[index], fix_grams)
        return
    if not _context_infer_should_fix(cur_case, exp, tokens_before, morph, code):
        return
    fix_grams = _grammemes_for_target_case(p, exp)
    parse_number = fix_grams & _OC_NUMBER
    lex_number = _number_from_noun_lexeme(morph, surfaces[index], exp)
    if lex_number:
        parse_number = {lex_number}
    fix_grams.difference_update(_OC_NUMBER)
    fix_grams.update(grams & _OC_GENDER)
    if parse_number:
        fix_grams.update(parse_number)
    elif grams & _OC_NUMBER:
        fix_grams.update(grams & _OC_NUMBER)
    else:
        fix_grams.add("sing")
    if _surface_matches_grammemes(morph, surfaces[index], fix_grams):
        return
    prefer_gent = exp == "gent" and (
        _negated_verb_in_context(tokens_before, morph, code)
        or code == "uk"
    )
    surfaces[index] = _try_fix_word_form(
        morph, surfaces[index], fix_grams, prefer_standard_gent=prefer_gent
    )


def _try_fix_word_form(
    morph,
    surface: str,
    grammemes: set[str],
    *,
    prefer_standard_gent: bool = False,
) -> str:
    if morph is None or not grammemes:
        return surface
    p = _parse_surface(morph, surface)
    if p is None:
        return surface
    pos = _gm().safe_parse_pos(p)
    if pos not in ("NOUN", "ADJF", "ADJS", "PRTF", "PRTS", "NUMR", "NPRO"):
        return surface
    nf = p.normal_form or surface
    fixed = _inflect_with_morph(
        morph,
        nf,
        grammemes,
        prefer_standard_gent=prefer_standard_gent,
    )
    if not fixed or fixed.lower() == surface.lower():
        return surface
    return _cap_like(surface, fixed)


def fix_sentence_slavic_morphology(sentence: str, lang: str) -> str:
    """
    保守修补一句俄/乌译文：前置词后格错误、形容词与名词格不一致。
    跳过 GLOSSA 占位符行。
    """
    line = sentence or ""
    if not line.strip():
        return line
    if "GLOSSA" in line.upper() or "ＧＬＯＳＳＡ" in line or "ГЛОССА" in line.upper():
        return line
    code = (lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return line
    morph = _morph_for_lang(code)
    if morph is None:
        return line

    spans = _word_spans(line, code)
    if not spans:
        return line
    surfaces = [w for _, _, w in spans]
    lowers = [_plain_surface(w) for w in surfaces]
    pmap = _prep_map(code)
    prep_keys = set(pmap.keys())

    fix_multiword_prep_surfaces_in_place(surfaces, lowers, morph, code)

    # 1) 前置词 + 后续词组格
    i = 0
    while i < len(spans):
        prep = lowers[i]
        if prep in prep_keys:
            if prep in ("у", "в") and _existential_u_pattern(lowers, code):
                i += 1
                continue
            poss = (
                _sgr.UK_U_POSSESSIVE_PRONOUN
                if code == "uk"
                else _sgr.RU_U_POSSESSIVE_PRONOUN
            )
            if (
                prep in ("у", "в")
                and i + 1 < len(lowers)
                and lowers[i + 1] in poss
            ):
                i += 1
                continue
            before = lowers[:i]
            exp = _expected_case_after_prep(prep, before, morph, code)
            if exp:
                j = i + 1
                while j < len(spans) and j <= i + 6:
                    if lowers[j] in _sgr.COORD_CONJ:
                        j += 1
                        continue
                    p = _parse_surface(morph, surfaces[j])
                    if p is None:
                        j += 1
                        continue
                    pos = _gm().safe_parse_pos(p)
                    if pos not in ("NOUN", "ADJF", "ADJS", "PRTF", "PRTS", "NUMR", "NPRO"):
                        j += 1
                        continue
                    cur_case = _parse_case_tag(p)
                    if _should_fix_to_case(
                        prep,
                        cur_case,
                        exp,
                        code,
                        tokens_before=before,
                        morph=morph,
                    ):
                        grams = _grammemes_for_target_case(p, exp)
                        surfaces[j] = _try_fix_word_form(morph, surfaces[j], grams)
                    if pos == "NOUN":
                        if (
                            j + 1 < len(spans)
                            and lowers[j + 1] in _sgr.COORD_CONJ
                        ):
                            j += 2
                            continue
                        break
                    j += 1
        i += 1

    # 2) 上下文句法（нет/много、动词宾语、形容词继承等）— 修正仍为主格的名词/形容词
    for j in range(len(spans)):
        _fix_word_from_context_infer(surfaces, j, morph, code)

    # 3) 形容词/分词 + 名词：格/性/数与名词一致（所有格/指示代词，不含与格人称代词）
    _AGREE_POS = ("ADJF", "ADJS", "PRTF", "PRTS", "NUMR")
    _POSSESSIVE_NPRO = frozenset(
        {
            "мой",
            "моя",
            "моё",
            "мои",
            "моего",
            "моей",
            "моих",
            "твой",
            "ваш",
            "ваша",
            "ваше",
            "ваши",
            "его",
            "её",
            "их",
            "свой",
            "своя",
            "своё",
            "свои",
            "мій",
            "моя",
            "моє",
            "мої",
            "твій",
            "ваш",
            "ваша",
            "ваше",
            "ваші",
            "його",
            "її",
            "їх",
            "свій",
            "своя",
            "своє",
            "свої",
        }
    )
    for j in range(len(spans) - 1):
        pn = _parse_surface(morph, surfaces[j + 1])
        pa = _parse_surface(morph, surfaces[j])
        if pn is None or pa is None:
            continue
        if _gm().safe_parse_pos(pn) != "NOUN":
            continue
        pa_pos = _gm().safe_parse_pos(pa)
        pa_low = lowers[j]
        if pa_pos in _AGREE_POS:
            if pa_pos == "NUMR":
                num_norm = _normalize_num_token(pa_low)
                if pa_low in _sgr.NUMERAL_ONE_HEADS or num_norm in _sgr.NUMERAL_ONE_HEADS:
                    pass
                elif (
                    pa_low in _sgr.NUMERAL_GENTIVE_HEADS
                    or num_norm in _sgr.NUMERAL_GENTIVE_HEADS
                ):
                    continue
        elif pa_pos == "NPRO" and pa_low in _POSSESSIVE_NPRO:
            pass
        elif _is_numeral_one_token(pa, surfaces[j]):
            pass
        else:
            continue
        target = _agreement_grammemes_from_head(pn)
        if not (target & _OC_CASES):
            continue
        if _is_numeral_one_token(pa, surfaces[j]):
            fixed = _inflect_numeral_one_to_match(morph, surfaces[j], target)
            if fixed and fixed.lower() != surfaces[j].lower():
                surfaces[j] = fixed
            continue
        fixed = _try_fix_word_form(morph, surfaces[j], target)
        if fixed.lower() != surfaces[j].lower():
            surfaces[j] = fixed

    # 4) 非人称句、反身代词、动词支配短语
    _fix_impersonal_constructions(surfaces, lowers, morph, code)
    _fix_reflexive_pronoun_case(surfaces, lowers, morph, code)
    _fix_verb_governed_phrase(surfaces, lowers, morph, code)

    # 5) 二次上下文推断（前述修正后补漏）
    for j in range(len(spans)):
        _fix_word_from_context_infer(surfaces, j, morph, code)

    return _rebuild_line(line, spans, surfaces)


def fix_text_slavic_morphology(text: str, lang: str, *, passes: int = 2) -> str:
    """逐行修补俄/乌译文变格（保留空行结构）；默认两遍，passes=1 用于长文加速。"""
    if not (text or "").strip():
        return text
    n = max(1, min(2, int(passes)))
    lines = (text or "").split("\n")
    fixed: list[str] = []
    for ln in lines:
        cur = ln
        for _ in range(n):
            cur = fix_sentence_slavic_morphology(cur, lang)
        fixed.append(cur)
    return "\n".join(fixed)


def slavic_morph_fix_enabled() -> bool:
    import os

    v = os.environ.get("ARGOS_SLAVIC_MORPH_FIX", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True
