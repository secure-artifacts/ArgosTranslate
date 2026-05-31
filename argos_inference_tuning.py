"""
按输入长度调整 Argos/CTranslate2 推理参数，并预热翻译引擎。
短词/短句用较小 beam；长中文则提高解码上限与 length_penalty，避免俄语输出过短。
"""
from __future__ import annotations


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


def debounce_ms_for_text(text: str) -> int:
    return 160 if is_short_text(text) else 360


def _scaled_max_decoding_tokens(text: str, saved: dict[str, object]) -> int:
    base = int(saved.get("max_decoding_tokens") or 512)
    t = (text or "").strip()
    if not t:
        return max(256, base)
    cjk = _cjk_char_count(t)
    plain_len = len(t)
    # 长中文需要更多目标语 token；按字数估算并封顶
    est = 320 + max(cjk, plain_len // 2) * 3
    if "\n" in t:
        est = max(est, 480 + max(len(p) for p in t.split("\n")) * 2)
    return max(base, min(4096, est))


def apply_for_input(text: str) -> None:
    global _SAVED
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

    if is_short_text(text):
        s.beam_size = min(4, int(_SAVED["beam_size"]) if int(_SAVED["beam_size"]) > 0 else 4)
        cjk = _cjk_char_count(text)
        s.max_decoding_tokens = 384 if cjk >= 12 else 256
        s.beam_patience = 1.0
        s.coverage_penalty = 0.0
        s.length_penalty = min(0.35, float(_SAVED["length_penalty"]))
        s.repetition_penalty = 1.0
    else:
        for key, val in _SAVED.items():
            setattr(s, key, val)
        s.max_decoding_tokens = _scaled_max_decoding_tokens(text, _SAVED)
        cjk = _cjk_char_count(text)
        if cjk >= 60 or len((text or "").strip()) >= 180:
            s.length_penalty = max(
                float(_SAVED["length_penalty"]),
                0.40 if cjk >= 120 else 0.36,
            )
            s.coverage_penalty = max(
                float(_SAVED["coverage_penalty"]),
                0.06 if cjk >= 120 else 0.0,
            )


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
            apply_for_input("тест")
            trans.translate("тест")
        except Exception:
            pass
