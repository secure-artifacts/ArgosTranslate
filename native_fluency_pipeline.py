"""中→俄/乌译后润色总线：collocation → style → anti-MT。"""
from __future__ import annotations

from native_fluency_config import detect_domain, native_fluency_enabled
from terminology_registry import normalize_source_lang


def post_edit_native(
    text: str,
    target_lang: str,
    *,
    source_text: str | None = None,
    domain: str | None = None,
) -> str:
    """
    译后润色链（不调用大模型）：
    collocation ranking → style rerank → anti-MT → cross-check
    """
    if not text or not native_fluency_enabled():
        return text
    lang = normalize_source_lang(target_lang)
    if lang not in ("ru", "uk"):
        return text
    src = source_text or ""
    dom = domain or detect_domain(src)
    t = text

    try:
        from slavic_collocation_rank import apply_collocation_ranking

        t = apply_collocation_ranking(src, t, lang, domain=dom)
    except ImportError:
        pass

    try:
        from news_style_rerank import apply_style_rerank

        t = apply_style_rerank(src, t, lang, domain=dom)
    except ImportError:
        pass

    try:
        from bidirectional_terminology import prevent_cross_track_mixing

        t = prevent_cross_track_mixing(t, lang, source_text=src)
    except ImportError:
        pass

    return t.strip() if t else t
