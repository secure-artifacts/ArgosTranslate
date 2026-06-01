#!/usr/bin/env python3
"""翻译质量评估 CLI。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="translation_eval")
    p.add_argument("--build-gold-baseline", action="store_true")
    p.add_argument("--source", default="un")
    p.add_argument("--run", metavar="TEST_SET", help="运行 test_sets/{name}.jsonl")
    p.add_argument("--run-all", action="store_true", help="运行全部 test_sets/*.jsonl")
    p.add_argument("--limit", type=int, default=50)
    args = p.parse_args()

    from corpus_pipeline.translation_eval import (
        build_baseline_from_gold,
        run_all_test_sets,
        run_eval_set,
        test_sets_dir,
    )

    if args.build_gold_baseline:
        path = build_baseline_from_gold(args.source, limit=args.limit)
        print("baseline written:", path)
        return 0

    if args.run_all:
        summary = run_all_test_sets()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.run:
        summary = run_eval_set(args.run)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    sets = sorted(x.name for x in test_sets_dir().glob("*.jsonl"))
    print("test_sets:", sets)
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
