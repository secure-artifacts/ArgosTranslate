#!/usr/bin/env python3
"""人工审核队列：UN article 对 + 用户采纳/低分句对。"""
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
    p.add_argument(
        "--source",
        default="user",
        help="队列来源：user（GUI 采纳/低分）| un | …",
    )
    p.add_argument("--list", action="store_true", help="列出 pending")
    p.add_argument("--approve", metavar="ID", help="批准并 promote 到 gold_corpus + TM")
    p.add_argument("--reject", metavar="ID", help="拒绝")
    p.add_argument("--delete", metavar="ID", help="永久删除（从队列文件移除）")
    p.add_argument(
        "--delete-all",
        action="store_true",
        help="永久删除全部 pending 条目",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="跳过确认（配合 --delete-all）",
    )
    p.add_argument("--note", default="", help="审核备注")
    p.add_argument(
        "--regression",
        action="store_true",
        help="批准后额外跑 user_gold + person_descriptions regression",
    )
    args = p.parse_args()

    from corpus_pipeline.config import USER_FEEDBACK_SOURCE
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

        if args.source == USER_FEEDBACK_SOURCE or item.get("kind") in (
            "user_adopt",
            "auto_low_quality",
        ):
            from corpus_pipeline.user_feedback import approve_user_item

            result = approve_user_item(
                args.approve, reviewer=args.note or "cli", note=args.note
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if args.regression and result.get("ok"):
                from corpus_pipeline.translation_eval import run_regression_guard

                guard = run_regression_guard(translate_fn=None)
                print("\nregression_guard:", json.dumps(guard, ensure_ascii=False, indent=2))
            return 0

        from corpus_pipeline.gold_corpus import promote_from_review

        set_status(args.source, args.approve, "approved", note=args.note)
        result = promote_from_review(item, reviewer=args.note or "cli")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.reject:
        if args.source == USER_FEEDBACK_SOURCE:
            from corpus_pipeline.user_feedback import reject_user_item

            ok = reject_user_item(args.reject, note=args.note)
        else:
            ok = set_status(args.source, args.reject, "rejected", note=args.note)
        print("rejected" if ok else "not found")
        return 0 if ok else 1

    if args.delete:
        if args.source == USER_FEEDBACK_SOURCE:
            from corpus_pipeline.user_feedback import delete_user_items

            result = delete_user_items([args.delete], note=args.note or "cli_delete")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ok") else 1
        from corpus_pipeline.manual_review_queue import delete_items

        n = delete_items(args.source, [args.delete])
        print(json.dumps({"ok": n > 0, "deleted": n}, ensure_ascii=False, indent=2))
        return 0 if n > 0 else 1

    if args.delete_all:
        if not args.yes:
            print("将永久删除全部 pending 条目。加 --yes 确认。")
            return 1
        if args.source == USER_FEEDBACK_SOURCE:
            from corpus_pipeline.user_feedback import delete_all_user_pending

            result = delete_all_user_pending(note=args.note or "cli_delete_all")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ok") else 1
        from corpus_pipeline.manual_review_queue import delete_all_pending

        n = delete_all_pending(args.source)
        print(json.dumps({"ok": n > 0, "deleted": n}, ensure_ascii=False, indent=2))
        return 0 if n > 0 else 1

    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
