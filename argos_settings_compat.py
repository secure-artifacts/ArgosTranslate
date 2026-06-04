"""兼容 PyPI 原版 argostranslate.settings（缺 max_decoding_tokens 等推理参数）。"""
from __future__ import annotations

import os

_APPLIED = False

_DEFAULTS: dict[str, object] = {
    "max_input_tokens": 0,
    "max_decoding_tokens": 4096,
    "length_penalty": 0.32,
    "beam_patience": 1.0,
    "coverage_penalty": 0.0,
    "repetition_penalty": 1.0,
}


def _parse_nonneg_int(key: str, default: int) -> int:
    try:
        import argostranslate.settings as s

        raw = os.environ.get(key)
        if raw is None:
            raw = s.get_setting(key, str(default))
        v = int(raw)
        return max(0, v)
    except (TypeError, ValueError, ImportError):
        return default


def _parse_float_setting(key: str, default: float) -> float:
    try:
        import argostranslate.settings as s

        raw = os.environ.get(key)
        if raw is None:
            raw = s.get_setting(key, str(default))
        return float(raw)
    except (TypeError, ValueError, ImportError):
        return default


def ensure_extended_settings() -> None:
    """向 argostranslate.settings 模块补齐本仓库推理调参所需的属性。"""
    global _APPLIED
    if _APPLIED:
        return
    try:
        import argostranslate.settings as s
    except ImportError:
        return

    if not hasattr(s, "max_decoding_tokens"):
        s.max_input_tokens = _parse_nonneg_int("ARGOS_MAX_INPUT_TOKENS", 0)
        s.max_decoding_tokens = max(
            64, _parse_nonneg_int("ARGOS_MAX_DECODING_TOKENS", 4096)
        )
        s.length_penalty = max(
            0.05, min(2.0, _parse_float_setting("ARGOS_LENGTH_PENALTY", 0.32))
        )
        s.beam_patience = max(
            1.0, min(3.0, _parse_float_setting("ARGOS_BEAM_PATIENCE", 1.0))
        )
        s.coverage_penalty = max(
            0.0, min(1.0, _parse_float_setting("ARGOS_COVERAGE_PENALTY", 0.0))
        )
        s.repetition_penalty = max(
            1.0, min(2.0, _parse_float_setting("ARGOS_REPETITION_PENALTY", 1.0))
        )
        true_vals = {"1", "true", "True", "TRUE", "yes", "on"}
        if os.environ.get("ARGOS_PRECISE_TRANSLATION", "").strip() in true_vals or (
            s.get_setting("ARGOS_PRECISE_TRANSLATION", "0") in true_vals
        ):
            s.beam_size = max(int(getattr(s, "beam_size", 4) or 4), 12)
            s.length_penalty = max(float(s.length_penalty), 0.38)
            s.beam_patience = max(float(s.beam_patience), 1.12)
            s.max_decoding_tokens = max(int(s.max_decoding_tokens), 6144)
            s.coverage_penalty = max(float(s.coverage_penalty), 0.1)
            s.repetition_penalty = max(float(s.repetition_penalty), 1.03)
    else:
        for key, val in _DEFAULTS.items():
            if not hasattr(s, key):
                setattr(s, key, val)

    _APPLIED = True
