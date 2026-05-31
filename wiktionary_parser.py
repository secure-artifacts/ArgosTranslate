"""
俄语词形：pymorphy2 词干 + 汉语维基「俄语」节（中文释义转大陆简体、带中文表头的表格）
+ 俄语维基「Русский」节表格；抓取时过滤「同根词总表」等非变位内容。俄语维基词条 HTML 中解析重音（{{по-слогам|…}}、词形表单元格等），供查词「单词解析」展示。
汉语 / 俄语 / 英语 / 西班牙语维基词条页并行请求以缩短等待；未命中磁盘缓存时可选节流环境变量 ARGOS_WIKI_THROTTLE_SEC（默认 0）。
查词「单词解析」义项摘录优先使用英语与西班牙语维基「俄语」节拉丁字母释义行，避免汉语节中的词源段落混入释义。
乌克兰语：先 uk→ru，再查 bkrs.info 中文义项（与俄语查词相同）；变位表用 goroh.pp.ua；
汉语/俄语维基作备用。
Горох 与双站维基在未命中缓存时并行请求。俄语维基乌克兰语人工索引见 RU_WIKT_UKRAINIAN_INDEX_URL。
"""
from __future__ import annotations

from html import unescape
import json
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote as url_unquote

import requests
from bs4 import BeautifulSoup, Tag

import glossary_manager as gm
from terminology_bridge import portable_root


RU_WIKI_MAIN = (
    "https://ru.wiktionary.org/wiki/"
    "%D0%92%D0%B8%D0%BA%D0%B8%D1%81%D0%BB%D0%BE%D0%B2%D0%B0%D1%80%D1%8C:"
    "%D0%97%D0%B0%D0%B3%D0%BB%D0%B0%D0%B2%D0%BD%D0%B0%D1%8F_%D1%81%D1%82%D1%80%D0%B0%D0%BD%D0%B8%D1%86%D0%B0"
)
# 俄语维基词典：乌克兰语词条人工索引（总目录，非单个词义）。
RU_WIKT_UKRAINIAN_INDEX_URL = (
    "https://ru.wiktionary.org/wiki/"
    "%D0%98%D0%BD%D0%B4%D0%B5%D0%BA%D1%81:%D0%A3%D0%BA%D1%80%D0%B0%D0%B8%D0%BD%D1%81%D0%BA%D0%B8%D0%B9_%D1%8F%D0%B7%D1%8B%D0%BA"
)
# 与浏览器地址栏一致：Викисловарь:Заглавная_страница（门户页，仅供展示/外链；抓释义走各词条页）。
CACHE_PATH = portable_root() / "data" / "cache" / "wiktionary_lemma_cache_v15.json"
_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": "ArgosTranslateLocalGlossary/1.0 (educational; Python requests)",
        "Accept-Language": "zh-CN,zh;q=0.9,ru;q=0.85,en;q=0.7",
    }
)
_CACHE: dict[str, Any] = {}
_CACHE_LOADED = False


def _ensure_cache() -> None:
    global _CACHE, _CACHE_LOADED
    if _CACHE_LOADED:
        return
    _CACHE_LOADED = True
    if CACHE_PATH.is_file():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                _CACHE = json.load(f)
            if not isinstance(_CACHE, dict):
                _CACHE = {}
        except (json.JSONDecodeError, OSError):
            _CACHE = {}


def _write_cache() -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_CACHE, f, ensure_ascii=False, indent=2)
    tmp.replace(CACHE_PATH)


def _simp_zh_tables(tbls: Any) -> list[list[list[str]]]:
    """表格单元格中的中文统一为大陆简体（俄语词形不受影响）。"""
    try:
        from inflection_display import to_zh_cn
    except ImportError:
        return tbls if isinstance(tbls, list) else []
    if not isinstance(tbls, list):
        return []
    out: list[list[list[str]]] = []
    for tbl in tbls:
        if not isinstance(tbl, list):
            continue
        rows: list[list[str]] = []
        for row in tbl:
            if isinstance(row, list):
                rows.append([to_zh_cn(str(c)) for c in row])
            else:
                rows.append([str(row)])
        if rows:
            out.append(rows)
    return out


def _normalize_wiktionary_zh_fields(d: dict[str, Any]) -> None:
    """就地处理：释义行、各语言变格表中的维基中文 → 简体。"""
    try:
        from inflection_display import strip_wiktionary_latin_transliteration_parens, to_zh_cn
    except ImportError:
        return
    gl = d.get("zh_gloss_lines")
    if isinstance(gl, list):
        d["zh_gloss_lines"] = [
            to_zh_cn(strip_wiktionary_latin_transliteration_parens(str(x))) for x in gl
        ]
    ru_gl = d.get("ru_gloss_lines")
    if isinstance(ru_gl, list):
        d["ru_gloss_lines"] = [
            to_zh_cn(strip_wiktionary_latin_transliteration_parens(str(x))) for x in ru_gl
        ]
    for key in ("zh_html_tables", "ru_html_tables", "html_tables"):
        if key in d:
            d[key] = _simp_zh_tables(d.get(key))
    gt = d.get("goroh_tables")
    if isinstance(gt, list):
        d["goroh_tables"] = _simp_zh_tables(gt)


def _pymorphy2_lexeme(word: str) -> dict[str, Any]:
    try:
        morph = gm.shared_morph_analyzer()
    except Exception:
        morph = None
    if morph is None:
        return {"source": "none", "error": "pymorphy2 未安装", "forms": [], "lemma": word}
    parses = morph.parse(word)
    if not parses:
        return {"source": "pymorphy2", "forms": [], "lemma": word}
    p = gm.pick_morph_parse(parses, word)
    forms = []
    seen = set()
    for lex in p.lexeme:
        w = lex.word
        low = w.lower()
        if low not in seen:
            seen.add(low)
            forms.append({"word": w, "tag": str(lex.tag)})
    return {
        "source": "pymorphy2",
        "lemma": p.normal_form,
        "tag": str(p.tag),
        "forms": forms[:32],
    }


def _wiki_index_url(subdomain: str, title: str) -> str:
    t = title.replace(" ", "_")
    return f"https://{subdomain}.wiktionary.org/wiki/{quote(t, safe='()%')}"


def _fetch_wiki_article_html(subdomain: str, title: str, timeout: float) -> str:
    url = _wiki_index_url(subdomain, title)
    r = _SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def _wiki_throttle_delay() -> None:
    """维基未命中缓存时的可选节流（秒）。默认 0；可设 ARGOS_WIKI_THROTTLE_SEC=0.28 等。"""
    try:
        sec = float((os.environ.get("ARGOS_WIKI_THROTTLE_SEC") or "0").strip())
    except ValueError:
        sec = 0.0
    if sec > 0:
        time.sleep(min(max(sec, 0.0), 2.0))


def _try_fetch_wiki_html(subdomain: str, title: str, timeout: float) -> tuple[str, str | None]:
    try:
        return _fetch_wiki_article_html(subdomain, title, timeout), None
    except Exception as e:
        return "", str(e)


def _parallel_zh_ru_en_es_wiki_fetch(
    lemma: str, timeout: float,
) -> tuple[str, str | None, str, str | None, str, str | None, str, str | None]:
    """并行抓取 zh / ru / en / es 四站维基词条 HTML。"""
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_zh = ex.submit(_try_fetch_wiki_html, "zh", lemma, timeout)
        f_ru = ex.submit(_try_fetch_wiki_html, "ru", lemma, timeout)
        f_en = ex.submit(_try_fetch_wiki_html, "en", lemma, timeout)
        f_es = ex.submit(_try_fetch_wiki_html, "es", lemma, timeout)
    zh_html, zh_err = f_zh.result()
    ru_html, ru_err = f_ru.result()
    en_html, en_err = f_en.result()
    es_html, es_err = f_es.result()
    return zh_html, zh_err, ru_html, ru_err, en_html, en_err, es_html, es_err


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def extract_wiktionary_ipa_brackets(html: str) -> str:
    """
    从汉语/俄语维基词条 HTML 中提取 IPA，返回带方括号的展示串（如 [pʲɪˈtʲet]）。
    仅接受维基常见 IPA 容器（span/abbr 的 IPA 类名），避免误抓正文。
    """
    if not (html or "").strip():
        return ""
    soup = _soup(html)
    ipa_like = re.compile(
        r"[a-zəɪʊɔæɑʌɜθðŋʃʒχɡˈˌːˑʲʹʺ\u02b9\u02bc0-9\s\.\-]",
        re.I,
    )
    candidates: list[str] = []
    for el in soup.find_all(["span", "abbr"]):
        cls = " ".join(el.get("class") or [])
        if not any(p.upper() == "IPA" for p in re.split(r"\s+", cls.strip())):
            continue
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if not t or len(t) > 90:
            continue
        if not ipa_like.search(t):
            continue
        if "http" in t or "wiktionary" in t.lower():
            continue
        candidates.append(t)
    if not candidates:
        return ""
    t0 = candidates[0]
    t0 = t0.strip("[] ")
    if not t0:
        return ""
    if not t0.startswith("["):
        t0 = "[" + t0
    if not t0.endswith("]"):
        t0 = t0 + "]"
    return t0


# --- 俄语重音（维基 HTML：{{по-слогам|…}}、data-mw 中 основа、变位表）---


def ru_strip_stress(s: str) -> str:
    """去掉组合重音符，用于比对词形。"""
    t = unicodedata.normalize("NFC", (s or "").strip())
    for c in ("\u0301", "\u0300", "\u030f"):
        t = t.replace(c, "")
    return t


def ru_stress_key(s: str) -> str:
    """比对键：去重音、连字符（分音节）与 ё→е。"""
    return ru_strip_stress(s).lower().replace("ё", "е").replace("-", "")


# 西里尔词形（含组合重音 U+0301 等；俄语 + 乌克兰语字母）
_CYR_WORD_IN_TEXT = re.compile(
    r"[А-Яа-яЁёІіЇїЄєҐґ]+(?:[\u0301\u0300\u030f]*[А-Яа-яЁёІіЇїЄєҐґ]+)*"
    r"(?:'[А-Яа-яЁёІіЇїЄєҐґ]+(?:[\u0301\u0300\u030f]*[А-Яа-яЁёІіЇїЄєҐґ]+)*)?"
    r"(?:-[А-Яа-яЁёІіЇїЄєҐґ]+(?:[\u0301\u0300\u030f]*[А-Яа-яЁёІіЇїЄєҐґ]+)*)*"
)


def _cyr_letter(c: str) -> bool:
    return "А" <= c <= "я" or c in "ЁёІіЇїЄєҐґ"


def _cyr_word_char(c: str) -> bool:
    if _cyr_letter(c) or c in "-'":
        return True
    return c in "\u0301\u0300\u030f" or ("\u0300" <= c <= "\u036f")


def cyrillic_word_bounds(text: str, pos: int) -> tuple[int, int]:
    """
    在 text 中取包含 pos 的西里尔词 [start, end)，含组合重音与连字符。
    Qt WordUnderCursor 会把 U+0301 拆出词外，导致带重音词无法查词。
    """
    if not text:
        return 0, 0
    n = len(text)
    pos = max(0, min(pos, n - 1))
    for m in _CYR_WORD_IN_TEXT.finditer(text):
        if m.start() <= pos < m.end():
            return m.start(), m.end()
    if not _cyr_word_char(text[pos]):
        for d in range(1, 6):
            if pos - d >= 0 and _cyr_letter(text[pos - d]):
                pos = pos - d
                break
            if pos + d < n and _cyr_letter(text[pos + d]):
                pos = pos + d
                break
        else:
            return pos, pos
    start = pos
    while start > 0 and _cyr_word_char(text[start - 1]):
        start -= 1
    end = pos + 1
    while end < n and _cyr_word_char(text[end]):
        end += 1
    while start < end and not _cyr_letter(text[start]) and text[start] not in "-'":
        start += 1
    while end > start and not _cyr_letter(text[end - 1]) and text[end - 1] not in "-'":
        end -= 1
    if start >= end:
        return pos, pos
    return start, end


def ru_has_stress_mark(s: str) -> bool:
    if not s:
        return False
    if any(c in s for c in ("\u0301", "\u0300", "\u030f")):
        return True
    return any(c in "ёЁ" for c in s)


def _syllabify_po_slogam_parts(parts: list[str]) -> str:
    """{{по-слогам|от|клю|ча́ть}} → от-клю-ча́ть（与 ru.wiktionary 展示一致）。"""
    clean = [p.strip() for p in parts if p.strip()]
    if len(clean) >= 2:
        return "-".join(clean)
    if clean:
        return clean[0]
    return ""


def extract_ru_lemma_stressed_from_html(html: str, lemma: str) -> str:
    """
    从 ru.wiktionary 词条 HTML 提取与 lemma 同形的重读形式（分音节连字符）。
    优先 {{по-слогам|…}}，其次页内 <strong>от-клю-ча́ть</strong>，再其次 «основа»。
    """
    if not (html and lemma):
        return ""
    key = ru_stress_key(lemma)
    raw = unescape(html)
    syllabified: list[str] = []
    plain_stressed: list[str] = []
    for m in re.finditer(r"\{\{\s*по-слогам\s*\|([^}]+)\}\}", raw, re.I | re.DOTALL):
        inner = (m.group(1) or "").strip()
        parts = [p.strip() for p in inner.split("|") if p.strip()]
        if len(parts) < 2:
            continue
        cand_syl = _syllabify_po_slogam_parts(parts)
        cand_plain = "".join(parts)
        if ru_stress_key(cand_plain) != key:
            continue
        if ru_has_stress_mark(cand_syl):
            syllabified.append(cand_syl)
        elif ru_has_stress_mark(cand_plain):
            plain_stressed.append(cand_plain)
    if syllabified:
        return syllabified[0]
    if plain_stressed:
        return plain_stressed[0]

    soup = _soup(html)
    for tag in soup.find_all(["strong", "b"]):
        t = tag.get_text(strip=True)
        if not (2 <= len(t) <= 72 and ru_stress_key(t) == key and ru_has_stress_mark(t)):
            continue
        if "-" in t:
            return t
        plain_stressed.append(t)
    if plain_stressed:
        return plain_stressed[0]

    m = re.search(r'"основа"\s*:\s*\{\s*"wt"\s*:\s*"([^"]+)"', raw)
    if m:
        osn = (m.group(1) or "").strip()
        if osn and ru_has_stress_mark(osn):
            lp = lemma.strip().lower()
            if lp.endswith("ться") and not osn.lower().endswith("ться"):
                cand = osn + "ться"
            else:
                cand = osn
            if ru_stress_key(cand) == key:
                return cand
    return ""


_RU_WIKI_POS_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"\bГлагол\b", re.I), "VERB", "动词"),
    (re.compile(r"\bСуществительное\b", re.I), "NOUN", "名词"),
    (re.compile(r"\bПрилагательное\b", re.I), "ADJF", "形容词"),
    (re.compile(r"\bНаречие\b", re.I), "ADVB", "副词"),
    (re.compile(r"\bМестоимение\b", re.I), "NPRO", "代词"),
    (re.compile(r"\bЧислительное\b", re.I), "NUMR", "数词"),
    (re.compile(r"\bПричастие\b", re.I), "PRTF", "分词"),
    (re.compile(r"\bДеепричастие\b", re.I), "GRND", "副动词"),
    (re.compile(r"\bМеждометие\b", re.I), "INTJ", "感叹词"),
    (re.compile(r"\bПредлог\b", re.I), "PREP", "介词"),
    (re.compile(r"\bСоюз\b", re.I), "CONJ", "连词"),
    (re.compile(r"\bЧастица\b", re.I), "PRCL", "语气词"),
)
_PYMORPHY_POS_RU_ZH: dict[str, tuple[str, str]] = {
    "NOUN": ("Существительное", "名词"),
    "VERB": ("Глагол", "动词"),
    "INFN": ("Глагол", "动词（不定式）"),
    "ADJF": ("Прилагательное", "形容词"),
    "ADJS": ("Краткое прилагательное", "短尾形容词"),
    "COMP": ("Сравнительная степень", "比较级"),
    "PRTF": ("Причастие", "分词"),
    "PRTS": ("Краткое причастие", "短尾分词"),
    "GRND": ("Деепричастие", "副动词"),
    "NUMR": ("Числительное", "数词"),
    "ADVB": ("Наречие", "副词"),
    "NPRO": ("Местоимение", "代词"),
    "PRED": ("Предикатив", "谓词"),
    "PREP": ("Предлог", "介词"),
    "CONJ": ("Союз", "连词"),
    "PRCL": ("Частица", "语气词"),
    "INTJ": ("Междометие", "感叹词"),
}
_PYMORPHY_ASPECT_ZH = {"perf": "完成体", "impf": "未完成体"}
_PYMORPHY_GENDER_ZH = {"masc": "阳性", "femn": "阴性", "neut": "中性"}
_PYMORPHY_ANIM_ZH = {"anim": "有生命", "inan": "无生命"}
_RU_WIKI_PAIR_RE = re.compile(
    r"Соответствующ(?:ий|ая)\s+"
    r"(?:глагол|форма)?\s*"
    r"(несовершенного|совершенного)\s+вида\s*[—–\-:]\s*"
    r"([А-Яа-яЁё][А-Яа-яЁё\-]*)",
    re.I,
)
_RU_WIKI_VERB_ASPECT_RE = re.compile(
    r"(совершенный|несовершенный)\s+вид", re.I
)


def extract_ru_wiki_morph_from_html(html: str) -> dict[str, Any]:
    """
    解析 ru.wiktionary「Морфологические и синтаксические свойства」首段语法行。
    例：Глагол, совершенный вид, переходный … — 4b. … отключать.
    """
    empty: dict[str, Any] = {
        "line_ru": "",
        "pos": "",
        "pos_ru": "",
        "pos_zh": "",
        "aspect": "",
        "aspect_ru": "",
        "aspect_zh": "",
        "transitivity_ru": "",
        "transitivity_zh": "",
        "gender_ru": "",
        "gender_zh": "",
        "animacy_ru": "",
        "animacy_zh": "",
        "decl_class": "",
        "conj_class": "",
        "pair_lemma": "",
        "pair_aspect": "",
        "pair_aspect_zh": "",
        "source": "",
    }
    if not (html or "").strip():
        return empty

    morph_text = ""
    soup = _soup(html)
    for h in soup.find_all(["h3", "h4"]):
        ht = h.get_text(" ", strip=True).lower()
        if "морфологическ" not in ht:
            continue
        for sib in h.find_next_siblings():
            if getattr(sib, "name", None) in ("h2", "h3", "h4"):
                break
            t = sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else ""
            if len(t) < 10:
                continue
            if any(pat.search(t) for pat, _, _ in _RU_WIKI_POS_PATTERNS):
                morph_text = t
                break
        if morph_text:
            break

    if not morph_text:
        for tag in soup.find_all(["p", "li", "div"]):
            t = tag.get_text(" ", strip=True)
            if len(t) < 12 or len(t) > 900:
                continue
            if any(pat.search(t) for pat, _, _ in _RU_WIKI_POS_PATTERNS):
                morph_text = t
                break

    if not morph_text:
        return empty

    out = dict(empty)
    out["source"] = "ru.wiktionary"
    out["line_ru"] = morph_text[:600]
    main = morph_text.split(".")[0] if "." in morph_text else morph_text

    for pat, pos_code, pos_zh in _RU_WIKI_POS_PATTERNS:
        m_pos = pat.search(main)
        if m_pos:
            out["pos"] = pos_code
            out["pos_ru"] = m_pos.group(0)
            out["pos_zh"] = pos_zh
            break

    if re.search(r"мужской\s+род", main, re.I):
        out["gender_ru"] = "мужской род"
        out["gender_zh"] = "阳性"
    elif re.search(r"женский\s+род", main, re.I):
        out["gender_ru"] = "женский род"
        out["gender_zh"] = "阴性"
    elif re.search(r"средний\s+род", main, re.I):
        out["gender_ru"] = "средний род"
        out["gender_zh"] = "中性"

    if re.search(r"\bпереходный\b", main, re.I) and not re.search(
        r"\bнепереходный\b", main, re.I
    ):
        out["transitivity_ru"] = "переходный"
        out["transitivity_zh"] = "及物"
    elif re.search(r"\bнепереходный\b", main, re.I):
        out["transitivity_ru"] = "непереходный"
        out["transitivity_zh"] = "不及物"

    if re.search(r"неодушевл", main, re.I):
        out["animacy_ru"] = "неодушевлённое"
        out["animacy_zh"] = "无生命"
    elif re.search(r"одушевл", main, re.I):
        out["animacy_ru"] = "одушевлённое"
        out["animacy_zh"] = "有生命"

    dm = re.search(
        r"склонен(?:ия|ие).*?Зализняка\s*[—–\-:]\s*([\da-z]+[a-z]?)\b",
        morph_text,
        re.I,
    )
    if dm:
        out["decl_class"] = dm.group(1)

    am = _RU_WIKI_VERB_ASPECT_RE.search(main)
    if am:
        ar = am.group(1).lower()
        out["aspect_ru"] = am.group(0)
        if ar.startswith("соверш"):
            out["aspect"] = "perf"
            out["aspect_zh"] = "完成体"
        else:
            out["aspect"] = "impf"
            out["aspect_zh"] = "未完成体"

    cm = re.search(
        r"Зализняка\s*[—–\-:]\s*([\da-z]+[a-z]?)\b", morph_text, re.I
    )
    if cm:
        out["conj_class"] = cm.group(1)

    pm = _RU_WIKI_PAIR_RE.search(morph_text)
    if pm:
        pair_ar = pm.group(1).lower()
        out["pair_lemma"] = pm.group(2).strip()
        if pair_ar.startswith("несоверш"):
            out["pair_aspect"] = "impf"
            out["pair_aspect_zh"] = "未完成体"
        else:
            out["pair_aspect"] = "perf"
            out["pair_aspect_zh"] = "完成体"

    return out


def format_ru_wiki_grammar_lines(grammar: dict[str, Any] | None) -> list[str]:
    """中文语法行列表：词性（含俄语名）+ 体/性/及物等。"""
    g = grammar if isinstance(grammar, dict) else {}
    lines: list[str] = []
    pos = (g.get("pos") or "").strip()
    pos_zh = (g.get("pos_zh") or "").strip()
    pos_ru = (g.get("pos_ru") or "").strip()
    if pos_zh:
        if pos_ru:
            lines.append(f"词性：{pos_zh}（{pos_ru}）")
        else:
            lines.append(f"词性：{pos_zh}")
    aspect_zh = (g.get("aspect_zh") or "").strip()
    if aspect_zh and pos in ("VERB", "INFN", "PRTF", "PRTS", "GRND"):
        lines.append(f"体：{aspect_zh}")
    if g.get("transitivity_zh"):
        lines.append(f"及物性：{g['transitivity_zh']}")
    if g.get("gender_zh"):
        lines.append(f"性：{g['gender_zh']}")
    if g.get("animacy_zh"):
        lines.append(f"生命性：{g['animacy_zh']}")
    if g.get("decl_class"):
        lines.append(f"变格类型：{g['decl_class']}")
    if g.get("conj_class"):
        lines.append(f"变位类型：{g['conj_class']}")
    if not lines and aspect_zh:
        lines.append(f"体：{aspect_zh}")
    return lines


def format_ru_wiki_grammar_zh(grammar: dict[str, Any] | None) -> str:
    return "<br/>".join(format_ru_wiki_grammar_lines(grammar))


def format_ru_wiki_grammar_plain_zh(grammar: dict[str, Any] | None) -> str:
    """单行摘要（胶囊标签等）。"""
    g = grammar if isinstance(grammar, dict) else {}
    bits: list[str] = []
    pos_zh = (g.get("pos_zh") or "").strip()
    if pos_zh:
        bits.append(pos_zh)
    if g.get("aspect_zh"):
        bits.append(str(g["aspect_zh"]))
    if g.get("gender_zh"):
        bits.append(str(g["gender_zh"]))
    if g.get("animacy_zh"):
        bits.append(str(g["animacy_zh"]))
    if g.get("transitivity_zh"):
        bits.append(str(g["transitivity_zh"]))
    return " · ".join(bits) if bits else ""


def grammar_from_pymorphy(word: str) -> dict[str, Any]:
    """维基无语法行时，用 pymorphy2 补词性/体/性等（附中俄对照）。"""
    empty: dict[str, Any] = {
        "line_ru": "",
        "pos": "",
        "pos_ru": "",
        "pos_zh": "",
        "aspect": "",
        "aspect_ru": "",
        "aspect_zh": "",
        "transitivity_ru": "",
        "transitivity_zh": "",
        "gender_ru": "",
        "gender_zh": "",
        "animacy_ru": "",
        "animacy_zh": "",
        "decl_class": "",
        "conj_class": "",
        "pair_lemma": "",
        "pair_aspect": "",
        "pair_aspect_zh": "",
        "source": "pymorphy2",
    }
    plain = ru_strip_stress((word or "").strip())
    if not plain:
        return empty
    morph = gm.shared_morph_analyzer()
    if morph is None:
        return empty
    parses = morph.parse(plain)
    if not parses:
        return empty
    p = gm.pick_morph_parse(parses, plain)
    tag = p.tag
    pos = tag.POS
    if not pos:
        return empty
    out = dict(empty)
    pos_s = str(pos)
    out["pos"] = pos_s
    ru_zh = _PYMORPHY_POS_RU_ZH.get(pos_s)
    if ru_zh:
        out["pos_ru"], out["pos_zh"] = ru_zh[0], ru_zh[1]
    else:
        out["pos_zh"] = pos_s
    if tag.aspect:
        asp = str(tag.aspect)
        out["aspect"] = asp
        out["aspect_zh"] = _PYMORPHY_ASPECT_ZH.get(asp, asp)
        out["aspect_ru"] = (
            "совершенный вид" if asp == "perf" else "несовершенный вид"
        )
    if tag.gender:
        g = str(tag.gender)
        out["gender_zh"] = _PYMORPHY_GENDER_ZH.get(g, g)
        out["gender_ru"] = {
            "masc": "мужской род",
            "femn": "женский род",
            "neut": "средний род",
        }.get(g, g)
    if tag.animacy and pos_s == "NOUN":
        a = str(tag.animacy)
        out["animacy_zh"] = _PYMORPHY_ANIM_ZH.get(a, a)
        out["animacy_ru"] = (
            "одушевлённое" if a == "anim" else "неодушевлённое"
        )
    return out


def format_ru_wiki_grammar_pair_zh(grammar: dict[str, Any] | None) -> str:
    g = grammar if isinstance(grammar, dict) else {}
    lem = (g.get("pair_lemma") or "").strip()
    if not lem:
        return ""
    az = (g.get("pair_aspect_zh") or "").strip() or "对应体"
    return f"对应{az}动词：{lem}"


def _apply_ru_grammar_dict(data: dict[str, Any], parsed: dict[str, Any]) -> None:
    if not (parsed.get("pos_zh") or parsed.get("aspect_zh")):
        return
    data["ru_wiki_grammar"] = parsed
    data["ru_wiki_grammar_zh"] = format_ru_wiki_grammar_zh(parsed)
    if parsed.get("pair_lemma"):
        data["ru_wiki_grammar_pair_zh"] = format_ru_wiki_grammar_pair_zh(parsed)


def merge_ru_wiki_grammar(data: dict[str, Any], timeout: float = 14.0) -> None:
    """写入 ru_wiki_grammar / ru_wiki_grammar_zh；维基优先，否则 pymorphy2。"""
    if not isinstance(data, dict):
        return
    gram = data.get("ru_wiki_grammar")
    if isinstance(gram, dict) and (gram.get("pos_zh") or gram.get("aspect_zh")):
        data["ru_wiki_grammar_zh"] = format_ru_wiki_grammar_zh(gram)
        return
    lem = (
        (data.get("bkrs_lemma") or data.get("clicked") or data.get("lemma") or "")
        .strip()
    )
    if not lem:
        return
    _wiki_throttle_delay()
    html, err = _try_fetch_wiki_html("ru", lem, timeout)
    if not err and html:
        parsed = extract_ru_wiki_morph_from_html(html)
        if parsed.get("pos_zh") or parsed.get("aspect_zh"):
            _apply_ru_grammar_dict(data, parsed)
            return
    pm = grammar_from_pymorphy(lem)
    if pm.get("pos_zh") or pm.get("aspect_zh"):
        _apply_ru_grammar_dict(data, pm)


def fetch_ru_lemma_stressed_syllables(lemma: str, timeout: float = 14.0) -> str:
    """仅抓取 ru.wiktionary 词条并解析 {{по-слогам|…}} 分音节重音。"""
    lem = (lemma or "").strip()
    if not lem:
        return ""
    _wiki_throttle_delay()
    html, err = _try_fetch_wiki_html("ru", lem, timeout)
    if err or not html:
        return ""
    return extract_ru_lemma_stressed_from_html(html, lem)


def merge_display_lemma_stress(data: dict[str, Any], timeout: float = 14.0) -> None:
    """
    查词展示用原形优先 BKRS/lemma；若 lemma_stressed 与展示原形不一致则再抓对应维基页。
    """
    display = (data.get("bkrs_lemma") or data.get("lemma") or "").strip()
    if not display:
        return
    cur = (data.get("lemma_stressed") or "").strip()
    if (
        cur
        and ru_stress_key(cur) == ru_stress_key(display)
        and ("-" in cur or ru_has_stress_mark(cur))
    ):
        return
    s = fetch_ru_lemma_stressed_syllables(display, timeout=timeout)
    if s:
        data["lemma_stressed"] = s


def build_ru_wiki_stress_map(
    lemma_stressed: str, lemma_plain: str, tables: list | None
) -> dict[str, str]:
    """无重音小写键 -> 维基带重音串（用于点击形与句内替换）。"""
    m: dict[str, str] = {}
    if lemma_stressed and ru_has_stress_mark(lemma_stressed):
        m[ru_stress_key(lemma_stressed)] = lemma_stressed
    for tbl in tables or []:
        if not isinstance(tbl, list):
            continue
        for row in tbl:
            if not isinstance(row, list):
                continue
            for cell in row:
                t = str(cell).strip()
                if not t or len(t) > 72:
                    continue
                if not re.search(r"[А-Яа-яЁё]", t):
                    continue
                if not ru_has_stress_mark(t):
                    continue
                k = ru_stress_key(t)
                if k not in m:
                    m[k] = t
    return m


def ru_resolve_clicked_stressed(
    clicked: str, lemma_plain: str, lemma_stressed: str, stress_map: dict[str, str]
) -> str:
    k = ru_stress_key(clicked)
    if k in stress_map:
        return stress_map[k]
    if ru_stress_key(lemma_plain) == k and lemma_stressed:
        return lemma_stressed
    return clicked


def ru_stress_sentence_and_spans(
    sentence: str, stress_map: dict[str, str]
) -> tuple[str, list[tuple[int, int]]]:
    """
    按 stress_map 替换句中西里尔词；返回新句及每个西里尔词在新句中的 (start, end)。
    """
    if not stress_map:
        return sentence, []
    spans: list[tuple[int, int]] = []
    parts = re.split(r"(" + _CYR_WORD_IN_TEXT.pattern + r")", sentence)
    pos = 0
    out: list[str] = []
    for part in parts:
        if _CYR_WORD_IN_TEXT.fullmatch(part or ""):
            rep = stress_map.get(ru_stress_key(part), part)
            spans.append((pos, pos + len(rep)))
            out.append(rep)
            pos += len(rep)
        else:
            out.append(part)
            pos += len(part)
    return "".join(out), spans


def ru_cyrillic_word_index_at(sentence: str, pos: int) -> int:
    for k, m in enumerate(_CYR_WORD_IN_TEXT.finditer(sentence)):
        if m.start() <= pos < m.end():
            return k
    return -1


def _find_h2_by_headline_ids(soup: BeautifulSoup, ids: tuple[str, ...]) -> Tag | None:
    """语言节标题：新版 ru.wiktionary 常用 h1#Русский，旧版与其它站点多为 h2。"""
    for hid in ids:
        for tag_name in ("h1", "h2", "h3"):
            h = soup.find(tag_name, id=hid)
            if h:
                return h
        sp = soup.find("span", class_="mw-headline", id=hid)
        if sp and sp.parent and sp.parent.name in ("h1", "h2", "h3"):
            return sp.parent
    for sp in soup.find_all("span", class_="mw-headline"):
        if sp.get("id") in ids:
            p = sp.parent
            if p and p.name in ("h1", "h2", "h3"):
                return p
    return None


def _nodes_after_h2_until_next_h2(h2: Tag) -> list[Tag]:
    """MediaWiki 将 h2 包在 div.mw-heading.mw-heading2 内，正文在后续兄弟节点中。"""
    parent = h2.parent
    if (
        isinstance(parent, Tag)
        and "mw-heading" in " ".join(parent.get("class", []))
        and parent.find("h2") is not None
    ):
        start: Tag = parent
    else:
        start = h2
    out: list[Tag] = []
    for sib in start.next_siblings:
        if not isinstance(sib, Tag):
            continue
        cls = " ".join(sib.get("class", []))
        if "mw-heading1" in cls or "mw-heading2" in cls:
            inner = sib.find(["h1", "h2"])
            if inner is not None:
                break
        out.append(sib)
    return out


def _has_cjk(s: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" for c in s)


_LAT_LET = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-žǍ-ǰ]")


def _latin_letter_count(s: str) -> int:
    return len(_LAT_LET.findall(s or ""))


def _cyr_letter_count(s: str) -> int:
    return len(re.findall(r"[А-Яа-яЁё]", s or ""))


def _latin_wiktionary_line_noise(t: str) -> bool:
    """词源、参见、词形模板长句等，不作为「义项举例」。"""
    if not (t or "").strip():
        return True
    if _has_cjk(t):
        return any(
            x in t
            for x in (
                "同源",
                "词源",
                "詞源",
                "与包括",
                "来自",
                "參見",
                "参见",
                "继承",
                "繼承",
            )
        )
    tl = t.lower()
    noise = (
        "cognate with",
        "cognates include",
        "cognate include",
        "borrowed from",
        "inherited from",
        "from proto-",
        "from late proto",
        "from middle proto",
        "etymology",
        "alternative forms",
        "alternative form",
        "derived terms",
        "see also",
        "further reading",
        "neologism sense",
        "calque of",
        "cognado con",
        "préstamo del",
        "préstamo de",
        "del latín",
        "del griego",
        "del ruso",
        "heredado del",
        "procedente del",
        "etimología",
    )
    if any(n in tl for n in noise):
        return True
    # 词源对照行：天城文、希腊字母等多文种混排
    dev = len(re.findall(r"[\u0900-\u097f]", t))
    gre = len(re.findall(r"[\u0370-\u03ff]", t))
    arab = len(re.findall(r"[\u0600-\u06ff]", t))
    if dev + gre + arab >= 2:
        return True
    if dev >= 1 and gre >= 1:
        return True
    if tl.startswith("declension") or tl.startswith("conjugation"):
        return True
    if re.search(r"\b(n|f|m)\s+(inan|anim)\b", tl) and (
        "genitive" in tl or "nominative" in tl or "plural" in tl
    ):
        return True
    if tl.startswith("compounds") or tl.startswith("compound"):
        return True
    if "inflection of" in tl and _cyr_letter_count(t) > 14:
        return True
    return False


def _latin_def_line_ok(t: str) -> bool:
    t = (t or "").strip()
    if len(t) < 5 or len(t) > 420:
        return False
    if _has_cjk(t):
        return False
    if _latin_letter_count(t) < 6:
        return False
    la = max(1, _latin_letter_count(t))
    if _cyr_letter_count(t) > la * 3:
        return False
    if _latin_wiktionary_line_noise(t):
        return False
    return True


def _mw_heading_span_id(tag: Tag) -> str:
    """mw-heading2/3/4 包裹层或裸 h3/h4 上的 mw-headline id。"""
    h = tag.find(["h2", "h3", "h4"]) if tag.name == "div" else tag
    if h is None:
        return ""
    sp = h.find("span", class_="mw-headline")
    if sp is not None and sp.get("id"):
        return str(sp.get("id"))
    return str(h.get("id") or "")


def _norm_headline_id(hid: str) -> str:
    return (hid or "").replace("_", " ").strip().lower()


def _latin_gloss_heading_zone(hid: str, *, es: bool) -> str | None:
    """
    根据小节标题决定义项收集区：'on' 收义项，'off' 不收，None 忽略（不改变状态）。
    """
    n = _norm_headline_id(hid)
    if not n:
        return None
    if es:
        stops = {
            "etimología",
            "pronunciación",
            "declinación",
            "conjugación",
            "afijos",
            "términos derivados",
            "términos relacionados",
            "véase también",
            "descendientes",
            "referencias",
            "anagramas",
            "compuestos",
        }
        if n in stops or any(n.startswith(s + " ") for s in stops):
            return "off"
        if any(
            n.startswith(p)
            for p in (
                "sustantivo",
                "verbo",
                "adjetivo",
                "adverbio",
                "nombre propio",
                "frase",
                "interjección",
                "partícula",
                "conjunción",
                "preposición",
                "pronombre",
                "numeral",
                "locución",
            )
        ):
            return "on"
        return None
    stops = {
        "etymology",
        "pronunciation",
        "declension",
        "conjugation",
        "inflection",
        "derived terms",
        "related terms",
        "see also",
        "descendants",
        "references",
        "further reading",
        "coordinate terms",
        "hyponyms",
        "compounds",
        "anagrams",
    }
    if n in stops:
        return "off"
    if any(n.startswith(s + " ") for s in stops):
        return "off"
    starts = (
        "noun",
        "verb",
        "adjective",
        "adverb",
        "proper noun",
        "phrase",
        "particle",
        "conjunction",
        "preposition",
        "interjection",
        "numeral",
        "pronoun",
        "determiner",
        "name",
        "suffix",
        "prefix",
        "romanization",
        "letter",
        "character",
        "syllable",
        "participle",
        "gerund",
    )
    if n in starts or any(n.startswith(s + " ") for s in starts):
        return "on"
    return None


def _gloss_lines_latin_from_section_html(
    html: str,
    headline_ids: tuple[str, ...],
    *,
    max_lines: int = 10,
    es_wiktionary: bool = False,
) -> list[str]:
    """
    英语 / 西班牙语维基词条内 ==Russian== / ==Ruso== 等节下的义项行。
    仅在词性小节（Noun 等）之后、变格 / 派生 / 参见 等小节之前收集，避免词源与派生词表。
    """
    if not (html or "").strip():
        return []
    soup = _soup(html)
    h2 = _find_h2_by_headline_ids(soup, headline_ids)
    if not h2:
        return []
    nodes = _nodes_after_h2_until_next_h2(h2)
    collected: list[str] = []
    seen: set[str] = set()
    allow = False
    for node in nodes:
        if not isinstance(node, Tag):
            continue
        cls = " ".join(node.get("class", []))
        if "mw-heading3" in cls or "mw-heading4" in cls:
            hid = _mw_heading_span_id(node)
            z = _latin_gloss_heading_zone(hid, es=es_wiktionary)
            if z == "on":
                allow = True
            elif z == "off":
                allow = False
            continue
        if not allow:
            continue
        if node.name == "table":
            continue
        cand_ols: list[Tag] = []
        if node.name == "ol":
            cand_ols.append(node)
        cand_ols.extend(node.find_all("ol", recursive=True))
        for ol in cand_ols:
            if ol.find_parent("table"):
                continue
            for li in ol.find_all("li", recursive=False):
                t = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
                if not t or t in seen:
                    continue
                if _latin_def_line_ok(t):
                    seen.add(t)
                    collected.append(t)
                    if len(collected) >= max_lines:
                        return collected
        cand_uls: list[Tag] = []
        if node.name == "ul":
            cand_uls.append(node)
        cand_uls.extend(node.find_all("ul", recursive=True))
        for ul in cand_uls:
            if ul.find_parent("table"):
                continue
            for li in ul.find_all("li", recursive=False):
                t = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
                if not t or t in seen:
                    continue
                if _latin_def_line_ok(t):
                    seen.add(t)
                    collected.append(t)
                    if len(collected) >= max_lines:
                        return collected
        if node.name == "p":
            t = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            if t and t not in seen and _latin_def_line_ok(t):
                seen.add(t)
                collected.append(t)
                if len(collected) >= max_lines:
                    return collected
    return collected[:max_lines]


def _gloss_lines_from_section_nodes(
    nodes: list[Tag],
    max_lines: int = 14,
    *,
    paragraphs_cjk_only: bool = True,
) -> list[str]:
    lines: list[str] = []
    _cyr = re.compile(r"[А-Яа-яЁёІЇЄҐіїєґ]")
    for node in nodes:
        if node.name == "p":
            t = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            if not t or len(t) >= 400:
                continue
            if paragraphs_cjk_only:
                ok = _has_cjk(t)
            else:
                ok = _has_cjk(t) or bool(_cyr.search(t))
            if ok:
                lines.append(t)
        elif node.name in ("ul", "ol"):
            for li in node.find_all("li", recursive=False):
                t = re.sub(r"\s+", " ", li.get_text(" ", strip=True))
                if not t or len(t) > 500:
                    continue
                if paragraphs_cjk_only:
                    if _has_cjk(t) or ("（" in t and _cyr.search(t)):
                        lines.append(t)
                else:
                    if _has_cjk(t) or _cyr.search(t):
                        lines.append(t)
        if len(lines) >= max_lines:
            break
    # 去重保序，去掉发音/词源导航等非释义噪声
    seen: set[str] = set()
    uniq: list[str] = []
    for ln in lines:
        if ln not in seen:
            seen.add(ln)
            uniq.append(ln)

    def _noise(ln: str) -> bool:
        bad = (
            "國際音標",
            "国际音标",
            "音頻",
            "音频",
            "韻部",
            "韵部",
            "斷字",
            "断字",
            "繼承 自",
            "继承自",
            "參見：",
            "参见：",
            "來自 ",
            "来自 ",
            "同源",
            "词源",
            "詞源",
            "与包括",
            "與包括",
        )
        return any(b in ln for b in bad)

    return [ln for ln in uniq if not _noise(ln)][:max_lines]


def _is_candidate_inflection_table(cls: str) -> bool:
    c = cls.lower()
    if "navbox" in c or "sidebar" in c or "metadata" in c:
        return False
    return (
        "wikitable" in c
        or "inflection-table" in c
        or "inflection" in c
        or "morfotable" in c
        or "склон" in c
    )


def _morfotable_to_rows(table: Tag) -> list[list[str]] | None:
    """morfotable 首行常为 colspan 节标题（单列），不能用 _table_to_rows 的「首行≥2列」规则。"""
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [
            re.sub(r"\s+", " ", td.get_text(" ", strip=True))
            for td in tr.find_all(["th", "td"])
        ]
        if cells:
            rows.append(cells)
    if len(rows) < 3:
        return None
    if max(len(r) for r in rows) < 2:
        return None
    return rows


def _morfotable_is_russian_lang(table: Tag) -> bool:
    """仅保留俄语变位/变格表（morfotable ru），排除 udm/be/ady 等同形词条它语表。"""
    cls = [c.lower() for c in table.get("class", [])]
    return "morfotable" in cls and "ru" in cls


def _reject_foreign_morfotable_rows(rows: list[list[str]]) -> bool:
    """非俄语六格/动词变位体例（如乌德穆尔特语十格、科米语等）。"""
    if not rows:
        return True
    blob = " ".join(" ".join(r) for r in rows[: min(16, len(rows))]).lower()
    foreign = (
        "тыос",
        "тыр",
        "тыхэр",
        "разд.",
        "лиш.",
        "соотв.",
        "эрг.",
        "займеннікі",
        "асабовыя",
        "склонение и притяжательность",
    )
    if any(n in blob for n in foreign):
        return True
    if re.search(r"\bмн\.\s*ч\.", blob) and "предл" not in blob and "предлож" not in blob:
        if any(x in blob for x in ("тыос", "тылэн", "тых", " -ос")):
            return True
    return False


def _collect_morfotable_from_nodes(
    nodes: list[Tag], limit: int
) -> list[list[list[str]]]:
    out: list[list[list[str]]] = []
    for node in nodes:
        if not isinstance(node, Tag):
            continue
        for table in node.find_all("table"):
            if not _morfotable_is_russian_lang(table):
                continue
            rows = _morfotable_to_rows(table)
            if not rows or reject_russian_wikitable_noise(rows):
                continue
            if _reject_foreign_morfotable_rows(rows):
                continue
            out.append(rows)
            if len(out) >= limit:
                return out
    return out


def _collect_morfotable_from_root(
    root: Tag, limit: int
) -> list[list[list[str]]]:
    out: list[list[list[str]]] = []
    for table in root.find_all("table"):
        if not _morfotable_is_russian_lang(table):
            continue
        rows = _morfotable_to_rows(table)
        if not rows or reject_russian_wikitable_noise(rows):
            continue
        if _reject_foreign_morfotable_rows(rows):
            continue
        out.append(rows)
        if len(out) >= limit:
            break
    return out


def extract_ru_morfotable_tables(
    html: str, limit: int = 6
) -> list[list[list[str]]]:
    """俄语维基「Русский」节内 class=morfotable ru 的变位/变格表。"""
    if not (html or "").strip():
        return []
    soup = _soup(html)
    h = _find_h2_by_headline_ids(soup, ("Русский",))
    if h:
        nodes = _nodes_after_h2_until_next_h2(h)
        found = _collect_morfotable_from_nodes(nodes, limit)
        if found:
            return found
    root = (
        soup.find("div", id="mw-content-text")
        or soup.find("div", class_=re.compile(r"mw-parser-output"))
        or soup
    )
    return _collect_morfotable_from_root(root, limit)


def reject_russian_wikitable_noise(rows: list[list[str]]) -> bool:
    """
    若表格内容明显是「同根词 / 派生词列举」等，而非格变/时态人称变位，返回 True（应丢弃）。
    俄语维基常见大块 wikitable（如 «Список всех слов с корнем …»）会误当成变格表。
    """
    if not rows or len(rows) < 2:
        return False
    blob = " ".join(" ".join(r) for r in rows[: min(12, len(rows))]).lower()
    needles = (
        "список всех слов с корнем",
        "слов с корнем",
        "слов с одним корнем",
        "этимологические двойники",
        "словообразовательн",
        "фразеологизмы с этим",
        "однокоренные слова",
    )
    if any(n in blob for n in needles):
        return True
    # 先按词类堆词、无格/时/人称表头时，多为派生词表
    if "существительные" in blob and "глаголы" in blob:
        decl_conj = (
            "падеж",
            "настоящ",
            "будущ",
            "прошед",
            "инфинит",
            "повелит",
            "лицо",
            "единствен",
            "множествен",
            "именитель",
            "родительн",
            "дательн",
            "винительн",
            "творительн",
            "предложн",
        )
        if not any(m in blob for m in decl_conj):
            return True
    return False


def filter_russian_wiki_table_list(
    tbls: list | None,
) -> list[list[list[str]]]:
    """去掉俄语维基中误抓的「同根词表」等噪声表格。"""
    if not isinstance(tbls, list):
        return []
    out: list[list[list[str]]] = []
    for t in tbls:
        if isinstance(t, list) and t and not reject_russian_wikitable_noise(t):
            out.append(t)
    return out


def _table_to_rows(table: Tag) -> list[list[str]] | None:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [
            re.sub(r"\s+", " ", td.get_text(" ", strip=True))
            for td in tr.find_all(["th", "td"])
        ]
        if cells:
            rows.append(cells)
    if len(rows) >= 2 and len(rows[0]) >= 2:
        return rows
    return None


def _tables_from_nodes(nodes: list[Tag], limit: int = 8) -> list[list[list[str]]]:
    found: list[list[list[str]]] = []
    for node in nodes:
        for table in node.find_all("table"):
            cls = " ".join(table.get("class", []))
            if not _is_candidate_inflection_table(cls):
                continue
            rows = _table_to_rows(table)
            if rows and reject_russian_wikitable_noise(rows):
                continue
            if rows:
                found.append(rows)
            if len(found) >= limit:
                return found
    return found


def _parse_tables_whole_page(html: str, limit: int = 5) -> list[list[list[str]]]:
    soup = _soup(html)
    root = soup.find("div", id="mw-content-text") or soup.find("div", class_=re.compile(r"mw-parser-output")) or soup
    out: list[list[list[str]]] = []
    for table in root.find_all("table"):
        cls = " ".join(table.get("class", []))
        if not _is_candidate_inflection_table(cls):
            continue
        rows = _table_to_rows(table)
        if rows and reject_russian_wikitable_noise(rows):
            continue
        if rows:
            out.append(rows)
        if len(out) >= limit:
            break
    return out


def _section_gloss_and_tables(
    html: str,
    headline_ids: tuple[str, ...],
    *,
    paragraphs_cjk_only: bool = True,
) -> tuple[list[str], list[list[list[str]]]]:
    soup = _soup(html)
    h2 = _find_h2_by_headline_ids(soup, headline_ids)
    if not h2:
        return [], []
    nodes = _nodes_after_h2_until_next_h2(h2)
    return (
        _gloss_lines_from_section_nodes(
            nodes, paragraphs_cjk_only=paragraphs_cjk_only
        ),
        _tables_from_nodes(nodes),
    )


_UK_CYR_WORD = re.compile(r"[А-Яа-яІіЇїЄєҐґ][А-Яа-яІіЇїЄєҐґ''-]*")
_UK_TRANS_ROW = re.compile(
    r"(?:Украинский|Українськ\w*)\s+uk\s*:\s*([^;]+)",
    re.IGNORECASE,
)


def _clean_uk_equivalent_surface(s: str) -> str:
    t = re.sub(r"\s+", " ", (s or "").strip())
    if not t:
        return ""
    t = re.split(r"\s*[\(\[{]", t, maxsplit=1)[0].strip()
    t = re.sub(r"\s+[жмсн]\.\s*$", "", t, flags=re.IGNORECASE).strip()
    m = _UK_CYR_WORD.match(t)
    if m:
        return m.group(0).strip()
    return ""


def _uk_interwiki_title_from_ru_html(ru_html: str) -> str:
    if not (ru_html or "").strip():
        return ""
    soup = _soup(ru_html)
    a = soup.select_one("li.interwiki-uk a.interlanguage-link-target")
    if a is None:
        a = soup.select_one("li.interwiki-uk a")
    if a is None:
        return ""
    href = (a.get("href") or "").strip()
    if href and "/wiki/" in href:
        frag = href.split("/wiki/", 1)[-1]
        return url_unquote(frag.split("#")[0]).replace("_", " ").strip()
    title = (a.get("title") or "").strip()
    if " — " in title:
        return title.split(" — ", 1)[0].strip()
    return title


def extract_uk_equivalents_for_russian_lemma(
    ru_html: str,
    zh_html: str,
    *,
    max_items: int = 6,
) -> list[str]:
    """
    从俄语维基词条（翻译表 / {{t|uk|…}}）与汉语维基「乌克兰语」节提取乌克兰语对应词形。
    """
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        w = _clean_uk_equivalent_surface(raw)
        if not w:
            return
        key = w.lower().replace("ё", "е")
        if key in seen:
            return
        seen.add(key)
        found.append(w)

    if ru_html:
        raw = unescape(ru_html)
        for pat in (
            r"\{\{t\+\|uk\|([^}|#\n]+)",
            r"\{\{t\|uk\|([^}|#\n]+)",
        ):
            for m in re.finditer(pat, raw, re.IGNORECASE):
                add(m.group(1))
        for m in _UK_TRANS_ROW.finditer(raw):
            add(m.group(1))
        soup = _soup(ru_html)
        for tr in soup.find_all("tr"):
            row = tr.get_text(" ", strip=True)
            for m in _UK_TRANS_ROW.finditer(row):
                add(m.group(1))

    if zh_html and len(found) < max_items:
        zh_uk, _ = _section_gloss_and_tables(
            zh_html, ("乌克兰语", "烏克蘭語", "烏克兰语")
        )
        for ln in zh_uk:
            for m in _UK_CYR_WORD.finditer(ln):
                if any(c in m.group(0) for c in "іїєґІЇЄҐ"):
                    add(m.group(0))
                elif len(found) == 0:
                    add(m.group(0))
                break
            if len(found) >= max_items:
                break

    return found[:max_items]


def get_russian_inflections(word: str, timeout: float = 14.0) -> dict[str, Any]:
    """
    返回:
      lemma: 词典原形（pymorphy2）
      zh_gloss_lines: 汉语维基「俄语」节中含中文的释义行（仍写入缓存；查词 UI 义项优先用英/西）
      en_gloss_lines / es_gloss_lines: 英语、西班牙语维基「俄语」节拉丁字母义项行（查词展示）
      zh_html_tables / ru_html_tables: 两站词条内该语言节下的变格表（单元格为纯文本）
      html_tables: 优先汉语节表格，否则俄语节，再否则 pymorphy2 仅词形
      ru_wiki_url / zh_wiki_url / en_wiki_url / es_wiki_url / uk_wiki_url: 各语言维基词条链接
      uk_equivalent_words: 乌克兰语对应词（俄语维基翻译表等）
      forms, pymorphy2: 同前
    """
    word = (word or "").strip()
    if not word:
        return {"source": "error", "error": "空词", "forms": []}
    clean = re.sub(r"^[^\wА-Яа-яЁё]+|[^\wА-Яа-яЁё]+$", "", word)
    if not clean:
        return {"source": "error", "error": "无有效字符", "forms": []}
    clean_plain = ru_strip_stress(clean)

    pm = _pymorphy2_lexeme(clean_plain)
    lemma = (pm.get("lemma") or clean_plain).strip() or clean_plain
    cache_key = lemma.lower()

    _ensure_cache()
    if cache_key in _CACHE:
        hit = dict(_CACHE[cache_key])
        hit["clicked"] = clean
        hit["zh_html_tables"] = filter_russian_wiki_table_list(hit.get("zh_html_tables"))
        hit["ru_html_tables"] = filter_russian_wiki_table_list(hit.get("ru_html_tables"))
        if hit["zh_html_tables"]:
            hit["html_tables"] = list(hit["zh_html_tables"])
        elif hit["ru_html_tables"]:
            hit["html_tables"] = list(hit["ru_html_tables"])
        else:
            hit["html_tables"] = []
        lemma0 = (hit.get("lemma") or clean).strip() or clean
        lemma_s = (hit.get("lemma_stressed") or lemma0).strip() or lemma0
        sm = build_ru_wiki_stress_map(lemma_s, lemma0, hit.get("ru_html_tables"))
        hit["lemma_stressed"] = lemma_s
        hit["clicked_stressed"] = ru_resolve_clicked_stressed(
            clean, lemma0, lemma_s, sm
        )
        hit.setdefault("en_gloss_lines", [])
        hit.setdefault("es_gloss_lines", [])
        lem_u = (hit.get("lemma") or clean).strip() or clean
        hit.setdefault("en_wiki_url", _wiki_index_url("en", lem_u))
        hit.setdefault("es_wiki_url", _wiki_index_url("es", lem_u))
        hit.setdefault("uk_equivalent_words", [])
        hit.setdefault("uk_wiki_url", "")
        hit.setdefault("ru_wiki_grammar", {})
        hit.setdefault("ru_wiki_grammar_zh", "")
        hit.setdefault("ru_wiki_grammar_pair_zh", "")
        if not (hit.get("ru_wiki_grammar_zh") or "").strip():
            merge_ru_wiki_grammar(hit, timeout=timeout)
        _normalize_wiktionary_zh_fields(hit)
        return hit

    _wiki_throttle_delay()

    out: dict[str, Any] = {
        "source": "wiktionary",
        "clicked": clean,
        "lemma": lemma,
        "word": clean,
        "zh_gloss_lines": [],
        "zh_html_tables": [],
        "ru_html_tables": [],
        "html_tables": [],
        "ipa_brackets": "",
        "uk_equivalent_words": [],
        "forms": pm.get("forms") or [],
        "pymorphy2": pm,
        "ru_wiki_url": _wiki_index_url("ru", lemma),
        "zh_wiki_url": _wiki_index_url("zh", lemma),
        "en_wiki_url": _wiki_index_url("en", lemma),
        "es_wiki_url": _wiki_index_url("es", lemma),
        "uk_wiki_url": "",
        "ru_wiktionary_main_url": RU_WIKI_MAIN,
        "error": None,
    }

    (
        zh_html,
        zh_err,
        ru_html,
        ru_err,
        en_html,
        en_err,
        es_html,
        es_err,
    ) = _parallel_zh_ru_en_es_wiki_fetch(lemma, timeout)
    if zh_err:
        out["zh_fetch_error"] = zh_err
    if ru_err:
        out["ru_fetch_error"] = ru_err
    if en_err:
        out["en_fetch_error"] = en_err
    if es_err:
        out["es_fetch_error"] = es_err

    zh_gloss: list[str] = []
    zh_tables: list[list[list[str]]] = []
    ru_tables: list[list[list[str]]] = []
    en_gloss: list[str] = []
    es_gloss: list[str] = []

    if en_html:
        en_gloss = _gloss_lines_latin_from_section_html(
            en_html, ("Russian",), max_lines=12, es_wiktionary=False
        )
    if es_html:
        es_gloss = _gloss_lines_latin_from_section_html(
            es_html,
            ("Ruso", "Rusa", "ruso", "Idioma_ruso"),
            max_lines=12,
            es_wiktionary=True,
        )
    if zh_html:
        zh_gloss, zh_tables = _section_gloss_and_tables(
            zh_html, ("俄语", "俄語", "俄罗斯语")
        )
        if not zh_tables:
            zh_tables = _parse_tables_whole_page(zh_html, limit=3)

    if ru_html:
        ru_gram = extract_ru_wiki_morph_from_html(ru_html)
        if ru_gram.get("pos_zh") or ru_gram.get("aspect_zh"):
            _apply_ru_grammar_dict(out, ru_gram)
        morfo = extract_ru_morfotable_tables(ru_html, limit=4)
        if morfo:
            ru_tables = morfo
        else:
            _, ru_tables = _section_gloss_and_tables(ru_html, ("Русский",))
            if not ru_tables:
                ru_tables = _parse_tables_whole_page(ru_html, limit=5)

    zh_tables = filter_russian_wiki_table_list(zh_tables)
    ru_tables = filter_russian_wiki_table_list(ru_tables)

    lemma_stressed = ""
    if ru_html:
        lemma_stressed = extract_ru_lemma_stressed_from_html(ru_html, lemma)
    sm0 = build_ru_wiki_stress_map(lemma_stressed, lemma, ru_tables)
    clicked_stressed = ru_resolve_clicked_stressed(clean, lemma, lemma_stressed, sm0)
    sm0[ru_stress_key(clean)] = clicked_stressed
    out["lemma_stressed"] = lemma_stressed or lemma
    out["clicked_stressed"] = clicked_stressed

    ipa = ""
    if ru_html:
        ipa = extract_wiktionary_ipa_brackets(ru_html)
    if not ipa and zh_html:
        ipa = extract_wiktionary_ipa_brackets(zh_html)
    out["ipa_brackets"] = ipa

    uk_words = extract_uk_equivalents_for_russian_lemma(ru_html or "", zh_html or "")
    out["uk_equivalent_words"] = uk_words
    iw_uk = _uk_interwiki_title_from_ru_html(ru_html or "")
    if iw_uk:
        out["uk_wiki_url"] = _wiki_index_url("uk", iw_uk)
    elif uk_words:
        out["uk_wiki_url"] = _wiki_index_url("uk", uk_words[0])
    else:
        out["uk_wiki_url"] = _wiki_index_url("uk", lemma)

    out["zh_gloss_lines"] = zh_gloss
    out["en_gloss_lines"] = en_gloss
    out["es_gloss_lines"] = es_gloss
    out["zh_html_tables"] = zh_tables
    out["ru_html_tables"] = ru_tables
    if zh_tables:
        out["html_tables"] = zh_tables
    elif ru_tables:
        out["html_tables"] = ru_tables
    else:
        out["html_tables"] = []
        out["source"] = "wiktionary_empty"

    if out.get("zh_fetch_error") and out.get("ru_fetch_error") and not out["html_tables"]:
        out["source"] = "wiktionary_error"
        out["error"] = str(out.get("zh_fetch_error") or out.get("ru_fetch_error"))

    if not (out.get("ru_wiki_grammar_zh") or "").strip():
        pm = grammar_from_pymorphy(lemma)
        if pm.get("pos_zh") or pm.get("aspect_zh"):
            _apply_ru_grammar_dict(out, pm)

    _normalize_wiktionary_zh_fields(out)

    _CACHE[cache_key] = {k: v for k, v in out.items() if k not in ("clicked", "clicked_stressed")}
    try:
        _write_cache()
    except OSError:
        pass
    return out


def _uk_clean_surface(word: str) -> str:
    """乌克兰语词形：去掉两端标点；保留词内连字符与撇号。"""
    w = (word or "").strip()
    return re.sub(
        r"^[^\wА-Яа-яЁёІЇЄҐіїєґ'-]+|[^\wА-Яа-яЁёІЇЄҐіїєґ'-]+$",
        "",
        w,
    )


def _uk_strip_stress_marks(s: str) -> str:
    return re.sub(r"[\u0300-\u036f]", "", s or "")


def _uk_has_meaning_gloss(d: dict[str, Any]) -> bool:
    for ln in d.get("bkrs_lines") or []:
        if re.search(r"[\u3400-\u9fff]", str(ln)):
            return True
    for key in ("zh_gloss_lines", "ru_gloss_lines"):
        for ln in d.get(key) or []:
            if re.search(r"[\u3400-\u9fff]", str(ln)):
                return True
            t = _uk_strip_stress_marks(str(ln))
            if len(t) >= 2 and re.search(r"[А-Яа-яІіЇїЄєҐґ]", t) and len(t) < 80:
                return True
    return False


def _uk_infinitive_guess(surface: str) -> str | None:
    """常见变位 → 不定式 -ти（如 знаєте → знати）。"""
    w = _uk_strip_stress_marks((surface or "").strip())
    if len(w) < 4 or w.endswith("ти"):
        return None
    for suf in (
        "єте",
        "ете",
        "ємо",
        "емо",
        "ють",
        "уть",
        "єш",
        "еш",
        "иш",
        "ує",
        "ю",
    ):
        if w.endswith(suf) and len(w) > len(suf) + 1:
            cand = w[: -len(suf)] + "ти"
            if cand.endswith("ти") and cand != w:
                return cand
    return None


def _uk_lemma_from_en_wikt(surface: str, timeout: float) -> str | None:
    html, err = _try_fetch_wiki_html("en", surface, timeout)
    if not html or err:
        return None
    for m in re.finditer(
        r"\bof\s+([А-Яа-яІіЇїЄєҐґ][А-Яа-яІіЇїЄєҐґ\u0300-\u036f''-]{1,})",
        html,
    ):
        w = _uk_strip_stress_marks(m.group(1).strip("'\""))
        if w.endswith("ти") and w.lower() != surface.strip().lower():
            return w
    return None


def _uk_lemma_candidates(surface: str, timeout: float) -> list[str]:
    clean = _uk_clean_surface(surface)
    if not clean:
        return []
    seen: set[str] = set()
    out: list[str] = []

    def add(w: str | None) -> None:
        if not w:
            return
        k = w.strip().lower()
        if not k or k == clean.lower() or k in seen:
            return
        seen.add(k)
        out.append(w.strip())

    add(_uk_infinitive_guess(clean))
    add(_uk_lemma_from_en_wikt(clean, timeout))
    return out


def _uk_merge_lemma_lookup(out: dict[str, Any], surface: str, timeout: float) -> None:
    if _uk_has_meaning_gloss(out):
        return
    for lemma in _uk_lemma_candidates(surface, timeout):
        sub = get_ukrainian_inflections(lemma, timeout=timeout)
        if not _uk_has_meaning_gloss(sub):
            continue
        out["lemma"] = lemma
        out["lemma_fallback_from"] = surface
        out["source"] = "lemma_fallback"
        out["error"] = None
        out["zh_gloss_lines"] = list(sub.get("zh_gloss_lines") or [])
        out["ru_gloss_lines"] = list(sub.get("ru_gloss_lines") or [])
        if sub.get("bkrs_lines"):
            out["bkrs_lines"] = list(sub.get("bkrs_lines") or [])
            out["bkrs_lemma"] = sub.get("bkrs_lemma") or ""
            out["bkrs_url"] = sub.get("bkrs_url") or ""
            out["ru_lookup_word"] = sub.get("ru_lookup_word") or ""
        if sub.get("zh_html_tables"):
            out["zh_html_tables"] = sub.get("zh_html_tables")
        if sub.get("ru_html_tables"):
            out["ru_html_tables"] = sub.get("ru_html_tables")
        return


def _uk_apply_bkrs_pack(out: dict[str, Any], bk: dict[str, Any]) -> None:
    out["ru_lookup_word"] = bk.get("ru_lookup_word") or ""
    out["bkrs_lines"] = list(bk.get("bkrs_lines") or [])
    out["bkrs_lemma"] = (bk.get("bkrs_lemma") or "").strip()
    out["bkrs_url"] = bk.get("bkrs_url") or ""
    if bk.get("bkrs_error"):
        out["bkrs_error"] = bk.get("bkrs_error")
    elif out["bkrs_lines"]:
        out["bkrs_error"] = None
    if out["bkrs_lemma"]:
        out["lemma_ru"] = out["bkrs_lemma"]


def _uk_merge_bkrs(out: dict[str, Any], surface: str, timeout: float) -> None:
    import uk_lookup_bridge as ulb

    uk_lem = (out.get("goroh_lemma") or "").strip() or None
    bk = ulb.fetch_bkrs_for_ukrainian(
        surface, uk_lemma=uk_lem, timeout=timeout
    )
    _uk_apply_bkrs_pack(out, bk)


def _uk_refine_bkrs_with_goroh_lemma(out: dict[str, Any], timeout: float) -> None:
    import uk_lookup_bridge as ulb

    lem = (out.get("goroh_lemma") or "").strip()
    if not lem:
        return
    pack = {
        "ru_lookup_word": out.get("ru_lookup_word") or "",
        "bkrs_lines": out.get("bkrs_lines") or [],
        "bkrs_lemma": out.get("bkrs_lemma") or "",
    }
    if not ulb.bkrs_pack_needs_retry(pack, uk_lemma=lem):
        return
    surface = str(out.get("clicked") or out.get("lemma") or "").strip()
    bk = ulb.fetch_bkrs_for_ukrainian(surface, uk_lemma=lem, timeout=timeout)
    _uk_apply_bkrs_pack(out, bk)


def get_ukrainian_inflections(word: str, timeout: float = 14.0) -> dict[str, Any]:
    """
    乌克兰语查词：
    - 词义：uk→ru 后查 bkrs.info（与俄语查词一致，含原形跳转）
    - 变位：Горох「Словозміна」（https://goroh.pp.ua/）
    - 备用：汉语维基「乌克兰语」节、俄语维基乌克兰语节
    """
    word = (word or "").strip()
    if not word:
        return {"source": "error", "error": "空词", "forms": []}
    clean = _uk_clean_surface(word)
    if not clean:
        return {"source": "error", "error": "无有效字符", "forms": []}
    clean_plain = _uk_strip_stress_marks(clean)

    cache_key = "uk|" + clean_plain.lower()
    _ensure_cache()
    if cache_key in _CACHE:
        hit = dict(_CACHE[cache_key])
        hit["clicked"] = clean
        _normalize_wiktionary_zh_fields(hit)
        import uk_lookup_bridge as ulb

        if (
            not hit.get("bkrs_lines")
            or ulb.bkrs_lemma_looks_invalid(hit.get("bkrs_lemma") or "")
            or ulb.looks_ukrainian(hit.get("ru_lookup_word") or "")
        ):
            _uk_merge_bkrs(hit, clean_plain, timeout)
        if hit.get("goroh_lemma"):
            _uk_refine_bkrs_with_goroh_lemma(hit, timeout)
        if not _uk_has_meaning_gloss(hit):
            _uk_merge_lemma_lookup(hit, clean_plain, timeout)
            if _uk_has_meaning_gloss(hit):
                _CACHE[cache_key] = {k: v for k, v in hit.items() if k != "clicked"}
                try:
                    _write_cache()
                except OSError:
                    pass
        return hit

    _wiki_throttle_delay()

    import goroh_parser as gp
    import uk_lookup_bridge as ulb

    with ThreadPoolExecutor(max_workers=4) as ex:
        fg = ex.submit(gp.fetch_slovozmina_tables, clean_plain, timeout=timeout)
        fbk = ex.submit(ulb.fetch_bkrs_for_ukrainian, clean_plain, timeout=timeout)
        fzh = ex.submit(_try_fetch_wiki_html, "zh", clean_plain, timeout)
        fru = ex.submit(_try_fetch_wiki_html, "ru", clean_plain, timeout)
    goroh = fg.result()
    bkrs_pack = fbk.result()
    zh_html, zh_fetch_e = fzh.result()
    ru_html, ru_fetch_e = fru.result()

    out: dict[str, Any] = {
        "source": "bkrs+goroh+wiktionary",
        "clicked": clean,
        "lemma": clean,
        "lemma_ru": "",
        "ru_lookup_word": bkrs_pack.get("ru_lookup_word") or "",
        "bkrs_lines": list(bkrs_pack.get("bkrs_lines") or []),
        "bkrs_lemma": (bkrs_pack.get("bkrs_lemma") or "").strip(),
        "bkrs_url": bkrs_pack.get("bkrs_url") or "",
        "bkrs_error": bkrs_pack.get("bkrs_error"),
        "zh_gloss_lines": [],
        "ru_gloss_lines": [],
        "zh_html_tables": [],
        "ru_html_tables": [],
        "goroh_tables": list(goroh.get("goroh_tables") or []),
        "goroh_url": goroh.get("goroh_url") or gp.slovozmina_url(clean_plain),
        "goroh_lemma": (goroh.get("goroh_lemma") or "").strip(),
        "goroh_lemma_url": goroh.get("goroh_lemma_url") or gp.slovozmina_url(clean_plain),
        "goroh_table_html": goroh.get("goroh_table_html") or "",
        "goroh_fetch_error": goroh.get("goroh_fetch_error"),
        "zh_wiki_url": _wiki_index_url("zh", clean_plain),
        "uk_wiki_url": _wiki_index_url("uk", clean_plain),
        "ru_wiki_url": _wiki_index_url("ru", clean_plain),
        "ru_wikt_uk_index_url": RU_WIKT_UKRAINIAN_INDEX_URL,
        "error": None,
        "forms": [],
    }
    if zh_fetch_e:
        out["zh_fetch_error"] = zh_fetch_e
    if ru_fetch_e:
        out["ru_fetch_error"] = ru_fetch_e

    zh_gloss: list[str] = []
    zh_tables: list[list[list[str]]] = []
    if zh_html:
        zh_gloss, zh_tables = _section_gloss_and_tables(
            zh_html, ("乌克兰语", "烏克蘭語", "烏克兰语")
        )
        if not zh_tables:
            zh_tables = _parse_tables_whole_page(zh_html, limit=4)

    ru_gloss: list[str] = []
    ru_tables: list[list[list[str]]] = []
    if ru_html:
        ru_gloss, ru_tables = _section_gloss_and_tables(
            ru_html,
            (
                "Украинский",
                "Український",
                "Українська",
                "Украї́нська",
            ),
            paragraphs_cjk_only=False,
        )
        if not ru_tables:
            ru_tables = _parse_tables_whole_page(ru_html, limit=4)
    ru_tables = filter_russian_wiki_table_list(ru_tables)

    out["zh_gloss_lines"] = zh_gloss
    out["zh_html_tables"] = zh_tables
    out["ru_gloss_lines"] = ru_gloss
    out["ru_html_tables"] = ru_tables

    if (
        not zh_gloss
        and not zh_tables
        and not out["goroh_tables"]
        and not ru_gloss
        and not ru_tables
    ):
        err = (
            out.get("goroh_fetch_error")
            or out.get("zh_fetch_error")
            or out.get("ru_fetch_error")
        )
        if err:
            out["source"] = "fetch_error"
            out["error"] = str(err)

    _normalize_wiktionary_zh_fields(out)
    if out.get("goroh_lemma"):
        out["lemma"] = out["goroh_lemma"]
        _uk_refine_bkrs_with_goroh_lemma(out, timeout)
    if out.get("bkrs_lemma"):
        out["lemma_ru"] = out["bkrs_lemma"]
    if not _uk_has_meaning_gloss(out):
        _uk_merge_lemma_lookup(out, clean_plain, timeout)
        _normalize_wiktionary_zh_fields(out)

    _CACHE[cache_key] = {k: v for k, v in out.items() if k != "clicked"}
    try:
        _write_cache()
    except OSError:
        pass
    return out
