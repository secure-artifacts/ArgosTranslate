#!/usr/bin/env python3
"""打印最近一次采集日志摘要（验证报告）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
LOGS = _ROOT / "logs"


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else "ukraine_ua"
    files = sorted(LOGS.glob(f"crawl_{source}_*.json"), reverse=True)
    if not files:
        print(f"无日志: {LOGS}/crawl_{source}_*.json")
        return 1
    path = files[0]
    data = json.loads(path.read_text(encoding="utf-8"))
    s = data.get("summary") or {}
    print(f"日志: {path.name}\n")
    print("=== 汇总 ===")
    for k in (
        "tm_entries_after",
        "tm_added",
        "tm_quarantined",
        "glossary_new_on_disk",
        "glossary_extracted_this_run",
        "failed_pages",
        "low_confidence_pairs",
        "low_confidence_rate",
        "avg_corpus_quality_score",
        "page_match_rate",
        "ru_lang_detect_accuracy",
        "zh_lang_detect_accuracy",
        "paired_pages",
        "sentence_pairs",
        "sentence_align_success_rate",
        "long_sentence_align_rate",
    ):
        if k in s:
            print(f"  {k}: {s[k]}")
    print("\n=== 示例句对 ===")
    for i, p in enumerate(data.get("sample_pairs") or [], 1):
        print(
            f"\n--- {i} conf={p.get('confidence')} "
            f"q={p.get('corpus_quality_score')} "
            f"url={p.get('source_url', '')[:60]}"
        )
        print(f"UK: {p.get('source', '')[:200]}")
        print(f"ZH: {p.get('target', '')[:200]}")
    print("\n=== 示例术语 (20) ===")
    for i, g in enumerate(data.get("sample_glossary") or [], 1):
        print(f"  {i}. [{g.get('category')}] {g.get('lemma')} → {g.get('zh')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
