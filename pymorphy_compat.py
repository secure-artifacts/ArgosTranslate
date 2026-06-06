"""
pymorphy3 / pymorphy2 兼容导入。

嵌入版 Python 3.12 无法使用原版 pymorphy2（inspect.getargspec 已移除），
需安装 pymorphy3；本模块优先加载 pymorphy3，再回退 pymorphy2。
"""
from __future__ import annotations

import sys
from typing import Any, Callable

_MorphAnalyzerClass: Callable[..., Any] | None | bool = False


def morph_analyzer_class() -> Callable[..., Any] | None:
    global _MorphAnalyzerClass
    if _MorphAnalyzerClass is not False:
        return _MorphAnalyzerClass
    for pkg in ("pymorphy3", "pymorphy2"):
        try:
            mod = __import__(pkg, fromlist=["MorphAnalyzer"])
            cls = getattr(mod, "MorphAnalyzer", None)
            if cls is not None:
                _MorphAnalyzerClass = cls
                return cls
        except Exception:
            continue
    _MorphAnalyzerClass = None
    return None


def backend_label() -> str:
    cls = morph_analyzer_class()
    if cls is None:
        return "pymorphy3"
    return (cls.__module__ or "pymorphy3").split(".", 1)[0]


def create_morph_analyzer(lang: str | None = None) -> Any | None:
    cls = morph_analyzer_class()
    if cls is None:
        return None
    try:
        code = (lang or "").strip().lower()
        morph = cls(lang=code) if code else cls()
        morph.parse("тест")
        return morph
    except Exception:
        return None


def dicts_package(lang: str) -> str:
    return f"{backend_label()}-dicts-{(lang or 'ru').strip().lower()}"


def install_command(*, lang: str | None = None) -> str:
    backend = backend_label()
    py = sys.executable
    if lang:
        return f'"{py}" -m pip install {backend} {dicts_package(lang)}'
    return (
        f'"{py}" -m pip install {backend} '
        f"{backend}-dicts-ru {backend}-dicts-uk"
    )
