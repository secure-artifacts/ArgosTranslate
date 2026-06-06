"""
中→俄/乌：分层质量守卫（速度 + 准度）。

快路径：全后处理一次 → 快分放行
慢路径：规则修补 → 至多 1 次按问题选档重译 → 长文才分段
"""
from __future__ import annotations

import os
import re

from slavic_translation_hints import is_zh_to_slavic

_GLOSSA_MARK = re.compile(
    r"GLOSSA|ＧＬＯＳＳＡ|ГЛОССА",
    re.I,
)


def _target_has_emotion_words(text: str) -> bool:
    low = (text or "").lower()
    return bool(
        re.search(
            r"чувств|настроен|пережив|эмоци|душевн|"
            r"почутт|настрій|відчутт",
            low,
        )
    )


def _degenerate_repetitive_ru(text: str) -> bool:
    low = (text or "").lower()
    if low.count("говорит") < 2:
        return False
    if not re.search(r"говорит\s+прям", low):
        return False
    parts = [p.strip() for p in re.split(r"[,;]", text) if p.strip()]
    if len(parts) < 2:
        return False
    a, b = parts[0].lower(), parts[1].lower()
    return "говорит" in a and "говорит" in b and "прям" in a and "прям" in b


def _quality_retry_enabled() -> bool:
    return os.environ.get("ARGOS_QUALITY_RETRY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _max_quality_retries() -> int:
    try:
        return max(0, min(3, int(os.environ.get("ARGOS_QUALITY_MAX_RETRIES", "1"))))
    except ValueError:
        return 1


def _extra_profiles_enabled() -> bool:
    return os.environ.get("ARGOS_QUALITY_MULTI_CANDIDATE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _fast_retry_heuristics(
    source_text: str,
    postprocessed: str,
    from_code: str,
    to_code: str,
) -> bool:
    """无 fluency 的硬错误快检（postprocessed 已算好，避免重复后处理）。"""
    src = (source_text or "").strip()
    pp = (postprocessed or "").strip()
    if not src or not pp:
        return False
    if _GLOSSA_MARK.search(pp):
        return False

    try:
        import argos_translation_quality as atq

        if atq.looks_good_enough(src, pp, from_code, to_code):
            return False
        if atq.should_improve_translation(src, pp, from_code, to_code):
            return True
    except ImportError:
        pass

    needs_emotion = ("心情" in src) or ("感受" in src) or (
        "说出来" in src and ("心情" in src or "感受" in src)
    )
    code = "uk" if re.search(r"[іїєґ]", pp, re.I) else "ru"
    try:
        import slavic_idioms as si

        if si._degenerate_repetitive_speech(pp, code):
            return True
        if needs_emotion and not _target_has_emotion_words(pp):
            if si._degenerate_repetitive_speech(pp, code) or (
                "说出来" in src and len(pp) < len(src) * 2
            ):
                return True
        if si._target_church_member_title_plural_error(src, pp):
            return True
        if si.person_trait_translation_bad(src, pp):
            return True
        if si.target_qualities_work_translation_bad(src, pp):
            return True
    except (ImportError, AttributeError):
        if needs_emotion and not _target_has_emotion_words(pp):
            if _degenerate_repetitive_ru(pp) or (
                "说出来" in src and len(pp) < len(src) * 2
            ):
                return True
        if _degenerate_repetitive_ru(pp):
            return True
    return False


def should_retry_translation(
    source_text: str,
    target_text: str,
    from_code: str,
    to_code: str,
    *,
    postprocessed: str | None = None,
) -> bool:
    if not is_zh_to_slavic(from_code, to_code):
        return False
    out = (target_text or "").strip()
    if not (source_text or "").strip() or not out:
        return False
    try:
        import argos_translation_quality as atq

        pp = postprocessed
        if pp is None:
            pp = atq.postprocess_zh_slavic_output(
                out, source_text, from_code, to_code
            )
        return _fast_retry_heuristics(source_text, pp, from_code, to_code)
    except ImportError:
        return False


def apply_retry_inference(text: str, from_code: str, to_code: str) -> None:
    _apply_retry_profile("balanced", text)


def _apply_retry_profile(profile: str, text: str) -> None:
    try:
        import argos_inference_tuning as ait
    except ImportError:
        return
    try:
        import argostranslate.settings as s
    except ImportError:
        return
    saved = ait._ensure_saved()
    s.beam_size = min(6, max(4, int(saved["beam_size"]) or 5))
    est = ait._short_decoding_tokens(text)
    s.max_decoding_tokens = max(
        est, 512, ait._scaled_max_decoding_tokens(text, saved)
    )
    s.coverage_penalty = max(float(saved["coverage_penalty"]), 0.05)
    s.beam_patience = min(1.15, max(1.0, float(saved["beam_patience"])))
    if profile == "fluent":
        s.length_penalty = max(0.48, float(saved["length_penalty"]))
        s.repetition_penalty = max(
            1.05, float(saved["repetition_penalty"] or 1.0)
        )
    elif profile == "coverage":
        s.length_penalty = max(0.30, float(saved["length_penalty"]) * 0.85)
        s.coverage_penalty = max(0.10, float(saved["coverage_penalty"]))
    else:
        s.length_penalty = max(0.38, float(saved["length_penalty"]))


def try_fast_repair(
    source_text: str,
    target_text: str,
    to_code: str,
) -> str | None:
    try:
        import slavic_idioms as si
        import argos_translation_quality as atq
    except ImportError:
        return None
    code = (to_code or "").strip().lower()
    if code not in ("ru", "uk"):
        return None
    t = target_text
    if si.slavic_idiom_fix_enabled():
        t = si.apply_idiom_fixes(
            t, code, source_text=source_text, source_lang="zh"
        )
    if t == target_text:
        return None
    return atq.postprocess_zh_slavic_output(
        t, source_text, "zh", code
    )


def retry_translate(
    source_text: str,
    translation,
    from_code: str,
    to_code: str,
    *,
    prepare_fn,
    profile: str = "balanced",
) -> str | None:
    if translation is None or not callable(prepare_fn):
        return None
    try:
        _apply_retry_profile(profile, source_text)
        prepared = prepare_fn(source_text)
        raw = translation.translate(prepared)
        import argos_translation_quality as atq

        return atq.postprocess_zh_slavic_output(
            raw, source_text, from_code, to_code
        )
    except Exception:
        return None


def ensure_quality(
    target_text: str,
    source_text: str,
    from_code: str,
    to_code: str,
    translation,
    *,
    prepare_fn,
) -> str:
    try:
        import argos_translation_quality as atq
    except ImportError:
        return target_text or ""

    try:
        import argos_inference_tuning as ait

        if (
            ait.is_ultra_short_text(source_text)
            and is_zh_to_slavic(from_code, to_code)
        ):
            return atq.postprocess_zh_slavic_ultra_short(
                target_text or "",
                source_text,
                from_code,
                to_code,
            )
    except ImportError:
        pass

    base_pp = atq.postprocess_zh_slavic_output(
        target_text or "",
        source_text,
        from_code,
        to_code,
    )

    if not should_retry_translation(
        source_text,
        target_text,
        from_code,
        to_code,
        postprocessed=base_pp,
    ):
        return base_pp

    candidates: list[str] = [base_pp]
    fast = try_fast_repair(source_text, target_text, to_code)
    if fast:
        candidates.append(fast)

    if atq.looks_good_enough(source_text, fast or base_pp, from_code, to_code):
        return atq.pick_best_candidate(
            source_text, candidates, from_code, to_code
        )

    if not _quality_retry_enabled():
        return atq.pick_best_candidate(
            source_text, candidates, from_code, to_code
        )

    rep = atq.score_translation(
        source_text,
        base_pp,
        to_code,
        from_code=from_code,
        deep=False,
    )
    profile = atq.retry_profile_for_issues(rep.issues)
    retries = atq.effective_max_retries(source_text)
    profiles = [profile]
    if _extra_profiles_enabled():
        for p in ("balanced", "fluent", "coverage"):
            if p not in profiles:
                profiles.append(p)
    elif retries > 1:
        alt = "fluent" if profile == "balanced" else "balanced"
        profiles.append(alt)

    retry_limit = len(profiles) if _extra_profiles_enabled() else max(1, retries)
    if translation is not None:
        for p in profiles[:retry_limit]:
            alt = retry_translate(
                source_text,
                translation,
                from_code,
                to_code,
                prepare_fn=prepare_fn,
                profile=p,
            )
            if alt:
                candidates.append(alt)
            if atq.looks_good_enough(source_text, alt or "", from_code, to_code):
                break

    best = atq.pick_best_candidate(
        source_text, candidates, from_code, to_code
    )
    if atq.looks_good_enough(source_text, best, from_code, to_code):
        return best

    if not atq.should_improve_translation(
        source_text, best, from_code, to_code
    ):
        return best

    seg = None
    if atq.should_try_segment_fallback(source_text):
        seg = atq.translate_by_line_segments(
            source_text,
            translation,
            from_code,
            to_code,
            prepare_fn=prepare_fn,
        )
    if seg:
        candidates.append(seg)
        best = atq.pick_best_candidate(
            source_text, candidates, from_code, to_code
        )
    return best
