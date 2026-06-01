"""采集器基类。"""
from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from corpus_pipeline.config import FETCH_DELAY_SEC, USER_AGENT

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class ParallelDocument:
    url: str
    source_lang: str
    target_lang: str
    source_text: str
    target_text: str
    domain: str
    title: str = ""
    zh_url: str = ""
    pair_confidence: float = 1.0
    pair_meta: dict | None = None


@dataclass
class FetchResult:
    documents: list[ParallelDocument] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    page_logs: list[dict] = field(default_factory=list)
    crawl_meta: dict = field(default_factory=dict)


class BaseFetcher(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, *, max_pages: int = 20) -> FetchResult:
        ...

    def http_get(self, url: str, timeout: int = 45) -> str:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,uk,ru,en;q=0.9",
                "Referer": "https://ukraine.ua/",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        for enc in ("utf-8", "utf-8-sig", "cp1251"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def polite_sleep(self) -> None:
        time.sleep(FETCH_DELAY_SEC)
