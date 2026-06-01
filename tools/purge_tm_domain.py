#!/usr/bin/env python3
"""从 TM 中移除指定 domain 的条目（如污染性的 ukraine_ua Wayback 数据）。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    domain = sys.argv[1] if len(sys.argv) > 1 else "ukraine_ua"
    from corpus_pipeline.tm_store import _connect, count_entries

    before = count_entries()
    conn = _connect()
    cur = conn.execute(
        "DELETE FROM translation_memory WHERE domain LIKE ?",
        (f"{domain}%",),
    )
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    after = count_entries()
    print(f"domain={domain} deleted={deleted} tm_before={before} tm_after={after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
