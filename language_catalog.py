"""
从已安装语言包的 metadata.json 扫描语言列表，不导入 ctranslate2 / torch。
用于翻译引擎 DLL 加载失败时仍能填充原语言 / 目标语言下拉框。
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _packages_dirs(portable_root: Path) -> list[Path]:
    dirs: list[Path] = []
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        p = Path(xdg) / "argos-translate" / "packages"
        if p.is_dir():
            dirs.append(p)
    local = portable_root / "data" / "local" / "argos-translate" / "packages"
    if local.is_dir() and local not in dirs:
        dirs.append(local)
    return dirs


def _iter_translate_metadata(packages_root: Path):
    for child in packages_root.iterdir():
        if not child.is_dir():
            continue
        meta_path = child / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        fc = (meta.get("from_code") or "").strip()
        tc = (meta.get("to_code") or "").strip()
        if not fc or not tc:
            continue
        yield {
            "from_code": fc,
            "from_name": (meta.get("from_name") or fc).strip(),
            "to_code": tc,
            "to_name": (meta.get("to_name") or tc).strip(),
        }


class Language:
    """与 argostranslate.translate.Language 字段兼容，避免导入 translate/sbd。"""

    def __init__(self, code: str, name: str):
        self.code = code
        self.name = name
        self.translations_from: list = []
        self.translations_to: list = []

    def get_translation(self, to) -> None:
        return None

    def __str__(self) -> str:
        return self.name


def load_languages_lightweight(portable_root: Path) -> list[Language]:
    """返回语言列表（无翻译路由，仅用于 UI 选语言）。"""
    try:
        import ollama_translate as ot

        if ot.use_ollama_backend():
            return ot.load_languages()
    except ImportError:
        pass
    by_code: dict[str, Language] = {}
    for pkg_root in _packages_dirs(portable_root):
        for row in _iter_translate_metadata(pkg_root):
            fc, fn = row["from_code"], row["from_name"]
            tc, tn = row["to_code"], row["to_name"]
            if fc not in by_code:
                by_code[fc] = Language(fc, fn)
            if tc not in by_code:
                by_code[tc] = Language(tc, tn)

    languages = list(by_code.values())
    if not languages:
        return []

    en_index = None
    for i, lang in enumerate(languages):
        if lang.code == "en":
            en_index = i
            break
    english = None
    if en_index is not None:
        english = languages.pop(en_index)
    languages.sort(key=lambda x: x.name)
    if english is not None:
        languages = [english] + languages
    return languages
