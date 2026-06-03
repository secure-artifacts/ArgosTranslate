#!/usr/bin/env python3
"""本地 TM 导入 / 导出。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="翻译记忆库（TM）导入/导出")
    sub = p.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("export", help="导出 TM")
    ex.add_argument("path", help="输出路径 (.json / .jsonl / .csv)")
    ex.add_argument("--source-lang", default="", help="过滤源语，如 zh")
    ex.add_argument("--target-lang", default="", help="过滤目标语，如 ru")

    im = sub.add_parser("import", help="导入 TM")
    im.add_argument("path", help="输入文件 (.json / .jsonl / .csv)")
    im.add_argument("--source-lang", default="", help="CSV 缺省源语")
    im.add_argument("--target-lang", default="", help="CSV 缺省目标语")
    im.add_argument(
        "--quality-gate",
        action="store_true",
        help="启用语料质量门（默认关闭，便于用户句对导入）",
    )
    im.add_argument(
        "--no-bidirectional",
        action="store_true",
        help="不自动写入反向句对",
    )

    imb = sub.add_parser("import-batch", help="批量导入 TM（多文件/目录，源句去重）")
    imb.add_argument(
        "paths",
        nargs="+",
        help="TM 文件或目录（目录内 json/jsonl/csv）",
    )
    imb.add_argument("--source-lang", default="", help="CSV 缺省源语")
    imb.add_argument("--target-lang", default="", help="CSV 缺省目标语")
    imb.add_argument(
        "--quality-gate",
        action="store_true",
        help="启用语料质量门（默认关闭）",
    )
    imb.add_argument(
        "--no-bidirectional",
        action="store_true",
        help="不自动写入反向句对",
    )

    st = sub.add_parser("stats", help="TM 条目统计")

    dl = sub.add_parser("delete", help="删除 TM 条目")
    dl.add_argument("--source-lang", default="", help="源语，如 zh")
    dl.add_argument("--target-lang", default="", help="目标语，如 ru")
    dl.add_argument(
        "--source-text",
        default="",
        help="删除单条：原文（需与 --source-lang / --target-lang 一起使用）",
    )
    dl.add_argument(
        "--all",
        dest="delete_all",
        action="store_true",
        help="删除该语言对下全部条目（需 --source-lang 与 --target-lang）",
    )
    dl.add_argument(
        "--no-reverse",
        action="store_true",
        help="不删除反向句对",
    )
    dl.add_argument(
        "--yes",
        action="store_true",
        help="跳过确认（配合 --all）",
    )

    args = p.parse_args()
    from corpus_pipeline.tm_io import delete_tm, export_tm, import_tm, import_tm_batch, tm_stats

    if args.cmd == "export":
        sl = args.source_lang or None
        tl = args.target_lang or None
        result = export_tm(args.path, source_lang=sl, target_lang=tl)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "import":
        result = import_tm(
            args.path,
            default_source_lang=args.source_lang,
            default_target_lang=args.target_lang,
            quality_gate=args.quality_gate,
            bidirectional=not args.no_bidirectional,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    if args.cmd == "import-batch":
        result = import_tm_batch(
            args.paths,
            default_source_lang=args.source_lang,
            default_target_lang=args.target_lang,
            quality_gate=args.quality_gate,
            bidirectional=not args.no_bidirectional,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    if args.cmd == "delete":
        delete_reverse = not args.no_reverse
        if args.delete_all:
            if not args.yes:
                if args.source_lang and args.target_lang:
                    print(
                        f"将删除 {args.source_lang} → {args.target_lang} "
                        f"{'及反向 ' if delete_reverse else ''}"
                        "全部 TM 条目。加 --yes 确认。"
                    )
                else:
                    print("将清空整个 TM 数据库。加 --yes 确认。")
                return 1
            result = delete_tm(
                source_lang=args.source_lang,
                target_lang=args.target_lang,
                delete_all=True,
                delete_reverse=delete_reverse,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ok") else 1

        if not args.source_text or not args.source_lang or not args.target_lang:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "单条删除需要 --source-lang、--target-lang、--source-text",
                    },
                    ensure_ascii=False,
                )
            )
            return 1
        result = delete_tm(
            entries=[
                {
                    "source_text": args.source_text,
                    "source_lang": args.source_lang,
                    "target_lang": args.target_lang,
                    "target_text": "",
                }
            ],
            delete_reverse=delete_reverse,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1

    print(json.dumps(tm_stats(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
