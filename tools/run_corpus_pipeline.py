#!/usr/bin/env python3
"""
语料自动采集与对齐 CLI。

示例：
  venv\\Scripts\\python.exe tools\\run_corpus_pipeline.py --source ukraine_ua --full
  venv\\Scripts\\python.exe tools\\run_corpus_pipeline.py --source un --max-pages 30
  venv\\Scripts\\python.exe tools\\run_corpus_pipeline.py --detect-conflicts
  venv\\Scripts\\python.exe tools\\run_corpus_pipeline.py --source opus --merge-glossary --confirm-merge
  venv\\Scripts\\python.exe tools\\run_corpus_pipeline.py --metrics
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="语料采集 / 对齐 / TM / 术语")
    p.add_argument(
        "--source",
        choices=("ukraine_ua", "un", "opus", "ted"),
        help="单个来源",
    )
    p.add_argument("--all", action="store_true", help="运行全部来源")
    p.add_argument(
        "--max-pages",
        type=int,
        default=15,
        help="页数上限；配合 --full 时 ukraine/un 使用配置上限",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Ukraine.ua / UN 全量爬取（受 UKRAINE_FULL_CAP / UN_FULL_CAP 限制）",
    )
    p.add_argument(
        "--merge-glossary",
        action="store_true",
        help="合并非冲突术语到 entities_and_terms.json",
    )
    p.add_argument(
        "--confirm-merge",
        action="store_true",
        help="确认合并（仍跳过 conflicts.json 中的冲突项与 locked 项）",
    )
    p.add_argument(
        "--detect-conflicts",
        action="store_true",
        help="仅扫描译名冲突，写入 data/glossary/pending/conflicts.json",
    )
    p.add_argument("--tm-count", action="store_true", help="TM 条数")
    p.add_argument("--metrics", action="store_true", help="指标摘要")
    args = p.parse_args()

    if args.tm_count:
        from corpus_pipeline.tm_store import count_entries

        print("TM entries:", count_entries())
        return 0

    if args.metrics:
        from corpus_pipeline.metrics import load_recent_pipeline_reports, summary

        print(json.dumps(summary(), ensure_ascii=False, indent=2))
        print("\nRecent pipeline reports:")
        for r in load_recent_pipeline_reports(5):
            print(
                f"  {r.get('source')} pairs={r.get('sentence_pairs')} "
                f"align_rate={r.get('sentence_align_success_rate')} "
                f"tm={r.get('tm_total')}"
            )
        return 0

    if args.detect_conflicts:
        from corpus_pipeline.merge_into_glossary import write_conflicts_report

        path = write_conflicts_report()
        print("conflicts written:", path)
        return 0

    max_pages = 0 if args.full else args.max_pages

    from corpus_pipeline.pipeline import run_all, run_source

    if args.all:
        reports = run_all(
            max_pages=max_pages,
            merge_glossary=args.merge_glossary,
            confirm_merge=args.confirm_merge,
        )
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return 0
    if not args.source:
        p.error("请指定 --source、--all、--detect-conflicts 或 --metrics")
        return 2
    report = run_source(
        args.source,
        max_pages=max_pages,
        merge_glossary=args.merge_glossary,
        confirm_merge=args.confirm_merge,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
