"""
大БКРС（bkrs.info）俄→中释义抓取。
变位形无词条时跟随「начальная форма」链接取原形释义。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from terminology_bridge import portable_root

BKRS_BASE = "https://bkrs.info/"
CACHE_PATH = portable_root() / "data" / "cache" / "bkrs_lookup_cache_v5.json"
_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": "ArgosTranslateLocal/1.0 (educational; offline lookup)",
        "Accept-Language": "ru,zh-CN;q=0.9,en;q=0.7",
    }
)
_CACHE: dict[str, Any] = {}
_CACHE_LOADED = False
_CA_COOKIE: str | None = None

_HAN_RE = re.compile(r"[\u3400-\u9fff]")
_CYR_RE = re.compile(r"[А-Яа-яЁё]")
_DEF_NUM_RE = re.compile(r"^(\d+)[\).]\s*(.*)$", re.DOTALL)
_CROSS_REF_RE = re.compile(
    r"см\.?\s*([А-Яа-яЁё][А-Яа-яЁё-]*)(?:\s+([\d\s,，]+))?",
    re.IGNORECASE,
)
_SKIP_ZH_RE = re.compile(
    r"^(见|参见|см\.?|тж\.?|сов\.?|未|完|的未完成体)$",
    re.IGNORECASE,
)
_PINYIN_RE = re.compile(
    r"\s+[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùüǖǘǚǜńňǹ]+(?:\s*,\s*[a-zA-Zāáǎàēéěèīíǐìōóǒòūúǔùüǖǘǚǜńňǹ]+)*"
)


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


def _clean_word(word: str) -> str:
    w = (word or "").strip()
    w = re.sub(r"[\u0301\u0300\u030f]", "", w)
    return re.sub(
        r"^[^\wА-Яа-яЁё'-]+|[^\wА-Яа-яЁё'-]+$",
        "",
        w,
    )


def _slovo_url(word: str) -> str:
    return BKRS_BASE + "slovo.php?ch=" + quote(_clean_word(word), safe="")


def _ensure_access() -> None:
    """通过 bkrs 反爬「入」页，在 Session 中写入 ca cookie。"""
    global _CA_COOKIE
    if _CA_COOKIE and _SESSION.cookies.get("ca"):
        return
    r = _SESSION.get(BKRS_BASE, timeout=12)
    m = re.search(r"name=['\"]ca['\"]\s+value=['\"]([^'\"]+)['\"]", r.text)
    if not m:
        m = re.search(r"document\.cookie\s*=\s*\"ca=([^;\"]+)", r.text)
    if m:
        _CA_COOKIE = m.group(1)
        _SESSION.cookies.set("ca", _CA_COOKIE, domain="bkrs.info", path="/")
        try:
            _SESSION.post(BKRS_BASE, data={"ca": _CA_COOKIE}, timeout=12)
        except requests.RequestException:
            pass


def _fetch_html(word: str, timeout: float) -> str:
    _ensure_access()
    url = _slovo_url(word)
    r = _SESSION.get(url, timeout=timeout)
    if "js" in r.text and "name='ca'" in r.text and len(r.text) < 2000:
        m = re.search(r"name=['\"]ca['\"]\s+value=['\"]([^'\"]+)['\"]", r.text)
        if m:
            _SESSION.post(url, data={"ca": m.group(1)}, timeout=timeout)
            r = _SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _lemma_from_page(soup: BeautifulSoup) -> str | None:
    box = soup.find("div", id="words_morphology")
    if not box:
        return None
    a = box.find("a", href=True)
    if not a:
        return None
    t = a.get_text(" ", strip=True)
    return t or None


def _to_zh_cn(s: str) -> str:
    try:
        from inflection_display import to_zh_cn

        return to_zh_cn(s)
    except ImportError:
        return s


def _zh_dedup_key(s: str) -> str:
    """去重键：仅保留汉字与全角括号内注释。"""
    t = (s or "").strip()
    t = re.sub(r"\[[^\]]*\]", "", t)
    return re.sub(r"[^\u3400-\u9fff]", "", t)


def _strip_pinyin(s: str) -> str:
    return _PINYIN_RE.sub("", s or "").strip()


def _normalize_zh_gloss(s: str) -> str:
    g = _to_zh_cn(_strip_pinyin((s or "").strip()))
    g = re.sub(r"\s+", "", g)
    g = g.replace("[电]", "（电）")
    g = re.sub(r"〈[^〉]+〉", "", g)
    if len(g) > 20:
        g = g[:20].rstrip() + "…"
    return g


def _gloss_acceptable(g: str) -> bool:
    key = _zh_dedup_key(g)
    if not key:
        return False
    if len(key) < 2 and g not in ("关",):
        return False
    if len(key) > 12:
        return False
    if re.search(r"[他她你您].*[了是在]", g):
        return False
    if g in ("口语", "电", "未", "完", "把", "的", "指", "见"):
        return False
    return True


def _extract_zh_glosses_from_text(text: str) -> list[str]:
    """从 BKRS 单行/片段中提取中文义项（去掉俄语、拼音、参见）。"""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t or not _HAN_RE.search(t):
        return []
    if _SKIP_ZH_RE.match(t) or re.fullmatch(r"见\s*[А-Яа-яЁё]+", t, re.I):
        return []
    if re.search(r"的未完成体", t):
        return []

    if re.search(r"\s[-–—]\s+", t):
        parts = re.split(r"\s[-–—]\s+", t, maxsplit=1)
        if len(parts) == 2 and _HAN_RE.search(parts[1]) and (
            not _HAN_RE.search(parts[0]) or _CYR_RE.search(parts[0])
        ):
            t = parts[1].strip()

    m = re.search(r"\bчто\s+", t, re.I)
    if m:
        t = t[m.end() :].strip()

    t = re.sub(r"^\([^)]*[А-Яа-яЁё][^)]*\)\s*", "", t)
    t = re.sub(r"^\[[^\]]*\]\s*", "", t)

    out: list[str] = []
    for part in re.split(r"[;；]", t):
        part = part.strip()
        if not part or not _HAN_RE.search(part):
            continue
        part = _strip_pinyin(part)
        part = re.sub(r"^[А-Яа-яЁё][А-Яа-яЁё.\s«»]*", "", part).strip()
        part = re.sub(r"\s+", " ", part).strip(" ,.")
        for m2 in re.finditer(
            r"[\u3400-\u9fff]+(?:[（(][^）)]{0,24}[）)])?",
            part,
        ):
            g = _normalize_zh_gloss(m2.group(0))
            if len(g) >= 1 and not _SKIP_ZH_RE.match(g):
                out.append(g)
    return out


def _dedupe_zh_glosses(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        g = _normalize_zh_gloss(raw)
        if not _gloss_acceptable(g):
            continue
        key = _zh_dedup_key(g)
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out


def _parse_numbered_div_glosses(ch: BeautifulSoup | None) -> list[str]:
    if not ch:
        return []
    found: list[str] = []
    for div in ch.find_all("div"):
        if div.find_parent("div", class_="m2"):
            continue
        classes = div.get("class") or []
        if "m2" in classes or "ex" in classes:
            continue
        t = div.get_text(" ", strip=True)
        m = _DEF_NUM_RE.match(t)
        if not m:
            continue
        body = m.group(2).strip()
        han = _HAN_RE.search(body)
        if han:
            found.extend(_extract_zh_glosses_from_text(body[han.start() :]))
    return found


def _parse_ch_ru_glosses(ch: BeautifulSoup) -> list[str]:
    found: list[str] = []
    for div in ch.find_all("div", recursive=False):
        classes = div.get("class") or []
        text = div.get_text(" ", strip=True)
        if not text or not _HAN_RE.search(text):
            continue
        if "m2" in classes or "ex" in classes:
            found.extend(_extract_zh_glosses_from_text(text))
        elif "m2" not in classes:
            if not _CYR_RE.fullmatch(text.replace(" ", "")):
                found.extend(_extract_zh_glosses_from_text(text))
    return found


def _parse_pt14_sats(soup: BeautifulSoup) -> list[str]:
    box = soup.find("div", id="sats") or soup.find("div", class_="pt14")
    if not box:
        return []
    found: list[str] = []
    html = str(box)
    for chunk in re.split(r"<br\s*/?>", html, flags=re.I):
        t = BeautifulSoup(chunk, "html.parser").get_text(" ", strip=True)
        if t:
            found.extend(_extract_zh_glosses_from_text(t))
    if not found:
        found.extend(_extract_zh_glosses_from_text(box.get_text(" ", strip=True)))
    return found


def _parse_examples_glosses(soup: BeautifulSoup) -> list[str]:
    """例句区：取「中文 + 俄语」配对中的简短中文译法。"""
    box = soup.find("div", class_="examples") or soup.find("div", id="examples")
    if not box:
        return []
    found: list[str] = []
    for div in box.find_all("div"):
        t = div.get_text(" ", strip=True)
        if not t or len(t) > 80:
            continue
        m = re.match(
            r"^([\u3400-\u9fff][\u3400-\u9fff（）()·、\s]{1,18})\s+[А-Яа-яЁё]",
            t,
        )
        if m:
            g = m.group(1).strip()
            if len(_zh_dedup_key(g)) <= 6:
                found.append(g)
    return found


def _parse_definition_lines(soup: BeautifulSoup) -> list[str]:
    """汇总词条页中文义项：ch_ru、сателлиты(pt14)、例句；去重后仅保留中文。"""
    ch = soup.find("div", class_="ch_ru")
    collected: list[str] = []
    if ch:
        collected.extend(_parse_ch_ru_glosses(ch))
        collected.extend(_parse_numbered_div_glosses(ch))
    collected.extend(_parse_pt14_sats(soup))
    collected.extend(_parse_examples_glosses(soup))
    return _dedupe_zh_glosses(collected)


def _page_has_entry(soup: BeautifulSoup) -> bool:
    if soup.find("div", id="no-such-word"):
        return False
    return bool(soup.find("div", class_="ch_ru"))


def _parse_sense_numbers(blob: str) -> set[int]:
    nums: set[int] = set()
    for part in re.split(r"[,，\s]+", (blob or "").strip()):
        if part.isdigit():
            nums.add(int(part))
    return nums


def _cross_ref_from_page(soup: BeautifulSoup) -> tuple[str, set[int]] | None:
    """解析「сов. см. включать 2, 3」类参见条目。"""
    ch = soup.find("div", class_="ch_ru")
    if not ch:
        return None
    text = ch.get_text(" ", strip=True)
    for a in ch.find_all("a", href=True):
        href = a.get("href") or ""
        if "slovo.php" not in href:
            continue
        ref = _clean_word(a.get_text(strip=True))
        if not ref:
            continue
        senses: set[int] = set()
        m = _CROSS_REF_RE.search(text)
        if m and m.group(1).lower() == ref.lower() and m.group(2):
            senses = _parse_sense_numbers(m.group(2))
        return ref, senses
    m = _CROSS_REF_RE.search(text)
    if not m:
        return None
    ref = _clean_word(m.group(1))
    if not ref:
        return None
    senses = _parse_sense_numbers(m.group(2) or "")
    return ref, senses


def _glosses_for_senses(soup: BeautifulSoup, senses: set[int]) -> list[str]:
    """参见条目指定义项号时，仅从 ch_ru 编号行提取对应中文。"""
    if not senses:
        return []
    ch = soup.find("div", class_="ch_ru")
    if not ch:
        return []
    found: list[str] = []
    for div in ch.find_all("div"):
        if div.find_parent("div", class_="m2"):
            continue
        classes = div.get("class") or []
        if "m2" in classes or "ex" in classes:
            continue
        t = div.get_text(" ", strip=True)
        m = _DEF_NUM_RE.match(t)
        if m and int(m.group(1)) in senses:
            found.extend(_extract_zh_glosses_from_text(m.group(2)))
    return _dedupe_zh_glosses(found)


def lookup_russian_word(word: str, timeout: float = 14.0) -> dict[str, Any]:
    """
    查询 bkrs.info，返回 definition_lines（去重后的中文义项，每行一条）、lemma。
    """
    clean = _clean_word(word)
    if not clean:
        return {"source": "error", "error": "空词", "definition_lines": [], "lemma": ""}

    key = clean.lower()
    _ensure_cache()
    if key in _CACHE:
        hit = dict(_CACHE[key])
        hit["queried"] = clean
        return hit

    time.sleep(0.2)
    out: dict[str, Any] = {
        "source": "bkrs.info",
        "queried": clean,
        "lemma": clean,
        "definition_lines": [],
        "bkrs_url": _slovo_url(clean),
        "error": None,
    }
    try:
        html = _fetch_html(clean, timeout)
        soup = _soup(html)
        lines = _parse_definition_lines(soup)
        title = soup.find("div", id="ru_ru")
        lemma = (title.get_text(strip=True) if title else None) or clean
        morph_lem = _lemma_from_page(soup)
        if morph_lem and morph_lem.lower() != clean.lower():
            html_lem = _fetch_html(morph_lem, timeout)
            soup_lem = _soup(html_lem)
            lem_lines = _parse_definition_lines(soup_lem)
            if lem_lines:
                lines = lem_lines
                lemma = morph_lem
                out["bkrs_url"] = _slovo_url(morph_lem)

        if not lines:
            xref = _cross_ref_from_page(soup)
            if xref:
                ref_word, senses = xref
                if ref_word.lower() != clean.lower():
                    html2 = _fetch_html(ref_word, timeout)
                    soup2 = _soup(html2)
                    lines = _glosses_for_senses(soup2, senses)
                    if not lines:
                        lines = _parse_definition_lines(soup2)
                    lemma = ref_word
                    out["bkrs_url"] = _slovo_url(ref_word)
            if not lines:
                lem = _lemma_from_page(soup)
                if lem and lem.lower() != clean.lower():
                    lemma = lem
                    html2 = _fetch_html(lem, timeout)
                    lines = _parse_definition_lines(_soup(html2))
                    out["bkrs_url"] = _slovo_url(lem)
                elif _page_has_entry(soup):
                    pass
        elif lemma.lower() != clean.lower():
            out["bkrs_url"] = _slovo_url(lemma)

        out["lemma"] = lemma
        out["definition_lines"] = lines
        if not lines:
            out["error"] = "未解析到中文义项"
    except Exception as e:
        out["source"] = "fetch_error"
        out["error"] = str(e)

    _CACHE[key] = {k: v for k, v in out.items() if k != "queried"}
    try:
        _write_cache()
    except OSError:
        pass
    return out
