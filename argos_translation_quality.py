"""
中→俄/乌：通用译文质量评分与全后处理（不依赖固定中文短语规则）。

速度与准度：
- 快路径：正则 + idiom 硬错误，无 fluency 扫描
- 深评分：仅边界分或重译选优时对少量候选做 fluency
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from slavic_translation_hints import is_zh_to_slavic

_GLOSSA_MARK = re.compile(
    r"GLOSSA|ＧＬＯＳＳＡ|ГЛОССА",
    re.I,
)
_CJK_IN_TARGET = re.compile(r"[\u4e00-\u9fff]")
_LATIN_WORD = re.compile(r"\b[a-zA-Z]{4,}\b")
_CYR = re.compile(r"[а-яіїєґёА-ЯІЇЄҐЁ]")

_GENERIC_MT_RU = (
    r"\bиметь возможность\b",
    r"\bимеет возможность\b",
    r"\bпровести \w+ение\b",
    r"\bпроводить \w+ение\b",
    r"\bосуществить \w+\b",
    r"\bв настоящее время\b",
    r"\bна данный момент\b",
    r"\bв целях\b",
    r"\bоказать помощь\b",
)
_GENERIC_MT_UK = (
    r"\bмати можливість\b",
    r"\bмає можливість\b",
    r"\bпровести \w+ення\b",
    r"\bпроводити \w+ення\b",
    r"\bздійснити \w+\b",
    r"\bна даний момент\b",
    r"\bнадати допомогу\b",
)


@dataclass(frozen=True)
class QualityTierPolicy:
    """与 argos_inference_tuning.text_tier 对齐的质量策略。"""

    tier: str  # short | medium | long
    good_enough_score: float
    min_quality_score: float
    max_retries: int
    segment_min_zh_chars: int
    segment_min_lines: int
    borderline_low: float
    borderline_high: float
    allow_segment: bool


@dataclass
class QualityReport:
    score: float
    issues: list[str] = field(default_factory=list)
    deep: bool = False
    min_threshold: float = 0.52

    @property
    def needs_improvement(self) -> bool:
        return self.score < self.min_threshold or bool(
            set(self.issues) & _critical_issues()
        )


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def quality_tier_policy(source_text: str) -> QualityTierPolicy:
    """
    短句聊天：快放行、少重译、不分段。
    长文讲道：更严评分、至多 2 次重译、允许分段兜底。
    """
    try:
        import argos_inference_tuning as ait

        tier = ait.text_tier(source_text)
    except ImportError:
        tier = "medium"

    if tier == "short":
        return QualityTierPolicy(
            tier="short",
            good_enough_score=_env_float("ARGOS_Q_SHORT_GOOD", 0.72),
            min_quality_score=_env_float("ARGOS_Q_SHORT_MIN", 0.54),
            max_retries=_env_int("ARGOS_Q_SHORT_RETRIES", 1),
            segment_min_zh_chars=9999,
            segment_min_lines=3,
            borderline_low=_env_float("ARGOS_Q_SHORT_BORDER_LO", 0.54),
            borderline_high=_env_float("ARGOS_Q_SHORT_BORDER_HI", 0.70),
            allow_segment=False,
        )
    if tier == "long":
        return QualityTierPolicy(
            tier="long",
            good_enough_score=_env_float("ARGOS_Q_LONG_GOOD", 0.62),
            min_quality_score=_env_float("ARGOS_Q_LONG_MIN", 0.50),
            max_retries=_env_int("ARGOS_Q_LONG_RETRIES", 2),
            segment_min_zh_chars=_env_int("ARGOS_Q_LONG_SEG_ZH", 12),
            segment_min_lines=2,
            borderline_low=_env_float("ARGOS_Q_LONG_BORDER_LO", 0.42),
            borderline_high=_env_float("ARGOS_Q_LONG_BORDER_HI", 0.78),
            allow_segment=True,
        )
    return QualityTierPolicy(
        tier="medium",
        good_enough_score=_env_float("ARGOS_Q_MED_GOOD", 0.66),
        min_quality_score=_env_float("ARGOS_Q_MED_MIN", 0.52),
        max_retries=_env_int("ARGOS_Q_MED_RETRIES", 1),
        segment_min_zh_chars=_env_int("ARGOS_Q_MED_SEG_ZH", 20),
        segment_min_lines=2,
        borderline_low=_env_float("ARGOS_Q_MED_BORDER_LO", 0.48),
        borderline_high=_env_float("ARGOS_Q_MED_BORDER_HI", 0.74),
        allow_segment=True,
    )


def effective_max_retries(source_text: str) -> int:
    """分档默认；若显式设置 ARGOS_QUALITY_MAX_RETRIES 则取二者较大值。"""
    pol = quality_tier_policy(source_text).max_retries
    if "ARGOS_QUALITY_MAX_RETRIES" not in os.environ:
        return pol
    return max(pol, _env_int("ARGOS_QUALITY_MAX_RETRIES", pol))


def _min_quality_score(source_text: str = "") -> float:
    if source_text:
        return quality_tier_policy(source_text).min_quality_score
    return _env_float("ARGOS_MIN_QUALITY_SCORE", 0.52)


def _good_enough_score(source_text: str = "") -> float:
    if source_text:
        return quality_tier_policy(source_text).good_enough_score
    return _env_float("ARGOS_GOOD_ENOUGH_SCORE", 0.68)


def _deep_score_mode() -> str:
    return os.environ.get("ARGOS_QUALITY_DEEP_SCORE", "auto").strip().lower()


def _critical_issues() -> frozenset[str]:
    return frozenset(
        {
            "glossa_leak",
            "too_short",
            "heavy_cjk_residue",
            "degenerate_repeat",
            "person_trait_flat",
            "qualities_work_bad",
            "church_title_plural",
            "empty",
        }
    )


def _zh_char_count(text: str) -> int:
    return len(_CJK_IN_TARGET.findall(text or ""))


def _cyrillic_ratio(text: str) -> float:
    t = text or ""
    if not t.strip():
        return 0.0
    cyr = len(_CYR.findall(t))
    return cyr / max(1, len(t))


def _needs_deep_score(
    fast: QualityReport,
    policy: QualityTierPolicy,
    *,
    zh_n: int = 0,
) -> bool:
    mode = _deep_score_mode()
    if mode in ("0", "false", "no", "off", "fast"):
        return False
    if mode in ("1", "true", "yes", "on", "always", "deep"):
        return True
    if set(fast.issues) & _critical_issues():
        return True
    if policy.tier == "long" and zh_n >= 36 and fast.score < 0.80:
        return True
    lo, hi = policy.borderline_low, policy.borderline_high
    return lo <= fast.score <= hi


def _score_core(
    source_text: str,
    target_text: str,
    to_code: str,
) -> tuple[float, list[str], int]:
    """轻量评分（无 fluency）。"""
    src = (source_text or "").strip()
    hyp = (target_text or "").strip()
    code = (to_code or "").strip().lower()
    issues: list[str] = []
    score = 1.0

    if not hyp:
        return 0.0, ["empty"], 0
    if _GLOSSA_MARK.search(hyp):
        return 0.05, ["glossa_leak"], _zh_char_count(src)

    zh_n = _zh_char_count(src)
    hyp_cyr = _cyrillic_ratio(hyp)
    if hyp_cyr < 0.25 and code in ("ru", "uk"):
        issues.append("low_cyrillic")
        score -= 0.35

    cjk_out = _zh_char_count(hyp)
    if cjk_out >= 2 and code in ("ru", "uk"):
        issues.append("heavy_cjk_residue")
        score -= min(0.45, 0.08 * cjk_out)

    if zh_n >= 6 and code in ("ru", "uk"):
        ratio = 0.35
        try:
            import argos_inference_tuning as ait

            if ait.text_tier(src) == "long":
                ratio = 0.42
        except ImportError:
            pass
        min_len = max(12, int(zh_n * ratio))
        if len(hyp) < min_len:
            issues.append("too_short")
            score -= 0.28
        ratio = len(hyp) / max(1, zh_n)
        if ratio > 4.5:
            issues.append("too_long")
            score -= 0.12

    latin = _LATIN_WORD.findall(hyp)
    if len(latin) >= 3 and code in ("ru", "uk"):
        issues.append("english_residue")
        score -= min(0.2, 0.04 * len(latin))

    low = hyp.lower()
    mt_pats = _GENERIC_MT_RU if code == "ru" else _GENERIC_MT_UK
    mt_hits = sum(1 for p in mt_pats if re.search(p, low, re.I))
    if mt_hits:
        issues.append("generic_mt")
        score -= min(0.35, 0.08 * mt_hits)

    try:
        import slavic_idioms as si

        if si._degenerate_repetitive_speech(hyp, code):
            issues.append("degenerate_repeat")
            score -= 0.3
        if si.person_trait_translation_bad(src, hyp):
            issues.append("person_trait_flat")
            score -= 0.38
        if si.target_qualities_work_translation_bad(src, hyp):
            issues.append("qualities_work_bad")
            score -= 0.2
        if si._target_church_member_title_plural_error(src, hyp):
            issues.append("church_title_plural")
            score -= 0.15
    except (ImportError, AttributeError):
        pass

    return max(0.0, min(1.0, score)), issues, zh_n


def _apply_fluency(
    src: str,
    hyp: str,
    code: str,
    score: float,
    issues: list[str],
    zh_n: int,
) -> float:
    try:
        from corpus_pipeline.translation_eval import _fluency_scores

        news, dip, native, coll, anti = _fluency_scores(src, hyp, code)
        score = score * 0.55 + native * 0.25 + news * 0.1 + (1.0 - anti) * 0.1
        if native < 0.42:
            issues.append("low_native_fluency")
            score -= 0.1
        if anti > 0.22:
            issues.append("anti_mt")
            score -= min(0.25, anti * 0.5)
        if coll < 0.25 and zh_n >= 6:
            issues.append("collocation_miss")
            score -= 0.06
    except ImportError:
        pass
    return round(max(0.0, min(1.0, score)), 4)


def score_translation(
    source_text: str,
    target_text: str,
    to_code: str,
    *,
    from_code: str = "zh",
    deep: bool | None = None,
) -> QualityReport:
    """
    0–1 分。deep=None（默认 auto）时：快分足够高/低则跳过 fluency。
    """
    src = (source_text or "").strip()
    policy = quality_tier_policy(src)
    score, issues, zh_n = _score_core(source_text, target_text, to_code)
    rep = QualityReport(
        score,
        issues,
        deep=False,
        min_threshold=policy.min_quality_score,
    )
    if deep is None:
        deep = _needs_deep_score(rep, policy, zh_n=zh_n)
    if deep:
        code = (to_code or "").strip().lower()
        score = _apply_fluency(
            (source_text or "").strip(),
            (target_text or "").strip(),
            code,
            score,
            issues,
            zh_n,
        )
        rep = QualityReport(
            score, issues, deep=True, min_threshold=policy.min_quality_score
        )
    else:
        rep.score = round(score, 4)
    return rep


def looks_good_enough(
    source_text: str,
    target_text: str,
    from_code: str,
    to_code: str,
) -> bool:
    """快路径：多数正常句在此返回，避免重译。"""
    if not is_zh_to_slavic(from_code, to_code):
        return True
    policy = quality_tier_policy(source_text)
    rep = score_translation(
        source_text, target_text, to_code, from_code=from_code, deep=False
    )
    if set(rep.issues) & _critical_issues():
        return False
    if rep.score >= policy.good_enough_score:
        return True
    if rep.needs_improvement:
        return False
    try:
        import slavic_idioms as si

        if si.person_trait_translation_bad(source_text, target_text):
            return False
        if si._degenerate_repetitive_speech(
            target_text, (to_code or "").strip().lower()
        ):
            return False
    except (ImportError, AttributeError):
        pass
    return True


def should_improve_translation(
    source_text: str,
    target_text: str,
    from_code: str,
    to_code: str,
) -> bool:
    if not is_zh_to_slavic(from_code, to_code):
        return False
    if looks_good_enough(source_text, target_text, from_code, to_code):
        return False
    rep = score_translation(
        source_text, target_text, to_code, from_code=from_code, deep=None
    )
    if rep.needs_improvement:
        return True
    code = (to_code or "").strip().lower()
    try:
        import slavic_idioms as si

        if si.person_trait_translation_bad(source_text, target_text):
            return True
        if si.target_qualities_work_translation_bad(source_text, target_text):
            return True
        if si._target_church_member_title_plural_error(
            source_text, target_text
        ):
            return True
        if si._degenerate_repetitive_speech(target_text, code):
            return True
    except (ImportError, AttributeError):
        pass
    return False


def retry_profile_for_issues(issues: list[str]) -> str:
    """按问题类型选推理档，单次重译即可对准。"""
    s = set(issues or [])
    if s & {"too_short", "low_cyrillic", "collocation_miss"}:
        return "coverage"
    if s & {"degenerate_repeat", "anti_mt", "generic_mt", "low_native_fluency"}:
        return "fluent"
    return "balanced"


def pick_best_candidate(
    source_text: str,
    candidates: list[str],
    from_code: str,
    to_code: str,
) -> str:
    """多候选：先快分筛，仅对领先候选做深评分。"""
    if not candidates:
        return ""
    policy = quality_tier_policy(source_text)
    scored: list[tuple[float, str, list[str]]] = []
    for c in candidates:
        if not (c or "").strip():
            continue
        rep = score_translation(
            source_text, c, to_code, from_code=from_code, deep=False
        )
        scored.append((rep.score, c, rep.issues))
    if not scored:
        return candidates[0]
    scored.sort(key=lambda x: x[0], reverse=True)
    top_sc, top_c, top_issues = scored[0]
    if len(scored) == 1:
        return top_c
    second_sc = scored[1][0]
    if top_sc - second_sc >= 0.04 and top_sc >= policy.good_enough_score:
        return top_c
    finalists = [scored[0]]
    if top_sc - second_sc < 0.04:
        finalists.append(scored[1])
    best_c = top_c
    best_sc = -1.0
    for sc, c, issues in finalists:
        rep = score_translation(
            source_text, c, to_code, from_code=from_code, deep=True
        )
        if rep.score > best_sc:
            best_sc = rep.score
            best_c = c
    return best_c


def postprocess_zh_slavic_ultra_short(
    text: str,
    source_text: str,
    from_code: str,
    to_code: str,
) -> str:
    """极短句：问候/常用语轻量修补，跳过变格与重译链。"""
    if not text or not is_zh_to_slavic(from_code, to_code):
        return text
    out = (text or "").strip()
    code = (to_code or "").strip().lower()
    src = source_text or ""
    try:
        import slavic_idioms as si

        if si.slavic_idiom_fix_enabled():
            out = si.apply_zh_greeting_fix(src, out, code)
            out = si.apply_zh_source_idiom_hints(src, out, code)
    except ImportError:
        pass
    try:
        import translation_quality as tq

        if hasattr(tq, "touchup_cyrillic_target_spacing"):
            out = tq.touchup_cyrillic_target_spacing(out)
    except ImportError:
        pass
    return out.strip() if out else out


def postprocess_zh_slavic_output(
    text: str,
    source_text: str,
    from_code: str,
    to_code: str,
) -> str:
    """完整 Argos 强化链（与界面 update_right_textEdit 一致）。"""
    if not text or not is_zh_to_slavic(from_code, to_code):
        return text
    try:
        import argos_inference_tuning as ait

        if ait.is_ultra_short_text(source_text):
            return postprocess_zh_slavic_ultra_short(
                text, source_text, from_code, to_code
            )
    except ImportError:
        pass
    out = text
    try:
        import slavic_translation_enhance as ste

        if ste.argos_slavic_enhance_enabled():
            out = ste.postprocess_argos_target(
                out,
                from_code,
                to_code,
                source_text=source_text,
            )
    except ImportError:
        pass
    return out.strip() if out else out


def should_try_segment_fallback(source_text: str) -> bool:
    """是否允许走分段翻译兜底。"""
    src = (source_text or "").strip()
    if not src:
        return False
    policy = quality_tier_policy(src)
    if not policy.allow_segment:
        return "\n" in src
    zh = _zh_char_count(src)
    if zh >= policy.segment_min_zh_chars:
        return True
    if "\n" in src:
        return True
    prep_lines = [ln for ln in src.split("\n") if ln.strip()]
    return len(prep_lines) >= policy.segment_min_lines


def translate_by_line_segments(
    source_text: str,
    translation,
    from_code: str,
    to_code: str,
    *,
    prepare_fn,
) -> str | None:
    """长文按行分段翻译（讲道/段落兜底）。"""
    if translation is None or not callable(prepare_fn):
        return None
    src = source_text or ""
    if not should_try_segment_fallback(src):
        return None
    prep = prepare_fn(src)
    policy = quality_tier_policy(src)
    min_lines = 2 if policy.allow_segment else policy.segment_min_lines
    lines = [ln.strip() for ln in prep.split("\n") if ln.strip()]
    if len(lines) < min_lines and policy.tier == "long":
        parts = re.split(r"(?<=[。！？!?；;])\s*", prep)
        lines = [p.strip() for p in parts if len(p.strip()) >= 4]
    if len(lines) < min_lines:
        return None
    try:
        parts = [translation.translate(ln) for ln in lines]
    except Exception:
        return None
    joined = "\n".join((p or "").strip() for p in parts)
    return postprocess_zh_slavic_output(
        joined, source_text, from_code, to_code
    )
