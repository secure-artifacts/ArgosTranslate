"""语料管线：采集 → 对齐 → 质量评分 → TM / quarantine → glossary → logs。"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from corpus_pipeline.align import align_document
from corpus_pipeline.config import (
    ALIGNED,
    GLOSSARY_DIR,
    LOW_CONFIDENCE_THRESHOLD,
    MIN_PAIR_CONFIDENCE_TM,
    RAW,
    REPORTS,
    UN_AUTO_TM,
)
from corpus_pipeline.crawl_log import CrawlLogger, count_glossary_entries
from corpus_pipeline.fetchers import FETCHERS
from corpus_pipeline.merge_into_glossary import (
    detect_conflicts,
    merge_into_entities_file,
    write_conflicts_report,
)
from corpus_pipeline.metrics import record_pipeline_stats
from corpus_pipeline.glossary_extract import (
    count_high_confidence_glossary,
    extract_glossary_from_pairs,
    save_glossary_candidates,
)
from corpus_pipeline.quarantine import quarantine_file
from corpus_pipeline.quality_score import score_pair
from corpus_pipeline.tm_purity_score import score_tm_purity
from corpus_pipeline.tm_store import TMEntry, count_entries, insert_pairs


def _sample_pairs(rows: list[dict[str, Any]], n: int = 20) -> list[dict[str, Any]]:
    sents = [r for r in rows if r.get("level") == "sentence"]
    if not sents:
        return []
    pick = sents if len(sents) <= n else random.sample(sents, n)
    return [
        {
            "source": r.get("source", "")[:400],
            "target": r.get("target", "")[:400],
            "confidence": r.get("confidence"),
            "corpus_quality_score": r.get("corpus_quality_score"),
            "source_url": r.get("source_url"),
            "domain": r.get("domain"),
        }
        for r in pick
    ]


def _sample_glossary_from_candidates(candidates: list, n: int = 20) -> list[dict]:
    items = [c.to_entry_dict() for c in candidates]
    if len(items) <= n:
        return items
    return random.sample(items, n)


def run_source(
    source: str,
    *,
    max_pages: int = 20,
    merge_glossary: bool = False,
    confirm_merge: bool = False,
    detect_conflicts_only: bool = False,
    sample_pair_count: int = 20,
) -> dict[str, Any]:
    cls = FETCHERS.get(source)
    if cls is None:
        raise ValueError(f"未知来源: {source}；可选: {', '.join(FETCHERS)}")

    if detect_conflicts_only:
        path = write_conflicts_report()
        return {
            "source": source,
            "conflicts": len(detect_conflicts()),
            "conflicts_file": str(path),
        }

    tm_before = count_entries()
    glossary_before = count_glossary_entries()

    fetcher = cls()
    fr = fetcher.fetch(max_pages=max_pages)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    logger = CrawlLogger(source, stamp)
    for pl in getattr(fr, "page_logs", []) or []:
        logger.pages.append(pl)
    logger.errors.extend(fr.errors)

    raw_dir = RAW / source / stamp
    raw_dir.mkdir(parents=True, exist_ok=True)
    q_path = quarantine_file(source, stamp)

    all_sentence_rows: list[dict[str, Any]] = []
    all_para_rows: list[dict[str, Any]] = []
    tm_batch: list[TMEntry] = []
    all_glossary_candidates: list = []
    quality_scores: list[float] = []
    align_stats = {
        "source_sent_total": 0,
        "target_sent_total": 0,
        "aligned_sent_count": 0,
        "long_splits": 0,
        "short_merges": 0,
        "paragraph_pairs": 0,
    }

    pair_confidences: list[float] = []
    tm_purity_scores: list[float] = []

    skip_tm = source == "un" and not UN_AUTO_TM

    for i, doc in enumerate(fr.documents):
        pair_conf = float(getattr(doc, "pair_confidence", 1.0) or 1.0)
        if pair_conf > 0:
            pair_confidences.append(pair_conf)
        meta = {
            "url": doc.url,
            "zh_url": getattr(doc, "zh_url", "") or "",
            "source_url": doc.url,
            "source_lang": doc.source_lang,
            "target_lang": doc.target_lang,
            "domain": doc.domain,
            "title": doc.title,
            "pair_confidence": pair_conf,
            "pair_meta": getattr(doc, "pair_meta", None) or {},
        }
        (raw_dir / f"doc_{i:04d}_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (raw_dir / f"doc_{i:04d}_source.txt").write_text(
            doc.source_text, encoding="utf-8"
        )
        (raw_dir / f"doc_{i:04d}_target.txt").write_text(
            doc.target_text, encoding="utf-8"
        )

        aligned = align_document(
            doc.source_text,
            doc.target_text,
            doc.source_lang,
            doc.target_lang,
        )
        align_stats["source_sent_total"] += aligned.source_sent_count
        align_stats["target_sent_total"] += aligned.target_sent_count
        align_stats["aligned_sent_count"] += aligned.aligned_sent_count
        align_stats["long_splits"] += aligned.long_splits
        align_stats["short_merges"] += aligned.short_merges
        align_stats["paragraph_pairs"] += len(aligned.paragraph_pairs)

        doc_log = {
            "doc_index": i,
            "source_url": doc.url,
            "zh_url": getattr(doc, "zh_url", "") or "",
            "domain": doc.domain,
            "title": doc.title,
            "pair_confidence": pair_conf,
            "sentence_pairs": len(aligned.sentence_pairs),
            "low_confidence_pairs": 0,
            "avg_corpus_quality_score": 0.0,
        }
        allow_tm = pair_conf >= MIN_PAIR_CONFIDENCE_TM
        doc_scores: list[float] = []

        for pp in aligned.paragraph_pairs:
            pq = score_pair(
                pp.source,
                pp.target,
                doc.source_lang,
                doc.target_lang,
                align_confidence=pp.confidence,
            )
            all_para_rows.append(
                {
                    "level": "paragraph",
                    "source": pp.source,
                    "target": pp.target,
                    "source_lang": doc.source_lang,
                    "target_lang": doc.target_lang,
                    "domain": doc.domain,
                    "confidence": pp.confidence,
                    "corpus_quality_score": pq.corpus_quality_score,
                    "source_url": doc.url,
                }
            )

        tgt_norm = doc.target_lang
        if tgt_norm in ("zh", "zt", "cn"):
            tgt_norm = "zh"
        for ap in aligned.sentence_pairs:
            pq = score_pair(
                ap.source,
                ap.target,
                doc.source_lang,
                doc.target_lang,
                align_confidence=ap.confidence,
            )
            doc_scores.append(pq.corpus_quality_score)
            quality_scores.append(pq.corpus_quality_score)
            if ap.confidence < LOW_CONFIDENCE_THRESHOLD:
                doc_log["low_confidence_pairs"] += 1
            row = {
                "level": "sentence",
                "source": ap.source,
                "target": ap.target,
                "source_lang": doc.source_lang,
                "target_lang": doc.target_lang,
                "domain": doc.domain,
                "confidence": ap.confidence,
                "corpus_quality_score": pq.corpus_quality_score,
                "quality_reject": pq.reject_reason,
                "source_url": doc.url,
                "pair_confidence": pair_conf,
            }
            all_sentence_rows.append(row)
            purity = score_tm_purity(
                ap.source,
                ap.target,
                doc.source_lang,
                doc.target_lang,
                align_confidence=ap.confidence,
            )
            tm_purity_scores.append(purity.tm_purity_score)
            row["tm_purity_score"] = purity.tm_purity_score
            if (
                not skip_tm
                and allow_tm
                and not pq.reject_reason
                and not purity.reject_reason
            ):
                tm_conf = min(
                    ap.confidence,
                    pq.corpus_quality_score,
                    pair_conf,
                    purity.tm_purity_score,
                )
                tm_batch.append(
                    TMEntry(
                        source_text=ap.source,
                        target_text=ap.target,
                        source_lang=doc.source_lang,
                        target_lang=tgt_norm,
                        domain=doc.domain,
                        confidence_score=tm_conf,
                        source_url=doc.url,
                        tm_purity_score=purity.tm_purity_score,
                    )
                )
                if doc.source_lang in ("ru", "uk") and tgt_norm == "zh":
                    tm_batch.append(
                        TMEntry(
                            source_text=ap.target,
                            target_text=ap.source,
                            source_lang="zh",
                            target_lang=doc.source_lang,
                            domain=doc.domain,
                            confidence_score=max(0.75, tm_conf * 0.95),
                            source_url=doc.url,
                            tm_purity_score=purity.tm_purity_score,
                        )
                    )
        if doc_scores:
            doc_log["avg_corpus_quality_score"] = round(
                sum(doc_scores) / len(doc_scores), 4
            )
        logger.add_document(doc_log)

    aligned_path = ALIGNED / f"{source}_{stamp}.jsonl"
    aligned_path.parent.mkdir(parents=True, exist_ok=True)
    with open(aligned_path, "w", encoding="utf-8") as f:
        for row in all_para_rows + all_sentence_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    added, skipped, quarantined = insert_pairs(
        tm_batch,
        quality_gate=True,
        quarantine_path=q_path,
    )
    tm_after = count_entries()

    ner_total = 0
    glossary_high_conf = 0
    for lang in ("uk", "ru"):
        sub = [r for r in all_sentence_rows if r.get("source_lang") == lang]
        if not sub:
            continue
        candidates = extract_glossary_from_pairs(sub, lang, default_domain=source)
        all_glossary_candidates.extend(candidates)
        if candidates:
            save_glossary_candidates(candidates, lang)
        ner_total += len(candidates)

    glossary_after = count_glossary_entries()
    glossary_high_conf = count_high_confidence_glossary(0.72)
    low_conf = sum(
        1
        for r in all_sentence_rows
        if r.get("level") == "sentence"
        and float(r.get("confidence") or 0) < LOW_CONFIDENCE_THRESHOLD
    )
    low_conf_rate = low_conf / max(
        sum(1 for r in all_sentence_rows if r.get("level") == "sentence"), 1
    )

    crawl_meta = getattr(fr, "crawl_meta", {}) or {}
    split_rate = align_stats["aligned_sent_count"] / max(
        align_stats["source_sent_total"], 1
    )
    long_split_rate = align_stats["long_splits"] / max(
        align_stats["aligned_sent_count"], 1
    )
    avg_quality = (
        round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else 0.0
    )

    sample_pairs = _sample_pairs(all_sentence_rows, sample_pair_count)
    sample_glossary = _sample_glossary_from_candidates(all_glossary_candidates, 20)

    merged = skipped_conflict = skipped_locked = 0
    if merge_glossary:
        write_conflicts_report()
        merged, skipped_conflict, skipped_locked = merge_into_entities_file(
            confirm=confirm_merge
        )

    summary = {
        "tm_entries_before": tm_before,
        "tm_added": added,
        "tm_skipped": skipped,
        "tm_quarantined": quarantined,
        "tm_entries_after": tm_after,
        "glossary_entries_before": glossary_before,
        "glossary_extracted_this_run": ner_total,
        "glossary_entries_after": glossary_after,
        "glossary_new_on_disk": max(0, glossary_after - glossary_before),
        "glossary_high_confidence_count": glossary_high_conf,
        "documents": len(fr.documents),
        "sentence_pairs": len(
            [r for r in all_sentence_rows if r.get("level") == "sentence"]
        ),
        "low_confidence_pairs": low_conf,
        "low_confidence_rate": round(low_conf_rate, 4),
        "avg_corpus_quality_score": avg_quality,
        "avg_pair_confidence": round(
            sum(pair_confidences) / len(pair_confidences), 4
        )
        if pair_confidences
        else 0.0,
        "pair_confidence_below_gate": sum(
            1 for c in pair_confidences if c < MIN_PAIR_CONFIDENCE_TM
        ),
        "avg_tm_purity_score": round(
            sum(tm_purity_scores) / len(tm_purity_scores), 4
        )
        if tm_purity_scores
        else 0.0,
        "quarantine_file": str(q_path),
        "failed_pages": crawl_meta.get("failed_pages", 0),
        "skipped_pages": crawl_meta.get("skipped_pages", 0),
        "page_match_rate": crawl_meta.get("page_match_rate"),
        "ru_lang_detect_accuracy": crawl_meta.get("ru_lang_detect_accuracy"),
        "zh_lang_detect_accuracy": crawl_meta.get("zh_lang_detect_accuracy"),
        "sentence_align_success_rate": round(split_rate, 4),
        "long_sentence_align_rate": round(split_rate, 4),
        "long_sentence_split_rate": round(long_split_rate, 4),
        "fetch_meta": crawl_meta,
    }

    log_path = logger.save(
        summary,
        sample_pairs=sample_pairs,
        sample_glossary=sample_glossary,
    )

    report = {
        "source": source,
        "stamp": stamp,
        "log_file": str(log_path),
        **summary,
        "align_stats": align_stats,
        "errors": fr.errors,
        "aligned_file": str(aligned_path),
        "sample_pairs": sample_pairs,
        "sample_glossary": sample_glossary,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"report_{source}_{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    record_pipeline_stats(source, report)
    return report


def run_all(
    *,
    max_pages: int = 15,
    merge_glossary: bool = False,
    confirm_merge: bool = False,
) -> list[dict[str, Any]]:
    reports = []
    for name in FETCHERS:
        try:
            reports.append(
                run_source(
                    name,
                    max_pages=max_pages,
                    merge_glossary=merge_glossary,
                    confirm_merge=confirm_merge,
                )
            )
        except Exception as e:
            reports.append({"source": name, "error": str(e)})
    return reports
