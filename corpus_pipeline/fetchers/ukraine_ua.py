"""Ukraine.ua 中英/乌中页面采集（BFS + hreflang 配对 + 逐页日志）。"""
from __future__ import annotations

import os
import re
from collections import deque
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse, urlunparse

from corpus_pipeline.clean import clean_paragraph
from corpus_pipeline.config import (
    UKRAINE_FULL_CAP,
    UKRAINE_OFFLINE_DIR,
    UKRAINE_UA_ALLOW_WAYBACK,
    UKRAINE_UA_FETCH_MODE,
    UKRAINE_UA_ZH,
    UKRAINE_WAYBACK_PREFIX,
)
from corpus_pipeline.fetchers.base import BaseFetcher, FetchResult, ParallelDocument
from corpus_pipeline.lang_detect import detect_cyrillic_lang

_BASE = "https://ukraine.ua"
_ZH_HOME = UKRAINE_UA_ZH
_LINK = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_HREFLANG = re.compile(
    r'<link[^>]+hreflang=["\']([^"\']+)["\'][^>]+href=["\']([^"\']+)["\']',
    re.I,
)
_HREFLANG_ALT = re.compile(
    r'<link[^>]+href=["\']([^"\']+)["\'][^>]+hreflang=["\']([^"\']+)["\']',
    re.I,
)
_MAIN = re.compile(r"<main[^>]*>(.*?)</main>", re.I | re.S)
_ARTICLE = re.compile(r"<article[^>]*>(.*?)</article>", re.I | re.S)
_TITLE = re.compile(r"<title[^>]*>([^<]+)</title>", re.I)


def _normalize_url(url: str) -> str:
    u = url.split("#")[0].strip()
    if u.endswith("/") and len(u) > len(_BASE) + 5:
        u = u.rstrip("/")
    return u


def _is_zh_url(url: str) -> bool:
    p = urlparse(url)
    return "ukraine.ua" in p.netloc and "/zh/" in p.path


def _zh_to_uk(zh_url: str) -> str:
    return zh_url.replace("/zh/", "/", 1)


def _domain_from_url(zh_url: str) -> str:
    path = urlparse(zh_url).path.lower()
    if "/news" in path or "news" in path.split("/"):
        return "ukraine_ua_news"
    if any(x in path for x in ("invest", "business", "econom")):
        return "ukraine_ua_economy"
    if any(x in path for x in ("culture", "art", "heritage")):
        return "ukraine_ua_culture"
    if any(x in path for x in ("war", "defense", "military")):
        return "ukraine_ua_defense"
    if any(x in path for x in ("about", "info")):
        return "ukraine_ua_about"
    return "ukraine_ua"


def _extract_body(html: str) -> str:
    for pat in (_MAIN, _ARTICLE):
        m = pat.search(html or "")
        if m:
            return clean_paragraph(m.group(1))
    return clean_paragraph(html)


def _extract_title(html: str) -> str:
    m = _TITLE.search(html or "")
    return clean_paragraph(m.group(1)) if m else ""


def _hreflang_map(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for pat in (_HREFLANG, _HREFLANG_ALT):
        for m in pat.finditer(html or ""):
            a, b = m.group(1).strip().lower(), m.group(2).strip()
            if pat is _HREFLANG_ALT:
                b, a = a, b
            if a and b:
                out[a] = urljoin(_BASE, b)
    return out


def _fetch_mode() -> str:
    mode = (
        os.environ.get("UKRAINE_UA_FETCH_MODE", UKRAINE_UA_FETCH_MODE)
        .strip()
        .lower()
    )
    if mode == "wayback" and not UKRAINE_UA_ALLOW_WAYBACK:
        return "offline"
    return mode


def _canonical_zh_url(url: str) -> str:
    u = url.split("#")[0].strip()
    m = re.search(
        r"(https://ukraine\.ua/zh/[^\s\"'<>]*)",
        u,
        re.I,
    )
    if m:
        return _normalize_url(m.group(1))
    if _is_zh_url(u):
        return _normalize_url(u)
    return u


_SKIP_PATH = re.compile(
    r"/feed|/comments|cookie|/category/|screenshot|web\.archive\.org",
    re.I,
)


def _wayback_url(live_url: str) -> str:
    if "web.archive.org" in live_url:
        return live_url
    p = urlparse(live_url)
    path = quote(p.path, safe="/-%")
    encoded = urlunparse((p.scheme, p.netloc, path, "", p.query, ""))
    return f"{UKRAINE_WAYBACK_PREFIX}{encoded}"


def _is_content_zh_url(url: str) -> bool:
    if not _is_zh_url(url):
        return False
    if _SKIP_PATH.search(url):
        return False
    path = urlparse(url).path.lower()
    if path in ("/zh", "/zh/"):
        return True
    if "/zh/explore" in path or "/zh/news" in path:
        return True
    return len(path) > 8 and "%" not in path[:20]


def _has_ukrainian_body(text: str) -> bool:
    if not text or len(text) < 40:
        return False
    lang = detect_cyrillic_lang(text)
    if lang == "uk":
        return True
    if lang == "ru":
        return False
    cyr = len(re.findall(r"[А-Яа-яІіЇїЄєҐґ]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    return cyr >= 40 and cyr > lat


def _offline_paths(zh_url: str) -> tuple[Path, Path]:
    slug = urlparse(zh_url).path.strip("/").replace("/", "_") or "home"
    base = UKRAINE_OFFLINE_DIR
    return base / f"{slug}.zh.html", base / f"{slug}.uk.html"


def _zh_links_from_html(html: str, base_url: str) -> list[str]:
    links: list[str] = []
    for m in _LINK.finditer(html or ""):
        href = m.group(1).strip()
        if not href or href.startswith("#") or "javascript:" in href.lower():
            continue
        full = _canonical_zh_url(urljoin(base_url, href))
        if _is_content_zh_url(full) and full not in links:
            links.append(full)
    return links


class UkraineUaFetcher(BaseFetcher):
    name = "ukraine_ua"

    def _get_html_file(self, path: Path) -> str:
        if not path.is_file():
            raise OSError(f"offline missing: {path}")
        return path.read_text(encoding="utf-8", errors="replace")

    def _get_html(self, live_url: str, *, file_path: Path | None = None) -> str:
        if file_path is not None:
            return self._get_html_file(file_path)
        mode = _fetch_mode()
        if mode == "offline":
            zh_p, uk_p = _offline_paths(live_url)
            path = zh_p if "/zh/" in live_url else uk_p
            return self._get_html_file(path)
        fetch_url = _wayback_url(live_url) if mode == "wayback" else live_url
        try:
            return self.http_get(fetch_url)
        except Exception as e:
            if mode == "live" and "403" in str(e):
                return self.http_get(_wayback_url(live_url))
            raise

            raise

    def _fetch_offline_manifest(
        self, cap: int, *, reviewed_only: bool = True
    ) -> FetchResult:
        from corpus_pipeline.ukraine_manifest import (
            domain_to_corpus,
            list_manifest_entries,
            manifest_path,
            validate_entry,
        )

        result = FetchResult()
        entries = list_manifest_entries(reviewed_only=reviewed_only)
        paired = failed = 0

        for entry in entries:
            if len(result.documents) >= cap:
                break
            slug = str(entry.get("slug") or "")
            domain = domain_to_corpus(str(entry.get("domain") or ""))
            zh_p = UKRAINE_OFFLINE_DIR / str(entry.get("zh_file") or f"{slug}.zh.html")
            uk_p = UKRAINE_OFFLINE_DIR / str(entry.get("uk_file") or f"{slug}.uk.html")
            page = {
                "slug": slug,
                "zh_url": f"offline://{slug}.zh",
                "uk_url": f"offline://{slug}.uk",
                "domain": domain,
                "manifest_reviewed": bool(entry.get("reviewed")),
                "status": "pending",
                "reason": "",
                "fetch_mode": "offline_manifest",
            }
            errs = validate_entry(entry)
            if errs:
                page["status"] = "skipped"
                page["reason"] = "; ".join(errs)
                result.page_logs.append(page)
                continue
            try:
                zh_html = self._get_html_file(zh_p)
                uk_html = self._get_html_file(uk_p)
            except OSError as e:
                page["status"] = "failed"
                page["reason"] = str(e)
                failed += 1
                result.page_logs.append(page)
                result.errors.append(f"{slug}: {e}")
                continue

            zh_text = _extract_body(zh_html)
            uk_text = _extract_body(uk_html)
            page["zh_len"] = len(zh_text)
            page["uk_len"] = len(uk_text)
            page["uk_lang_detect"] = detect_cyrillic_lang(uk_text)

            if len(zh_text) < 60:
                page["status"] = "skipped"
                page["reason"] = "zh_body_too_short"
                result.page_logs.append(page)
                continue
            if not uk_text or len(uk_text) < 40:
                page["status"] = "skipped"
                page["reason"] = "uk_body_too_short"
                result.page_logs.append(page)
                continue
            if not _has_ukrainian_body(uk_text):
                page["status"] = "skipped"
                page["reason"] = "uk_body_not_ukrainian"
                result.page_logs.append(page)
                continue

            page["status"] = "success"
            page["reason"] = "manifest_ok"
            paired += 1
            result.page_logs.append(page)
            result.documents.append(
                ParallelDocument(
                    url=f"offline://ukraine_ua/{slug}",
                    source_lang="uk",
                    target_lang="zh",
                    source_text=uk_text,
                    target_text=zh_text,
                    domain=domain,
                    title=_extract_title(zh_html) or slug,
                )
            )

        result.crawl_meta = {
            "fetch_mode": "offline_manifest",
            "manifest_file": str(manifest_path()),
            "manifest_entries": len(entries),
            "paired_pages": paired,
            "failed_pages": failed,
            "reviewed_only": reviewed_only,
        }
        return result

    def fetch(self, *, max_pages: int = 20) -> FetchResult:
        result = FetchResult()
        cap = UKRAINE_FULL_CAP if max_pages <= 0 else max_pages
        mode = _fetch_mode()

        if mode == "offline":
            reviewed_only = os.environ.get(
                "UKRAINE_MANIFEST_REVIEWED_ONLY", "1"
            ).strip() in ("1", "true", "yes")
            from corpus_pipeline.ukraine_manifest import list_manifest_entries

            if list_manifest_entries(reviewed_only=False):
                return self._fetch_offline_manifest(cap, reviewed_only=reviewed_only)

        queue: deque[str] = deque([_ZH_HOME])
        visited_zh: set[str] = set()
        paired = 0
        failed = 0
        mode = _fetch_mode()

        while queue and len(result.documents) < cap:
            zh_url = _normalize_url(queue.popleft())
            if zh_url in visited_zh:
                continue
            visited_zh.add(zh_url)
            domain = _domain_from_url(zh_url)
            page: dict = {
                "zh_url": zh_url,
                "uk_url": "",
                "domain": domain,
                "status": "pending",
                "reason": "",
                "zh_len": 0,
                "uk_len": 0,
                "uk_lang_detect": "",
                "hreflang_uk": False,
                "fetch_mode": mode,
            }

            try:
                self.polite_sleep()
                zh_html = self._get_html(zh_url)
            except Exception as e:
                page["status"] = "failed"
                page["reason"] = f"zh_fetch: {e}"
                failed += 1
                result.page_logs.append(page)
                result.errors.append(f"{zh_url}: {e}")
                continue

            for link in _zh_links_from_html(zh_html, zh_url):
                if link not in visited_zh:
                    queue.append(link)

            hl = _hreflang_map(zh_html)
            uk_url = hl.get("uk") or hl.get("uk-ua") or _zh_to_uk(zh_url)
            uk_url = _normalize_url(uk_url)
            page["uk_url"] = uk_url
            page["hreflang_uk"] = bool(hl.get("uk") or hl.get("uk-ua"))

            zh_text = _extract_body(zh_html)
            page["zh_len"] = len(zh_text)
            if len(zh_text) < 60:
                page["status"] = "skipped"
                page["reason"] = "zh_body_too_short"
                result.page_logs.append(page)
                continue

            try:
                self.polite_sleep()
                uk_html = self._get_html(uk_url)
                uk_text = _extract_body(uk_html)
            except Exception as e:
                page["status"] = "failed"
                page["reason"] = f"uk_fetch: {e}"
                page["uk_len"] = 0
                failed += 1
                result.page_logs.append(page)
                result.errors.append(f"{uk_url}: {e}")
                continue

            page["uk_len"] = len(uk_text)
            page["uk_lang_detect"] = detect_cyrillic_lang(uk_text)

            if not uk_text or len(uk_text) < 40:
                page["status"] = "skipped"
                page["reason"] = "uk_body_too_short"
                result.page_logs.append(page)
                continue

            if not _has_ukrainian_body(uk_text):
                page["status"] = "skipped"
                page["reason"] = "uk_body_not_ukrainian_en_or_empty"
                result.page_logs.append(page)
                continue

            if page["uk_lang_detect"] == "ru":
                page["reason"] = "uk_page_ru_script_dominant"
            elif page["uk_lang_detect"] == "mixed":
                page["reason"] = "uk_lang_mixed"
            else:
                page["reason"] = "paired_ok"

            page["status"] = "success"
            paired += 1
            result.page_logs.append(page)
            result.documents.append(
                ParallelDocument(
                    url=zh_url,
                    source_lang="uk",
                    target_lang="zh",
                    source_text=uk_text,
                    target_text=zh_text,
                    domain=domain,
                    title=_extract_title(zh_html) or urlparse(zh_url).path,
                )
            )

        result.crawl_meta = {
            "fetch_mode": mode,
            "discovered_zh": len(visited_zh),
            "paired_pages": paired,
            "failed_pages": failed,
            "skipped_pages": sum(
                1 for p in result.page_logs if p.get("status") == "skipped"
            ),
            "page_match_rate": round(paired / max(len(visited_zh), 1), 4),
            "uk_lang_ok": sum(
                1
                for p in result.page_logs
                if p.get("status") == "success"
                and p.get("uk_lang_detect") in ("uk", "mixed")
            ),
        }
        result.errors.append(
            f"ukraine_ua: discovered_zh={len(visited_zh)} paired={paired} failed={failed}"
        )
        return result
