"""Ukraine.ua offline 配对清单：可追踪、可版本化、可人工审核。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_pipeline.config import UKRAINE_OFFLINE_DIR

MANIFEST_NAME = "manifest.json"

_PREFERRED_DOMAINS = frozenset(
    {"news", "politics", "military", "diplomacy", "international"}
)
_AVOID_DOMAINS = frozenset({"tourism", "promo", "media", "video"})


def manifest_path(base: Path | None = None) -> Path:
    return (base or UKRAINE_OFFLINE_DIR).parent / MANIFEST_NAME


def _default_manifest() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": [],
    }


def load_manifest(base: Path | None = None) -> dict[str, Any]:
    p = manifest_path(base)
    if not p.is_file():
        return _default_manifest()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {"version": 1, "entries": data}
        return data
    except (OSError, json.JSONDecodeError):
        return _default_manifest()


def save_manifest(data: dict[str, Any], base: Path | None = None) -> Path:
    p = manifest_path(base)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def domain_to_corpus(domain: str) -> str:
    d = (domain or "general").strip().lower()
    mapping = {
        "news": "ukraine_ua_news",
        "politics": "ukraine_ua_politics",
        "military": "ukraine_ua_defense",
        "diplomacy": "ukraine_ua_diplomatic",
        "international": "ukraine_ua_diplomatic",
        "economy": "ukraine_ua_economy",
    }
    return mapping.get(d, f"ukraine_ua_{d}" if d else "ukraine_ua")


def validate_entry(entry: dict[str, Any], base: Path | None = None) -> list[str]:
    root = base or UKRAINE_OFFLINE_DIR
    errors: list[str] = []
    slug = str(entry.get("slug") or "").strip()
    if not slug:
        errors.append("missing slug")
    zh_f = entry.get("zh_file") or f"{slug}.zh.html"
    uk_f = entry.get("uk_file") or f"{slug}.uk.html"
    if not (root / zh_f).is_file():
        errors.append(f"missing zh: {zh_f}")
    if not (root / uk_f).is_file():
        errors.append(f"missing uk: {uk_f}")
    dom = str(entry.get("domain") or "").lower()
    if dom in _AVOID_DOMAINS:
        errors.append(f"avoid domain: {dom}")
    return errors


def list_manifest_entries(
    *,
    reviewed_only: bool = False,
    base: Path | None = None,
) -> list[dict[str, Any]]:
    entries = list(load_manifest(base).get("entries") or [])
    if reviewed_only:
        entries = [e for e in entries if e.get("reviewed")]
    return entries


def sync_from_files(base: Path | None = None) -> dict[str, Any]:
    """扫描 offline_html 成对文件，合并进 manifest（不覆盖已有条目 metadata）。"""
    root = base or UKRAINE_OFFLINE_DIR
    root.mkdir(parents=True, exist_ok=True)
    data = load_manifest(root)
    by_slug = {str(e.get("slug")): e for e in data.get("entries") or []}

    for zp in sorted(root.glob("*.zh.html")):
        slug = zp.stem.replace(".zh", "") if zp.name.endswith(".zh.html") else zp.name.replace(".zh.html", "")
        uk_p = root / f"{slug}.uk.html"
        if not uk_p.is_file():
            continue
        if slug not in by_slug:
            by_slug[slug] = {
                "slug": slug,
                "uk_file": f"{slug}.uk.html",
                "zh_file": f"{slug}.zh.html",
                "domain": "news",
                "reviewed": False,
            }
        else:
            by_slug[slug].setdefault("uk_file", f"{slug}.uk.html")
            by_slug[slug].setdefault("zh_file", f"{slug}.zh.html")

    data["entries"] = sorted(by_slug.values(), key=lambda x: x.get("slug", ""))
    save_manifest(data, root)
    return data


def add_entry(
    slug: str,
    *,
    domain: str = "news",
    reviewed: bool = False,
    notes: str = "",
    base: Path | None = None,
) -> tuple[bool, str]:
    root = base or UKRAINE_OFFLINE_DIR
    data = load_manifest(root)
    entries = list(data.get("entries") or [])
    if any(str(e.get("slug")) == slug for e in entries):
        return False, "slug_exists"
    entry = {
        "slug": slug,
        "uk_file": f"{slug}.uk.html",
        "zh_file": f"{slug}.zh.html",
        "domain": domain,
        "reviewed": reviewed,
        "notes": notes,
    }
    errs = validate_entry(entry, root)
    if errs:
        return False, "; ".join(errs)
    entries.append(entry)
    data["entries"] = entries
    save_manifest(data, root)
    return True, "added"
