"""联合国 news.un.org：两阶段 RU↔ZH 配对（宽召回 → embedding rerank）。"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from corpus_pipeline.article_content_score import (
    extract_article_body,
    score_article_content,
)
from corpus_pipeline.candidate_pairs import append_candidate, candidate_pairs_path
from corpus_pipeline.config import (
    MIN_PAIR_CONFIDENCE_TM,
    RECALL_MAX_DELTA_SEC,
    UN_AUTO_TM,
    UN_FULL_CAP,
)
from corpus_pipeline.manual_review_queue import enqueue_for_review, queue_file
from corpus_pipeline.fetchers.base import BaseFetcher, FetchResult, ParallelDocument
from corpus_pipeline.lang_detect import detect_cyrillic_lang, han_ratio
from corpus_pipeline.un_article_pairing import (
    collect_story_urls,
    match_by_published_time,
    parse_article_meta,
    score_article_pair_precision,
    stage1_recall_passes,
)

_NEWS_RU = "https://news.un.org/ru/"
_NEWS_ZH = "https://news.un.org/zh/"
_NEWS_ARCHIVE = ("https://news.un.org/ru/news", "https://news.un.org/zh/news")
_ARTICLE_MIN_SCORE = 0.48


def _un_domain(url: str) -> str:
    u = (url or "").lower()
    if "security-council" in u or "/sc/" in u:
        return "un_diplomatic"
    if "resolution" in u or "/ga/" in u:
        return "un_resolution"
    if "briefing" in u or "diplomat" in u:
        return "un_diplomatic"
    return "un_news"


class UnOrgFetcher(BaseFetcher):
    name = "un"

    def _fetch_meta(self, url: str) -> object:
        self.polite_sleep()
        raw = self.http_get(url)
        return parse_article_meta(raw, url)

    def _collect_lang_urls(self, lang: str, *, max_links: int) -> list[str]:
        home = _NEWS_RU if lang == "ru" else _NEWS_ZH
        archive = _NEWS_ARCHIVE[0] if lang == "ru" else _NEWS_ARCHIVE[1]
        out: list[str] = []
        for seed in (home, archive):
            for page_num in range(1, 16):
                if len(out) >= max_links:
                    break
                page_url = seed if page_num == 1 else f"{seed}?page={page_num}"
                try:
                    self.polite_sleep()
                    html = self.http_get(page_url)
                    for u in collect_story_urls(html, page_url, lang):
                        if u not in out:
                            out.append(u)
                except Exception:
                    continue
        return out[:max_links]

    def fetch(self, *, max_pages: int = 15) -> FetchResult:
        result = FetchResult()
        cap = UN_FULL_CAP if max_pages <= 0 else max_pages
        link_budget = max(cap * 3, 150)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        cand_path = candidate_pairs_path("un", stamp)

        ru_urls = self._collect_lang_urls("ru", max_links=link_budget)
        zh_urls = self._collect_lang_urls("zh", max_links=link_budget)

        ru_meta_list = []
        zh_meta_list = []
        for u in ru_urls:
            try:
                ru_meta_list.append(self._fetch_meta(u))
            except Exception as e:
                result.errors.append(f"meta {u}: {e}")
        for u in zh_urls:
            try:
                zh_meta_list.append(self._fetch_meta(u))
            except Exception as e:
                result.errors.append(f"meta {u}: {e}")

        ru_valid = [(m.url, m.published) for m in ru_meta_list if m.published]
        zh_valid = [(m.url, m.published) for m in zh_meta_list if m.published]
        meta_by_url = {m.url: m for m in ru_meta_list + zh_meta_list}

        pairs = match_by_published_time(
            ru_valid, zh_valid, max_delta_sec=RECALL_MAX_DELTA_SEC
        )[: cap * 3]

        fetched = 0
        recall_count = 0
        review_queued = 0
        pair_scores: list[dict] = []
        precision_rejected: list[dict] = []

        for ru_url, zh_url, time_delta in pairs:
            if fetched >= cap:
                break
            domain = _un_domain(ru_url)
            ru_m = meta_by_url.get(ru_url)
            zh_m = meta_by_url.get(zh_url)
            page: dict = {
                "ru_url": ru_url,
                "zh_url": zh_url,
                "time_delta_sec": round(time_delta, 1),
                "domain": domain,
                "status": "pending",
                "reason": "",
                "stage": "recall",
            }
            try:
                self.polite_sleep()
                ru_html = self.http_get(ru_url)
                ru_text = extract_article_body(ru_html)
                ru_score = score_article_content(ru_text, expect_lang="ru")
                page.update(ru_score.to_dict())
                page["ru_lang_detect"] = detect_cyrillic_lang(ru_text)
                ru_title = (ru_m.title if ru_m else "") or parse_article_meta(
                    ru_html, ru_url
                ).title

                if ru_score.reject_reason or ru_score.score < _ARTICLE_MIN_SCORE:
                    page["status"] = "skipped"
                    page["reason"] = ru_score.reject_reason or "low_article_content_score"
                    result.page_logs.append(page)
                    continue
                if page["ru_lang_detect"] not in ("ru", "mixed"):
                    page["status"] = "skipped"
                    page["reason"] = f"ru_lang_{page['ru_lang_detect']}"
                    result.page_logs.append(page)
                    continue

                self.polite_sleep()
                zh_html = self.http_get(zh_url)
                zh_text = extract_article_body(zh_html)
                zh_score = score_article_content(zh_text, expect_lang="zh")
                page["zh_han_ratio"] = round(han_ratio(zh_text), 4)
                page["zh_article_content_score"] = zh_score.score
                zh_title = (zh_m.title if zh_m else "") or parse_article_meta(
                    zh_html, zh_url
                ).title

                if zh_score.reject_reason or zh_score.score < _ARTICLE_MIN_SCORE:
                    page["status"] = "skipped"
                    page["reason"] = f"zh_{zh_score.reject_reason or 'low_score'}"
                    result.page_logs.append(page)
                    continue
                if page["zh_han_ratio"] < 0.12:
                    page["status"] = "skipped"
                    page["reason"] = "zh_low_han_ratio"
                    result.page_logs.append(page)
                    continue

                ok_recall, recall_reason = stage1_recall_passes(
                    ru_text=ru_text,
                    zh_text=zh_text,
                    time_delta_sec=time_delta,
                )
                if not ok_recall:
                    page["status"] = "skipped"
                    page["reason"] = recall_reason
                    page["stage"] = "recall_rejected"
                    result.page_logs.append(page)
                    continue

                recall_count += 1
                recall_record = {
                    "stage": "recall",
                    "ru_url": ru_url,
                    "zh_url": zh_url,
                    "ru_title": ru_title,
                    "zh_title": zh_title,
                    "time_delta_sec": round(time_delta, 1),
                    "topic_keyword_hits": page.get("topic_keyword_hits"),
                    "domain": domain,
                    "ru_body_len": len(ru_text),
                    "zh_body_len": len(zh_text),
                }
                append_candidate(cand_path, recall_record)

                ps = score_article_pair_precision(
                    ru_url=ru_url,
                    zh_url=zh_url,
                    ru_text=ru_text,
                    zh_text=zh_text,
                    ru_title=ru_title,
                    zh_title=zh_title,
                    time_delta_sec=time_delta,
                )
                ps_dict = ps.to_dict()
                pair_scores.append(ps_dict)
                append_candidate(
                    cand_path,
                    {**recall_record, "stage": "precision", **ps_dict},
                )
                page.update(
                    {
                        "stage": "precision",
                        "pair_confidence": ps.pair_confidence,
                        "topic_keyword_hits": ps.topic_keyword_hits,
                        "topic_overlap": ps.topic_overlap,
                        "title_similarity": ps.title_similarity,
                        "entity_overlap": ps.entity_overlap,
                        "embedding_combined": ps.embedding_combined,
                        "paragraph_topic_consistency": ps.paragraph_topic_consistency,
                    }
                )

                if not ps.accept:
                    page["status"] = "skipped"
                    page["reason"] = ps.reject_reason
                    precision_rejected.append(ps_dict)
                    result.page_logs.append(page)
                    continue

                review_item = {
                    "ru_url": ru_url,
                    "zh_url": zh_url,
                    "ru_title": ru_title,
                    "zh_title": zh_title,
                    "ru_text": ru_text,
                    "zh_text": zh_text,
                    "domain": domain,
                }
                queued, qreason = enqueue_for_review("un", review_item, pair_meta=ps_dict)
                page["manual_review"] = queued
                page["manual_review_reason"] = qreason
                if queued:
                    review_queued += 1
                    page["status"] = "review_queued"
                    page["reason"] = "manual_review_queue"
                else:
                    page["status"] = "precision_ok"
                    page["reason"] = ps.reject_reason or qreason or "below_review_threshold"

                result.page_logs.append(page)

                if UN_AUTO_TM:
                    result.documents.append(
                        ParallelDocument(
                            url=ru_url,
                            source_lang="ru",
                            target_lang="zh",
                            source_text=ru_text,
                            target_text=zh_text,
                            domain=domain,
                            title=urlparse(ru_url).path.rsplit("/", 1)[-1],
                            zh_url=zh_url,
                            pair_confidence=ps.pair_confidence,
                            pair_meta=ps_dict,
                        )
                    )
                    fetched += 1
            except Exception as e:
                page["status"] = "failed"
                page["reason"] = str(e)
                result.page_logs.append(page)
                result.errors.append(f"{ru_url}: {e}")

        success_logs = [p for p in result.page_logs if p.get("status") == "success"]
        confs = [float(p.get("pair_confidence") or 0) for p in success_logs]
        all_prec = [float(p.get("pair_confidence") or 0) for p in pair_scores]

        result.crawl_meta = {
            "source": "news.un.org_two_stage",
            "pairing_mode": "recall_then_embedding_rerank",
            "un_auto_tm": UN_AUTO_TM,
            "manual_review_queued": review_queued,
            "manual_review_file": str(queue_file("un")),
            "recall_max_delta_sec": RECALL_MAX_DELTA_SEC,
            "min_pair_confidence_tm": MIN_PAIR_CONFIDENCE_TM,
            "candidate_pairs_file": str(cand_path),
            "recall_candidates": recall_count,
            "precision_evaluated": len(pair_scores),
            "precision_rejected": len(precision_rejected),
            "discovered_ru_links": len(ru_urls),
            "discovered_zh_links": len(zh_urls),
            "time_matched_pairs": len(pairs),
            "paired_pages": fetched,
            "failed_pages": sum(
                1 for p in result.page_logs if p.get("status") == "failed"
            ),
            "skipped_pages": sum(
                1 for p in result.page_logs if p.get("status") == "skipped"
            ),
            "page_match_rate": round(fetched / max(len(pairs), 1), 4),
            "avg_pair_confidence": round(sum(confs) / len(confs), 4) if confs else 0.0,
            "pair_confidence_distribution": {
                "min": round(min(all_prec), 4) if all_prec else 0.0,
                "max": round(max(all_prec), 4) if all_prec else 0.0,
                "avg": round(sum(all_prec) / len(all_prec), 4) if all_prec else 0.0,
                "above_080": sum(1 for c in all_prec if c >= 0.80),
            },
            "article_pairs": pair_scores,
        }
        return result
