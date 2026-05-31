"""
查词本地缓存与生词本（按「语言|单词」去重，最新查阅在前）。
数据：data/config/word_lookup_notebook.json
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from terminology_bridge import portable_root

_LANG_LABEL = {"ru": "俄语", "uk": "乌克兰语"}

_EXPORT_FIELDS = (
    "looked_at",
    "first_at",
    "look_count",
    "lang",
    "lang_label",
    "word",
    "lemma",
    "meaning",
    "sentence_zh",
)


def notebook_path():
    p = portable_root() / "data" / "config" / "word_lookup_notebook.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now_str() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def normalize_word(word: str) -> str:
    return (word or "").strip()


def make_key(lang: str, word: str) -> str:
    lg = (lang or "").strip().lower()
    w = normalize_word(word).lower()
    return f"{lg}|{w}"


def _load_raw() -> dict[str, Any]:
    path = notebook_path()
    if not path.is_file():
        return {"version": 1, "entries": []}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "entries": []}
    if not isinstance(raw, dict):
        return {"version": 1, "entries": []}
    entries = raw.get("entries")
    if not isinstance(entries, list):
        entries = []
    return {"version": 1, "entries": [e for e in entries if isinstance(e, dict)]}


def _save_raw(data: dict[str, Any]) -> None:
    path = notebook_path()
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def load_entries() -> list[dict[str, Any]]:
    return list(_load_raw().get("entries") or [])


def load_entries_for_lang(lang: str) -> list[dict[str, Any]]:
    """按语系筛选（ru / uk）。"""
    lg = (lang or "").strip().lower()
    if not lg:
        return load_entries()
    return [
        e
        for e in load_entries()
        if (e.get("lang") or "").strip().lower() == lg
    ]


def get_entry(lang: str, word: str) -> dict[str, Any] | None:
    key = make_key(lang, word)
    for e in load_entries():
        if (e.get("key") or "") == key:
            return dict(e)
    return None


def _meaning_preview(meaning: str, *, max_len: int = 80) -> str:
    t = re.sub(r"\s+", " ", (meaning or "").strip())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def upsert_entry(
    *,
    lang: str,
    word: str,
    lemma: str = "",
    meaning: str = "",
    sentence_zh: str = "",
    panel_html: str = "",
    max_entries: int = 3000,
) -> dict[str, Any]:
    """写入或更新一条记录（同词不重复，刷新时间与内容并移到列表最前）。"""
    w = normalize_word(word)
    if not w:
        return {}
    key = make_key(lang, w)
    now = _now_str()
    data = _load_raw()
    entries: list[dict[str, Any]] = list(data.get("entries") or [])
    kept = [e for e in entries if (e.get("key") or "") != key]
    old = next((e for e in entries if (e.get("key") or "") == key), None)
    look_count = int((old or {}).get("look_count") or 0) + 1
    first_at = (old or {}).get("first_at") or now
    entry: dict[str, Any] = {
        "key": key,
        "lang": (lang or "").strip().lower(),
        "word": w,
        "lemma": (lemma or "").strip(),
        "meaning": (meaning or "").strip(),
        "meaning_preview": _meaning_preview(meaning),
        "sentence_zh": (sentence_zh or "").strip(),
        "panel_html": (panel_html or "").strip(),
        "first_at": first_at,
        "looked_at": now,
        "look_count": look_count,
    }
    kept.insert(0, entry)
    data["entries"] = kept[:max_entries]
    _save_raw(data)
    return entry


def touch_entry(lang: str, word: str) -> None:
    """命中缓存再次点击：仅更新查阅时间与次数。"""
    key = make_key(lang, word)
    data = _load_raw()
    entries: list[dict[str, Any]] = list(data.get("entries") or [])
    hit = None
    rest: list[dict[str, Any]] = []
    for e in entries:
        if (e.get("key") or "") == key:
            hit = dict(e)
        else:
            rest.append(e)
    if hit is None:
        return
    hit["looked_at"] = _now_str()
    hit["look_count"] = int(hit.get("look_count") or 0) + 1
    rest.insert(0, hit)
    data["entries"] = rest
    _save_raw(data)


def delete_entry(lang: str, word: str) -> None:
    key = make_key(lang, word)
    data = _load_raw()
    data["entries"] = [e for e in data.get("entries") or [] if (e.get("key") or "") != key]
    _save_raw(data)


def clear_all_entries() -> int:
    """删除生词本全部词条，返回删除前的条数。"""
    data = _load_raw()
    n = len(data.get("entries") or [])
    data["entries"] = []
    _save_raw(data)
    return n


def clear_entries_for_lang(lang: str) -> int:
    """删除某一语系的全部词条，返回删除条数。"""
    lg = (lang or "").strip().lower()
    if not lg:
        return 0
    data = _load_raw()
    before = list(data.get("entries") or [])
    kept = [e for e in before if (e.get("lang") or "").strip().lower() != lg]
    n_removed = len(before) - len(kept)
    if n_removed:
        data["entries"] = kept
        _save_raw(data)
    return n_removed


def _entry_for_export(e: dict[str, Any]) -> dict[str, Any]:
    lg = str(e.get("lang") or "")
    return {
        "looked_at": e.get("looked_at") or "",
        "first_at": e.get("first_at") or "",
        "look_count": e.get("look_count") or 0,
        "lang": lg,
        "lang_label": _LANG_LABEL.get(lg, lg),
        "word": e.get("word") or "",
        "lemma": e.get("lemma") or "",
        "meaning": e.get("meaning") or "",
        "sentence_zh": e.get("sentence_zh") or "",
    }


def export_entries_to_csv(
    path: str | Path, entries: list[dict[str, Any]] | None = None
) -> int:
    """导出为 CSV（UTF-8 BOM，便于 Excel 打开）。"""
    entries = entries if entries is not None else load_entries()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(_EXPORT_FIELDS)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        for e in entries:
            w.writerow(_entry_for_export(e))
    return len(entries)


def export_entries_to_json(
    path: str | Path,
    *,
    include_html: bool = False,
    entries: list[dict[str, Any]] | None = None,
) -> int:
    """导出为 JSON（默认不含 panel_html，体积更小）。"""
    entries = entries if entries is not None else load_entries()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out_list: list[dict[str, Any]] = []
    for e in entries:
        row = _entry_for_export(e)
        if include_html:
            row["panel_html"] = e.get("panel_html") or ""
        out_list.append(row)
    payload = {
        "version": 1,
        "exported_at": _now_str(),
        "count": len(out_list),
        "entries": out_list,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return len(entries)


def export_entries_to_txt(
    path: str | Path, entries: list[dict[str, Any]] | None = None
) -> int:
    """导出为纯文本，便于打印或阅读。"""
    entries = entries if entries is not None else load_entries()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "生词本导出",
        f"导出时间：{_now_str()}",
        f"词条数：{len(entries)}",
        "",
    ]
    for i, e in enumerate(entries, 1):
        ex = _entry_for_export(e)
        lines.append(f"—— {i}. {ex['word']} ({ex['lang_label']}) ——")
        if ex["lemma"] and ex["lemma"] != ex["word"]:
            lines.append(f"原形：{ex['lemma']}")
        lines.append(f"最近查阅：{ex['looked_at']}（共 {ex['look_count']} 次）")
        lines.append("词义：")
        for ln in (ex["meaning"] or "").splitlines():
            if ln.strip():
                lines.append(f"  {ln.strip()}")
        if ex["sentence_zh"]:
            lines.append(f"例句（中文）：{ex['sentence_zh']}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return len(entries)


def export_entries(path: str | Path, *, lang: str | None = None) -> int:
    """按扩展名自动选择格式：.csv / .json / 其余为 .txt。lang 指定时仅导出该语系。"""
    path = Path(path)
    entries = load_entries_for_lang(lang) if lang else load_entries()
    suf = path.suffix.lower()
    if suf == ".csv":
        return export_entries_to_csv(path, entries)
    if suf == ".json":
        return export_entries_to_json(path, entries=entries)
    if not suf:
        path = path.with_suffix(".txt")
    return export_entries_to_txt(path, entries)
