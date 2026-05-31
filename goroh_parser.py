"""
Горох（goroh.pp.ua）乌克兰语「Словозміна」变格表抓取与解析。
体例与网站一致：https://goroh.pp.ua/
"""
from __future__ import annotations

import html as html_lib
import json
import re
import time
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

from terminology_bridge import portable_root

GOROH_SLOVOZMINA = "Словозміна"
GOROH_HOME = "https://goroh.pp.ua/"
CACHE_PATH = portable_root() / "data" / "cache" / "goroh_slovozmina_cache_v5.json"
_UK_CYR = re.compile(
    r"[А-Яа-яІіЇїЄєҐґ]+(?:\u0301|\u0300|\u030f)?"
    r"(?:-[А-Яа-яІіЇїЄєҐґ]+(?:\u0301|\u0300|\u030f)?)*"
)
_UK_LABEL_ZH: dict[str, str] = {
    "інфінітив": "不定式",
    "однина": "单数",
    "множина": "复数",
    "наказовий спосіб": "命令式",
    "майбутній час": "将来时",
    "минулий час": "过去时",
    "безособова форма": "无人称形式",
    "1 особа": "第一人称",
    "2 особа": "第二人称",
    "3 особа": "第三人称",
    "особа": "人称",
    "чол. р.": "阳性",
    "жін. р.": "阴性",
    "сер. р.": "中性",
    "чол. р": "阳性",
    "жін. р": "阴性",
    "сер. р": "中性",
    "чол р": "阳性",
    "жін р": "阴性",
    "сер р": "中性",
    "називний": "主格",
    "родовий": "属格",
    "давальний": "与格",
    "знахідний": "宾格",
    "орудний": "工具格",
    "місцевий": "方位格",
    "кличний": "呼格",
    "відмінок": "格",
}
_UK_LABEL_MARKERS = (
    "особа",
    "однина",
    "множина",
    "час",
    "спосіб",
    "форма",
    " р.",
    " р ",
    "інфінітив",
    "назив",
    "родов",
    "даваль",
    "знахід",
    "орудн",
    "місцев",
    "клич",
    "відмінок",
    "безособ",
    "наказов",
)

GOROH_TABLE_STYLE = """
<style>
.lk-goroh-wrap.lk-goroh-v4{width:100%;margin:6px 0 0;overflow-x:auto;box-sizing:border-box}
.lk-goroh-wrap table.goroh-table{width:100%;border-collapse:collapse;table-layout:fixed;
font-size:13px;line-height:1.3;font-family:'Segoe UI','Microsoft YaHei UI',sans-serif;
color:#2b2b2b}
.lk-goroh-wrap table.goroh-table td,.lk-goroh-wrap table.goroh-table th{
border:1px solid #b8caca;padding:5px 8px;vertical-align:middle}
.lk-goroh-wrap tr.subgroup-header td{background:#6d9194;color:#fff;font-weight:700;
text-align:center;padding:6px 8px;font-size:13px;white-space:normal}
.lk-goroh-wrap tr.column-header td{background:#89a5a8;color:#fff;font-weight:600;
text-align:center;padding:5px 8px;white-space:normal}
.lk-goroh-wrap td.cell.header{background:#eef3f3;font-weight:600;color:#333;
white-space:normal;line-height:1.35;word-break:normal}
.lk-goroh-wrap td.cell.light-cell{background:#f0f4f4}
.lk-goroh-wrap td.cell.ta-center{text-align:center}
.lk-goroh-wrap td.cell.form-cell{text-align:center;white-space:normal;word-break:normal}
.lk-goroh-wrap span.word.searched-word{color:#0d47a1;font-weight:700}
.lk-goroh-wrap span.word{white-space:normal}
.lk-goroh-wrap span.lk-goroh-zh{color:#5f6368;font-weight:400;font-size:11px;
line-height:1.25}
.lk-goroh-wrap span.lk-goroh-zh-inline{margin-left:5px}
.lk-goroh-wrap span.lk-goroh-zh-block{display:block;margin-top:2px}
.lk-goroh-wrap tr.subgroup-header td span.lk-goroh-zh,.lk-goroh-wrap tr.column-header td span.lk-goroh-zh{
color:#e8f4ff;font-weight:500}
</style>
"""
_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": "ArgosTranslateLocalGlossary/1.0 (educational; Python requests)",
        "Accept-Language": "uk,zh-CN;q=0.9,en;q=0.7",
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


def slovozmina_url(surface: str) -> str:
    t = (surface or "").strip()
    return (
        GOROH_HOME
        + quote(GOROH_SLOVOZMINA, safe="")
        + "/"
        + quote(t, safe="")
    )


def goroh_home_url() -> str:
    return GOROH_HOME


def _soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


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


def _is_declension_table(rows: list[list[str]]) -> bool:
    if not rows or len(rows[0]) < 2:
        return False
    head_join = " ".join(rows[0]).lower()
    if "відмінок" in head_join or "однина" in head_join or "множина" in head_join:
        return True
    first_col = " ".join(r[0].lower() for r in rows[1:4] if r)
    keys = ("називний", "родовий", "давальний", "знахідний", "орудний", "місцевий", "кличний")
    return any(k in first_col for k in keys)


def _is_conjugation_table(rows: list[list[str]]) -> bool:
    if not rows:
        return False
    blob = " ".join(" ".join(r) for r in rows[:12]).lower()
    keys = (
        "інфінітив",
        "спосіб",
        "особа",
        "минулий",
        "майбутн",
        "наказов",
        "чол. р.",
        "жін. р.",
        "безособова",
    )
    return sum(1 for k in keys if k in blob) >= 2


def _is_inflection_table(rows: list[list[str]]) -> bool:
    return _is_declension_table(rows) or _is_conjugation_table(rows)


def _first_uk_token(text: str) -> str:
    m = _UK_CYR.search((text or "").replace("\u0301", "").replace("\u0300", ""))
    if not m:
        return ""
    return m.group(0).strip()


def extract_lemma_from_table_rows(rows: list[list[str]]) -> str:
    for row in rows:
        if not row:
            continue
        head = (row[0] or "").lower()
        if "інфінітив" in head and len(row) > 1:
            raw = row[1].replace("\u0301", "").replace("\u0300", "").replace("\u030f", "")
            tok = _first_uk_token(raw.split(",")[0])
            if tok:
                return tok
    return ""


def _uk_norm_key(s: str) -> str:
    return re.sub(r"[\u0301\u0300\u030f]", "", (s or "")).lower().replace("'", "'")


def _label_with_zh(text: str, *, stack_zh: bool = False) -> str:
    raw = (text or "").strip()
    if not raw or raw == "\xa0":
        return raw
    low = _uk_norm_key(raw)
    for uk, zh in sorted(_UK_LABEL_ZH.items(), key=lambda x: -len(x[0])):
        if uk == low or uk in low:
            if stack_zh:
                return (
                    f"{html_lib.escape(raw)}"
                    f'<br/><span class="lk-goroh-zh lk-goroh-zh-block">'
                    f"{html_lib.escape(zh)}</span>"
                )
            return (
                f"{html_lib.escape(raw)}"
                f' <span class="lk-goroh-zh lk-goroh-zh-inline">'
                f"{html_lib.escape(zh)}</span>"
            )
    return html_lib.escape(raw)


def _is_uk_goroh_label_cell(cell: str) -> bool:
    s = (cell or "").strip()
    if not s:
        return False
    if not re.search(r"[А-Яа-яІіЇїЄєҐґ]", s):
        return False
    low = _uk_norm_key(s)
    if re.search(r"\d", s) and "особа" in low:
        return True
    return any(m in low for m in _UK_LABEL_MARKERS)


def _is_uk_section_title(cell: str) -> bool:
    s = (cell or "").strip()
    if not s:
        return False
    low = _uk_norm_key(s)
    if low in _UK_LABEL_ZH:
        return True
    return any(m in low for m in ("час", "спосіб", "форма", "відмінок", "причаст", "дееприч"))


def _is_uk_column_header_row(row: list[str]) -> bool:
    cells = [(c or "").strip() for c in row]
    if cells and not cells[0]:
        return any(_uk_norm_key(c) in ("однина", "множина") for c in cells[1:])
    return False


def _format_uk_words_html(text: str, clicked_key: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "&nbsp;"
    parts = [p.strip() for p in re.split(r"\s*,\s*", raw) if p.strip()]
    if not parts:
        return "&nbsp;"
    chunks: list[str] = []
    for i, part in enumerate(parts):
        if i:
            chunks.append(", ")
        cls = "word"
        if clicked_key and _uk_norm_key(part) == clicked_key:
            cls = "word searched-word"
        chunks.append(f'<span class="{cls}">{html_lib.escape(part)}</span>')
    return "".join(chunks)


def _goroh_row_colspan(row: list[str]) -> int:
    return max(3, len([c for c in row if c is not None]))


def _goroh_table_col_count(rows: list[list[str]] | None, rows_html: str = "") -> int:
    n = 3
    if rows:
        for row in rows:
            n = max(n, len(row))
    if rows_html:
        for m in re.finditer(r'colspan="(\d+)"', rows_html, flags=re.I):
            n = max(n, int(m.group(1)))
        tr_chunks = re.findall(r"<tr\b[^>]*>(.*?)</tr>", rows_html, flags=re.I | re.DOTALL)
        for chunk in tr_chunks:
            span = 0
            for m in re.finditer(r'colspan="(\d+)"', chunk, flags=re.I):
                span += int(m.group(1))
            bare = len(re.findall(r"<t[dh]\b", chunk, flags=re.I))
            if span:
                n = max(n, span)
            elif bare:
                n = max(n, bare)
    return max(3, min(n, 6))


def _goroh_colgroup_html(col_count: int) -> str:
    n = max(2, min(int(col_count or 3), 6))
    if n == 2:
        widths = ("32%", "68%")
    elif n == 3:
        widths = ("28%", "36%", "36%")
    elif n == 4:
        widths = ("22%", "26%", "26%", "26%")
    else:
        each = max(12, 100 // n)
        widths = tuple(f"{each}%" for _ in range(n - 1)) + (f"{100 - each * (n - 1)}%",)
    cols = "".join(f'<col width="{w}">' for w in widths)
    return f"<colgroup>{cols}</colgroup>"


def _goroh_table_shell(rows_html: str, *, col_count: int = 3) -> str:
    cg = _goroh_colgroup_html(col_count)
    return (
        GOROH_TABLE_STYLE
        + '<div class="lk-goroh-wrap lk-goroh-v4"><table class="goroh-table" width="100%" '
        'cellspacing="0" cellpadding="0">'
        + cg
        + "<tbody>"
        + rows_html
        + "</tbody></table></div>"
    )


def _sanitize_goroh_td_style(style: str) -> str:
    """去掉 Goroh 原站为大屏写的 padding-right 等，避免侧栏里标签竖排、行高过大。"""
    s = (style or "").strip()
    if not s:
        return ""
    allow: list[str] = []
    for part in s.split(";"):
        part = part.strip()
        if not part:
            continue
        low = part.lower()
        if low.startswith("padding-right") or low.startswith("padding-left"):
            continue
        if low.startswith("padding:") and "110" in low:
            continue
        if low.startswith("text-align"):
            allow.append(part)
        if (
            low.startswith("width")
            or low.startswith("min-width")
            or low.startswith("max-width")
        ):
            continue
    return "; ".join(allow)


def _patch_goroh_table_tag(table_html: str, col_count: int) -> str:
    """为 Qt QTextBrowser 补上 width=100% 与 colgroup，使表随侧栏拉伸。"""
    t = table_html
    if not re.search(r'\bwidth\s*=\s*["\']?100', t, flags=re.I):
        t = re.sub(
            r"<table\b",
            '<table width="100%" cellspacing="0" cellpadding="0"',
            t,
            count=1,
            flags=re.I,
        )
    if "<colgroup" not in t.lower():
        t = re.sub(
            r"(<table\b[^>]*>)",
            r"\1" + _goroh_colgroup_html(col_count),
            t,
            count=1,
            flags=re.I,
        )
    return t


def _refresh_goroh_block_styles(block: str) -> str:
    """缓存里的表内嵌旧 CSS 时，换成当前紧凑样式。"""
    b = (block or "").strip()
    if not b:
        return ""
    b = re.sub(r"<style>.*?</style>", "", b, flags=re.DOTALL | re.I).strip()
    b = re.sub(r"<colgroup>.*?</colgroup>", "", b, flags=re.DOTALL | re.I)
    col_count = _goroh_table_col_count(None, b)
    if "<table" in b:
        b = re.sub(
            r'class="lk-goroh-wrap(?:\s+lk-goroh-v[234])?"',
            'class="lk-goroh-wrap lk-goroh-v4"',
            b,
            count=1,
        )
        if "lk-goroh-v4" not in b and "goroh-table" in b:
            b = '<div class="lk-goroh-wrap lk-goroh-v4">' + b + "</div>"
        b = re.sub(
            r'<table class="goroh-table"[^>]*>',
            lambda m: _patch_goroh_table_tag(m.group(0), col_count),
            b,
            count=1,
            flags=re.I,
        )
    return GOROH_TABLE_STYLE + b


def build_goroh_table_from_rows(
    rows: list[list[str]], clicked: str = ""
) -> str:
    """由 goroh_tables 纯文本行生成带中文标注的 Goroh 风格表。"""
    if not rows:
        return ""
    ck = _uk_norm_key(clicked)
    rows_out: list[str] = []
    for row in rows[:28]:
        cells = [(c or "").strip() for c in row]
        non_empty = [c for c in cells if c]
        if len(non_empty) == 1 and _is_uk_section_title(non_empty[0]):
            title = _label_with_zh(non_empty[0])
            span = _goroh_row_colspan(row)
            rows_out.append(
                f'<tr class="row subgroup-header">'
                f'<td colspan="{span}" class="cell ta-center">{title}</td></tr>'
            )
            continue
        if _is_uk_column_header_row(row):
            rows_out.append('<tr class="row column-header">')
            for c in cells:
                inner = _label_with_zh(c) if (c or "").strip() else "&nbsp;"
                rows_out.append(f'<td class="cell">{inner}</td>')
            rows_out.append("</tr>")
            continue
        if len(non_empty) == 1 and not _is_uk_goroh_label_cell(non_empty[0]):
            inner = _format_uk_words_html(non_empty[0], ck)
            span = _goroh_row_colspan(row)
            rows_out.append(
                f'<tr class="row">'
                f'<td colspan="{span}" class="cell ta-center">{inner}</td></tr>'
            )
            continue
        rows_out.append('<tr class="row">')
        for i, c in enumerate(cells):
            if not c:
                inner = "&nbsp;"
                cls = "cell"
            elif _is_uk_goroh_label_cell(c):
                inner = _label_with_zh(c, stack_zh=True)
                cls = "cell header"
            else:
                inner = _format_uk_words_html(c, ck)
                cls = "cell form-cell light-cell" if i > 0 else "cell form-cell"
            rows_out.append(f'<td class="{cls}">{inner}</td>')
        rows_out.append("</tr>")
    if not rows_out:
        return ""
    body = "".join(rows_out)
    return _goroh_table_shell(body, col_count=_goroh_table_col_count(rows, body))


def ensure_goroh_table_html(data: dict[str, Any], clicked: str = "") -> str:
    """优先用带中文的 goroh_table_html；缺失时由 goroh_tables 生成。"""
    block = (data.get("goroh_table_html") or "").strip()
    if block and "lk-goroh-zh" in block:
        return _refresh_goroh_block_styles(block)
    tables = data.get("goroh_tables") or []
    if isinstance(tables, list) and tables and isinstance(tables[0], list):
        built = build_goroh_table_from_rows(tables[0], clicked=clicked)
        if built:
            return built
    return _refresh_goroh_block_styles(block) if block else ""


def _td_inner_html(td: Tag, *, clicked_key: str) -> str:
    classes = td.get("class") or []
    if "header" in classes and "ta-center" not in classes:
        return _label_with_zh(td.get_text(" ", strip=True), stack_zh=True)
    if "ta-center" in classes and len(td.get_text(strip=True)) < 48:
        return _label_with_zh(td.get_text(" ", strip=True))
    chunks: list[str] = []
    for child in td.children:
        if isinstance(child, NavigableString):
            chunks.append(html_lib.escape(str(child)))
            continue
        if not isinstance(child, Tag):
            continue
        if child.name == "span" and "word" in (child.get("class") or []):
            wtxt = child.get_text(strip=True)
            cls = ["word"]
            if clicked_key and _uk_norm_key(wtxt) == clicked_key:
                cls.append("searched-word")
            elif "searched-word" in (child.get("class") or []):
                cls.append("searched-word")
            title = child.get("title")
            tit = f' title="{html_lib.escape(title)}"' if title else ""
            chunks.append(
                f'<span class="{" ".join(cls)}"{tit}>{html_lib.escape(wtxt)}</span>'
            )
        else:
            chunks.append(str(child))
    return "".join(chunks) or "&nbsp;"


def build_goroh_table_html(page_html: str, clicked: str = "") -> str:
    """按 goroh.pp.ua 页面结构复刻变位/变格表（保留重音、样式接近官网）。"""
    soup = _soup(page_html)
    table = soup.select_one("div.table-wrapper table.table") or soup.find(
        "table", class_="table"
    )
    if not table:
        return ""
    ck = _uk_norm_key(clicked)
    rows_out: list[str] = []
    for tr in table.find_all("tr"):
        tr_cls = " ".join(tr.get("class") or []) or "row"
        is_col_header = "column-header" in tr_cls
        cells: list[str] = []
        for td in tr.find_all(["td", "th"], recursive=False):
            td_cls = " ".join(td.get("class") or []) or "cell"
            if is_col_header and (td.get_text(strip=True) or "").strip():
                td_cls = (td_cls + " ta-center").strip()
            colspan = td.get("colspan")
            rowspan = td.get("rowspan")
            style = _sanitize_goroh_td_style(td.get("style") or "")
            attrs = [f'class="{html_lib.escape(td_cls)}"']
            if colspan:
                attrs.append(f'colspan="{colspan}"')
            if rowspan:
                attrs.append(f'rowspan="{rowspan}"')
            if style:
                attrs.append(f'style="{html_lib.escape(style)}"')
            title = td.get("title")
            if title:
                attrs.append(f'title="{html_lib.escape(title)}"')
            if is_col_header:
                inner = _label_with_zh(td.get_text(" ", strip=True))
            else:
                inner = _td_inner_html(td, clicked_key=ck)
            cells.append(f"<td {' '.join(attrs)}>{inner}</td>")
        rows_out.append(f'<tr class="{html_lib.escape(tr_cls)}">{"".join(cells)}</tr>')
    if not rows_out:
        return ""
    body = "".join(rows_out)
    return _goroh_table_shell(body, col_count=_goroh_table_col_count(None, body))


def extract_lemma_from_html(html: str, tables: list[list[list[str]]] | None = None) -> str:
    soup = _soup(html)
    table = soup.select_one("div.table-wrapper table.table") or soup.find(
        "table", class_="table"
    )
    if table:
        for tr in table.find_all("tr"):
            td0 = tr.find("td", class_=lambda c: c and "header" in (c if isinstance(c, list) else [c]))
            if td0 and "інфінітив" in td0.get_text().lower():
                sp = tr.find("span", class_=lambda c: c and "word" in c)
                if sp:
                    return sp.get_text(strip=True)
    for tbl in tables or []:
        lem = extract_lemma_from_table_rows(tbl)
        if lem:
            return lem
    for tag in soup.find_all(["h1", "h2", "h3"]):
        t = tag.get_text(" ", strip=True)
        if _uk_norm_key(t):
            return t
    return ""


def parse_inflection_tables_from_html(html: str, limit: int = 4) -> list[list[list[str]]]:
    soup = _soup(html)
    root = (
        soup.find("div", id="mw-content-text")
        or soup.find("div", class_=re.compile(r"mw-parser-output"))
        or soup.find("article")
        or soup.find("main")
        or soup
    )
    out: list[list[list[str]]] = []
    for table in root.find_all("table"):
        rows = _table_to_rows(table)
        if rows and _is_inflection_table(rows):
            out.append(rows)
        if len(out) >= limit:
            break
    return out


def parse_declension_tables_from_html(html: str, limit: int = 4) -> list[list[list[str]]]:
    return parse_inflection_tables_from_html(html, limit=limit)


def _goroh_lookup_surface(surface: str) -> str:
    return re.sub(r"[\u0301\u0300\u030f]", "", (surface or "").strip())


def fetch_slovozmina_tables(surface: str, timeout: float = 14.0) -> dict[str, Any]:
    """
    返回 goroh_url、goroh_tables（名词变格 / 动词变位）、goroh_lemma（原形，多为不定式）。
    变位页：https://goroh.pp.ua/Словозміна/<词形>
    """
    w = _goroh_lookup_surface(surface)
    out: dict[str, Any] = {
        "goroh_url": slovozmina_url(w),
        "goroh_lemma_url": slovozmina_url(w),
        "goroh_lemma": "",
        "goroh_tables": [],
        "goroh_table_html": "",
        "goroh_fetch_error": None,
    }
    if not w:
        out["goroh_fetch_error"] = "空词"
        return out

    key = w.lower()
    _ensure_cache()
    if key in _CACHE:
        hit = dict(_CACHE[key])
        hit["goroh_url"] = slovozmina_url(w)
        lem = (hit.get("goroh_lemma") or "").strip()
        if lem:
            hit["goroh_lemma_url"] = slovozmina_url(lem)
        else:
            hit["goroh_lemma_url"] = hit["goroh_url"]
        hit["goroh_table_html"] = ensure_goroh_table_html(hit, clicked=w)
        return hit

    time.sleep(0.22)
    try:
        r = _SESSION.get(out["goroh_url"], timeout=timeout)
        r.raise_for_status()
        tables = parse_inflection_tables_from_html(r.text)
        lemma = extract_lemma_from_html(r.text, tables)
        out["goroh_tables"] = tables
        out["goroh_table_html"] = build_goroh_table_html(r.text, clicked=w)
        if not out["goroh_table_html"] and tables:
            out["goroh_table_html"] = build_goroh_table_from_rows(tables[0], clicked=w)
        out["goroh_lemma"] = lemma
        if lemma:
            out["goroh_lemma_url"] = slovozmina_url(lemma)
        if not tables and not out["goroh_table_html"]:
            out["goroh_fetch_error"] = "页面无变格/变位表（可能无此词或标题不同）"
    except Exception as e:
        out["goroh_fetch_error"] = str(e)

    _CACHE[key] = {
        k: v
        for k, v in out.items()
        if k not in ("goroh_url", "goroh_lemma_url")
    }
    if out.get("goroh_table_html"):
        _CACHE[key]["goroh_table_html"] = out["goroh_table_html"]
    try:
        _write_cache()
    except OSError:
        pass
    out["goroh_lemma_url"] = (
        slovozmina_url(out["goroh_lemma"]) if out.get("goroh_lemma") else out["goroh_url"]
    )
    return out
