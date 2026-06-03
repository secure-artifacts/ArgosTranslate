"""TM 导入 / 导出（JSON / JSONL / CSV，本地文件）。"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_pipeline.config import TM_DB
from corpus_pipeline.quality import normalize_source_for_storage
from corpus_pipeline.tm_store import (
    TMEntry,
    count_entries,
    delete_all_entries,
    delete_entries,
    delete_filtered,
    delete_lang_pair,
    insert_pairs,
    iter_entries,
)


def _normalize_lang_pair(
    source_lang: str | None,
    target_lang: str | None,
) -> tuple[str | None, str | None]:
    from bidirectional_terminology import lookup_tm_langs

    if not source_lang and not target_lang:
        return None, None
    sl_in = (source_lang or "zh").strip()
    tl_in = (target_lang or "ru").strip()
    return lookup_tm_langs(sl_in, tl_in)


def _entry_to_dict(e: TMEntry) -> dict[str, Any]:
    return {
        "source_text": e.source_text,
        "target_text": e.target_text,
        "source_lang": e.source_lang,
        "target_lang": e.target_lang,
        "domain": e.domain or "",
        "confidence_score": float(e.confidence_score),
        "source_url": e.source_url or "",
        "tm_purity_score": float(e.tm_purity_score),
    }


def export_tm(
    path: str | Path,
    *,
    source_lang: str | None = None,
    target_lang: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """导出 TM 到 json / jsonl / csv。"""
    p = Path(path)
    sl, tl = _normalize_lang_pair(source_lang, target_lang)
    entries = iter_entries(source_lang=sl, target_lang=tl, db_path=db_path)
    rows = [_entry_to_dict(e) for e in entries]
    meta = {
        "format": "argos_tm_export",
        "version": 1,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(rows),
        "filter": {"source_lang": sl, "target_lang": tl},
        "db": str(db_path or TM_DB),
    }
    suffix = p.suffix.lower()
    p.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".jsonl":
        with open(p, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    elif suffix == ".csv":
        with open(p, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "source_text",
                    "target_text",
                    "source_lang",
                    "target_lang",
                    "domain",
                    "confidence_score",
                    "tm_purity_score",
                    "source_url",
                ]
            )
            for row in rows:
                w.writerow(
                    [
                        row["source_text"],
                        row["target_text"],
                        row["source_lang"],
                        row["target_lang"],
                        row.get("domain") or "",
                        row.get("confidence_score") or "",
                        row.get("tm_purity_score") or "",
                        row.get("source_url") or "",
                    ]
                )
    else:
        payload = {"meta": meta, "entries": rows}
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "path": str(p), "count": len(rows), "meta": meta}


def _dict_to_entry(row: dict[str, Any]) -> TMEntry | None:
    src = (row.get("source_text") or row.get("source") or "").strip()
    tgt = (row.get("target_text") or row.get("target") or "").strip()
    sl = (row.get("source_lang") or row.get("src_lang") or "").strip().lower()
    tl = (row.get("target_lang") or row.get("tgt_lang") or "").strip().lower()
    if not src or not tgt or not sl or not tl:
        return None
    from bidirectional_terminology import lookup_tm_langs

    sl, _ = lookup_tm_langs(sl, tl)
    _, tl = lookup_tm_langs(sl, tl)
    return TMEntry(
        source_text=src,
        target_text=tgt,
        source_lang=sl,
        target_lang=tl,
        domain=str(row.get("domain") or "import"),
        confidence_score=float(row.get("confidence_score") or 0.85),
        source_url=str(row.get("source_url") or "import"),
        tm_purity_score=float(row.get("tm_purity_score") or 0.80),
    )


def _load_rows_from_file(
    path: Path,
    *,
    default_source_lang: str = "",
    default_target_lang: str = "",
) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8-sig")
    if suffix == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows
    if suffix == ".csv":
        rows = []
        reader = csv.DictReader(text.splitlines())
        for row in reader:
            if not row:
                continue
            src = (row.get("source_text") or row.get("source") or "").strip()
            tgt = (row.get("target_text") or row.get("target") or "").strip()
            if not src or not tgt:
                continue
            sl = (
                row.get("source_lang")
                or row.get("src_lang")
                or default_source_lang
            )
            tl = (
                row.get("target_lang")
                or row.get("tgt_lang")
                or default_target_lang
            )
            rows.append({**row, "source_text": src, "target_text": tgt,
                         "source_lang": sl, "target_lang": tl})
        return rows
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("entries") or data.get("pairs") or [])
    return []


def _normalize_header_cell(cell: str) -> str:
    return (cell or "").strip().lower().replace(" ", "_")


def _header_field_map(cells: list[str]) -> dict[str, int] | None:
    """识别表头列：source_text / target_text / 原文 / 译文 等。"""
    aliases: dict[str, set[str]] = {
        "source_text": {
            "source_text",
            "source",
            "src",
            "原文",
            "中文",
            "汉语",
            "源文",
            "源文本",
        },
        "target_text": {
            "target_text",
            "target",
            "tgt",
            "译文",
            "翻译",
            "俄语",
            "俄文",
            "乌克兰语",
            "乌语",
        },
        "source_lang": {"source_lang", "src_lang", "源语", "源语言"},
        "target_lang": {"target_lang", "tgt_lang", "目标语", "目标语言", "语言"},
    }
    norm = [_normalize_header_cell(c) for c in cells]
    idx: dict[str, int] = {}
    for i, name in enumerate(norm):
        if not name:
            continue
        for field, names in aliases.items():
            if name in names or name.replace("_", "") in {
                n.replace("_", "") for n in names
            }:
                idx.setdefault(field, i)
    if "source_text" in idx and "target_text" in idx:
        return idx
    return None


def _split_table_line(line: str) -> list[str]:
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    if ";" in line and line.count(";") >= 1:
        return [c.strip() for c in line.split(";")]
    if "," in line and line.count(",") >= 1:
        try:
            return [c.strip() for c in next(csv.reader([line]))]
        except csv.Error:
            pass
    parts = [line.strip()]
    return parts


def parse_table_text(
    text: str,
    *,
    default_source_lang: str = "",
    default_target_lang: str = "",
) -> list[dict[str, Any]]:
    """
    解析 Google 表格 / Excel 复制的表格文本（TSV 为主）。
    支持两列（原文\\t译文）或带表头多列。
    """
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return []
    lines = [ln for ln in raw.split("\n") if ln.strip()]
    if not lines:
        return []

    header_map: dict[str, int] | None = None
    start = 0
    first_cells = _split_table_line(lines[0])
    if len(first_cells) >= 2:
        header_map = _header_field_map(first_cells)
        if header_map is not None:
            start = 1

    rows: list[dict[str, Any]] = []
    for line in lines[start:]:
        cells = _split_table_line(line)
        if len(cells) < 2:
            continue
        row: dict[str, Any] = {}
        if header_map is not None:
            si = header_map.get("source_text", 0)
            ti = header_map.get("target_text", 1)
            src = cells[si] if si < len(cells) else ""
            tgt = cells[ti] if ti < len(cells) else ""
            if "source_lang" in header_map:
                li = header_map["source_lang"]
                if li < len(cells):
                    row["source_lang"] = cells[li]
            if "target_lang" in header_map:
                li = header_map["target_lang"]
                if li < len(cells):
                    row["target_lang"] = cells[li]
        else:
            src = cells[0]
            tgt = cells[1]
            if len(cells) >= 4:
                row["source_lang"] = cells[2]
                row["target_lang"] = cells[3]
        src = (src or "").strip()
        tgt = (tgt or "").strip()
        if not src or not tgt:
            continue
        if not row.get("source_lang") and default_source_lang:
            row["source_lang"] = default_source_lang
        if not row.get("target_lang") and default_target_lang:
            row["target_lang"] = default_target_lang
        row["source_text"] = src
        row["target_text"] = tgt
        rows.append(row)
    return rows


def import_tm_from_table_text(
    text: str,
    *,
    default_source_lang: str = "",
    default_target_lang: str = "",
    quality_gate: bool = False,
    skip_noisy: bool = False,
    bidirectional: bool = True,
    db_path: Path | None = None,
    contributor: str = "google_sheets",
) -> dict[str, Any]:
    """从 Google 表格等复制的 TSV/CSV 文本导入 TM。"""
    raw_rows = parse_table_text(
        text,
        default_source_lang=default_source_lang,
        default_target_lang=default_target_lang,
    )
    if not raw_rows:
        return {
            "ok": False,
            "reason": "no_rows",
            "parsed": 0,
        }
    seen_source_keys: set[str] = set()
    entries, parsed, dup = _rows_to_entries(
        raw_rows,
        default_source_lang=default_source_lang,
        default_target_lang=default_target_lang,
        bidirectional=bidirectional,
        seen_source_keys=seen_source_keys,
        contributor=contributor,
    )
    added, skipped, quarantined = insert_pairs(
        entries,
        db_path=db_path,
        skip_noisy=skip_noisy,
        quality_gate=quality_gate,
    )
    return {
        "ok": True,
        "mode": "table_paste",
        "parsed": parsed,
        "dup_skipped": dup,
        "batch_size": len(entries),
        "added": added,
        "skipped": skipped,
        "quarantined": quarantined,
        "total_in_db": count_entries(db_path=db_path),
    }


def _source_side_key(entry: TMEntry) -> str:
    """与库内 UNIQUE(source_lang, target_lang, source_text) 一致的去重键。"""
    src_store = normalize_source_for_storage(entry.source_text, entry.source_lang)
    return f"{entry.source_lang}|{entry.target_lang}|{src_store}"


def _expand_import_paths(paths: list[str | Path]) -> list[Path]:
    """展开文件列表；目录则收集其下 json/jsonl/csv。"""
    out: list[Path] = []
    seen_paths: set[str] = set()
    for raw in paths:
        p = Path(raw)
        candidates: list[Path] = []
        if p.is_dir():
            for ext in ("*.json", "*.jsonl", "*.csv"):
                candidates.extend(sorted(p.glob(ext)))
        elif p.is_file():
            candidates.append(p)
        for c in candidates:
            key = str(c.resolve()).lower()
            if key in seen_paths:
                continue
            seen_paths.add(key)
            out.append(c)
    return out


def _entry_with_contributor(entry: TMEntry, contributor: str) -> TMEntry:
    label = (contributor or "").strip()
    if not label:
        return entry
    url = (entry.source_url or "").strip()
    if not url or url == "import":
        return TMEntry(
            source_text=entry.source_text,
            target_text=entry.target_text,
            source_lang=entry.source_lang,
            target_lang=entry.target_lang,
            domain=entry.domain,
            confidence_score=entry.confidence_score,
            source_url=label,
            tm_purity_score=entry.tm_purity_score,
        )
    return entry


def _rows_to_entries(
    raw_rows: list[dict[str, Any]],
    *,
    default_source_lang: str = "",
    default_target_lang: str = "",
    bidirectional: bool = True,
    seen_source_keys: set[str],
    contributor: str = "",
) -> tuple[list[TMEntry], int, int]:
    """解析行并跨文件按源句去重。返回 (entries, parsed, dup_skipped)。"""
    batch: list[TMEntry] = []
    parsed = 0
    dup_skipped = 0

    def _try_add(entry: TMEntry | None) -> None:
        nonlocal dup_skipped
        if entry is None:
            return
        entry = _entry_with_contributor(entry, contributor)
        key = _source_side_key(entry)
        if key in seen_source_keys:
            dup_skipped += 1
            return
        seen_source_keys.add(key)
        batch.append(entry)

    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        if not row.get("source_lang") and default_source_lang:
            row["source_lang"] = default_source_lang
        if not row.get("target_lang") and default_target_lang:
            row["target_lang"] = default_target_lang
        entry = _dict_to_entry(row)
        if entry is None:
            continue
        parsed += 1
        _try_add(entry)
        if bidirectional:
            from bidirectional_terminology import is_bidirectional_pair

            if is_bidirectional_pair(entry.source_lang, entry.target_lang):
                _try_add(
                    TMEntry(
                        source_text=entry.target_text,
                        target_text=entry.source_text,
                        source_lang=entry.target_lang,
                        target_lang=entry.source_lang,
                        domain=entry.domain,
                        confidence_score=max(0.75, entry.confidence_score * 0.95),
                        source_url=entry.source_url,
                        tm_purity_score=entry.tm_purity_score,
                    )
                )
    return batch, parsed, dup_skipped


def import_tm_batch(
    paths: list[str | Path],
    *,
    default_source_lang: str = "",
    default_target_lang: str = "",
    quality_gate: bool = False,
    skip_noisy: bool = False,
    bidirectional: bool = True,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """
    批量导入 TM（多人 / 多文件 / 目录）。
    同一语言对下相同原文只保留首次出现，与库内已有句对也不重叠写入。
    """
    expanded = _expand_import_paths(paths)
    if not expanded:
        return {
            "ok": False,
            "reason": "no_files",
            "paths": [str(p) for p in paths],
        }

    seen_source_keys: set[str] = set()
    batch: list[TMEntry] = []
    file_results: list[dict[str, Any]] = []
    total_parsed = 0
    total_dup = 0

    for p in expanded:
        if not p.is_file():
            file_results.append(
                {"path": str(p), "ok": False, "reason": "file_not_found"}
            )
            continue
        raw_rows = _load_rows_from_file(
            p,
            default_source_lang=default_source_lang,
            default_target_lang=default_target_lang,
        )
        entries, parsed, dup = _rows_to_entries(
            raw_rows,
            default_source_lang=default_source_lang,
            default_target_lang=default_target_lang,
            bidirectional=bidirectional,
            seen_source_keys=seen_source_keys,
            contributor=p.stem,
        )
        batch.extend(entries)
        total_parsed += parsed
        total_dup += dup
        file_results.append(
            {
                "path": str(p),
                "ok": True,
                "parsed": parsed,
                "dup_skipped": dup,
                "queued": len(entries),
            }
        )

    added, skipped, quarantined = insert_pairs(
        batch,
        db_path=db_path,
        skip_noisy=skip_noisy,
        quality_gate=quality_gate,
    )
    return {
        "ok": True,
        "files": len(expanded),
        "file_results": file_results,
        "parsed": total_parsed,
        "dup_skipped": total_dup,
        "batch_size": len(batch),
        "added": added,
        "skipped": skipped,
        "quarantined": quarantined,
        "total_in_db": count_entries(db_path=db_path),
    }


def import_tm(
    path: str | Path,
    *,
    default_source_lang: str = "",
    default_target_lang: str = "",
    quality_gate: bool = False,
    skip_noisy: bool = False,
    bidirectional: bool = True,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """
    从 json / jsonl / csv 导入 TM。
    CSV 可省略语言列，使用 default_source_lang / default_target_lang（通常为当前界面语言对）。
    """
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "reason": "file_not_found", "path": str(p)}

    result = import_tm_batch(
        [p],
        default_source_lang=default_source_lang,
        default_target_lang=default_target_lang,
        quality_gate=quality_gate,
        skip_noisy=skip_noisy,
        bidirectional=bidirectional,
        db_path=db_path,
    )
    if not result.get("ok"):
        return result
    fr = (result.get("file_results") or [{}])[0]
    return {
        "ok": True,
        "path": str(p),
        "parsed": fr.get("parsed", result.get("parsed", 0)),
        "dup_skipped": fr.get("dup_skipped", result.get("dup_skipped", 0)),
        "batch_size": result.get("batch_size", 0),
        "added": result.get("added", 0),
        "skipped": result.get("skipped", 0),
        "quarantined": result.get("quarantined", 0),
        "total_in_db": result.get("total_in_db", 0),
    }


def tm_stats(db_path: Path | None = None) -> dict[str, Any]:
    return {
        "total": count_entries(db_path=db_path),
        "db": str(db_path or TM_DB),
    }


def delete_tm(
    *,
    entries: list[dict[str, Any]] | None = None,
    source_lang: str | None = None,
    target_lang: str | None = None,
    delete_all: bool = False,
    delete_reverse: bool = True,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """从 TM 删除句对：按条目列表，或按语言对/整库全部删除。"""
    if delete_all:
        sl_in = (source_lang or "").strip()
        tl_in = (target_lang or "").strip()
        if not sl_in and not tl_in:
            deleted = delete_all_entries(db_path=db_path)
            return {
                "ok": True,
                "deleted": deleted,
                "mode": "entire_db",
                "total_in_db": count_entries(db_path=db_path),
            }
        from corpus_pipeline.lang_filter import pair_filter_codes

        sl, tl = pair_filter_codes(sl_in, tl_in)
        if sl and tl:
            deleted = delete_lang_pair(
                sl,
                tl,
                db_path=db_path,
                bidirectional=delete_reverse,
            )
            return {
                "ok": True,
                "deleted": deleted,
                "mode": "lang_pair",
                "filter": {"source_lang": sl, "target_lang": tl},
                "total_in_db": count_entries(db_path=db_path),
            }
        deleted = delete_filtered(
            source_lang=sl,
            target_lang=tl,
            db_path=db_path,
        )
        return {
            "ok": True,
            "deleted": deleted,
            "mode": "filtered",
            "filter": {"source_lang": sl, "target_lang": tl},
            "total_in_db": count_entries(db_path=db_path),
        }

    batch: list[TMEntry] = []
    for row in entries or []:
        entry = _dict_to_entry(row)
        if entry is not None:
            batch.append(entry)
    if not batch:
        return {"ok": False, "error": "未指定可删除的 TM 条目"}
    deleted = delete_entries(
        batch,
        db_path=db_path,
        delete_reverse=delete_reverse,
    )
    return {
        "ok": True,
        "deleted": deleted,
        "requested": len(batch),
        "total_in_db": count_entries(db_path=db_path),
    }
