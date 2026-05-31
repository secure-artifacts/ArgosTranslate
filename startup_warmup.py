"""
启动后后台预热：翻译模型与 pymorphy2 并行加载，缩短首次翻译等待。
"""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

_done_lock = threading.Lock()
_done = False
_early_started = False


def _warmup_translation_pairs(pairs: set[tuple[str, str]]) -> None:
    try:
        import argostranslate.translate as tr
        import argos_inference_tuning as ait

        langs = {l.code: l for l in tr.get_installed_languages()}
        if not langs:
            return
        ait.apply_for_input("тест")
        sample = "тест"
        for fc, tc in pairs:
            L = langs.get(fc)
            R = langs.get(tc)
            if L is None or R is None:
                continue
            trans = L.get_translation(R)
            if trans is None:
                continue
            try:
                trans.translate(sample)
            except Exception:
                pass
    except Exception:
        pass


def _translation_pairs_for(
    from_code: str = "zh", to_code: str = "ru"
) -> set[tuple[str, str]]:
    fc = (from_code or "zh").strip().lower()
    tc = (to_code or "ru").strip().lower()
    pairs: set[tuple[str, str]] = {(fc, tc)}
    if "ru" in (fc, tc):
        pairs.add((fc if fc != "ru" else "zh", "ru"))
    if "uk" in (fc, tc):
        pairs.add((fc if fc != "uk" else "zh", "uk"))
    return pairs


def _preload_glossary_morphology() -> None:
    try:
        import terminology_bridge as tb
        import glossary_manager as gm

        gm.preload_morph_analyzer()
        glossary = tb.load_glossary()
        if glossary:
            gm.build_ru_lemma_index(glossary)
    except Exception:
        pass


def _wait_for_installed_languages(
    timeout_sec: float = 90.0, interval_sec: float = 0.35
) -> bool:
    deadline = time.monotonic() + max(5.0, timeout_sec)
    while time.monotonic() < deadline:
        try:
            import argostranslate.translate as tr

            if tr.get_installed_languages():
                return True
        except Exception:
            pass
        time.sleep(interval_sec)
    return False


def run_once_in_background(
    *,
    from_code: str = "zh",
    to_code: str = "ru",
    wait_languages: bool = True,
) -> None:
    """进程内只跑一次；在后台线程 / QThreadPool 中调用。"""
    global _done
    with _done_lock:
        if _done:
            return
        _done = True

    pairs = _translation_pairs_for(from_code, to_code)

    def _warmup_trans() -> None:
        if wait_languages:
            _wait_for_installed_languages()
        _warmup_translation_pairs(pairs)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="argos-warm") as pool:
        f_morph = pool.submit(_preload_glossary_morphology)
        f_trans = pool.submit(_warmup_trans)
        wait((f_morph, f_trans), return_when="ALL_COMPLETED")


def schedule_early() -> None:
    """GUI 显示前尽早启动：pymorphy2 立即加载，翻译模型轮询就绪后预热。"""
    global _early_started
    with _done_lock:
        if _early_started:
            return
        _early_started = True

    if os.environ.get("ARGOS_SKIP_EARLY_WARMUP", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return

    try:
        import glossary_manager as gm

        gm.preload_morph_analyzer_async()
    except Exception:
        pass

    def _run() -> None:
        run_once_in_background(wait_languages=True)

    threading.Thread(
        target=_run, name="argos-early-warmup", daemon=True
    ).start()


def schedule_from_tab(tab: Any) -> None:
    """语言包就绪后按当前标签语言对补预热（若早期任务尚未完成）。"""
    fc, tc = "zh", "ru"
    try:
        li = tab.left_language_combo.currentIndex()
        ri = tab.right_language_combo.currentIndex()
        L = tab._language_at_combo_index(li)
        R = tab._language_at_combo_index(ri)
        if L is not None and R is not None:
            fc = (L.code or "zh").strip().lower()
            tc = (R.code or "ru").strip().lower()
    except Exception:
        pass

    with _done_lock:
        already = _done

    if already:
        pairs = _translation_pairs_for(fc, tc)

        def _topup() -> None:
            _warmup_translation_pairs(pairs)

        threading.Thread(target=_topup, name="argos-warmup-topup", daemon=True).start()
        return

    from PyQt5.QtCore import QRunnable, QThreadPool

    class _Job(QRunnable):
        def run(self) -> None:
            run_once_in_background(
                from_code=fc, to_code=tc, wait_languages=False
            )

    QThreadPool.globalInstance().start(_Job())
