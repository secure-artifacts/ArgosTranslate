"""OPUS 本地双语文本导入（用户先下载后放入 data/corpus/raw/opus/）。"""
from __future__ import annotations

from pathlib import Path

from corpus_pipeline.config import RAW
from corpus_pipeline.fetchers.base import BaseFetcher, FetchResult, ParallelDocument

# Moses / OPUS 常见格式：source ||| target
# 或 .ru / .zh 成对文件


class OpusLocalFetcher(BaseFetcher):
    name = "opus"

    def fetch(self, *, max_pages: int = 999999) -> FetchResult:
        result = FetchResult()
        root = RAW / "opus"
        if not root.is_dir():
            result.errors.append(
                f"缺少目录 {root}；请从 https://opus.nlpl.eu/ 下载 ru-zh / uk-zh "
                "并解压为 opus/*.txt 或 *.moses"
            )
            return result
        count = 0
        for path in sorted(root.rglob("*")):
            if count >= max_pages:
                break
            if path.suffix.lower() not in (".txt", ".moses", ".mt", ".tsv"):
                continue
            try:
                pairs = _read_bitext_file(path)
            except OSError as e:
                result.errors.append(f"{path}: {e}")
                continue
            lang = "uk" if "uk" in path.name.lower() else "ru"
            for src, tgt in pairs:
                if count >= max_pages:
                    break
                result.documents.append(
                    ParallelDocument(
                        url=str(path),
                        source_lang=lang,
                        target_lang="zh",
                        source_text=src,
                        target_text=tgt,
                        domain="opus",
                    )
                )
                count += 1
        return result


def _read_bitext_file(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if " ||| " in line:
            a, b = line.split(" ||| ", 1)
            out.append((a.strip(), b.strip()))
        elif "\t" in line:
            a, b = line.split("\t", 1)
            out.append((a.strip(), b.strip()))
    return out
