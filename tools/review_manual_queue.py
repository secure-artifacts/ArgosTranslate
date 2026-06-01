#!/usr/bin/env python3
"""人工审核队列：列出 / 批准 / 拒绝 UN 等高置信 article 对。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="manual_review_queue 管理")
    p.add_argument("--source", default="un")
    p.add_argument("--list", action="store_true", help="列出 pending")
    p.add_argument("--approve", metavar="ID", help="批准并 promote 到 gold_corpus + TM")
    p.add_argument("--reject", metavar="ID", help="拒绝")
    p.add_argument("--note", default="", help="审核备注")
    args = p.parse_args()

    from corpus_pipeline.manual_review_queue import (
        get_queue_item,
        list_pending,
        queue_file,
        set_status,
    )

    if args.list:
        items = list_pending(args.source)
        print(json.dumps(items, ensure_ascii=False, indent=2))
        print(f"\npending={len(items)} file={queue_file(args.source)}")
        return 0

    if args.approve:
        item = get_queue_item(args.source, args.approve)
        if not item:
            print("not found:", args.approve)
            return 1
        from corpus_pipeline.gold_corpus import promote_from_review

        set_status(args.source, args.approve, "approved", note=args.note)
        result = promote_from_review(item, reviewer=args.note or "cli")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.reject:
        ok = set_status(args.source, args.reject, "rejected", note=args.note)
        print("rejected" if ok else "not found")
        return 0 if ok else 1

    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
