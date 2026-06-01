"""news.un.org RU↔ZH 配对：发布时间 + 主题/实体/标题联合置信度。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

from corpus_pipeline.article_content_score import is_allowed_news_article_url
from corpus_pipeline.config import (
    MIN_PAIR_CONFIDENCE_TM,
    RECALL_MAX_DELTA_SEC,
    RECALL_MIN_DELTA_SEC,
    RECALL_MIN_TOPIC_HITS,
    ROOT,
)

_STORY_LINK = re.compile(
    r'href=["\']([^"\']*/(?:ru|zh)/story/\d{4}/\d{2}/\d+)["\']',
    re.I,
)
_PUBLISHED = re.compile(
    r'property=["\']article:published_time["\']\s+content=["\']([^"\']+)["\']',
    re.I,
)
_OG_TITLE = re.compile(
    r'property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
    re.I,
)
_TIME_TAG = re.compile(r'<time[^>]+datetime=["\']([^"\']+)["\']', re.I)
_CYR_WORD = re.compile(r"[А-Яа-яЁё]{4,}")
_HAN_TERM = re.compile(r"[\u4e00-\u9fff]{2,6}")
_NUM = re.compile(r"\d{2,4}")

DEFAULT_MAX_DELTA_SEC = RECALL_MAX_DELTA_SEC
MIN_TOPIC_KEYWORD_HITS = 2
MIN_PAIR_CONFIDENCE = MIN_PAIR_CONFIDENCE_TM
MIN_TOPIC_KEYWORD_HITS_RECALL = RECALL_MIN_TOPIC_HITS
MIN_TITLE_SIMILARITY = 0.12

_DIGEST = re.compile(
    r"Главные новости дня|главные события|Top stories|news in brief|"
    r"新闻简报|要闻|每日新闻",
    re.I,
)
_SECTION_HEAD = re.compile(
    r"(?:^|\n)([А-ЯЁA-Z][^\n]{8,72})\n(?=[А-Яа-яA-Z])",
    re.M,
)

_TOPIC_MARKERS = (
    ("эбол", "埃博拉"),
    ("конго", "刚果"),
    ("войн", "战争"),
    ("оон", "联合国"),
    ("воз", "世卫"),
    ("гутер", "古特雷斯"),
    ("украин", "乌克兰"),
    ("ливан", "黎巴嫩"),
    ("израил", "以色列"),
    ("лебан", "黎巴嫩"),
    ("ормуз", "霍尔木兹"),
    ("палест", "巴勒斯坦"),
    ("газ", "加沙"),
    ("климат", "气候"),
    ("ядер", "核"),
    ("судан", "苏丹"),
    ("сир", "叙利亚"),
    ("иран", "伊朗"),
    ("миротвор", "维和"),
    ("афган", "阿富汗"),
    ("румын", "罗马尼亚"),
    ("дрон", "无人机"),
    ("горм", "霍尔木兹"),
    ("удобрен", "化肥"),
    ("жиль", "住房"),
    ("эконом", "经济"),
    ("инфля", "通胀"),
    ("футбол", "足球"),
    ("монгол", "蒙古"),
)


@dataclass
class ArticleMeta:
    url: str
    published: datetime | None
    title: str = ""


@dataclass
class ArticlePairScore:
    ru_url: str
    zh_url: str
    time_delta_sec: float
    topic_keyword_hits: int
    topic_overlap: float
    title_similarity: float
    entity_overlap: float
    token_overlap: float
    pair_confidence: float
    accept: bool
    reject_reason: str = ""
    embedding_title_similarity: float = 0.0
    embedding_body_similarity: float = 0.0
    embedding_combined: float = 0.0
    paragraph_topic_consistency: float = 0.0
    stage: str = "precision"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["accept"] = self.accept
        return d


def parse_published_time(html: str) -> datetime | None:
    h = html or ""
    m = _PUBLISHED.search(h) or _TIME_TAG.search(h)
    if not m:
        return None
    s = m.group(1).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def parse_og_title(html: str) -> str:
    m = _OG_TITLE.search(html or "")
    if not m:
        return ""
    return unescape(m.group(1).strip())


def parse_article_meta(html: str, url: str) -> ArticleMeta:
    head = (html or "")[:65536]
    return ArticleMeta(
        url=url,
        published=parse_published_time(head),
        title=parse_og_title(head),
    )


def collect_story_urls(html: str, base_url: str, lang: str) -> list[str]:
    out: list[str] = []
    for m in _STORY_LINK.finditer(html or ""):
        full = urljoin(base_url, unescape(m.group(1))).split("#")[0]
        if f"/{lang}/" not in full:
            continue
        if not is_allowed_news_article_url(full.replace(f"/{lang}/", "/ru/")):
            continue
        if full not in out:
            out.append(full)
    return out


def match_by_published_time(
    ru_times: list[tuple[str, datetime]],
    zh_times: list[tuple[str, datetime]],
    *,
    max_delta_sec: float = DEFAULT_MAX_DELTA_SEC,
) -> list[tuple[str, str, float]]:
    candidates: list[tuple[float, str, str]] = []
    for ru_url, ru_t in ru_times:
        if not ru_t:
            continue
        for zh_url, zh_t in zh_times:
            if not zh_t:
                continue
            delta = abs((ru_t - zh_t).total_seconds())
            if delta <= max_delta_sec:
                candidates.append((delta, ru_url, zh_url))
    candidates.sort(key=lambda x: x[0])

    used_ru: set[str] = set()
    used_zh: set[str] = set()
    pairs: list[tuple[str, str, float]] = []
    for delta, ru_url, zh_url in candidates:
        if ru_url in used_ru or zh_url in used_zh:
            continue
        used_ru.add(ru_url)
        used_zh.add(zh_url)
        pairs.append((ru_url, zh_url, delta))
    return pairs


def count_topic_keyword_hits(ru_text: str, zh_text: str) -> int:
    ru = (ru_text or "").lower()
    zh = zh_text or ""
    return sum(1 for a, b in _TOPIC_MARKERS if a in ru and b in zh)


def _token_overlap_score(ru_text: str, zh_text: str) -> float:
    """轻量“TF”重合：西里尔词干 + 汉字词 + 共享数字。"""
    ru_tokens = {w[:6].lower() for w in _CYR_WORD.findall(ru_text or "")}
    zh_tokens = set(_HAN_TERM.findall(zh_text or ""))
    nums = set(_NUM.findall(ru_text or "")) & set(_NUM.findall(zh_text or ""))
    if not ru_tokens and not zh_tokens:
        return 0.0
    # 跨语言无法直接 Jaccard；用数字 + 主题 marker 已覆盖，此处用数字权重
    num_score = len(nums) / max(
        len(set(_NUM.findall(ru_text or "")) | set(_NUM.findall(zh_text or ""))),
        1,
    )
    # 长度结构相似
    lr = len(ru_text or "") / max(len(zh_text or ""), 1)
    lr = lr if lr <= 1 else 1 / lr
    struct = 1.0 if 0.35 <= lr <= 2.8 else 0.4
    return min(1.0, 0.55 * num_score + 0.45 * struct)


def _title_similarity(ru_title: str, zh_title: str) -> float:
    if not ru_title or not zh_title:
        return 0.0
    hits = count_topic_keyword_hits(ru_title, zh_title)
    nums_ru = set(_NUM.findall(ru_title))
    nums_zh = set(_NUM.findall(zh_title))
    num_ov = len(nums_ru & nums_zh) / max(len(nums_ru | nums_zh), 1) if nums_ru else 0.0
    hit_score = min(1.0, hits / 3.0)
    return min(1.0, 0.55 * hit_score + 0.45 * num_ov)


def _zh_entity_spans(zh_text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in _HAN_TERM.findall(zh_text or ""):
        if len(m) < 2:
            continue
        et = "GPE" if m.endswith(("国", "市", "省", "州")) else "PERSON"
        if m in ("联合国", "安理会", "大会", "秘书处", "北约", "欧盟", "世卫组织"):
            et = "ORG"
        out.append((m, et))
    return out


def _entity_overlap_score(ru_text: str, zh_text: str) -> float:
    from corpus_pipeline.ner_backends import extract_typed_entities

    allowed = frozenset({"PERSON", "GPE", "ORG", "LOC", "EVENT"})
    ru_ents = [
        e
        for e in extract_typed_entities(ru_text or "", "ru")
        if e.entity_type in allowed and len(e.text) >= 2
    ]
    zh_ents = _zh_entity_spans(zh_text or "")
    anchors = _load_entity_anchors()

    hits = 0
    for anc in anchors:
        if anc["ru"].lower() in (ru_text or "").lower() and anc["zh"] in (zh_text or ""):
            hits += 1
    hits = min(hits, 3)

    for re_ent in ru_ents:
        ru_low = re_ent.text.lower()
        matched = False
        for zh_txt, zh_et in zh_ents:
            if re_ent.entity_type != zh_et and not (
                re_ent.entity_type in ("ORG", "GPE") and zh_et in ("ORG", "GPE")
            ):
                continue
            if len(zh_txt) >= 2:
                matched = True
                break
        if matched:
            hits += 1
            continue
        for anc in anchors:
            if anc["entity_type"] != re_ent.entity_type:
                continue
            if anc["ru"].lower() in ru_low and anc["zh"] in (zh_text or ""):
                hits += 1
                break

    denom = max(len(ru_ents) + len(anchors) // 8, 1)
    return min(1.0, hits / min(denom, 6))


def _load_entity_anchors() -> list[dict]:
    p = ROOT / "data" / "glossary" / "entity_anchors_ru_zh.json"
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return list(data.get("anchors") or [])
    except (OSError, json.JSONDecodeError):
        return []


def is_multi_story_digest(text: str) -> bool:
    return bool(_DIGEST.search(text or ""))


def _paragraph_topic_consistency(ru_text: str, zh_text: str) -> float:
    ru_paras = [p.strip() for p in re.split(r"\n{2,}", ru_text or "") if len(p.strip()) > 60]
    zh_paras = [p.strip() for p in re.split(r"\n{2,}", zh_text or "") if len(p.strip()) > 30]
    if not ru_paras or not zh_paras:
        return 0.0
    matched = 0
    for rp in ru_paras[:8]:
        if count_topic_keyword_hits(rp, " ".join(zh_paras)) >= 1:
            matched += 1
            continue
        best = 0.0
        for zp in zh_paras[:8]:
            try:
                from corpus_pipeline.bilingual_rerank import cross_lingual_similarity

                best = max(best, cross_lingual_similarity(rp[:300], zp[:300]))
            except Exception:
                pass
        if best >= 0.55:
            matched += 1
    return round(matched / min(len(ru_paras), 8), 4)


def stage1_recall_passes(
    *,
    ru_text: str,
    zh_text: str,
    time_delta_sec: float,
) -> tuple[bool, str]:
    if is_multi_story_digest(ru_text) or is_multi_story_digest(zh_text):
        return False, "multi_story_digest"
    if time_delta_sec > RECALL_MAX_DELTA_SEC:
        return False, "time_delta_exceeded"
    if time_delta_sec < RECALL_MIN_DELTA_SEC:
        return False, "time_delta_below_min"
    hits = count_topic_keyword_hits(ru_text, zh_text)
    if hits < RECALL_MIN_TOPIC_HITS:
        return False, "insufficient_topic_keywords_recall"
    return True, ""


def score_article_pair_precision(
    *,
    ru_url: str,
    zh_url: str,
    ru_text: str,
    zh_text: str,
    ru_title: str = "",
    zh_title: str = "",
    time_delta_sec: float,
) -> ArticlePairScore:
    """Stage 2：embedding rerank + 实体/段落一致性，pair_confidence ≥ 0.80 才 accept。"""
    from corpus_pipeline.bilingual_rerank import combined_ru_zh_similarity

    kw_hits = count_topic_keyword_hits(ru_text, zh_text)
    kw_title = count_topic_keyword_hits(ru_title, zh_title)
    kw_hits = max(kw_hits, kw_title)

    topic_overlap = min(1.0, kw_hits / 4.0)
    title_sim_kw = _title_similarity(ru_title, zh_title)
    ent_ov = _entity_overlap_score(ru_text, zh_text)
    tok_ov = _token_overlap_score(ru_text, zh_text)
    para_cons = _paragraph_topic_consistency(ru_text, zh_text)

    emb = combined_ru_zh_similarity(
        ru_title=ru_title,
        zh_title=zh_title,
        ru_body=ru_text,
        zh_body=zh_text,
    )
    emb_title = float(emb.get("embedding_title_similarity") or 0)
    emb_body = float(emb.get("embedding_body_similarity") or 0)
    emb_combined = float(emb.get("embedding_combined") or 0)

    time_score = max(0.0, 1.0 - (time_delta_sec / RECALL_MAX_DELTA_SEC))

    pair_confidence = (
        0.32 * emb_combined
        + 0.18 * emb_title
        + 0.18 * ent_ov
        + 0.14 * para_cons
        + 0.10 * topic_overlap
        + 0.08 * time_score
    )
    if kw_hits >= 2 and emb_combined >= 0.62:
        pair_confidence = min(1.0, pair_confidence + 0.04)
    if ent_ov >= 0.5 and emb_title >= 0.55:
        pair_confidence = min(1.0, pair_confidence + 0.03)
    pair_confidence = round(min(1.0, pair_confidence), 4)

    reject = ""
    if is_multi_story_digest(ru_text) or is_multi_story_digest(zh_text):
        reject = "multi_story_digest"
    elif time_delta_sec > RECALL_MAX_DELTA_SEC:
        reject = "time_delta_exceeded"
    elif kw_hits < 2:
        reject = "insufficient_topic_keywords_precision"
    elif emb_combined < 0.50 and emb_title < 0.45:
        reject = "low_embedding_similarity"
    elif pair_confidence < MIN_PAIR_CONFIDENCE_TM:
        reject = "low_pair_confidence"

    return ArticlePairScore(
        ru_url=ru_url,
        zh_url=zh_url,
        time_delta_sec=round(time_delta_sec, 1),
        topic_keyword_hits=kw_hits,
        topic_overlap=round(topic_overlap, 4),
        title_similarity=round(max(title_sim_kw, emb_title), 4),
        entity_overlap=round(ent_ov, 4),
        token_overlap=round(tok_ov, 4),
        pair_confidence=pair_confidence,
        accept=not reject,
        reject_reason=reject,
        embedding_title_similarity=emb_title,
        embedding_body_similarity=emb_body,
        embedding_combined=emb_combined,
        paragraph_topic_consistency=para_cons,
        stage="precision",
    )


def score_article_pair(
    *,
    ru_url: str,
    zh_url: str,
    ru_text: str,
    zh_text: str,
    ru_title: str = "",
    zh_title: str = "",
    time_delta_sec: float,
) -> ArticlePairScore:
    """兼容旧接口 → Stage 2 precision。"""
    return score_article_pair_precision(
        ru_url=ru_url,
        zh_url=zh_url,
        ru_text=ru_text,
        zh_text=zh_text,
        ru_title=ru_title,
        zh_title=zh_title,
        time_delta_sec=time_delta_sec,
    )


def cross_lingual_topic_overlap(ru_text: str, zh_text: str) -> float:
    """兼容旧接口：返回 topic_overlap 分数。"""
    hits = count_topic_keyword_hits(ru_text, zh_text)
    return min(1.0, hits / 4.0) if hits >= MIN_TOPIC_KEYWORD_HITS else hits * 0.15
