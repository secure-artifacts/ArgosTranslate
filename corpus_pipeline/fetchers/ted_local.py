"""TED 字幕本地导入（data/corpus/raw/ted/*.srt 或 *.json）。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from corpus_pipeline.config import RAW
from corpus_pipeline.fetchers.base import BaseFetcher, FetchResult, ParallelDocument

_SRT_BLOCK = re.compile(
    r"\d+\s*\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n([\s\S]*?)(?=\n\d+\n|\Z)"
)


class TedLocalFetcher(BaseFetcher):
    name = "ted"

    def fetch(self, *, max_pages: int = 5000) -> FetchResult:
        result = FetchResult()
        root = RAW / "ted"
        if not root.is_dir():
            result.errors.append(
                f"缺少 {root}；请将 TED 双语字幕放入 ted/en-zh 或 ted/ru-zh 目录"
            )
            return result
        n = 0
        for path in sorted(root.rglob("*")):
            if n >= max_pages:
                break
            if path.suffix.lower() == ".srt":
                pairs = _read_srt_pair(path)
                lang = "ru" if "ru" in str(path).lower() else "en"
                for src, tgt in pairs:
                    result.documents.append(
                        ParallelDocument(
                            url=str(path),
                            source_lang=lang,
                            target_lang="zh",
                            source_text=src,
                            target_text=tgt,
                            domain="ted",
                        )
                    )
                    n += 1
            elif path.suffix.lower() == ".json":
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as e:
                    result.errors.append(str(e))
                    continue
                for item in data if isinstance(data, list) else []:
                    if not isinstance(item, dict):
                        continue
                    src = str(item.get("source") or item.get("ru") or "").strip()
                    tgt = str(item.get("zh") or item.get("target") or "").strip()
                    if src and tgt:
                        result.documents.append(
                            ParallelDocument(
                                url=str(path),
                                source_lang="ru",
                                target_lang="zh",
                                source_text=src,
                                target_text=tgt,
                                domain="ted",
                            )
                        )
                        n += 1
        return result


def _read_srt_pair(path: Path) -> list[tuple[str, str]]:
    """单文件内交替行或双文件需用户命名为 talk.ru.srt + talk.zh.srt"""
    name = path.name.lower()
    if ".zh." in name or name.endswith(".zh.srt"):
        other = path.with_name(path.name.replace(".zh.", ".ru."))
        if not other.is_file():
            other = path.with_name(path.name.replace(".zh.", ".en."))
        if other.is_file():
            zh_lines = _srt_text_lines(path)
            ru_lines = _srt_text_lines(other)
            return list(zip(ru_lines, zh_lines))[:500]
    return []


def _srt_text_lines(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines: list[str] = []
    for m in _SRT_BLOCK.finditer(raw):
        t = " ".join(m.group(3).strip().split())
        if t:
            lines.append(t)
    return lines
