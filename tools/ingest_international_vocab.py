#!/usr/bin/env python3
"""从 Tatoeba / Wiktionary 拉取日常词汇并合并进 entities_and_terms.json。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from corpus_pipeline.international_vocab import (  # noqa: E402
    apply_to_entities_and_terms,
    fetch_daily_vocab,
    write_glossary_files,
)


def main() -> int:
    ap = argparse.ArgumentParser(description="国际开放语料日常词汇入库")
    ap.add_argument(
        "--words",
        nargs="*",
        help="仅处理指定中文词（默认用 seeds/daily_life_zh.json 全表）",
    )
    ap.add_argument(
        "--min-confidence",
        type=float,
        default=0.55,
        help="拉取阶段最低置信度（默认 0.55）",
    )
    ap.add_argument(
        "--apply-min-confidence",
        type=float,
        default=0.72,
        help="写入 entities_and_terms 的最低置信度（默认 0.72）",
    )
    ap.add_argument(
        "--throttle",
        type=float,
        default=0.35,
        help="Tatoeba 请求间隔秒数",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="合并进 data/terminology/entities_and_terms.json",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印结果，不写 glossary / entities 文件",
    )
    args = ap.parse_args()

    rows = fetch_daily_vocab(
        words=args.words,
        min_confidence=args.min_confidence,
        throttle_sec=args.throttle,
    )
    print(f"[OK] fetched {len(rows)} zh entries")
    for row in rows[:20]:
        print(
            f"  {row['zh']:8} ru={row.get('ru',''):20} uk={row.get('uk',''):16} "
            f"conf={row.get('confidence')} src={row.get('source')}"
        )
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more")

    if args.dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    ru_path, uk_path = write_glossary_files(rows)
    print(f"[OK] glossary -> {ru_path}")
    print(f"[OK] glossary -> {uk_path}")

    if args.apply:
        added_lemma, added_zh_to = apply_to_entities_and_terms(
            rows, min_confidence=args.apply_min_confidence
        )
        print(
            f"[OK] merged into entities_and_terms.json "
            f"(+{added_lemma} daily lemmas, +{added_zh_to} zh_to)"
        )
    else:
        print("[hint] add --apply to merge into entities_and_terms.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
