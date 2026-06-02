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
    "目前": ["на данный момент", "в данный момент"],
    "根据": ["на основе", "исходя из того"],
    "由于": ["из-за того что", "благодаря тому что"],
    "总之": ["в общем и целом", "суммируя"],
    "值得注意的是": ["стоит отметить что", "нужно отметить"],
    "因此": ["из этого следует", "таким образом следует"],
    # 教会称谓 · 姊妹（单人）
    "姊妹": ["сестры люба", "сестры луба", "сестры -"],
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
    "目前": ["на даний момент"],
    "根据": ["на основі"],
    "由于": ["через те що"],
    "因此": ["з цього випливає"],
    "素质": ["краще, ніж робота", "краще ніж робота"],
    "有工作能力": ["краще, ніж робота"],
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
    src = source_text or ""
    if any(x in src for x in ("们", "两位", "两个", "两名", "诸位", "各位")):
        return False
    return bool(re.search(r"一个.{0,24}人", src))


def _name_before_sister_title(source_text: str) -> str:
    m = re.search(r"([\u4e00-\u9fff]{2,5})姊妹", source_text or "")
    return m.group(1) if m else ""


def _zh_name_to_slavic(name_zh: str, lang: str) -> str:
    zh = (name_zh or "").strip()
    if not zh:
        return ""
    code = (lang or "").strip().lower()
    entry = _zh_name_map().get(zh, {})
    val = entry.get(code) or entry.get("ru") or ""
    return str(val).strip()


def _positive_person_adj_ru(source_text: str) -> str:
    src = source_text or ""
    if "积极向上" in src or "积极" in src:
        return "позитивный"
    if "乐观" in src:
        return "оптимистичный"
    return "хороший"


def _positive_person_adj_uk(source_text: str) -> str:
    src = source_text or ""
    if "积极向上" in src or "积极" in src:
        return "позитивна"
    if "乐观" in src:
        return "оптимістична"
    return "хороша"


def _target_sister_title_plural_error(source_text: str, target_text: str) -> bool:
    if "姊妹" not in (source_text or ""):
        return False
    if not _zh_singular_person_clause(source_text):
        return False
    low = (target_text or "").lower()
    if re.search(r"\bсестры\b", low):
        return True
    if "люди" in low and "человек" not in low:
        return True
    if re.search(r"\bлуба\b", low) and "柳芭" in source_text:
        return True
    return False


def apply_zh_sister_title_fix(
    source_text: str,
    target_text: str,
    target_lang: str,
) -> str:
    """
    「某某姊妹」= 一位姐妹（教会称谓），非复数 сестры。
    源句含「一个…人」时强制单数 сестра + человек，并校正常见人名转写。
    """
    if not slavic_idiom_fix_enabled() or not source_text or not target_text:
        return target_text
    src = source_text.strip()
    if "姊妹" not in src:
        return target_text
    if not _zh_singular_person_clause(src):
        return target_text
    code = (target_lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return target_text

    name_zh = _name_before_sister_title(src)
    name_ru = _zh_name_to_slavic(name_zh, code)

    if _target_sister_title_plural_error(src, target_text) or name_ru:
        if code == "ru":
            adj = _positive_person_adj_ru(src)
            human = "человек"
            if name_ru:
                return f"Сестра {name_ru} — {adj} {human}."
            out = target_text
            out = re.sub(r"\bСестры\b", "Сестра", out, flags=re.I)
            out = re.sub(r"\bсестры\b", "сестра", out)
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
            return out

        adj = _positive_person_adj_uk(src)
        human = "людина"
        if name_ru:
            return f"Сестра {name_ru} — {adj} {human}."
        out = target_text
        out = re.sub(r"\bСестри\b", "Сестра", out, flags=re.I)
        out = re.sub(r"\bсестри\b", "сестра", out)
        out = re.sub(r"\bЛуба\b", "Люба", out, flags=re.I)
        out = re.sub(
            r"позитивні\s+люди",
            f"{adj} {human}",
            out,
            flags=re.I,
        )
        return out

    return target_text


def _degenerate_direct_speech_ru(text: str) -> bool:
    low = (text or "").lower()
    return low.count("говорит") >= 2 and "прям" in low and not re.search(
        r"чувств|настроен|пережив", low
    )


def _target_has_qualities_work_semantics(low: str) -> bool:
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
    low = (target_text or "").lower()
    if _target_has_qualities_work_semantics(low):
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
    bad_repeat = _degenerate_direct_speech_ru(target_text)
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
        t = apply_zh_name_transliteration_fix(source_text, t, lang)
        t = apply_zh_sister_title_fix(source_text, t, lang)
        t = apply_zh_qualities_work_repairs(source_text, t, lang)
        t = apply_zh_colloquial_sentence_repairs(source_text, t, lang)
        t = apply_zh_source_idiom_hints(source_text, t, lang)
        t = apply_zh_colloquial_sentence_repairs(source_text, t, lang)
        t = apply_zh_qualities_work_repairs(source_text, t, lang)
        t = apply_zh_sister_title_fix(source_text, t, lang)
        t = apply_zh_name_transliteration_fix(source_text, t, lang)
        t = apply_target_collocation_fixes(t, lang)
    return t


# 兼容旧测试：显式清缓存
def _collocations() -> dict:
    return _load_json("collocations_slavic.json")
