#!/usr/bin/env python3
"""Ukraine.ua 离线 HTML 配对入库：manifest 追踪 + pipeline 运行。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="Ukraine.ua offline HTML + manifest")
    p.add_argument("--check", action="store_true", help="检查 offline 目录与 manifest 配对")
    p.add_argument("--sync-manifest", action="store_true", help="从 offline_html 扫描并合并 manifest")
    p.add_argument(
        "--add-entry",
        metavar="SLUG",
        help="添加 manifest 条目（需已有成对 HTML）",
    )
    p.add_argument("--domain", default="news", help="add-entry 时的 domain")
    p.add_argument(
        "--reviewed",
        action="store_true",
        help="add-entry 时标记 reviewed=true",
    )
    p.add_argument("--run", action="store_true", help="offline 模式跑 pipeline（manifest 优先）")
    p.add_argument("--max-pages", type=int, default=20)
    args = p.parse_args()

    from corpus_pipeline.config import UKRAINE_OFFLINE_DIR
    from corpus_pipeline.ukraine_manifest import (
        add_entry,
        list_manifest_entries,
        load_manifest,
        manifest_path,
        sync_from_files,
        validate_entry,
    )

    if args.sync_manifest:
        data = sync_from_files()
        n = len(data.get("entries") or [])
        print(f"synced {n} entries -> {manifest_path()}")
        return 0

    if args.add_entry:
        ok, msg = add_entry(
            args.add_entry.strip(),
            domain=args.domain,
            reviewed=args.reviewed,
        )
        print(msg)
        return 0 if ok else 1

    if args.check:
        base = UKRAINE_OFFLINE_DIR
        base.mkdir(parents=True, exist_ok=True)
        mp = manifest_path()
        print(f"offline_dir: {base}")
        print(f"manifest:    {mp} ({'exists' if mp.is_file() else 'missing'})")

        zh = sorted(base.glob("*.zh.html"))
        uk = sorted(base.glob("*.uk.html"))
        paired_fs = 0
        for zp in zh:
            slug = zp.name.replace(".zh.html", "")
            up = base / f"{slug}.uk.html"
            ok = up.is_file()
            if ok:
                paired_fs += 1
            print(f"  [file] {slug}: zh={'OK' if zp.is_file() else '-'} uk={'OK' if ok else 'MISSING'}")

        entries = list_manifest_entries(reviewed_only=False)
        reviewed = list_manifest_entries(reviewed_only=True)
        print(f"\nfiles: zh={len(zh)} uk={len(uk)} paired={paired_fs}")
        print(f"manifest: total={len(entries)} reviewed={len(reviewed)}")

        for entry in entries:
            slug = entry.get("slug")
            errs = validate_entry(entry)
            flag = "OK" if not errs else "ERR"
            rev = "reviewed" if entry.get("reviewed") else "pending"
            dom = entry.get("domain", "?")
            detail = "; ".join(errs) if errs else rev
            print(f"  [manifest] {slug} [{dom}] {flag}: {detail}")

        preferred = {"news", "politics", "military", "diplomacy", "international"}
        avoid = {"tourism", "promo", "media", "video"}
        print("\n采集建议:")
        print(f"  优先 domain: {', '.join(sorted(preferred))}")
        print(f"  避免 domain: {', '.join(sorted(avoid))}")
        print("  人工审核通过后设 reviewed=true，再 --run")
        return 0

    if args.run:
        import os

        os.environ["UKRAINE_UA_FETCH_MODE"] = "offline"
        from corpus_pipeline.pipeline import run_source

        report = run_source("ukraine_ua", max_pages=args.max_pages)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
