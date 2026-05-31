"""
变格表展示：中文统一为简体；单元格仅保留西里尔字母词形（去掉拉丁转写）。
pymorphy2 标签串 → 中文语法说明（避免整行英文缩写）。
"""
from __future__ import annotations

import re

# OpenCorpora 常见语素 → 简体中文（不全时回退为缩写）
_GRAM_ZH: dict[str, str] = {
    # POS
    "NOUN": "名词",
    "VERB": "动词",
    "INFN": "不定式",
    "ADJF": "形容词",
    "ADJS": "形容词短尾",
    "COMP": "比较级",
    "PRTF": "形动词",
    "PRTS": "短尾形动词",
    "NUMR": "数词",
    "ADVB": "副词",
    "NPRO": "代词",
    "PREP": "前置词",
    "CONJ": "连词",
    "PRCL": "语气词",
    "INTJ": "感叹词",
    "GRND": "副动词",
    "PRED": "谓词副词",
    # Number / Case
    "sing": "单数",
    "plur": "复数",
    "nomn": "主格",
    "gent": "属格",
    "datv": "与格",
    "accs": "宾格",
    "ablt": "工具格",
    "loct": "方位格",
    "voct": "呼格",
    "gen2": "第二属格",
    "acc2": "第二宾格",
    "loc2": "第二方位格",
    # Gender / animacy
    "masc": "阳性",
    "femn": "阴性",
    "neut": "中性",
    "ms-f": "共性",
    "anim": "有生命",
    "inan": "无生命",
    # Verb / participle
    "perf": "完成体",
    "impf": "未完成体",
    "tran": "及物",
    "intr": "不及物",
    "pres": "现在时",
    "past": "过去时",
    "futr": "将来时",
    "indc": "直陈式",
    "impr": "命令式",
    "cond": "条件式",
    "1per": "第一人称",
    "2per": "第二人称",
    "3per": "第三人称",
    "actv": "主动",
    "pssv": "被动",
    "incl": "包括式",
    "excl": "排除式",
    "Auxt": "辅助",
    "Infr": "口语",
    "Slng": "俚语",
    "Arch": "古语",
    "Dist": "疏远",
    "V-be": "系动词",
    "Sgtm": "单件",
    "Pltm": "复件",
}


def to_zh_cn(text: str) -> str:
    if not text:
        return ""
    try:
        import zhconv

        return zhconv.convert(text, "zh-cn")
    except Exception:
        return text


_CJK_IN_TEXT = re.compile(r"[\u4e00-\u9fff]")
_CYR_IN_TEXT = re.compile(r"[\u0400-\u04FF]")
# 汉语维基「俄语」节释义行里常见的拉丁转写括号，如 ( pojéstʹ )；不含西里尔与汉字。
_TRANSCRIPTION_PAREN_CHARS = re.compile(
    r"^[\s0-9A-Za-z'.,\-/ˈːˑʹʺ·"
    r"\u00C0-\u024F"
    r"\u0250-\u02AF"
    r"\u02B0-\u02FF"
    r"\u0300-\u036F"
    r"\u1E00-\u1EFF"
    r"]+$",
    re.UNICODE,
)


def strip_wiktionary_latin_transliteration_parens(text: str) -> str:
    """
    去掉释义行中「仅拉丁转写 / IPA 风格」的半角或全角括号片段。
    保留含西里尔字母或汉字的括号（如配对体说明）。
    """
    if not text:
        return ""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "(（":
            close = ")" if ch == "(" else "）"
            j = text.find(close, i + 1)
            if j == -1:
                out.append(text[i:])
                break
            inner = text[i + 1 : j]
            if _wiktionary_paren_is_latin_transliteration_only(inner):
                if out and out[-1] and (not out[-1].endswith((" ", "\t"))):
                    out.append(" ")
                i = j + 1
                while i < n and text[i] in " \t":
                    i += 1
                continue
            out.append(text[i : j + 1])
            i = j + 1
            continue
        out.append(ch)
        i += 1
    s = "".join(out)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^\s*•\s*", "", s)
    return s.strip()


def _wiktionary_paren_is_latin_transliteration_only(inner: str) -> bool:
    t = inner.strip()
    if len(t) < 2:
        return False
    if _CYR_IN_TEXT.search(t) or _CJK_IN_TEXT.search(t):
        return False
    if "." in t:
        return False
    if len(re.findall(r"[A-Za-z]", t)) < 5:
        return False
    return bool(_TRANSCRIPTION_PAREN_CHARS.match(t))


_RU_UK_TOKEN = re.compile(
    r"[А-Яа-яЁёІіЇЄҐґ]+(?:\u0301|\u0300|\u030f)?"
    r"(?:-[А-Яа-яЁёІіЇЄҐґ]+(?:\u0301|\u0300|\u030f)?)*"
)


def uk_cell_display(cell: str) -> str:
    """乌克兰语变格单元格：保留重音符号，逗号分隔多形式。"""
    s = (cell or "").strip()
    if not s:
        return ""
    parts = re.split(r"\s*,\s*", s)
    out: list[str] = []
    for p in parts:
        tokens = _RU_UK_TOKEN.findall(p)
        if tokens:
            out.append(", ".join(tokens))
        else:
            t = to_zh_cn(p)
            if t and _CYR_IN_TEXT.search(t):
                out.append(t)
    return ", ".join(out) if out else to_zh_cn(s)


def declension_cell_display(cell: str) -> str:
    """
    变格表单元格：先转简体；若含俄语/乌克兰语西里尔词形则只保留这些词（去掉拉丁转写等）。
    纯中文表头则只保留简体字；纯拉丁转写格则置空。
    """
    s = to_zh_cn((cell or "").strip())
    if re.search(r"[\u0400-\u04FF]", s):
        return uk_cell_display(cell)
    tokens = _RU_UK_TOKEN.findall(s)
    if tokens:
        return " ".join(tokens)
    s2 = re.sub(
        r"[A-Za-záéíóúěščřžňťďĺľýÁÉÍÓÚÝĚŠČŘŽŇŤĎĹĽ\.\'´`\-]+",
        "",
        s,
    )
    s2 = re.sub(r"\s+", " ", s2).strip()
    return s2


def opencorpora_tag_string_to_zh(tag_str: str) -> str:
    """将 pymorphy2 打印的标签串转为中文说明（逗号/空格切分语素）。"""
    if not tag_str:
        return ""
    parts = re.split(r"[\s,]+", tag_str.strip())
    seen: list[str] = []
    for p in parts:
        if not p:
            continue
        zh = _GRAM_ZH.get(p)
        if zh is None:
            if len(p) <= 4 and p.isascii() and p.isalpha():
                zh = f"〔{p}〕"
            else:
                zh = p
        if zh not in seen:
            seen.append(zh)
    return "，".join(seen) if seen else tag_str
