"""
成语、固定搭配与 calque 修补（国际开放语料）。

数据来源见 data/idioms/*.json meta.sources：
Wiktionary (CC BY-SA), Tatoeba (CC BY), OpenRussian (CC BY-SA), Sussex Blok Grammar。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "data" / "idioms"

_GLOSSA_SKIP = re.compile(
    r"GLOSSA|ＧＬＯＳＳＡ|ГЛОССА",
    re.I,
)

_SKIP_COLLATION = frozenset({"zh_slavic_idioms.json", "zh_religious_idioms.json"})


def _load_json(name: str) -> dict:
    p = _DATA_DIR / name
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=1)
def _merged_collocation_items(lang: str) -> tuple[dict, ...]:
    """合并 data/idioms 下所有搭配 JSON（除 zh 源语表）。"""
    code = (lang or "").strip().lower()
    items: list[dict] = []
    if not _DATA_DIR.is_dir():
        return tuple()
    for p in sorted(_DATA_DIR.glob("*.json")):
        if p.name in _SKIP_COLLATION:
            continue
        data = _load_json(p.name)
        chunk = data.get(code) or []
        if isinstance(chunk, list):
            for it in chunk:
                if isinstance(it, dict) and it.get("wrong") != it.get("right"):
                    items.append(it)
    return tuple(items)


@lru_cache(maxsize=1)
def _merged_zh_idiom_items(lang: str) -> tuple[dict, ...]:
    """合并 data/idioms/zh_*.json 中的源语→目标语 idiom 表。"""
    code = (lang or "").strip().lower()
    key = "zh_ru" if code == "ru" else "zh_uk"
    items: list[dict] = []
    if not _DATA_DIR.is_dir():
        return tuple()
    for p in sorted(_DATA_DIR.glob("zh_*.json")):
        chunk = _load_json(p.name).get(key) or []
        if isinstance(chunk, list):
            items.extend(it for it in chunk if isinstance(it, dict))
    return tuple(items)


@lru_cache(maxsize=1)
def _zh_idioms() -> dict:
    return _load_json("zh_slavic_idioms.json")


def slavic_idiom_fix_enabled() -> bool:
    import os

    v = os.environ.get("ARGOS_SLAVIC_IDIOM_FIX", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return False
    return True


def _case_insensitive_replace(text: str, wrong: str, right: str) -> str:
    if not wrong or not right or wrong == right:
        return text
    pat = re.compile(re.escape(wrong), re.I)
    return pat.sub(right, text)


_CATHOLIC_MARKERS = (
    "教宗", "教皇", "枢机", "梵蒂冈", "罗马教廷",
    "玫瑰经", "特伦托", "教区", "本堂", "修院",
)
_ORTHODOX_MARKERS = (
    "东正教", "正教", "牧首", "宗主教", "大主教", "圣像", "神品",
    "祝圣", "傅油", "大斋期", "拜占庭", "事奉",
)
_PROTESTANT_MARKERS = (
    "新教", "福音派", "路德", "加尔文", "浸信", "长老会", "卫理",
    "改革宗", "清教徒", "五旬节派", "传道人",
)


def _christian_tradition(source_text: str) -> str:
    """根据源语标记推断基督教教派语境；默认东正/ синodal 书面语。"""
    src = source_text or ""
    if any(m in src for m in ("东正教", "正教")):
        return "orthodox"
    if "天主教" in src:
        return "catholic"
    if any(m in src for m in _PROTESTANT_MARKERS):
        return "protestant"
    if any(m in src for m in _ORTHODOX_MARKERS):
        return "orthodox"
    if any(m in src for m in _CATHOLIC_MARKERS):
        return "catholic"
    if "天主" in src:
        return "catholic"
    return "orthodox"


def _resolve_zh_target(item: dict, tgt_key: str, tradition: str) -> str:
    """解析 zh idiom 目标形；支持 ru_catholic / ru_protestant 等变体。"""
    if tradition == "catholic":
        alt = item.get(f"{tgt_key}_catholic")
        if alt:
            return str(alt).strip()
    elif tradition == "protestant":
        alt = item.get(f"{tgt_key}_protestant")
        if alt:
            return str(alt).strip()
    elif tradition == "orthodox":
        alt = item.get(f"{tgt_key}_orthodox")
        if alt:
            return str(alt).strip()
    return str(item.get(tgt_key) or "").strip()


def apply_target_collocation_fixes(text: str, lang: str) -> str:
    """俄/乌译文：替换常见 calque 与介词搭配错误。"""
    if not text or not slavic_idiom_fix_enabled():
        return text
    code = (lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return text
    out = text
    for item in _merged_collocation_items(code):
        wrong = str(item.get("wrong") or "").strip()
        right = str(item.get("right") or "").strip()
        if wrong and right:
            out = _case_insensitive_replace(out, wrong, right)
    return out


_CALQUES_RU: dict[str, list[str]] = {
    "没关系": ["это не имеет отношения", "нет отношения"],
    "不用谢": ["не нужно благодарить", "не надо благодарить"],
    "实际上": ["в действительности", "в реальности"],
    "目前": ["на данный момент", "в данный момент", "в настоящее время"],
    "根据": ["на основе", "исходя из того"],
    "由于": ["из-за того что", "благодаря тому что"],
    "总之": ["в общем и целом", "суммируя"],
    "值得注意的是": ["стоит отметить что", "нужно отметить"],
    "因此": ["из этого следует", "таким образом следует"],
    # 教会称谓 · 姊妹/弟兄（单人；MT 常误译为复数）
    "姊妹": [
        "сестры люба",
        "сестры луба",
        "сестры -",
        "сестры любы",
        "сестер люба",
        "сёстры",
    ],
    "弟兄": [
        "братья пётр",
        "братья петр",
        "братья -",
        "братьев пётр",
        "братьев петр",
    ],
    # 素质 / 工作能力（口语评价）
    "素质": ["лучше, чем работа", "лучше чем работа", "лучше, чем работу"],
    "有工作能力": ["лучше, чем работа", "лучше чем работа"],
    "工作能力": ["лучше, чем работа", "чем работа"],
    # Colloquial (zh_colloquial_idioms.json)
    "说话比较直接": [
        "говорит прямо, ей говорит прямо",
        "говорит прямо, ей говорит прямо.",
        "она говорит прямо, ей говорит прямо",
    ],
    "把心情说出来": ["ей говорит прямо", "говорит прямо, ей"],
    "直接把心情说出来": ["говорит прямо, ей говорит прямо"],
    # Christian register (zh_religious_idioms.json)
    "上帝": ["небесный отец", "небесного отца", "божество", "sky father"],
    "天主": ["небесный отец", "божество"],
    "耶和华": ["jehovah", "иeговa"],
    "罪": ["вина", "преступление"],
    "做祷告": ["делать молитву", "делает молитву", "говорить молитву"],
    "祈祷": ["делать молитву", "говорить молитву"],
    "福音": ["хорошие новости", "хорошая новость", "good news"],
    "复活节": ["пасхальный праздник", "пасхальное воскресенье"],
    "教堂": ["идти на церковь", "ходить на церковь", "идти на храм"],
    "礼拜": ["церковная служба", "служба в церкви"],
    "弥撒": ["божественная литургия", "литургия"],
    "圣餐": ["коммуния", "комunion", "евхаристия"],
    "告解": ["конфессия"],
    "忏悔": ["признание в грехах"],
    "得救": ["спасение души"],
    "哈利路亚": ["аллилуйя", "аллилуia"],
    "牧师": ["священнослужитель", "священник"],
    "神父": ["священнослужитель"],
    "圣母": ["дева мария"],
    "领圣餐": ["принимать communion", "принимать причастие"],
    "主祷文": ["молитва отца нашего", "отче наш"],
    "赞美上帝": ["хвалить бога", "хвалят бога"],
    "圣经": ["священное писание"],
    "十诫": ["десять заповедей"],
    "洗礼": ["крещение водой"],
}

_TRADITION_CALQUES_RU: dict[tuple[str, str], list[str]] = {
    ("catholic", "弥撒"): ["божественная литургия", "литургия"],
    ("orthodox", "弥撒"): ["месса"],
    ("catholic", "圣母"): ["богородица"],
    ("protestant", "牧师"): ["священник", "священнослужитель"],
    ("protestant", "教堂"): ["храм"],
}

_TRADITION_CALQUES_UK: dict[tuple[str, str], list[str]] = {
    ("catholic", "弥撒"): ["божественна літургія"],
    ("orthodox", "弥撒"): ["меса"],
    ("catholic", "圣母"): ["богородица"],
    ("protestant", "牧师"): ["священник"],
}

_CALQUES_UK: dict[str, list[str]] = {
    "没关系": ["це не має відношення"],
    "不用谢": ["не потрібно дякувати"],
    "实际上": ["в дійсності", "в реальності"],
    "目前": ["на даний момент", "в даний час"],
    "根据": ["на основі"],
    "由于": ["через те що"],
    "因此": ["з цього випливає"],
    "素质": ["краще, ніж робота", "краще ніж робота"],
    "有工作能力": ["краще, ніж робота"],
    "姊妹": ["сестри люба", "сестри луба", "сестер люба"],
    "弟兄": ["брати петро", "брати пётр", "братів петро"],
    "说话比较直接": ["говорить прямо, їй говорить прямо"],
    "把心情说出来": ["їй говорить прямо"],
    "上帝": ["небесний отець"],
    "天主": ["небесний отець"],
    "罪": ["вина", "злочин"],
    "做祷告": ["робити молитву", "робить молитву", "говорити молитву"],
    "祈祷": ["робити молитву"],
    "福音": ["хороші новини"],
    "教堂": ["йти на церкву", "ходити на церкву"],
    "礼拜": ["церковна служба"],
    "弥撒": ["божественна літургія"],
    "圣餐": ["комunion"],
    "告解": ["конфесія"],
    "复活节": ["великодній свят"],
    "哈利路亚": ["аллелуia", "аллілуia"],
    "牧师": ["пастор"],
}


def apply_zh_source_idiom_hints(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """
    若译文仍含字面直译痕迹而源文为固定说法，尝试替换为 idiom 目标形。
    保守：仅当目标句包含明显 calque 子串时才替换。
    """
    if not source_text or not target_text or not slavic_idiom_fix_enabled():
        return target_text
    code = (target_lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return target_text

    tgt_key = "ru" if code == "ru" else "uk"
    items = _merged_zh_idiom_items(code)
    src = source_text.strip()
    tradition = _christian_tradition(src)
    out = target_text
    calques = _CALQUES_RU if code == "ru" else _CALQUES_UK

    for item in items:
        if not isinstance(item, dict):
            continue
        zh = str(item.get("zh") or "").strip()
        expected = _resolve_zh_target(item, tgt_key, tradition)
        if not zh or not expected:
            continue
        if zh not in src:
            continue
        if expected.lower() in out.lower():
            continue
        bad_list = list(calques.get(zh, []))
        trad_calques = _TRADITION_CALQUES_RU if code == "ru" else _TRADITION_CALQUES_UK
        bad_list.extend(trad_calques.get((tradition, zh), []))
        for bad in bad_list:
            if bad.lower() in out.lower():
                out = _case_insensitive_replace(out, bad, expected)
                break
    return out


@lru_cache(maxsize=1)
def _zh_name_map() -> dict[str, dict[str, object]]:
    data = _load_json("zh_names_slavic.json")
    out: dict[str, dict[str, object]] = {}
    for item in data.get("names") or []:
        if not isinstance(item, dict):
            continue
        zh = str(item.get("zh") or "").strip()
        if not zh:
            continue
        wrong_ru = [
            str(x).strip()
            for x in (item.get("wrong_ru") or [])
            if str(x).strip()
        ]
        wrong_uk = [
            str(x).strip()
            for x in (item.get("wrong_uk") or wrong_ru or [])
            if str(x).strip()
        ]
        out[zh] = {
            "ru": str(item.get("ru") or "").strip(),
            "uk": str(item.get("uk") or item.get("ru") or "").strip(),
            "wrong_ru": wrong_ru,
            "wrong_uk": wrong_uk,
        }
    return out


def apply_zh_name_transliteration_fix(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """源文出现的中文人名：把译文里常见错写替换为惯用转写。"""
    if not slavic_idiom_fix_enabled() or not source_text or not target_text:
        return target_text
    code = (target_lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return target_text
    src = source_text
    out = target_text
    wrong_key = "wrong_ru" if code == "ru" else "wrong_uk"
    items = sorted(_zh_name_map().items(), key=lambda kv: -len(kv[0]))
    for zh, entry in items:
        if zh not in src:
            continue
        right = str(entry.get(code) or entry.get("ru") or "").strip()
        if not right:
            continue
        if right.lower() in out.lower():
            continue
        for wrong in entry.get(wrong_key) or ():
            w = str(wrong).strip()
            if w and w.lower() in out.lower():
                out = _case_insensitive_replace(out, w, right)
                break
    return out


def _zh_singular_person_clause(source_text: str) -> bool:
    return _zh_person_description_clause(source_text)


def _zh_predicative_copula_ge(source_text: str) -> bool:
    """源语含「是+个/一个/位/名」类谓语（是个与是一个应同译）。"""
    src = source_text or ""
    return bool(
        re.search(
            r"是(?:一个|一位|一名|个(?=[\u4e00-\u9fff])|位(?=[\u4e00-\u9fff])|名(?=[\u4e00-\u9fff]))|是个",
            src,
        )
    )


def _ru_inst_adj_to_nom(adj: str) -> str:
    a = (adj or "").strip()
    low = a.lower()
    if low.endswith("ичным"):
        return a[:-5] + "ичный"
    if low.endswith("ным") and len(low) > 4:
        return a[:-2] + "ый"
    if low.endswith("им") and len(low) > 3:
        return a[:-2] + "ий"
    if low.endswith("ой"):
        return a[:-2] + "ый"
    if low.endswith("ей"):
        return a[:-2] + "ий"
    return a


def _uk_inst_adj_to_nom(adj: str) -> str:
    a = (adj or "").strip()
    low = a.lower()
    if low.endswith("ним") and len(low) > 4:
        return a[:-3] + "ний"
    if low.endswith("ою"):
        return a[:-2] + "а"
    return a


def apply_zh_predicative_copula_repairs(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """
    「是个 / 是一个 / 是位…」：译文统一为破折号谓语或自然系词，避免
    является / это / есть 混用导致同句不同译法。
    """
    if not slavic_idiom_fix_enabled() or not source_text or not target_text:
        return target_text
    if not _zh_predicative_copula_ge(source_text):
        return target_text
    code = (target_lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return target_text
    out = target_text
    human = "человек" if code == "ru" else "людина"

    if code == "ru":
        out = re.sub(r"\bэто\s+является\s+", "это ", out, flags=re.I)
        out = re.sub(
            r"\bявляется\s+([а-яё]+(?:им|ым|ой|ей))\s+"
            + re.escape(human)
            + r"ом\b",
            lambda m: f"— {_ru_inst_adj_to_nom(m.group(1))} {human}",
            out,
            flags=re.I,
        )
        if _zh_person_description_clause(source_text):
            out = re.sub(
                r"([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\s+(?:это|является|есть)\s+",
                r"\1 — ",
                out,
                count=3,
            )
            out = re.sub(
                r"—\s*([а-яё]+(?:им|ым))\s+"
                + re.escape(human)
                + r"ом\b",
                lambda m: f"— {_ru_inst_adj_to_nom(m.group(1))} {human}",
                out,
                flags=re.I,
            )
    else:
        out = re.sub(r"\bце\s+є\s+", "це ", out, flags=re.I)
        out = re.sub(
            r"\bє\s+([а-яіїєґ]+(?:им|ою))\s+"
            + re.escape(human)
            + r"ою\b",
            lambda m: f"— {_uk_inst_adj_to_nom(m.group(1))} {human}",
            out,
            flags=re.I,
        )
        if _zh_person_description_clause(source_text):
            out = re.sub(
                r"([А-ЯІЇЄҐ][а-яіїєґ]+(?:\s+[А-ЯІЇЄҐ][а-яіїєґ]+)?)\s+(?:це|є)\s+",
                r"\1 — ",
                out,
                count=3,
            )
    out = re.sub(r"\s+—\s+—\s+", " — ", out)
    out = re.sub(r"\s{2,}", " ", out)
    return out.strip() if out else out


def _zh_person_description_clause(source_text: str) -> bool:
    """源语描述「一个/是个/是一位…的人」等（单人，非复数）。"""
    src = source_text or ""
    if any(x in src for x in ("们", "两位", "两个", "两名", "诸位", "各位")):
        return False
    return bool(
        re.search(
            r"(?:一个|是个|是一个|是位|是一名|此人是|这个人是|他是|她是).{0,28}人",
            src,
        )
        or re.search(r"(?:很|非常|十分|极其|特别).{0,16}(?:的)?人", src)
        or re.search(r"为人.{0,12}(?:的)?人", src)
    )


@lru_cache(maxsize=1)
def _person_traits_bundle() -> dict:
    return _load_json("zh_person_traits.json")


@lru_cache(maxsize=1)
def _person_trait_rules() -> tuple[dict, ...]:
    data = _person_traits_bundle()
    rules: list[dict] = []
    for item in data.get("rules") or []:
        if isinstance(item, dict) and str(item.get("zh") or "").strip():
            rules.append(item)
    rules.sort(key=lambda r: len(str(r.get("zh") or "")), reverse=True)
    return tuple(rules)


@lru_cache(maxsize=1)
def _person_trait_objects() -> dict[str, dict]:
    raw = _person_traits_bundle().get("objects") or {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


@lru_cache(maxsize=1)
def _person_verb_templates() -> tuple[dict, ...]:
    tpls = _person_traits_bundle().get("verb_templates") or []
    out: list[dict] = []
    for item in tpls:
        if isinstance(item, dict) and str(item.get("prefix") or "").strip():
            out.append(item)
    out.sort(key=lambda t: len(str(t.get("prefix") or "")), reverse=True)
    return tuple(out)


def clear_person_trait_cache() -> None:
    _person_traits_bundle.cache_clear()
    _person_trait_rules.cache_clear()
    _person_trait_objects.cache_clear()
    _person_verb_templates.cache_clear()


_PERSON_INNER_CLAUSE = re.compile(
    r"(?:是(?:个|一个|一位|一名|位|名)?)([^，。；！？\n]{2,24}?)(?:的)?人"
)


def _extract_person_inner_clause(source_text: str) -> str:
    src = source_text or ""
    m = _PERSON_INNER_CLAUSE.search(src)
    if not m:
        return ""
    return (m.group(1) or "").strip()


def _format_predicate(template: str, obj: dict) -> str:
    merged = {k: str(v) for k, v in obj.items() if not k.startswith("stems")}
    try:
        return template.format(**merged)
    except KeyError:
        return ""


def _rule_from_verb_template(inner: str, tpl: dict, obj: dict) -> dict | None:
    pred_ru = _format_predicate(str(tpl.get("predicate_ru") or ""), obj)
    pred_uk = _format_predicate(str(tpl.get("predicate_uk") or ""), obj)
    if not pred_ru and not pred_uk:
        return None
    stems_ru = list(obj.get("stems_ru") or [])
    stems_uk = list(obj.get("stems_uk") or [])
    stems_ru.extend(tpl.get("extra_stems_ru") or [])
    stems_uk.extend(tpl.get("extra_stems_uk") or [])
    return {
        "zh": inner,
        "ru": pred_ru.split(",")[-1].strip() if pred_ru else "",
        "uk": pred_uk.split(",")[-1].strip() if pred_uk else "",
        "predicate_ru": pred_ru,
        "predicate_uk": pred_uk,
        "stems_ru": stems_ru,
        "stems_uk": stems_uk,
    }


def _match_dynamic_person_trait_rule(inner: str) -> dict | None:
    inner = (inner or "").strip()
    if not inner:
        return None
    objects = _person_trait_objects()
    for tpl in _person_verb_templates():
        prefix = str(tpl.get("prefix") or "")
        if not inner.startswith(prefix):
            continue
        obj_key = inner[len(prefix) :].strip()
        obj = objects.get(obj_key)
        if obj is None:
            continue
        rule = _rule_from_verb_template(inner, tpl, obj)
        if rule:
            return rule
    return None


def _trait_predicate(rule: dict, lang: str) -> str:
    code = (lang or "").strip().lower()
    if code == "uk":
        return str(rule.get("predicate_uk") or "").strip()
    return str(rule.get("predicate_ru") or "").strip()


# 机翻常用 - / – / — 作系词
_PREDICATE_DASH = r"[-—–‐‑‒]\s*"


def _match_person_trait_rule(source_text: str) -> dict | None:
    src = source_text or ""
    for rule in _person_trait_rules():
        zh = str(rule.get("zh") or "").strip()
        if zh and zh in src:
            return rule
    inner = _extract_person_inner_clause(src)
    if inner:
        for rule in _person_trait_rules():
            zh = str(rule.get("zh") or "").strip()
            if zh and (inner == zh or inner.startswith(zh)):
                return rule
        dyn = _match_dynamic_person_trait_rule(inner)
        if dyn:
            return dyn
    return None


def _trait_adj(rule: dict, lang: str) -> str:
    code = (lang or "").strip().lower()
    if code == "uk":
        return str(rule.get("uk") or rule.get("ru") or "").strip()
    return str(rule.get("ru") or "").strip()


def _target_has_person_trait_stem(target_text: str, rule: dict, lang: str) -> bool:
    low = (target_text or "").lower()
    code = (lang or "").strip().lower()
    key = "stems_uk" if code == "uk" else "stems_ru"
    for stem in rule.get(key) or rule.get("stems_ru") or ():
        s = str(stem).strip().lower()
        if s and s in low:
            return True
    return False


def _target_has_generic_person_praise(target_text: str, lang: str) -> bool:
    low = (target_text or "").lower()
    code = (lang or "").strip().lower()
    if code == "ru":
        return bool(
            re.search(r"\bхорош\w*(?:\s+человек|\s+личность)?\b", low)
            or re.search(r"\bдобр\w*\s+человек\b", low)
        )
    return bool(
        re.search(r"\bхорош\w*\s+людин[аиу]?\b", low)
        or re.search(r"\bдобр\w*\s+людин[аиу]?\b", low)
    )


_SISTER_EXPLICIT_PLURAL_RE = re.compile(
    r"姊妹们|众姊妹|诸位姊妹|各位姊妹|"
    r"(?:两|三|四|五|六|七|八|九|十|几|若干|许多|很多|不少|多位|几位|数个|多个)(?:个|名|位)?姊妹|"
    r"\d+\s*个?\s*姊妹|"
    r"姊妹\s*(?:们|等|俩|两者)"
)


def _zh_sister_title_explicit_plural(source_text: str) -> bool:
    """源语明确表示多位姊妹（生物姐妹或复数称谓），不做单数强制。"""
    return bool(_SISTER_EXPLICIT_PLURAL_RE.search(source_text or ""))


def _zh_sister_title_singular_context(source_text: str) -> bool:
    """教会称谓「姊妹」默认按单人理解，除非源语写明复数。"""
    src = source_text or ""
    return "姊妹" in src and not _zh_sister_title_explicit_plural(src)


def _name_for_sister_title(source_text: str) -> str:
    src = source_text or ""
    m = re.search(r"([\u4e00-\u9fff]{2,5})姊妹", src)
    if m:
        return m.group(1)
    m = re.search(r"姊妹([\u4e00-\u9fff]{2,5})", src)
    return m.group(1) if m else ""


def _name_before_sister_title(source_text: str) -> str:
    return _name_for_sister_title(source_text)


def _zh_name_to_slavic(name_zh: str, lang: str) -> str:
    zh = (name_zh or "").strip()
    if not zh:
        return ""
    code = (lang or "").strip().lower()
    entry = _zh_name_map().get(zh, {})
    val = entry.get(code) or entry.get("ru") or ""
    return str(val).strip()


def _positive_person_adj_ru(source_text: str) -> str:
    return _person_trait_adj(source_text, "ru")


def _positive_person_adj_uk(source_text: str) -> str:
    return _person_trait_adj(source_text, "uk")


def _person_trait_adj(source_text: str, lang: str) -> str:
    """性格形容词（与 человек/людина 搭配，用阳性形式）。"""
    rule = _match_person_trait_rule(source_text)
    if rule:
        return _trait_adj(rule, lang)
    code = (lang or "").strip().lower()
    return "хороший" if code == "ru" else "хороша"


def _person_trait_target_phrase(source_text: str, lang: str) -> str:
    """称谓句谓语：优先 predicate（如 человек, стремящийся к истине）。"""
    code = (lang or "").strip().lower()
    human = "человек" if code == "ru" else "людина"
    rule = _match_person_trait_rule(source_text)
    if rule is None:
        return f"{_person_trait_adj(source_text, lang)} {human}"
    pred = _trait_predicate(rule, lang)
    if pred:
        return pred
    adj = _trait_adj(rule, lang)
    return f"{adj} {human}" if adj else human


def _source_has_person_trait(source_text: str) -> bool:
    return _match_person_trait_rule(source_text) is not None


def _target_person_trait_mismatch(
    source_text: str, target_text: str, lang: str
) -> bool:
    rule = _match_person_trait_rule(source_text)
    if rule is None:
        return False
    if _target_has_person_trait_stem(target_text, rule, lang):
        return False
    return _target_has_generic_person_praise(target_text, lang) or _zh_person_description_clause(
        source_text
    )


def _ru_instrumental_adj(adj: str) -> str:
    a = (adj or "").strip()
    if a.endswith("ий"):
        return a[:-2] + "им"
    if a.endswith("ый"):
        return a[:-2] + "ым"
    return a


def _apply_person_trait_adj_fix(
    source_text: str,
    target_text: str,
    rule: dict,
    lang: str,
) -> str:
    adj = _trait_adj(rule, lang)
    predicate = _trait_predicate(rule, lang)
    if not adj and not predicate:
        return target_text
    code = (lang or "").strip().lower()
    human = "человек" if code == "ru" else "людина"
    out = target_text
    zh = str(rule.get("zh") or "")

    if predicate:
        pred_esc = re.escape(predicate)
        if code == "ru":
            out = re.sub(
                _PREDICATE_DASH
                + r"хорош(?:ий|ая|ое)\s+человек\.?",
                f"— {predicate}.",
                out,
                flags=re.I,
            )
            out = re.sub(
                r"\bхорош(?:ий|ая|ое)\s+человек\.?",
                f"{predicate}.",
                out,
                flags=re.I,
            )
            out = re.sub(
                r"\bдобр(?:ый|ая|ое)\s+человек\.?",
                f"{predicate}.",
                out,
                flags=re.I,
            )
            out = re.sub(
                r"\bявляется\s+хорош(?:им|ой|ым)\s+человеком\.?",
                f"— {predicate}.",
                out,
                flags=re.I,
            )
        else:
            out = re.sub(
                _PREDICATE_DASH
                + r"хорош(?:ий|а|е)\s+людин[аиу]?\.?",
                f"— {predicate}.",
                out,
                flags=re.I,
            )
            out = re.sub(
                r"\bхорош(?:ий|а|е)\s+людин[аиу]?\.?",
                f"{predicate}.",
                out,
                flags=re.I,
            )
        if re.search(pred_esc, out, flags=re.I):
            return out.strip() if out else out
        return out.strip() if out else out
    # 善良/好心：保留 добр-，不把 добрый 改成别的
    if zh not in ("善良", "好心", "慈祥"):
        if code == "ru":
            out = re.sub(
                r"\bхорош(?:ий|ая|ое)(?:\s+человек|\s+личность)?\b",
                f"{adj} {human}",
                out,
                flags=re.I,
            )
            out = re.sub(
                r"\bдобр(?:ый|ая|ое)\s+человек\b",
                f"{adj} {human}",
                out,
                flags=re.I,
            )
            out = re.sub(
                _PREDICATE_DASH + r"хорош(?:ий|ая|ое)\s+человек\b",
                f"— {adj} {human}",
                out,
                flags=re.I,
            )
            out = re.sub(
                r"\bочень\s+хорош(?:ий|ая|ое)\b",
                f"очень {adj}",
                out,
                flags=re.I,
            )
            inst = _ru_instrumental_adj(adj)
            out = re.sub(
                r"\bявляется\s+хорош(?:им|ой|ым)\s+человеком\b",
                f"является {inst} человеком",
                out,
                flags=re.I,
            )
        else:
            out = re.sub(
                r"\bхорош(?:ий|а|е)\s+людин[аиу]?\b",
                f"{adj} {human}",
                out,
                flags=re.I,
            )
            out = re.sub(
                r"\bдобр(?:ий|а|е)\s+людин[аиу]?\b",
                f"{adj} {human}",
                out,
                flags=re.I,
            )
            out = re.sub(
                _PREDICATE_DASH + r"хорош(?:ий|а|е)\s+людин[аиу]?\b",
                f"— {adj} {human}",
                out,
                flags=re.I,
            )
            out = re.sub(
                r"\bдуже\s+хорош(?:ий|а|е)\b",
                f"дуже {adj}",
                out,
                flags=re.I,
            )
            out = re.sub(
                r"\bочень\s+хорош(?:ий|а|е)\b",
                f"очень {adj}",
                out,
                flags=re.I,
            )
    elif code == "ru" and re.search(r"\bхорош\w*\s+человек", out, flags=re.I):
        out = re.sub(
            r"\bхорош(?:ий|ая|ое)\s+человек\b",
            f"{adj} {human}",
            out,
            flags=re.I,
        )
    return out


def _fix_person_trait_with_human(
    source_text: str,
    target_text: str,
    lang: str,
) -> str:
    return apply_zh_person_trait_repairs(source_text, target_text, lang)


def apply_zh_person_trait_repairs(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """
    性格/人品评价：避免 Argos 把具体褒义词一律译成 хороший/добрый。
    适用于「…的人」、称谓+评价、很…等句式。
    """
    if not slavic_idiom_fix_enabled() or not source_text or not target_text:
        return target_text
    code = (target_lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return target_text
    rule = _match_person_trait_rule(source_text)
    if rule is None:
        return target_text
    if _target_has_person_trait_stem(target_text, rule, code):
        return target_text
    if not (
        _target_has_generic_person_praise(target_text, code)
        or _zh_person_description_clause(source_text)
        or re.search(r"(?:很|非常|十分|极其).{0,12}", source_text)
    ):
        return target_text
    return _apply_person_trait_adj_fix(source_text, target_text, rule, code)


def person_trait_translation_bad(source_text: str, target_text: str) -> bool:
    """译文是否把具体性格词泛化成「好」。"""
    code = (
        "uk"
        if re.search(r"[іїєґ]", target_text or "", re.I)
        else "ru"
    )
    return _target_person_trait_mismatch(source_text, target_text, code)


def _target_has_church_sister_plural(target_text: str, lang: str, *, name_slavic: str = "") -> bool:
    """译文把教会称谓「姊妹」译成复数形式（非属格单数 у сестры）。"""
    out = target_text or ""
    low = out.lower()
    code = (lang or "").strip().lower()
    name = (name_slavic or "").strip()
    if code == "ru":
        if name and re.search(
            rf"\bсестры\s+{re.escape(name)}\b", out, flags=re.I
        ):
            return True
        if re.search(r"(?:^|[.!?]\s+)сестры\b", low):
            return True
        if re.search(r"\bсестры\s+[а-яё]", low) and not re.search(
            r"(?<=[уо])\s+сестры\b", low
        ):
            return True
        return False
    if code == "uk":
        if name and re.search(
            rf"\bсестри\s+{re.escape(name)}\b", out, flags=re.I
        ):
            return True
        if re.search(r"(?:^|[.!?]\s+)сестри\b", low):
            return True
        if re.search(r"\bсестри\s+[а-яіїєґ]", low) and not re.search(
            r"(?<=[уо])\s+сестри\b", low
        ):
            return True
    return False


def _target_sister_title_plural_error(source_text: str, target_text: str) -> bool:
    if not _zh_sister_title_singular_context(source_text):
        return False
    code = "ru"
    if re.search(r"[іїєґ]", target_text or "", re.I):
        code = "uk"
    name = _zh_name_to_slavic(_name_for_sister_title(source_text), code)
    if _target_has_church_sister_plural(target_text, code, name_slavic=name):
        return True
    low = (target_text or "").lower()
    if _zh_singular_person_clause(source_text):
        if "люди" in low and "человек" not in low and "людина" not in low:
            return True
        if re.search(r"\bлуба\b", low) and "柳芭" in source_text:
            return True
    return False


def _fix_church_sister_plural_forms(
    target_text: str,
    lang: str,
    *,
    name_slavic: str = "",
) -> str:
    """将教会称谓误译的复数 сестры/сестри 改为单数 сестра（保留 у сестры 属格）。"""
    out = target_text
    code = (lang or "").strip().lower()
    name = (name_slavic or "").strip()
    if code == "ru":
        if name:
            out = re.sub(
                rf"\bСестры\s+{re.escape(name)}\b",
                f"Сестра {name}",
                out,
                flags=re.I,
            )
            out = re.sub(
                rf"\bсестры\s+{re.escape(name)}\b",
                f"сестра {name}",
                out,
                flags=re.I,
            )
        out = re.sub(r"\bСестры\b", "Сестра", out)
        out = re.sub(r"(?:^|[.!?]\s+)сестры\b", lambda m: m.group(0).replace("сестры", "сестра"), out, flags=re.I)
        return out
    if code == "uk":
        if name:
            out = re.sub(
                rf"\bСестри\s+{re.escape(name)}\b",
                f"Сестра {name}",
                out,
                flags=re.I,
            )
            out = re.sub(
                rf"\bсестри\s+{re.escape(name)}\b",
                f"сестра {name}",
                out,
                flags=re.I,
            )
        out = re.sub(r"\bСестри\b", "Сестра", out)
        out = re.sub(r"(?:^|[.!?]\s+)сестри\b", lambda m: m.group(0).replace("сестри", "сестра"), out, flags=re.I)
    return out


def apply_zh_sister_title_fix(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """
    「某某姊妹」= 一位姐妹（教会称谓），非复数 сестры。
    默认按单数处理；源语含「姊妹们/两位姊妹」等时保留复数。
    源句含「一个…人」时可整句改写为「Сестра … — … человек」。
    """
    if not slavic_idiom_fix_enabled() or not source_text or not target_text:
        return target_text
    src = source_text.strip()
    if not _zh_sister_title_singular_context(src):
        return target_text
    code = (target_lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return target_text

    name_zh = _name_for_sister_title(src)
    name_slavic = _zh_name_to_slavic(name_zh, code)
    out = target_text

    if _zh_person_description_clause(src) and name_slavic:
        rule = _match_person_trait_rule(src)
        if rule and _target_has_person_trait_stem(out, rule, code):
            pass
        elif _source_has_person_trait(src) or _target_person_trait_mismatch(
            src, out, code
        ):
            phrase = _person_trait_target_phrase(src, code)
            return f"Сестра {name_slavic} — {phrase}."

    if _zh_singular_person_clause(src) and (
        _target_sister_title_plural_error(src, out) or name_slavic
    ):
        if code == "ru":
            if name_slavic:
                phrase = _person_trait_target_phrase(src, code)
                return f"Сестра {name_slavic} — {phrase}."
            adj = _positive_person_adj_ru(src)
            human = "человек"
            out = re.sub(r"\bЛуба\b", "Люба", out, flags=re.I)
            out = re.sub(
                r"позитивные\s+люди",
                f"{adj} {human}",
                out,
                flags=re.I,
            )
            out = re.sub(
                r"позитивных\s+людей",
                f"{adj} {human}",
                out,
                flags=re.I,
            )
        else:
            if name_slavic:
                phrase = _person_trait_target_phrase(src, code)
                return f"Сестра {name_slavic} — {phrase}."
            adj = _positive_person_adj_uk(src)
            human = "людина"
            out = re.sub(r"\bЛуба\b", "Люба", out, flags=re.I)
            out = re.sub(
                r"позитивні\s+люди",
                f"{adj} {human}",
                out,
                flags=re.I,
            )

    if _target_has_church_sister_plural(out, code, name_slavic=name_slavic):
        out = _fix_church_sister_plural_forms(out, code, name_slavic=name_slavic)

    # 名+姊妹：确保标题为「Сестра Имя」
    if name_slavic and name_zh in src:
        title = f"Сестра {name_slavic}"
        if title.lower() not in out.lower():
            for bad in (
                f"Сестры {name_slavic}",
                f"сестры {name_slavic}",
                f"Сестри {name_slavic}",
                f"сестри {name_slavic}",
            ):
                if bad.lower() in out.lower():
                    out = _case_insensitive_replace(out, bad, title)
                    break

    out = _fix_person_trait_with_human(src, out, code)
    return out


_BROTHER_EXPLICIT_PLURAL_RE = re.compile(
    r"弟兄们|众弟兄|诸位弟兄|各位弟兄|"
    r"(?:两|三|四|五|六|七|八|九|十|几|若干|许多|很多|不少|多位|几位|数个|多个)(?:个|名|位)?弟兄|"
    r"\d+\s*个?\s*弟兄|"
    r"弟兄\s*(?:们|等|俩|两者)"
)


def _zh_brother_title_explicit_plural(source_text: str) -> bool:
    return bool(_BROTHER_EXPLICIT_PLURAL_RE.search(source_text or ""))


def _zh_brother_title_singular_context(source_text: str) -> bool:
    src = source_text or ""
    return "弟兄" in src and not _zh_brother_title_explicit_plural(src)


def _name_for_brother_title(source_text: str) -> str:
    src = source_text or ""
    m = re.search(r"([\u4e00-\u9fff]{2,5})弟兄", src)
    if m:
        return m.group(1)
    m = re.search(r"弟兄([\u4e00-\u9fff]{2,5})", src)
    return m.group(1) if m else ""


def _target_has_church_brother_plural(
    target_text: str, lang: str, *, name_slavic: str = ""
) -> bool:
    out = target_text or ""
    low = out.lower()
    code = (lang or "").strip().lower()
    name = (name_slavic or "").strip()
    if code == "ru":
        if name and re.search(
            rf"\bбратья\s+{re.escape(name)}\b", out, flags=re.I
        ):
            return True
        if re.search(r"(?:^|[.!?]\s+)братья\b", low):
            return True
        if re.search(r"\bбратья\s+[а-яё]", low) and not re.search(
            r"(?<=[уо])\s+братья\b", low
        ):
            return True
        return False
    if code == "uk":
        if name and re.search(
            rf"\bбрати\s+{re.escape(name)}\b", out, flags=re.I
        ):
            return True
        if re.search(r"(?:^|[.!?]\s+)брати\b", low):
            return True
        if re.search(r"\bбрати\s+[а-яіїєґ]", low) and not re.search(
            r"(?<=[уо])\s+брати\b", low
        ):
            return True
    return False


def _target_brother_title_plural_error(source_text: str, target_text: str) -> bool:
    if not _zh_brother_title_singular_context(source_text):
        return False
    code = "ru"
    if re.search(r"[іїєґ]", target_text or "", re.I):
        code = "uk"
    name = _zh_name_to_slavic(_name_for_brother_title(source_text), code)
    if _target_has_church_brother_plural(target_text, code, name_slavic=name):
        return True
    low = (target_text or "").lower()
    if _zh_singular_person_clause(source_text):
        if "люди" in low and "человек" not in low and "людина" not in low:
            return True
    return False


def _fix_church_brother_plural_forms(
    target_text: str,
    lang: str,
    *,
    name_slavic: str = "",
) -> str:
    out = target_text
    code = (lang or "").strip().lower()
    name = (name_slavic or "").strip()
    if code == "ru":
        if name:
            out = re.sub(
                rf"\bБратья\s+{re.escape(name)}\b",
                f"Брат {name}",
                out,
                flags=re.I,
            )
            out = re.sub(
                rf"\bбратья\s+{re.escape(name)}\b",
                f"брат {name}",
                out,
                flags=re.I,
            )
        out = re.sub(r"\bБратья\b", "Брат", out)
        out = re.sub(
            r"(?:^|[.!?]\s+)братья\b",
            lambda m: m.group(0).replace("братья", "брат"),
            out,
            flags=re.I,
        )
        return out
    if code == "uk":
        if name:
            out = re.sub(
                rf"\bБрати\s+{re.escape(name)}\b",
                f"Брат {name}",
                out,
                flags=re.I,
            )
            out = re.sub(
                rf"\bбрати\s+{re.escape(name)}\b",
                f"брат {name}",
                out,
                flags=re.I,
            )
        out = re.sub(r"\bБрати\b", "Брат", out)
        out = re.sub(
            r"(?:^|[.!?]\s+)брати\b",
            lambda m: m.group(0).replace("брати", "брат"),
            out,
            flags=re.I,
        )
    return out


def apply_zh_brother_title_fix(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """
    「某某弟兄」= 一位弟兄（教会称谓），非复数 братья。
    规则同 apply_zh_sister_title_fix。
    """
    if not slavic_idiom_fix_enabled() or not source_text or not target_text:
        return target_text
    src = source_text.strip()
    if not _zh_brother_title_singular_context(src):
        return target_text
    code = (target_lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return target_text

    name_zh = _name_for_brother_title(src)
    name_slavic = _zh_name_to_slavic(name_zh, code)
    out = target_text

    if _zh_person_description_clause(src) and name_slavic:
        rule = _match_person_trait_rule(src)
        if rule and _target_has_person_trait_stem(out, rule, code):
            pass
        elif _source_has_person_trait(src) or _target_person_trait_mismatch(
            src, out, code
        ):
            phrase = _person_trait_target_phrase(src, code)
            return f"Брат {name_slavic} — {phrase}."

    if _zh_singular_person_clause(src) and (
        _target_brother_title_plural_error(src, out) or name_slavic
    ):
        if code == "ru":
            if name_slavic:
                phrase = _person_trait_target_phrase(src, code)
                return f"Брат {name_slavic} — {phrase}."
            adj = _positive_person_adj_ru(src)
            human = "человек"
            out = re.sub(
                r"позитивные\s+люди",
                f"{adj} {human}",
                out,
                flags=re.I,
            )
            out = re.sub(
                r"позитивных\s+людей",
                f"{adj} {human}",
                out,
                flags=re.I,
            )
        else:
            if name_slavic:
                phrase = _person_trait_target_phrase(src, code)
                return f"Брат {name_slavic} — {phrase}."
            adj = _positive_person_adj_uk(src)
            human = "людина"
            out = re.sub(
                r"позитивні\s+люди",
                f"{adj} {human}",
                out,
                flags=re.I,
            )

    if _target_has_church_brother_plural(out, code, name_slavic=name_slavic):
        out = _fix_church_brother_plural_forms(out, code, name_slavic=name_slavic)

    if name_slavic and name_zh in src:
        title = f"Брат {name_slavic}"
        if title.lower() not in out.lower():
            for bad in (
                f"Братья {name_slavic}",
                f"братья {name_slavic}",
                f"Брати {name_slavic}",
                f"брати {name_slavic}",
            ):
                if bad.lower() in out.lower():
                    out = _case_insensitive_replace(out, bad, title)
                    break

    out = _fix_person_trait_with_human(src, out, code)
    return out


def _target_church_member_title_plural_error(
    source_text: str, target_text: str
) -> bool:
    return _target_sister_title_plural_error(
        source_text, target_text
    ) or _target_brother_title_plural_error(source_text, target_text)


def apply_zh_church_member_title_fix(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """教会称谓「姊妹」「弟兄」单数修补（入口）。"""
    t = apply_zh_sister_title_fix(source_text, target_text, target_lang)
    return apply_zh_brother_title_fix(source_text, t, target_lang)


def _degenerate_direct_speech_ru(text: str) -> bool:
    low = (text or "").lower()
    return low.count("говорит") >= 2 and "прям" in low and not re.search(
        r"чувств|настроен|пережив", low
    )


def _degenerate_repetitive_ru(text: str) -> bool:
    """如：Она говорит прямо, ей говорит прямо."""
    low = (text or "").lower()
    if low.count("говорит") < 2:
        return False
    if not re.search(r"говорит\s+прям", low):
        return False
    parts = [p.strip() for p in re.split(r"[,;]", text) if p.strip()]
    if len(parts) < 2:
        return False
    a, b = parts[0].lower(), parts[1].lower()
    return "говорит" in a and "говорит" in b and "прям" in a and "прям" in b


def _degenerate_repetitive_speech(text: str, lang: str) -> bool:
    """口语直译重复（俄/乌）：говорит прямо, … говорит прямо。"""
    code = (lang or "").strip().lower()
    if code == "uk":
        low = (text or "").lower()
        if low.count("говорить") < 2 and low.count("говорит") < 2:
            return False
        if not re.search(r"говорит\w*\s+прям|прямолінійн", low):
            return False
        parts = [p.strip() for p in re.split(r"[,;]", text) if p.strip()]
        if len(parts) < 2:
            return False
        a, b = parts[0].lower(), parts[1].lower()
        return ("говор" in a and "говор" in b and "прям" in a and "прям" in b)
    return _degenerate_repetitive_ru(text)


def _degenerate_direct_speech(text: str, lang: str) -> bool:
    code = (lang or "").strip().lower()
    low = (text or "").lower()
    if code == "uk":
        hits = low.count("говорить") + low.count("говорит")
        return hits >= 2 and "прям" in low and not re.search(
            r"почутт|настрій|відчутт|чувств|настроен|пережив",
            low,
        )
    return _degenerate_direct_speech_ru(text)


def _target_has_qualities_work_semantics(low: str, lang: str = "ru") -> bool:
    code = (lang or "").strip().lower()
    if code == "uk":
        return bool(
            re.search(
                r"якост|кваліф|здатн|працездат|професійн|компетент",
                low,
            )
        )
    return bool(
        re.search(
            r"качеств|квалиф|способн|работоспособ|профессион|компетент",
            low,
        )
    )


def target_qualities_work_translation_bad(
    source_text: str, target_text: str
) -> bool:
    """「素质…工作能力」被误译成「比工作好」类字面句。"""
    src = (source_text or "").strip()
    if "素质" not in src:
        return False
    if not (
        "工作能力" in src
        or "办事能力" in src
        or ("工作" in src and "能力" in src)
    ):
        return False
    code = "uk" if re.search(r"[іїєґ]", target_text or "", re.I) else "ru"
    low = (target_text or "").lower()
    if _target_has_qualities_work_semantics(low, code):
        return False
    if code == "uk":
        if re.search(r"краще.{0,24}робот|ніж\s+робот", low):
            return True
        if "робот" in low and "краще" in low:
            return True
        return False
    if re.search(r"лучше.{0,20}работ|чем\s+работ", low):
        return True
    if "работа" in low and "лучше" in low:
        return True
    return False


def apply_zh_qualities_work_repairs(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """「素质比较好，有工作能力」→ 素质与办事能力，非「比工作好」。"""
    if not slavic_idiom_fix_enabled() or not source_text or not target_text:
        return target_text
    src = source_text.strip()
    code = (target_lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return target_text
    if not target_qualities_work_translation_bad(src, target_text):
        return target_text
    if code == "ru":
        if "她" in src:
            return (
                "У неё хорошие личные качества, она работоспособна "
                "и умеет работать."
            )
        if "他" in src:
            return (
                "У него хорошие личные качества, он работоспособен "
                "и умеет работать."
            )
        return (
            "Хорошие личные качества, работоспособность "
            "и умение работать."
        )
    if "她" in src:
        return (
            "У неї хороші особисті якості, вона працездатна "
            "і вміє працювати."
        )
    if "他" in src:
        return (
            "У нього хороші особисті якості, він працездатний "
            "і вміє працювати."
        )
    return (
        "Хороші особисті якості, працездатність і вміння працювати."
    )


def _apply_zh_household_vocab_repairs(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """日常家居词汇：窗帘≠窗户；厚窗帘用 плотные шторы，不用 толстое окно。"""
    src = (source_text or "").strip()
    t = target_text or ""
    code = (target_lang or "").strip().lower()
    if not src or not t or code not in ("ru", "uk"):
        return t
    if "窗帘" not in src:
        return t
    thick = "更厚" in src or "厚一点" in src or "厚些" in src or "厚些" in src
    bad_window = re.search(r"(?i)окн|вікн", t)
    bad_thick = re.search(r"(?i)толст|товст", t)
    bad_curtain = bad_window or (thick and bad_thick)
    if not bad_curtain:
        return t
    if code == "ru":
        if thick and ("有没有" in src or re.search(r"有.+?窗帘", src)):
            return "Есть ли более плотные шторы?"
        t = re.sub(r"(?i)окн\w+", "шторы", t)
        if thick:
            t = re.sub(r"(?i)более\s+толст\w+", "более плотные", t)
            t = re.sub(r"(?i)\bтолст\w+\b", "плотные", t)
        return t
    if thick and ("有没有" in src or re.search(r"有.+?窗帘", src)):
        return "Чи є більш щільні штори?"
    t = re.sub(r"(?i)вікн\w+", "штори", t)
    if thick:
        t = re.sub(r"(?i)більш\s+товст\w+", "більш щільні", t)
        t = re.sub(r"(?i)\bтовст\w+\b", "щільні", t)
    return t


def _apply_zh_colloquial_mt_repairs(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """口语机翻常见硬错：觉得/语气/自然/夸张等场景的 calque 修补。"""
    src = (source_text or "").strip()
    t = target_text or ""
    code = (target_lang or "").strip().lower()
    if not src or not t or code not in ("ru", "uk"):
        return t
    if code == "ru":
        if ("这一遍" in src or "这一次" in src) and re.search(
            r"(?i)\bты\s+говоришь\s+вс[её]\s+это\b", t
        ):
            t = re.sub(
                r"(?i)\bты\s+говоришь\s+вс[её]\s+это\b",
                "на этот раз",
                t,
                count=1,
            )
        if "自然" in src:
            t = re.sub(
                r"(?i)в\s+разговоре,\s*естественно,\s*что\s+речь\s+"
                r"(?:идёт|идет)\s+о\s+чём-то|о\s+чем-то",
                "речь звучит естественнее",
                t,
                count=1,
            )
            t = re.sub(
                r"(?i)в\s+разговоре,\s*естественно,\s*что\s+речь\s+звучит",
                "речь звучит",
                t,
                count=1,
            )
            t = re.sub(
                r"(?i)\bречь\s+(?:идёт|идет)\s+речь\s+звучит",
                "речь звучит",
                t,
                count=1,
            )
        if ("刻意" in src or "夸张" in src) and re.search(
            r"(?i)мудр\w+\s+преувелич", t
        ):
            t = re.sub(
                r"(?i)(?:без\s+(?:столь\s+|такой\s+)?|столь\s+|такого\s+)?"
                r"мудр\w+\s+преувелич\w*",
                "без такой намеренно преувеличенной интонации",
                t,
                count=1,
            )
        t = re.sub(r"(?i),\s*и\s+мне\s+кажется\b", ", мне кажется", t)
    elif code == "uk":
        if ("这一遍" in src or "这一次" in src) and re.search(
            r"(?i)\bти\s+говориш\s+ус[еі]\s+це\b", t
        ):
            t = re.sub(
                r"(?i)\bти\s+говориш\s+ус[еі]\s+це\b",
                "цього разу",
                t,
                count=1,
            )
        if "自然" in src:
            t = re.sub(
                r"(?i)у\s+розмові,\s*природно,\s*що\s+мова\s+"
                r"(?:йдеться|іде)\s+про",
                "мова звучить природніше",
                t,
                count=1,
            )
            t = re.sub(
                r"(?i)у\s+розмові,\s*природно,\s*що\s+мова\s+звучить",
                "мова звучить",
                t,
                count=1,
            )
            t = re.sub(
                r"(?i)\bмова\s+(?:йдеться|іде)\s+мова\s+звучить",
                "мова звучить",
                t,
                count=1,
            )
        if ("刻意" in src or "夸张" in src) and re.search(
            r"(?i)мудр\w+\s+перебільш", t
        ):
            t = re.sub(
                r"(?i)(?:без\s+(?:такої\s+|такого\s+)?|такої\s+|такого\s+)?"
                r"мудр\w+\s+перебільш\w*",
                "без такої навмисно перебільшення інтонації",
                t,
                count=1,
            )
        t = re.sub(r"(?i),\s*і\s+мені\s+здається\b", ", мені здається", t)
    return t


def apply_zh_colloquial_sentence_repairs(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """口语整句修补：如「说话直接 + 把心情说出来」被译成重复「говорит прямо」。"""
    if not slavic_idiom_fix_enabled() or not source_text or not target_text:
        return target_text
    t = _apply_zh_household_vocab_repairs(source_text, target_text, target_lang)
    t = _apply_zh_colloquial_mt_repairs(source_text, t, target_lang)
    src = source_text.strip()
    code = (target_lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return t
    if "心情" not in src or not ("说出来" in src or "说出" in src):
        return t
    low = t.lower()
    missing_emotion = not re.search(r"чувств|настроен|пережив|почутт", low)
    bad_repeat = _degenerate_direct_speech(target_text, code)
    bad_partial = missing_emotion and bool(
        re.search(r"говорит\s+прям|прямолинейн", low)
    )
    if not (bad_repeat or bad_partial):
        return t
    if code == "ru":
        if "她" in src:
            return (
                "Она говорит прямолинейно и открыто высказывает свои чувства."
            )
        if "他" in src:
            return (
                "Он говорит прямолинейно и открыто высказывает свои чувства."
            )
        return (
            "Говорит прямолинейно и открыто высказывает свои чувства."
        )
    if "她" in src:
        return (
            "Вона говорить прямолінійно і відкрито висловлює свої почуття."
        )
    if "他" in src:
        return (
            "Він говорить прямолінійно і відкрито висловлює свої почуття."
        )
    return "Говорить прямолінійно і відкрито висловлює свої почуття."


def apply_idiom_fixes(
    target_text: str,
    lang: str,
    *,
    source_text: str | None = None,
    source_lang: str | None = None,
) -> str:
    """成语/搭配修补入口。"""
    if not target_text or _GLOSSA_SKIP.search(target_text):
        return target_text
    t = apply_target_collocation_fixes(target_text, lang)
    src_lang = (source_lang or "").strip().lower()
    if source_text and src_lang in ("zh", "zt", "cn"):
        try:
            from zh_to_slavic_enhance import apply_diplomatic_news_calques

            t = apply_diplomatic_news_calques(source_text, t, lang)
        except ImportError:
            pass
        try:
            from news_style_rerank import apply_style_rerank
            from native_fluency_config import detect_domain

            t = apply_style_rerank(
                source_text,
                t,
                lang,
                domain=detect_domain(source_text),
            )
        except ImportError:
            pass
        t = apply_zh_name_transliteration_fix(source_text, t, lang)
        t = apply_zh_predicative_copula_repairs(source_text, t, lang)
        t = _apply_zh_colloquial_mt_repairs(source_text, t, lang)
        t = apply_zh_person_trait_repairs(source_text, t, lang)
        t = apply_zh_church_member_title_fix(source_text, t, lang)
        t = apply_zh_qualities_work_repairs(source_text, t, lang)
        t = apply_zh_colloquial_sentence_repairs(source_text, t, lang)
        t = apply_zh_source_idiom_hints(source_text, t, lang)
        t = _apply_zh_colloquial_mt_repairs(source_text, t, lang)
        t = apply_zh_colloquial_sentence_repairs(source_text, t, lang)
        t = apply_zh_predicative_copula_repairs(source_text, t, lang)
        t = apply_zh_person_trait_repairs(source_text, t, lang)
        t = apply_zh_qualities_work_repairs(source_text, t, lang)
        t = apply_zh_church_member_title_fix(source_text, t, lang)
        t = apply_zh_name_transliteration_fix(source_text, t, lang)
        t = apply_zh_predicative_copula_repairs(source_text, t, lang)
        t = apply_zh_person_trait_repairs(source_text, t, lang)
        t = apply_target_collocation_fixes(t, lang)
    return t


# 兼容旧测试：显式清缓存
def _collocations() -> dict:
    return _load_json("collocations_slavic.json")
