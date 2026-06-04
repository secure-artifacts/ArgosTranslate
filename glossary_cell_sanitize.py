"""术语库单元格：清理从 Google 表格 / Excel 粘贴带来的引号与空值标记。"""
from __future__ import annotations

import csv
import io
import re


def sanitize_glossary_cell(text: str) -> str:
    """
    去掉粘贴时常见的 ""、外层引号、BOM、不换行空格等。
    Google 表格复制空单元格时，剪贴板里有时会出现字面量 \"\"\"。
    """
    if text is None:
        return ""
    t = str(text).replace("\ufeff", "")
    t = re.sub(r"[\u200b-\u200d\ufeff]", "", t)
    t = t.replace("\u00a0", " ").strip()
    if not t:
        return ""
    if t in ('""', "''", '"""""', "“”", "''"):
        return ""
    if t.replace('"', "").replace("'", "").strip() == "":
        return ""
    while len(t) >= 2 and t[0] == t[-1] == '"':
        t = t[1:-1].replace('""', '"').strip()
    while len(t) >= 2 and t[0] == t[-1] == "'":
        t = t[1:-1].strip()
    if t.startswith('""'):
        t = t[2:].lstrip()
    if t.endswith('""'):
        t = t[:-2].rstrip()
    if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
        t = t[1:-1].replace('""', '"').strip()
    return t.strip()


def parse_clipboard_table(text: str) -> list[list[str]]:
    """解析剪贴板 TSV/CSV 为二维表（每格已 sanitize）。"""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return []
    first_line = raw.split("\n", 1)[0]
    if "\t" in first_line:
        delim = "\t"
    elif first_line.count(",") >= first_line.count(";"):
        delim = ","
    else:
        delim = ";"
    reader = csv.reader(
        io.StringIO(raw),
        delimiter=delim,
        quotechar='"',
        skipinitialspace=True,
    )
    rows: list[list[str]] = []
    for row in reader:
        cells = [sanitize_glossary_cell(c) for c in row]
        if any(cells):
            rows.append(cells)
    return expand_single_column_multiline_rows(rows)


def expand_single_column_multiline_rows(
    rows: list[list[str]],
) -> list[list[str]]:
    """
    单列多行粘贴、或单格内含换行（Google 表格 Alt+Enter）时展开为多行。
    """
    if not rows:
        return []
    max_cols = max(len(r) for r in rows)
    if max_cols != 1:
        return rows
    if len(rows) == 1:
        inner = rows[0][0]
        if "\n" not in inner:
            return rows
        lines = [
            sanitize_glossary_cell(ln)
            for ln in inner.split("\n")
            if sanitize_glossary_cell(ln)
        ]
        return [[ln] for ln in lines] if len(lines) > 1 else rows
    if len(rows) > 1:
        return rows
    return rows
