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
    "牧师": ["священнослужитель"],
    "圣母": ["дева мария"],
    "领圣餐": ["принимать communion"],
    "主祷文": ["молитва отца нашего"],
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
        t = apply_zh_source_idiom_hints(source_text, t, lang)
        t = apply_target_collocation_fixes(t, lang)
    return t


# 兼容旧测试：显式清缓存
def _collocations() -> dict:
    return _load_json("collocations_slavic.json")
