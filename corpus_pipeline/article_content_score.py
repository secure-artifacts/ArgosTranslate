"""UN 正文质量分：过滤导航/索引/多语菜单页。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

_NAV_MARKERS = re.compile(
    r"Toggle navigation|Submit Search|Search the United Nations|"
    r"Указатель|Меню|网址索引|multilingual|"
    r"跳至主要内容|欢迎来到联合国|全球视野|高级搜索|"
    r"中文\s*\n|English\s*\n|Français\s*\n|Русский\s*\n|"
    r"العربية|Nederlands|Kiswahili",
    re.I,
)
_FIELD_CONTENT = re.compile(
    r'<div[^>]+class="[^"]*field-content[^"]*"[^>]*>(.*?)</div>',
    re.I | re.S,
)
_STORY_MARKERS = (
    "views-field-field-news-story-lead",
    "views-field-field-news-story",
)
_LINK = re.compile(r"https?://|www\.", re.I)
_CYR = re.compile(r"[А-Яа-яЁё]")
_HAN = re.compile(r"[\u4e00-\u9fff]")
_LAT = re.compile(r"[A-Za-z]{3,}")

# 仅 news.un.org 单篇
_ALLOWED_PATH = re.compile(
    r"^/ru/(?:story|interview|feature)/(?:\d{4}/\d{2}/)?[^/]+",
    re.I,
)
_ALLOWED_DATED = re.compile(
    r"^/ru/\d{4}/\d{2}/\d{2}/[^/]+",
    re.I,
)
_BLOCKED_PATH = re.compile(
    r"/(?:events?|index|category|categories|tag|tags|sitemap|"
    r"our-work|sections?|ga/|feed|page/\d|search|about)(?:/|$)",
    re.I,
)

_POST_BODY = re.compile(
    r'<(?:article|div)[^>]+class="[^"]*(?:post-content|entry-content|'
    r'article-body|story-body|field-body|field-news-story|'
    r'views-field-field-news-story)[^"]*"[^>]*>(.*?)</(?:article|div)>',
    re.I | re.S,
)
_NEWS_STORY_FIELD = re.compile(
    r'class="[^"]*field-content[^"]*"[^>]*>\s*'
    r'(?:<div[^>]*>)*\s*(.*?)\s*</div>\s*</div>\s*</div>\s*</div>\s*</div>',
    re.I | re.S,
)
_ARTICLE = re.compile(r"<article[^>]*>(.*?)</article>", re.I | re.S)


@dataclass
class ArticleScore:
    score: float
    body_len: int
    paragraph_density: float
    nav_ratio: float
    link_density: float
    cyrillic_density: float
    reject_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "article_content_score": round(self.score, 4),
            "body_len": self.body_len,
            "paragraph_density": round(self.paragraph_density, 4),
            "nav_ratio": round(self.nav_ratio, 4),
            "link_density": round(self.link_density, 4),
            "cyrillic_density": round(self.cyrillic_density, 4),
            "reject_reason": self.reject_reason,
        }


def is_allowed_news_article_url(url: str) -> bool:
    u = (url or "").strip()
    p = urlparse(u)
    if p.netloc.lower() not in ("news.un.org", "www.news.un.org"):
        return False
    path = p.path or ""
    if _BLOCKED_PATH.search(path):
        return False
    if _ALLOWED_PATH.match(path) or _ALLOWED_DATED.match(path):
        return True
    return False


def _extract_story_field_blocks(h: str) -> list[str]:
    from corpus_pipeline.clean import clean_paragraph

    parts: list[str] = []
    seen: set[str] = set()
    for marker in _STORY_MARKERS:
        start = 0
        while True:
            idx = h.find(marker, start)
            if idx < 0:
                break
            tail = h[idx : idx + len(marker) + 12]
            if "photo" in tail:
                start = idx + len(marker)
                continue
            chunk = h[idx : idx + 60000]
            for m in _FIELD_CONTENT.finditer(chunk):
                t = clean_paragraph(m.group(1))
                if len(t) >= 40 and t not in seen:
                    seen.add(t)
                    parts.append(t)
            start = idx + len(marker)
    return parts


def extract_article_body(html: str) -> str:
    from corpus_pipeline.clean import clean_paragraph

    h = html or ""
    blocks = _extract_story_field_blocks(h)
    if blocks:
        joined = "\n\n".join(blocks)
        if len(joined) >= 120:
            return joined

    for anchor in ("views-field-field-news-story", "field--name-field-news-story"):
        idx = h.find(anchor)
        while idx >= 0:
            if "photo" in h[idx : idx + len(anchor) + 8]:
                idx = h.find(anchor, idx + 1)
                continue
            chunk = h[idx : idx + 120000]
            m = _POST_BODY.search(chunk)
            if m:
                t = clean_paragraph(m.group(1))
                if len(t) >= 120:
                    return t
            break

    for pat in (_POST_BODY, _ARTICLE):
        m = pat.search(h)
        if m:
            t = clean_paragraph(m.group(1))
            if len(t) >= 120:
                return t
    return clean_paragraph(html)


def score_article_content(
    text: str,
    *,
    expect_lang: str = "ru",
    min_score: float = 0.48,
) -> ArticleScore:
    t = (text or "").strip()
    n = len(t)
    if n < 200:
        return ArticleScore(
            0.0, n, 0.0, 1.0, 1.0, 0.0, "body_too_short"
        )

    paras = [p.strip() for p in re.split(r"\n{2,}|\n", t) if len(p.strip()) > 40]
    para_density = len(paras) / max(n / 500, 1)
    para_score = min(1.0, para_density / 3.0)

    nav_hits = len(_NAV_MARKERS.findall(t))
    nav_ratio = nav_hits / max(len(paras) + 1, 1)
    nav_score = max(0.0, 1.0 - nav_ratio * 2.5)

    link_hits = len(_LINK.findall(t))
    link_density = link_hits / max(n / 100, 1)
    link_score = max(0.0, 1.0 - link_density * 0.35)

    cyr_n = len(_CYR.findall(t))
    han_n = len(_HAN.findall(t))
    lat_n = len(_LAT.findall(t))
    cyr_density = cyr_n / max(n, 1)

    if expect_lang == "ru":
        lang_score = min(1.0, cyr_density / 0.35) if cyr_n >= 50 else 0.2
        if lat_n > cyr_n * 1.8 and cyr_n < 80:
            lang_score = 0.15
    else:
        lang_score = min(1.0, han_n / max(n, 1) / 0.12) if han_n >= 30 else 0.2

    len_score = min(1.0, n / 1200)

    combined = (
        0.22 * len_score
        + 0.22 * para_score
        + 0.22 * nav_score
        + 0.14 * link_score
        + 0.20 * lang_score
    )
    combined = round(min(1.0, combined), 4)

    reason = ""
    if nav_ratio > 0.45:
        reason = "high_nav_ratio"
    elif link_density > 2.5:
        reason = "high_link_density"
    elif lang_score < 0.35:
        reason = "low_cyrillic_density" if expect_lang == "ru" else "low_han_density"
    elif combined < min_score:
        reason = "low_article_content_score"

    return ArticleScore(
        combined,
        n,
        para_density,
        nav_ratio,
        link_density,
        cyr_density,
        reason,
    )
