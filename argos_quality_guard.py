"""
中→俄/乌：检测明显劣质译文（重复直译、漏译情绪/感受等）并自动高精度重译一次。
"""
from __future__ import annotations

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
    """如：Она говорит прямо, ей говорит прямо."""
    low = (text or "").lower()
    if low.count("говорит") < 2:
        return False
    if not re.search(r"говорит\s+прям", low):
        return False
    parts = [p.strip() for p in re.split(r"[,;]", text) if p.strip()]
    if len(parts) < 2:
        return False
    a, b = parts[0].lower(), parts[1].lower()
    if "говорит" in a and "говорит" in b and "прям" in a and "прям" in b:
        return True
    return False


def should_retry_translation(
    source_text: str,
    target_text: str,
    from_code: str,
    to_code: str,
) -> bool:
    if not is_zh_to_slavic(from_code, to_code):
        return False
    src = (source_text or "").strip()
    out = (target_text or "").strip()
    if not src or not out:
        return False
    if _GLOSSA_MARK.search(out):
        return False
    needs_emotion = ("心情" in src) or ("感受" in src) or (
        "说出来" in src and ("心情" in src or "感受" in src)
    )
    if needs_emotion and not _target_has_emotion_words(out):
        if _degenerate_repetitive_ru(out) or (
            "说出来" in src and len(out) < len(src) * 2
        ):
            return True
    if _degenerate_repetitive_ru(out):
        return True
    try:
        import slavic_idioms as si

        if si._target_sister_title_plural_error(src, out):
            return True
        if si.target_qualities_work_translation_bad(src, out):
            return True
    except (ImportError, AttributeError):
        pass
    return False


def apply_retry_inference(text: str, from_code: str, to_code: str) -> None:
    """重译前：略提高 beam / 解码上限，优先译全。"""
    try:
        import argos_inference_tuning as ait
    except ImportError:
        return
    try:
        import argostranslate.settings as s
    except ImportError:
        return
    saved = ait._ensure_saved()
    base_beam = int(saved["beam_size"]) if int(saved["beam_size"]) > 0 else 5
    s.beam_size = min(5, max(5, base_beam))
    est = ait._short_decoding_tokens(text)
    s.max_decoding_tokens = max(est, 512, ait._scaled_max_decoding_tokens(text, saved))
    s.length_penalty = max(float(saved["length_penalty"]), 0.38)
    s.coverage_penalty = max(float(saved["coverage_penalty"]), 0.05)
    s.beam_patience = min(1.1, max(1.0, float(saved["beam_patience"])))


def _quality_retry_enabled() -> bool:
    import os

    return os.environ.get("ARGOS_QUALITY_RETRY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def try_fast_repair(
    source_text: str,
    target_text: str,
    to_code: str,
) -> str | None:
    """规则修补（毫秒级），避免为个别错句再跑一遍 CT2。"""
    try:
        import slavic_idioms as si
    except ImportError:
        return None
    code = (to_code or "").strip().lower()
    if code not in ("ru", "uk"):
        return None
    repaired = si.apply_zh_sister_title_fix(source_text, target_text, code)
    if repaired != target_text:
        target_text = repaired
    repaired = si.apply_zh_qualities_work_repairs(source_text, target_text, code)
    if repaired != target_text:
        target_text = repaired
    repaired = si.apply_zh_colloquial_sentence_repairs(
        source_text, target_text, code
    )
    if repaired == target_text:
        return None
    return repaired


def retry_translate(
    source_text: str,
    translation,
    from_code: str,
    to_code: str,
    *,
    prepare_fn,
) -> str | None:
    if translation is None or not callable(prepare_fn):
        return None
    try:
        apply_retry_inference(source_text, from_code, to_code)
        prepared = prepare_fn(source_text)
        return translation.translate(prepared)
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
    out = target_text or ""
    if not should_retry_translation(source_text, out, from_code, to_code):
        return out
    if not _quality_retry_enabled():
        fast = try_fast_repair(source_text, out, to_code)
        return fast if fast else out
    fast = try_fast_repair(source_text, out, to_code)
    if fast and not should_retry_translation(source_text, fast, from_code, to_code):
        return fast
    retry = retry_translate(
        source_text,
        translation,
        from_code,
        to_code,
        prepare_fn=prepare_fn,
    )
    if not retry:
        return out
    if should_retry_translation(source_text, retry, from_code, to_code):
        return out if len(out) > len(retry) else retry
    return retry
