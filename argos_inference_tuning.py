"""
按输入长度调整 Argos/CTranslate2 推理参数，并预热翻译引擎。
短句：beam 4 + 按字数估算解码上限，避免截断；中/长句分档兼顾速度与译全。
"""
from __future__ import annotations

import os

_SAVED: dict[str, object] | None = None


def _cjk_char_count(text: str) -> int:
    n = 0
    for c in text or "":
        o = ord(c)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            n += 1
    return n


def is_short_text(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    cjk = _cjk_char_count(t)
    if cjk >= 24:
        return len(t) < 56 and t.count("\n") < 2
    return len(t) < 120 and t.count("\n") < 2


def is_ultra_short_text(text: str) -> bool:
    """极短句（如「你好」「谢谢」）：优先速度，跳过重型后处理/重译。"""
    t = (text or "").strip()
    if not t or "\n" in t:
        return False
    cjk = _cjk_char_count(t)
    return cjk <= 8 and len(t) <= 16


def text_tier(text: str) -> str:
    """short | medium | long — 用于推理与后处理分级。"""
    t = (text or "").strip()
    if not t or is_short_text(t):
        return "short"
    cjk = _cjk_char_count(t)
    if cjk >= 90 or len(t) >= 260 or t.count("\n") >= 4:
        return "long"
    return "medium"


def _short_decoding_tokens(text: str) -> int:
    """短句解码上限：按源语长度估算，避免俄/乌尾句被截断。"""
    t = (text or "").strip()
    if is_ultra_short_text(t):
        return max(48, min(96, 32 + _cjk_char_count(t) * 8 + len(t) * 2))
    cjk = _cjk_char_count(t)
    plain = len(t)
    est = 128 + cjk * 12 + plain * 2
    return max(320, min(640, est))


def debounce_ms_for_text(text: str) -> int:
    tier = text_tier(text)
    if tier == "short":
        return 450
    if tier == "medium":
        return 800
    return 1200


def debounce_ms_for_char_count(chars: int, *, block_count: int = 1) -> int:
    """按字数估算去抖（避免每次按键 toPlainText 全量扫描）。"""
    n = max(0, int(chars))
    nl = max(1, int(block_count))
    if n <= 4 and nl < 2:
        return 50
    if n < 120 and nl < 2:
        return 280
    if n < 260 and nl < 4:
        return 700
    return 1100


def _scaled_max_decoding_tokens(text: str, saved: dict[str, object]) -> int:
    base = int(saved.get("max_decoding_tokens") or 512)
    t = (text or "").strip()
    if not t:
        return max(256, base)
    cjk = _cjk_char_count(t)
    plain_len = len(t)
    est = 280 + max(cjk, plain_len // 2) * 2
    if "\n" in t:
        est = max(est, 420 + max(len(p) for p in t.split("\n")) * 2)
    tier = text_tier(t)
    cap = 2048 if tier == "short" else 2560 if tier == "medium" else 3840
    return max(base, min(cap, est))


def _ensure_saved() -> dict[str, object]:
    global _SAVED
    try:
        import argos_settings_compat as asc

        asc.ensure_extended_settings()
    except ImportError:
        pass
    import argostranslate.settings as s

    if _SAVED is None:
        _SAVED = {
            "beam_size": s.beam_size,
            "max_decoding_tokens": s.max_decoding_tokens,
            "beam_patience": s.beam_patience,
            "coverage_penalty": s.coverage_penalty,
            "length_penalty": s.length_penalty,
            "repetition_penalty": s.repetition_penalty,
        }
    return _SAVED


def apply_for_input(text: str) -> None:
    try:
        import argos_cpu_tuning as act

        act.apply_cpu_defaults()
    except ImportError:
        pass
    import argostranslate.settings as s

    saved = _ensure_saved()
    tier = text_tier(text)

    if is_ultra_short_text(text):
        s.beam_size = 1
        s.max_decoding_tokens = _short_decoding_tokens(text)
        s.beam_patience = 1.0
        s.coverage_penalty = max(0.01, float(saved["coverage_penalty"]))
        s.length_penalty = max(0.32, float(saved["length_penalty"]))
        s.repetition_penalty = max(1.0, float(saved["repetition_penalty"]))
        return

    if tier == "short":
        base_beam = int(saved["beam_size"]) if int(saved["beam_size"]) > 0 else 4
        s.beam_size = min(4, max(3, base_beam))
        s.max_decoding_tokens = _short_decoding_tokens(text)
        s.beam_patience = 1.0
        s.coverage_penalty = max(0.02, float(saved["coverage_penalty"]))
        s.length_penalty = max(0.36, float(saved["length_penalty"]))
        s.repetition_penalty = max(1.0, float(saved["repetition_penalty"]))
        return

    for key, val in saved.items():
        setattr(s, key, val)
    s.max_decoding_tokens = _scaled_max_decoding_tokens(text, saved)

    if tier == "medium":
        base_beam = int(saved["beam_size"]) if int(saved["beam_size"]) > 0 else 4
        s.beam_size = min(4, max(4, base_beam))
        s.length_penalty = max(float(saved["length_penalty"]), 0.37)
        s.coverage_penalty = max(float(saved["coverage_penalty"]), 0.04)
        s.beam_patience = 1.0
    else:
        # 长句：beam 5 + 略高 length/coverage，比 beam 6 更快且译文更完整
        base_beam = int(saved["beam_size"]) if int(saved["beam_size"]) > 0 else 5
        s.beam_size = min(5, max(5, base_beam))
        s.length_penalty = max(float(saved["length_penalty"]), 0.40)
        s.coverage_penalty = max(float(saved["coverage_penalty"]), 0.05)
        s.beam_patience = min(1.08, max(1.0, float(saved["beam_patience"])))


def apply_for_slavic_pair(text: str, from_code: str, to_code: str) -> None:
    """
    中→俄/乌：统一速度/准度分档（不再叠加大 beam）。
  环境变量 ARGOS_SLAVIC_FAST=1 时长文也用 beam 5。
    """
    src = (from_code or "").strip().lower()
    tgt = (to_code or "").strip().lower()
    if src not in ("zh", "zt", "cn", "zho") or tgt not in ("ru", "uk"):
        apply_for_input(text)
        return

    apply_for_input(text)

    import argostranslate.settings as s

    saved = _ensure_saved()
    if is_ultra_short_text(text):
        return
    tier = text_tier(text)
    if tier == "short":
        base_beam = int(saved["beam_size"]) if int(saved["beam_size"]) > 0 else 5
        s.beam_size = min(4, max(4, base_beam))
        s.max_decoding_tokens = _short_decoding_tokens(text)
        s.length_penalty = max(float(saved["length_penalty"]), 0.37)
        s.coverage_penalty = max(float(saved["coverage_penalty"]), 0.03)

    fast = os.environ.get("ARGOS_SLAVIC_FAST", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not fast:
        return
    if tier == "short":
        s.beam_size = 3
        return
    base = int(saved["beam_size"]) if int(saved["beam_size"]) > 0 else 5
    s.beam_size = min(5, base)
    s.coverage_penalty = float(saved["coverage_penalty"])


def warmup_translation(from_code: str, to_code: str) -> None:
    """后台预热：加载 CT2 模型与 Stanza 分句（首次 ru/uk 直译会快很多）。"""
    try:
        import startup_warmup as sw

        sw._warmup_translation_pairs(sw._translation_pairs_for(from_code, to_code))
    except Exception:
        fc = (from_code or "").strip().lower()
        tc = (to_code or "").strip().lower()
        if not fc or not tc:
            return
        try:
            import argostranslate.translate as tr

            langs = {l.code: l for l in tr.get_installed_languages()}
            if fc not in langs or tc not in langs:
                return
            trans = langs[fc].get_translation(langs[tc])
            if trans is None:
                return
            apply_for_slavic_pair("测试短句。", fc, tc)
            trans.translate("тест")
        except Exception:
            pass
