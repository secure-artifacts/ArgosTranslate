"""
Argos/CTranslate2 CPU 并行：在首次翻译前应用一次，加快多核机器上的推理。
可通过 settings.json 或环境变量 ARGOS_INTER_THREADS / ARGOS_INTRA_THREADS 覆盖。
"""
from __future__ import annotations

import os

_APPLIED = False


def _cpu_count() -> int:
    try:
        return max(2, int(os.cpu_count() or 4))
    except (TypeError, ValueError):
        return 4


def recommended_inter_threads() -> int:
    n = _cpu_count()
    return max(2, min(6, n // 2))


def recommended_intra_threads() -> int:
    n = _cpu_count()
    return max(2, min(8, n))


def apply_cpu_defaults() -> None:
    """仅进程内执行一次；不覆盖用户已在环境变量中显式设置的值。"""
    global _APPLIED
    if _APPLIED:
        return
    _APPLIED = True
    try:
        import argos_settings_compat as asc

        asc.ensure_extended_settings()
    except ImportError:
        pass
    try:
        import argostranslate.settings as s
    except ImportError:
        return

    if not os.environ.get("ARGOS_INTER_THREADS", "").strip():
        if int(getattr(s, "inter_threads", 1) or 1) <= 1:
            s.inter_threads = recommended_inter_threads()
    if not os.environ.get("ARGOS_INTRA_THREADS", "").strip():
        if int(getattr(s, "intra_threads", 0) or 0) <= 0:
            s.intra_threads = recommended_intra_threads()
