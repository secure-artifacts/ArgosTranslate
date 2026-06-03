"""翻译质量评估：专名/TM/glossary/语义/语法/幻觉指标。"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from corpus_pipeline.config import GOLD_CORPUS_DIR, TRANSLATION_EVAL_DIR
from corpus_pipeline.locked_glossary import load_locked

_HAN = re.compile(r"[\u4e00-\u9fff]{2,8}")
_CYR_ENT = re.compile(
    r"[А-ЯЁІЇЄҐ][А-Яа-яЁёІіЇїЄєҐґ\-]+(?:\s+[А-ЯЁІЇЄҐ][А-Яа-яЁёІіЇїЄєҐґ\-]+){0,2}"
)
_NUM = re.compile(r"\d{2,}")
_LAT_WORD = re.compile(r"[A-Za-z]{4,}")
_HTML_JUNK = re.compile(r"<[^>]+>|&[a-z]+;|https?://", re.I)


@dataclass
class EvalCaseResult:
    case_id: str
    source_lang: str
    target_lang: str
    hypothesis: str
    reference: str
    entity_recall: float
    glossary_coverage: float
    glossary_hit_rate: float
    locked_entity_consistency: float
    grammar_error_rate: float
    long_sentence_readability: float
    hallucination_rate: float
    tm_hit: bool
    tm_similarity: float
    tm_purity: float
    semantic_score: float
    length_ratio: float
    news_style_score: float
    diplomatic_style_score: float
    native_fluency_score: float
    collocation_hit_rate: float
    anti_mt_violation_rate: float

    def to_dict(self) -> dict:
        return asdict(self)


def test_sets_dir() -> Path:
    d = TRANSLATION_EVAL_DIR / "test_sets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def results_dir() -> Path:
    d = TRANSLATION_EVAL_DIR / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slavic_lang(source_lang: str) -> str:
    sl = (source_lang or "").lower()
    if sl == "ru":
        return "ru"
    if sl == "uk":
        return "uk"
    if sl == "zh":
        return "zh"
    return sl


def _entity_recall(hypothesis: str, reference: str) -> float:
    ref_ents = set(_HAN.findall(reference)) | {
        x.strip() for x in _CYR_ENT.findall(reference)
    }
    if not ref_ents:
        return 1.0
    hits = sum(1 for e in ref_ents if e in (hypothesis or ""))
    return round(hits / len(ref_ents), 4)


def _glossary_stats(source: str, hypothesis: str, source_lang: str) -> tuple[float, float]:
    """返回 (coverage, hit_rate)。"""
    sl = _slavic_lang(source_lang)
    if sl == "zh":
        return 0.5, 0.5
    locked = load_locked(sl) if sl in ("ru", "uk") else []
    if not locked:
        return 0.5, 0.5
    src_low = (source or "").lower()
    hits = total = 0
    for e in locked:
        lem = str(e.get("lemma") or e.get("source") or "")
        zh = str(e.get("zh") or e.get("target") or "")
        if len(lem) < 2:
            continue
        if lem.lower() in src_low:
            total += 1
            if zh and zh in (hypothesis or ""):
                hits += 1
    if total == 0:
        return 0.5, 0.5
    rate = hits / total
    return round(rate, 4), round(rate, 4)


def _locked_entity_consistency(
    source: str, hypothesis: str, reference: str, source_lang: str
) -> float:
    sl = _slavic_lang(source_lang)
    if sl not in ("ru", "uk"):
        return 1.0
    locked = load_locked(sl)
    src_low = (source or "").lower()
    hyp, ref = hypothesis or "", reference or ""
    checked = correct = 0
    for e in locked:
        lem = str(e.get("lemma") or e.get("source") or "")
        zh = str(e.get("zh") or e.get("target") or "")
        if len(lem) < 2 or lem.lower() not in src_low:
            continue
        checked += 1
        if zh in hyp and zh in ref:
            correct += 1
        elif zh in ref and zh not in hyp:
            pass  # miss
        elif zh in hyp:
            correct += 1
    if checked == 0:
        return 1.0
    return round(correct / checked, 4)


def _grammar_error_rate(hypothesis: str, target_lang: str) -> float:
    """启发式语法错误率（越高越差）。"""
    hyp = hypothesis or ""
    if not hyp:
        return 1.0
    tl = (target_lang or "").lower()
    errors = 0
    checks = 1
    if tl in ("zh", "cn", "zt"):
        checks += 1
        cyr = len(re.findall(r"[А-Яа-яЁёІіЇїЄєҐґ]", hyp))
        if cyr > max(len(hyp) * 0.08, 8):
            errors += 1
        if _LAT_WORD.findall(hyp) and len(_LAT_WORD.findall(hyp)) > 3:
            errors += 0.5
    if tl in ("ru", "uk"):
        checks += 1
        han = len(_HAN.findall(hyp))
        if han > max(len(hyp) * 0.06, 6):
            errors += 1
    if re.search(r"[。！？]{3,}|[,.]{4,}", hyp):
        errors += 1
        checks += 1
    if _HTML_JUNK.search(hyp):
        errors += 1
        checks += 1
    return round(min(1.0, errors / max(checks, 1)), 4)


def _long_sentence_readability(source: str, hypothesis: str, reference: str) -> float:
    src = source or ""
    if len(src) < 80:
        return 1.0
    hyp, ref = hypothesis or "", reference or ""
    if not hyp:
        return 0.0
    lr = len(hyp) / max(len(ref), 1)
    lr = lr if lr <= 1 else 1 / lr
    punct_ok = 1.0 if re.search(r"[。！？.!?]", hyp) else 0.6
    return round(min(1.0, 0.6 * lr + 0.4 * punct_ok), 4)


def _hallucination_rate(source: str, hypothesis: str, reference: str) -> float:
    """假设中出现 source/reference 均未出现的数字或长专名片段。"""
    hyp = hypothesis or ""
    src, ref = source or "", reference or ""
    pool = src + " " + ref
    spurious = 0
    total = 0
    for n in set(_NUM.findall(hyp)):
        total += 1
        if n not in pool:
            spurious += 1
    for ent in _CYR_ENT.findall(hyp):
        if len(ent) < 8:
            continue
        total += 1
        if ent not in pool and ent[:6] not in pool:
            spurious += 1
    for ent in _HAN.findall(hyp):
        if len(ent) < 3:
            continue
        total += 1
        if ent not in pool:
            spurious += 1
    if total == 0:
        return 0.0
    return round(spurious / total, 4)


def _fluency_scores(
    source: str, hypothesis: str, target_lang: str
) -> tuple[float, float, float, float, float]:
    """news, diplomatic, native_fluency, collocation_hit, anti_mt_violation。"""
    tl = (target_lang or "").lower()
    if tl not in ("ru", "uk"):
        return 0.5, 0.5, 0.5, 0.5, 0.0
    hyp = hypothesis or ""
    src = source or ""
    news = dip = native = 0.5
    coll_hit = 0.5
    anti_mt = 0.0
    try:
        from native_fluency_config import detect_domain
        from news_style_rerank import (
            diplomatic_style_score,
            native_fluency_score,
            news_style_score,
        )

        dom = detect_domain(src)
        news = news_style_score(hyp, domain=dom)
        dip = diplomatic_style_score(hyp)
        native = native_fluency_score(hyp, source_text=src, domain=dom)
    except ImportError:
        pass

    try:
        from slavic_collocation_rank import _load_collocations
        from native_fluency_config import detect_domain

        dom = detect_domain(src)
        total = hits = 0
        for entry in _load_collocations(tl):
            zh = str(entry.get("zh") or "").strip()
            if not zh or zh not in src:
                continue
            ed = str(entry.get("domain") or "")
            if ed and ed != dom and dom != "news":
                continue
            pref = str(entry.get("preferred") or "").strip()
            if not pref:
                continue
            total += 1
            if pref.lower() in hyp.lower():
                hits += 1
        if total:
            coll_hit = hits / total
    except ImportError:
        pass

    try:
        from native_fluency_config import _anti_mt_config

        rows = (_anti_mt_config().get(tl) or []) if tl in ("ru", "uk") else []
        violations = 0
        checked = 0
        low = hyp.lower()
        for row in rows:
            if not isinstance(row, dict):
                continue
            avoid = str(row.get("avoid") or "").strip().lower()
            if len(avoid) < 4:
                continue
            checked += 1
            if avoid in low:
                violations += 1
        if checked:
            anti_mt = violations / checked
    except ImportError:
        pass

    return (
        round(news, 4),
        round(dip, 4),
        round(native, 4),
        round(coll_hit, 4),
        round(anti_mt, 4),
    )


def evaluate_case(
    case: dict[str, Any],
    hypothesis: str,
    *,
    tm_lookup: bool = True,
) -> EvalCaseResult:
    cid = str(case.get("id") or case.get("case_id") or "unknown")
    src = case.get("source") or ""
    ref = case.get("reference") or case.get("target") or ""
    sl = case.get("source_lang") or "ru"
    tl = case.get("target_lang") or "zh"
    hyp = hypothesis or ""

    ls = max(len(re.sub(r"\s+", "", src)), 1)
    lt = max(len(re.sub(r"\s+", "", ref)), 1)
    lr = ls / lt if ls > lt else lt / ls

    gloss_cov, gloss_hit = _glossary_stats(src, hyp, sl)

    semantic = 0.0
    if hyp and ref:
        if hyp.strip() == ref.strip():
            semantic = 1.0
        else:
            try:
                from corpus_pipeline.bilingual_rerank import cross_lingual_similarity

                semantic = cross_lingual_similarity(hyp[:500], ref[:500])
            except Exception:
                semantic = _entity_recall(hyp, ref)

    tm_hit = False
    tm_sim = 0.0
    tm_pur = 0.0
    if tm_lookup and sl in ("ru", "uk") and tl == "zh":
        try:
            from corpus_pipeline.tm_store import best_match

            hit = best_match(src, sl, tl, min_ratio=0.88)
            if hit:
                tm_hit = True
                tm_sim = hit.similarity
                tm_pur = getattr(hit, "tm_purity_score", hit.confidence_score)
        except Exception:
            pass

    news_s, dip_s, flu_s, coll_s, anti_s = _fluency_scores(src, hyp, tl)

    return EvalCaseResult(
        case_id=cid,
        source_lang=sl,
        target_lang=tl,
        hypothesis=hyp,
        reference=ref,
        entity_recall=_entity_recall(hyp, ref),
        glossary_coverage=gloss_cov,
        glossary_hit_rate=gloss_hit,
        locked_entity_consistency=_locked_entity_consistency(src, hyp, ref, sl),
        grammar_error_rate=_grammar_error_rate(hyp, tl),
        long_sentence_readability=_long_sentence_readability(src, hyp, ref),
        hallucination_rate=_hallucination_rate(src, hyp, ref),
        tm_hit=tm_hit,
        tm_similarity=tm_sim,
        tm_purity=tm_pur,
        semantic_score=round(float(semantic), 4),
        length_ratio=round(lr, 4),
        news_style_score=news_s,
        diplomatic_style_score=dip_s,
        native_fluency_score=flu_s,
        collocation_hit_rate=coll_s,
        anti_mt_violation_rate=anti_s,
    )


def load_test_set(name: str) -> list[dict[str, Any]]:
    p = test_sets_dir() / f"{name}.jsonl"
    if not p.is_file():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def user_regression_path() -> Path:
    return test_sets_dir() / "user_gold_regression.jsonl"


def append_user_regression_case(
    source: str,
    reference: str,
    source_lang: str,
    target_lang: str,
    *,
    tags: list[str] | None = None,
    case_id: str | None = None,
) -> str:
    """用户 gold 句对写入 regression 测试集（防规则/TM 退化）。"""
    import hashlib

    src = (source or "").strip()
    ref = (reference or "").strip()
    cid = case_id or f"user_{hashlib.sha256(src.encode('utf-8')).hexdigest()[:12]}"
    path = user_regression_path()
    existing_ids: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                existing_ids.add(str(json.loads(line).get("id") or ""))
            except json.JSONDecodeError:
                continue
    if cid in existing_ids:
        return cid
    case = {
        "id": cid,
        "source": src,
        "reference": ref,
        "source_lang": (source_lang or "zh").strip().lower(),
        "target_lang": (target_lang or "ru").strip().lower(),
        "tags": list(tags or ["user_gold", "regression"]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(case, ensure_ascii=False) + "\n")
    return cid


def run_regression_guard(
    translate_fn=None,
    *,
    sets: tuple[str, ...] = ("user_gold_regression", "zh_person_descriptions"),
) -> dict[str, Any]:
    """推广后或发版前：跑关键 regression 集，检测 glossary/风格退化。"""
    summary: dict[str, Any] = {"sets": {}, "ok": True}
    for name in sets:
        p = test_sets_dir() / f"{name}.jsonl"
        if not p.is_file():
            summary["sets"][name] = {"skipped": True}
            continue
        rep = run_eval_set(name, translate_fn=translate_fn)
        summary["sets"][name] = rep
        avg = float(rep.get("avg_native_fluency_score") or 0)
        locked = float(rep.get("avg_locked_entity_consistency") or 1)
        if avg < 0.45 and translate_fn is not None:
            summary["ok"] = False
        if locked < 0.85:
            summary["ok"] = False
    return summary


def build_baseline_from_gold(source: str = "un", *, limit: int = 50) -> Path:
    sp = GOLD_CORPUS_DIR / source / "sentences.jsonl"
    out = test_sets_dir() / f"gold_{source}_baseline.jsonl"
    if not sp.is_file():
        out.write_text("", encoding="utf-8")
        return out
    rows: list[str] = []
    for i, line in enumerate(sp.read_text(encoding="utf-8").splitlines()):
        if i >= limit:
            break
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        case = {
            "id": f"gold_{source}_{i:04d}",
            "source": row.get("source"),
            "reference": row.get("target"),
            "source_lang": row.get("source_lang", "ru"),
            "target_lang": row.get("target_lang", "zh"),
            "tags": ["gold", source],
        }
        rows.append(json.dumps(case, ensure_ascii=False))
    out.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return out


def run_eval_set(name: str, translate_fn=None) -> dict[str, Any]:
    cases = load_test_set(name)
    results: list[dict] = []
    for case in cases:
        src = case.get("source") or ""
        ref = case.get("reference") or ""
        if translate_fn:
            hyp = translate_fn(src, case.get("source_lang"), case.get("target_lang"))
        else:
            hyp = ref
        results.append(evaluate_case(case, hyp).to_dict())

    def avg(key: str) -> float:
        vals = [float(x.get(key) or 0) for x in results]
        return round(sum(vals) / max(len(vals), 1), 4)

    summary = {
        "test_set": name,
        "cases": len(results),
        "avg_entity_recall": avg("entity_recall"),
        "avg_glossary_coverage": avg("glossary_coverage"),
        "avg_glossary_hit_rate": avg("glossary_hit_rate"),
        "avg_locked_entity_consistency": avg("locked_entity_consistency"),
        "avg_grammar_error_rate": avg("grammar_error_rate"),
        "avg_long_sentence_readability": avg("long_sentence_readability"),
        "avg_hallucination_rate": avg("hallucination_rate"),
        "tm_hit_rate": round(
            sum(1 for x in results if x.get("tm_hit")) / max(len(results), 1), 4
        ),
        "avg_tm_similarity": avg("tm_similarity"),
        "avg_semantic_score": avg("semantic_score"),
        "avg_news_style_score": avg("news_style_score"),
        "avg_diplomatic_style_score": avg("diplomatic_style_score"),
        "avg_native_fluency_score": avg("native_fluency_score"),
        "avg_collocation_hit_rate": avg("collocation_hit_rate"),
        "avg_anti_mt_violation_rate": avg("anti_mt_violation_rate"),
        "results": results,
    }
    out_path = results_dir() / f"eval_{name}.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def run_all_test_sets(translate_fn=None) -> dict[str, Any]:
    sets = sorted(p.stem for p in test_sets_dir().glob("*.jsonl"))
    reports = {}
    for name in sets:
        reports[name] = {
            k: v
            for k, v in run_eval_set(name, translate_fn=translate_fn).items()
            if k != "results"
        }
    out = results_dir() / "eval_all_summary.json"
    out.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    return reports
