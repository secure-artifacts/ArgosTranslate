"""
Argos 主路径强化：源语整理 + 分档推理 + 俄/乌后处理。
默认开启（ARGOS_SLAVIC_ENHANCE=0 可关闭）。
"""
from __future__ import annotations

import os

from slavic_translation_hints import is_slavic_target, is_zh_to_slavic


def argos_slavic_enhance_enabled() -> bool:
    v = os.environ.get("ARGOS_SLAVIC_ENHANCE", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def prepare_argos_source(
    text: str,
    from_code: str,
    to_code: str,
) -> str:
    """Argos 翻译前源语整理（含中→俄/乌书名号与标点）。"""
    if not text or not argos_slavic_enhance_enabled():
        return text
    try:
        import translation_quality as tq
    except ImportError:
        return text
    src = (from_code or "").strip().lower()
    tgt = (to_code or "").strip().lower()
    t = tq.sanitize_source_text(text, for_llm=False)
    if is_zh_to_slavic(src, tgt):
        if hasattr(tq, "prepare_zh_for_cyrillic_target"):
            t = tq.prepare_zh_for_cyrillic_target(t, tgt)
        elif hasattr(tq, "normalize_zh_for_mt"):
            t = tq.normalize_zh_for_mt(t)
    elif hasattr(tq, "normalize_zh_for_mt") and src in ("zh", "zt", "cn"):
        t = tq.normalize_zh_for_mt(t)
    return t


def apply_argos_inference_tuning(
    text: str,
    from_code: str,
    to_code: str,
) -> None:
    """Argos CT2：按篇幅分档 beam（短句快、长句稍准），避免重复抬高 beam。"""
    if not argos_slavic_enhance_enabled():
        return
    try:
        import argos_inference_tuning as ait
    except ImportError:
        return
    if is_zh_to_slavic(from_code, to_code):
        ait.apply_for_slavic_pair(text, from_code, to_code)
    else:
        ait.apply_for_input(text)


def postprocess_depth(
    text: str,
    *,
    source_text: str | None = None,
    from_code: str | None = None,
    to_code: str | None = None,
) -> str:
    """
    short | normal | long | fast — 控制后处理耗时。
    中→俄/乌短句用 short：宗教/成语全保留 + 变格一遍（快且准）；其它语言对极短用 fast。
    """
    try:
        import argos_inference_tuning as ait
    except ImportError:
        return "normal"
    src = source_text or text
    tier = ait.text_tier(src)
    tlen = len((text or "").strip())
    if tier == "short" and tlen < 120:
        if is_zh_to_slavic(from_code or "", to_code or ""):
            return "short"
        return "fast"
    if tier == "long" or tlen >= 500:
        return "long"
    return "normal"


def postprocess_argos_target(
    text: str,
    from_code: str,
    to_code: str,
    *,
    source_text: str | None = None,
) -> str:
    """
    Argos 译文后处理（宗教搭配、成语 calque、变格、高级形态、文体冻结）。
    与 translation_quality.postprocess_translation_target 配合完成俄/乌后处理。
    """
    if not text:
        return text
    tgt = (to_code or "").strip().lower()
    if not is_slavic_target(tgt):
        return text
    if not argos_slavic_enhance_enabled():
        return text
    try:
        import translation_quality as tq
    except ImportError:
        return text
    src = (from_code or "").strip().lower()
    depth = postprocess_depth(
        text,
        source_text=source_text,
        from_code=from_code,
        to_code=to_code,
    )
    if is_zh_to_slavic(src, tgt):
        try:
            import zh_to_slavic_enhance as zts

            text = zts.postprocess_zh_to_slavic(
                text, tgt, source_text=source_text
            )
        except ImportError:
            pass
    if hasattr(tq, "postprocess_translation_target"):
        text = tq.postprocess_translation_target(
            text,
            tgt,
            source_text=source_text,
            source_lang_code=src,
            postprocess_depth=depth,
        )
        if is_zh_to_slavic(src, tgt):
            try:
                import zh_to_slavic_enhance as zts

                text = zts.apply_zh_to_slavic_terminology(
                    text, tgt, source_text=source_text
                )
                text = zts.prevent_cross_track_mixing(
                    text, tgt, source_text=source_text
                )
            except ImportError:
                try:
                    from bidirectional_terminology import (
                        apply_zh_to_slavic_terminology,
                        prevent_cross_track_mixing,
                    )

                    text = apply_zh_to_slavic_terminology(
                        text, tgt, source_text=source_text
                    )
                    text = prevent_cross_track_mixing(
                        text, tgt, source_text=source_text
                    )
                except ImportError:
                    pass
        return text
    if hasattr(tq, "touchup_cyrillic_target_spacing"):
        return tq.touchup_cyrillic_target_spacing(text)
    return text
