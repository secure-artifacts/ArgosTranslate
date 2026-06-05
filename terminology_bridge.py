"""
术语库：源语言为中文时，在送入 Argos 前用占位符替换术语，译后再替换为指定外语词。
俄语/乌克兰语：还原时结合译文中占位符前后上下文，用 pymorphy2 自动变格（见 glossary_inflection.py）。
术语 JSON 中仍可为俄语写 lemma + grammemes 以强制固定格。
"""
from __future__ import annotations

import json
import re
import importlib.util
import unicodedata
from pathlib import Path
from typing import Any

import glossary_inflection as gi

try:
    import glossary_alternatives as ga
except ImportError:
    ga = None  # type: ignore

_bulk_prepare_fn: Any = None


def _prepare_for_argos_engine(text: str) -> str:
    """长文本切块副本，供 Argos 引擎使用（不修改用户编辑区原文）。"""
    global _bulk_prepare_fn
    if _bulk_prepare_fn is False:
        return text
    if _bulk_prepare_fn is not None:
        return _bulk_prepare_fn(text)
    bp = Path(__file__).resolve().parent / "bulk_text.py"
    if not bp.is_file():
        _bulk_prepare_fn = False
        return text
    spec = importlib.util.spec_from_file_location("bulk_text", bp)
    if spec is None or spec.loader is None:
        _bulk_prepare_fn = False
        return text
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, "prepare_long_translation_input", None)
    if not callable(fn):
        _bulk_prepare_fn = False
        return text
    _bulk_prepare_fn = fn
    return _bulk_prepare_fn(text)


def prepare_engine_input(text: str) -> str:
    """长文本切块副本（非中文源或 GUI 侧预处理）；中文术语路径在 apply_glossary 内已调用。"""
    return _prepare_for_argos_engine(text)


def portable_root() -> Path:
    return Path(__file__).resolve().parent


def glossary_path() -> Path:
    import os

    custom = os.environ.get("ARGOS_ZH_GLOSSARY")
    if custom:
        return Path(custom)
    return portable_root() / "data" / "glossary" / "zh_glossary.json"


def load_glossary() -> dict[str, Any]:
    path = glossary_path()
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_glossary(data: dict[str, Any]) -> None:
    path = glossary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def ru_cell_text(entry: Any) -> str:
    """兼容旧代码：显示俄语列。"""
    return target_cell_text(entry, "ru")


def target_cell_text(entry: Any, lang_code: str) -> str:
    """表格目标语列：字符串或结构化俄/乌术语的 lemma 显示。"""
    code = (lang_code or "").strip().lower()
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return str(entry) if entry is not None else ""
    val = entry.get(code)
    if isinstance(val, list):
        parts: list[str] = []
        for item in val:
            t = target_cell_text({code: item}, lang_code)
            if t:
                parts.append(t)
        return " / ".join(parts)
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        lem = str(val.get("lemma") or "").strip()
        if lem:
            return lem
    if code in ("ru", "uk"):
        lem = gi.term_lemma_from_entry(entry, code)
        if lem:
            return lem
    return ""


def parse_ru_cell(ru_raw: str) -> Any:
    """将表格单元格解析为写入 JSON 的 ru 字段（识别格并规范为 lemma）。"""
    ru_raw = (ru_raw or "").strip()
    if not ru_raw:
        return ""
    if ru_raw.startswith("{") and ru_raw.endswith("}"):
        try:
            obj = json.loads(ru_raw)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return gi.normalize_for_glossary_storage(ru_raw, "ru")


def parse_target_cell(raw: str, lang_code: str) -> Any:
    """写入 JSON 的目标语字段；俄/乌语识别各词格并规范为 lemma。"""
    code = (lang_code or "").strip().lower()
    raw = (raw or "").strip()
    if not raw:
        return ""
    if code == "ru":
        return parse_ru_cell(raw)
    if code == "uk":
        if raw.startswith("{") and raw.endswith("}"):
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        return gi.normalize_for_glossary_storage(raw, "uk")
    return raw


def _entry_has_target(entry: Any, to_code: str) -> bool:
    return bool(_resolve_target(entry, to_code))


def should_apply_glossary(from_code: str, to_code: str) -> bool:
    """当前语言对是否存在可用的术语译文（源文键由用户在术语表中按源语填写）。"""
    glossary = load_glossary()
    if not glossary:
        return False
    to_code = (to_code or "").strip().lower()
    if not to_code:
        return False
    for entry in glossary.values():
        if _entry_has_target(entry, to_code):
            return True
    return False


_LANG_LABEL_ZH: dict[str, str] = {
    "zh": "中文",
    "zt": "中文(繁体)",
    "en": "英语",
    "ru": "俄语",
    "uk": "乌克兰语",
    "de": "德语",
    "fr": "法语",
    "es": "西班牙语",
    "it": "意大利语",
    "pt": "葡萄牙语",
    "ja": "日语",
    "ko": "韩语",
    "ar": "阿拉伯语",
    "tr": "土耳其语",
    "pl": "波兰语",
    "nl": "荷兰语",
    "vi": "越南语",
}


def lang_display_name(code: str) -> str:
    c = (code or "").strip().lower()
    if not c:
        return ""
    if c in _LANG_LABEL_ZH:
        return _LANG_LABEL_ZH[c]
    try:
        import argostranslate.translate as tr

        for lang in tr.get_installed_languages():
            if (lang.code or "").strip().lower() == c:
                name = (lang.name or c).strip()
                return _LANG_LABEL_ZH.get(c, name)
    except Exception:
        pass
    return c.upper()


def list_glossary_language_choices() -> list[tuple[str, str]]:
    """术语库语言下拉：(code, 中文显示名)。"""
    seen: dict[str, str] = dict(_LANG_LABEL_ZH)
    try:
        import argostranslate.translate as tr

        for lang in tr.get_installed_languages():
            c = (lang.code or "").strip().lower()
            if not c or c in seen:
                continue
            name = (lang.name or c).strip()
            seen[c] = _LANG_LABEL_ZH.get(c, name)
    except Exception:
        pass
    return sorted(seen.items(), key=lambda x: (x[1], x[0]))


def _ru_inflect(lemma: str, grammemes: list[str]) -> str | None:
    try:
        import glossary_manager as gm
    except ImportError:
        return None
    morph = gm.shared_morph_analyzer()
    if morph is None:
        return None
    parses = morph.parse(lemma)
    if not parses:
        return lemma
    p = parses[0]
    tags = frozenset(g for g in grammemes if g)
    inf = p.inflect(tags)
    if inf is None:
        return lemma
    return inf.word


def _raw_target_string(entry: Any, to_code: str) -> str:
    """术语条目中的目标语原始字符串（未拆多义）。"""
    code = (to_code or "").strip().lower()
    if isinstance(entry, str):
        return entry.strip()
    if not isinstance(entry, dict):
        return str(entry or "").strip()
    val = None
    for k, v in entry.items():
        if isinstance(k, str) and k.strip().lower() == code:
            val = v
            break
    if val is None:
        val = entry.get("default")
    if isinstance(val, list):
        parts: list[str] = []
        if ga is not None:
            for item in val:
                parts.extend(ga.stored_rows_as_strings(item))
        else:
            for item in val:
                s = str(item).strip() if not isinstance(item, dict) else str(
                    item.get("surface") or item.get("lemma") or ""
                ).strip()
                if s:
                    parts.append(s)
        return " / ".join(parts)
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, dict):
        return str(val.get("surface") or val.get("lemma") or "").strip()
    if code in ("ru", "uk"):
        lem = gi.term_lemma_from_entry(entry, code)
        if lem:
            return lem
    val = entry.get("default")
    if isinstance(val, str):
        return val.strip()
    return ""


def _lemma_for_chosen(chosen: str, to_code: str) -> str:
    text = (chosen or "").strip()
    if not text:
        return ""
    code = (to_code or "").strip().lower()
    if code in ("ru", "uk"):
        analysis = gi.analyze_slavic_phrase(text, code)
        return str(analysis.get("lemma") or text).strip() or text
    return text


def _resolve_target(entry: Any, to_code: str) -> str | None:
    to_code = (to_code or "").strip().lower()
    if entry is None:
        return None
    if ga is not None:
        chosen, _, _ = ga.pick_for_translation(entry, to_code)
        if chosen:
            return _lemma_for_chosen(chosen, to_code)
    raw = _raw_target_string(entry, to_code)
    if not raw:
        return None
    if to_code in ("ru", "uk"):
        lem = gi.term_lemma_from_entry(entry, to_code)
        if lem:
            return lem
    if isinstance(entry, str):
        return entry.strip() or None
    if not isinstance(entry, dict):
        return str(entry).strip() or None
    for k, val in entry.items():
        if isinstance(k, str) and k.strip().lower() == to_code:
            if isinstance(val, str):
                return val.strip() or None
            if isinstance(val, dict):
                lem = str(val.get("lemma") or "").strip()
                return lem or None
            break
    val = entry.get("default")
    if isinstance(val, str):
        return val.strip() or None
    return None


def _resolve_ru_dict(d: dict[str, Any]) -> str | None:
    """返回 lemma（不在此处变格；变格在 restore_markers 时按句上下文进行）。"""
    lemma = str(d.get("lemma") or "").strip()
    return lemma or None


def _to_fullwidth_latin_digits(s: str) -> str:
    """ASCII 字母数字 → 全角，占位符更易被中文侧 SentencePiece 当作整块「西文」拷贝。"""
    out: list[str] = []
    for c in s:
        o = ord(c)
        if 48 <= o <= 57:
            out.append(chr(0xFF10 + (o - 48)))
        elif 65 <= o <= 90:
            out.append(chr(0xFF21 + (o - 65)))
        elif 97 <= o <= 122:
            out.append(chr(0xFF41 + (o - 97)))
        else:
            out.append(c)
    return "".join(out)


def _glossary_surface_marker(used: int) -> tuple[str, str]:
    """返回 (送入模型的全角标记, 对应的半角 canonical 串 GLOSSA####)。"""
    ascii_m = f"GLOSSA{used:04d}"
    return _to_fullwidth_latin_digits(ascii_m), ascii_m


def _glossary_alias_matches(glossary: dict[str, Any]) -> list[tuple[str, str]]:
    """(可匹配源语片段, 术语库存储键)，按片段长度降序。"""
    pairs: list[tuple[str, str]] = []
    for key in glossary.keys():
        if not isinstance(key, str) or not key.strip():
            continue
        storage_key = key.strip()
        if ga is not None:
            aliases = ga.list_source_aliases(storage_key)
        else:
            aliases = [storage_key]
        for alias in aliases:
            if alias:
                pairs.append((alias, storage_key))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def mask_source_terms(
    text: str, glossary: dict[str, Any], to_code: str
) -> tuple[str, list[dict[str, Any]]]:
    to_code = (to_code or "").strip().lower()
    slots: list[dict[str, Any]] = []
    out = text
    used = 0
    for alias, key in _glossary_alias_matches(glossary):
        entry = glossary[key]
        try:
            if ga is not None:
                chosen_surface, alternatives, chosen_index = ga.pick_for_translation(
                    entry, to_code
                )
                repl = (
                    _lemma_for_chosen(chosen_surface, to_code)
                    if chosen_surface
                    else None
                )
            else:
                repl = _resolve_target(entry, to_code)
                alternatives = [repl] if repl else []
                chosen_index = 0
                chosen_surface = alternatives[0] if alternatives else ""
        except Exception:
            # 跳过损坏术语条目，不影响其它术语与整句翻译。
            continue
        if not repl:
            continue
        meta = gi.extract_term_meta(
            {to_code: chosen_surface} if chosen_surface else entry, to_code
        )
        if not meta.get("lemma"):
            meta["lemma"] = repl
        raw_cell = _raw_target_string(entry, to_code) or repl
        if ga is not None and not alternatives:
            alternatives = ga.list_options_from_entry(entry, to_code) or [repl]
        while alias in out:
            surface, ascii_m = _glossary_surface_marker(used)
            used += 1
            out = out.replace(alias, surface, 1)
            slots.append(
                {
                    "marker": surface,
                    "marker_ascii": ascii_m,
                    "lemma": meta.get("lemma") or repl,
                    "fixed_grammemes": meta.get("fixed_grammemes"),
                    "pos": meta.get("pos"),
                    "words": meta.get("words") or [],
                    "replacement": repl,
                    "zh_source": key,
                    "zh_matched": alias,
                    "raw_cell": raw_cell,
                    "alternatives": alternatives,
                    "chosen_index": chosen_index,
                }
            )
    return out, slots


def mask_zh_terms(text: str, glossary: dict[str, Any], to_code: str) -> tuple[str, list[dict[str, Any]]]:
    """兼容旧名。"""
    return mask_source_terms(text, glossary, to_code)


def _marker_index(marker: str) -> int:
    m = marker or ""
    if m.startswith("GLOSSA"):
        tail = m[6:]
        if tail.isdigit():
            return int(tail)
    # 全角 GＬＯＳＳＡ 后接全角数字
    if m.startswith("ＧＬＯＳＳＡ") and len(m) >= 10:
        tail = m[6:]
        digits = "".join(
            str(ord(c) - 0xFF10) if 0xFF10 <= ord(c) <= 0xFF19 else ""
            for c in tail
        )
        if len(digits) == 4 and digits.isdigit():
            return int(digits)
    return 0


def _slot_sort_key(slot: dict[str, Any]) -> int:
    return _marker_index(slot.get("marker_ascii") or slot.get("marker") or "")


def _slot_replacement(
    slot: dict[str, Any],
    context_before: str,
    context_after: str,
    to_code: str,
) -> str:
    """按语言与上下文生成占位符还原文本。"""
    code = (to_code or "").strip().lower()
    lemma = str(slot.get("lemma") or slot.get("replacement") or "").strip()
    if not lemma:
        return ""
    if code in ("ru", "uk"):
        return gi.inflect_glossary_term(
            lemma,
            code,
            context_before,
            context_after,
            fixed_grammemes=slot.get("fixed_grammemes"),
            pos_hint=slot.get("pos"),
            words=slot.get("words") if isinstance(slot.get("words"), list) else None,
        )
    return str(slot.get("replacement") or lemma)


def restore_markers(
    translated: str, slots: list[dict[str, Any]], *, to_code: str = ""
) -> str:
    out, _ = restore_markers_with_spans(translated, slots, to_code=to_code)
    return out


def restore_markers_with_spans(
    translated: str,
    slots: list[dict[str, Any]],
    *,
    to_code: str = "",
) -> tuple[str, list[dict[str, Any]]]:
    """
    将译文中的术语占位符还原为带变格的术语形（俄/乌）或固定译文（其它语言）。
    送入模型的是全角「ＧＬＯＳＳＡ００００」；译文中也可能被规范成半角
    GLOSSA0000，或被插空格 / 西里尔同形字母，故做多轮替换与容错正则。
    """
    if not slots:
        return translated, []
    out = unicodedata.normalize("NFKC", translated or "")
    code = (to_code or "").strip().lower()
    spans: list[dict[str, Any]] = []
    by_ascii = {
        s["marker_ascii"]: s for s in slots if s.get("marker_ascii")
    }

    def _record_span(start: int, end: int, slot: dict[str, Any], surface: str) -> None:
        if end <= start or not surface:
            return
        alts = slot.get("alternatives")
        if not isinstance(alts, list) or len(alts) < 2:
            return
        spans.append(
            {
                "start": start,
                "end": end,
                "surface": surface,
                "zh_source": str(slot.get("zh_source") or ""),
                "raw_cell": str(slot.get("raw_cell") or ""),
                "alternatives": list(alts),
                "chosen_index": int(slot.get("chosen_index") or 0),
                "lemma": str(slot.get("lemma") or slot.get("replacement") or ""),
                "fixed_grammemes": slot.get("fixed_grammemes"),
                "pos": slot.get("pos"),
                "words": slot.get("words") if isinstance(slot.get("words"), list) else [],
                "context_before": out[:start],
                "context_after": out[end:],
                "target_lang": code,
            }
        )

    def _repl_at(match: re.Match[str], slot: dict[str, Any]) -> str:
        before = out[: match.start()]
        after = out[match.end() :]
        return _slot_replacement(slot, before, after, code)

    def _insert_repl(start: int, end: int, repl: str, slot: dict[str, Any]) -> None:
        nonlocal out
        before = out[:start]
        after = out[end:]
        _record_span(len(before), len(before) + len(repl), slot, repl)
        out = before + repl + after

    # 精确标记（全角 / 半角）
    ordered = sorted(slots, key=_slot_sort_key, reverse=True)
    for s in ordered:
        for key in (s.get("marker"), s.get("marker_ascii")):
            if not key:
                continue
            start = 0
            while True:
                idx = out.find(key, start)
                if idx < 0:
                    break
                before = out[:idx]
                after = out[idx + len(key) :]
                repl = _slot_replacement(s, before, after, code)
                _insert_repl(idx, idx + len(key), repl, s)
                start = idx + len(repl)

    # 容错：G L O S S A 0001、glossa0001、零宽空白等（半角）
    _gap = r"[\s\u200b-\u200d\ufeff\u00a0]*"
    flex_hw = re.compile(
        rf"G{_gap}L{_gap}O{_gap}S{_gap}S{_gap}A{_gap}(\d{{3,4}})(?!\d)",
        re.IGNORECASE,
    )

    def _flex_repl_hw(mm: re.Match[str]) -> str:
        d = mm.group(1).zfill(4)
        if not d.isdigit() or len(d) != 4:
            return mm.group(0)
        slot = by_ascii.get(f"GLOSSA{d}")
        if not slot:
            return mm.group(0)
        return _repl_at(mm, slot)

    out = flex_hw.sub(_flex_repl_hw, out)

    # 俄译模型常把拉丁占位整块「转写」为西里尔 ГЛОССА + 数字
    flex_cyr = re.compile(
        r"[Гг][\s\u200b-\u200d\ufeff\u00a0]*[Лл][\s\u200b-\u200d\ufeff\u00a0]*[Оо][\s\u200b-\u200d\ufeff\u00a0]*"
        r"[Сс][\s\u200b-\u200d\ufeff\u00a0]*[Сс][\s\u200b-\u200d\ufeff\u00a0]*[Аа][\s\u200b-\u200d\ufeff\u00a0]*"
        r"([\d０-９]{3,4})(?!\d)"
    )

    def _flex_repl_cyr(mm: re.Match[str]) -> str:
        raw_d = mm.group(1)
        d = "".join(
            str(ord(c) - 0xFF10) if 0xFF10 <= ord(c) <= 0xFF19 else c
            for c in raw_d
        )
        if not d.isdigit() or not (3 <= len(d) <= 4):
            return mm.group(0)
        slot = by_ascii.get("GLOSSA" + d.zfill(4))
        if not slot:
            return mm.group(0)
        return _repl_at(mm, slot)

    out = flex_cyr.sub(_flex_repl_cyr, out)

    # 全角字母数字间的空白容错
    _gfw = r"[\s\u200b-\u200d\ufeff\u00a0]*"
    flex_fw = re.compile(
        rf"Ｇ{_gfw}Ｌ{_gfw}Ｏ{_gfw}Ｓ{_gfw}Ｓ{_gfw}Ａ{_gfw}([０-９]{{3,4}})(?![０-９])"
    )

    def _repl_fw(mm: re.Match[str]) -> str:
        fw_d = mm.group(1)
        d = "".join(str(ord(c) - 0xFF10) for c in fw_d)
        if not d.isdigit() or not (3 <= len(d) <= 4):
            return mm.group(0)
        slot = by_ascii.get("GLOSSA" + d.zfill(4))
        if not slot:
            return mm.group(0)
        return _repl_at(mm, slot)

    out = flex_fw.sub(_repl_fw, out)

    # GLOSSA 0001 首字母后插空格
    for s in ordered:
        masc = s.get("marker_ascii") or ""
        if not masc:
            continue
        pat = re.compile(
            re.escape(masc[0]) + r"\s*" + re.escape(masc[1:]), re.IGNORECASE
        )

        def _spaced_repl(mm: re.Match[str], slot: dict[str, Any] = s) -> str:
            return _repl_at(mm, slot)

        out = pat.sub(_spaced_repl, out)
    return out, spans


def relocate_glossary_spans(text: str, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """后处理可能改动词形：在最终译文中重新定位术语高亮区间。"""
    if not text or not spans:
        return []
    out: list[dict[str, Any]] = []
    used_ranges: list[tuple[int, int]] = []
    for sp in sorted(spans, key=lambda s: int(s.get("start") or 0)):
        surface = str(sp.get("surface") or "").strip()
        if not surface:
            continue
        start_hint = int(sp.get("start") or 0)
        idx = -1
        for probe in (surface, surface.lower(), surface.capitalize()):
            pos = text.find(probe, max(0, start_hint - 48))
            if pos < 0:
                pos = text.find(probe)
            if pos >= 0:
                end = pos + len(probe)
                if not any(not (end <= a or pos >= b) for a, b in used_ranges):
                    idx = pos
                    surface = probe
                    break
        if idx < 0:
            continue
        end = idx + len(surface)
        used_ranges.append((idx, end))
        row = dict(sp)
        row["start"] = idx
        row["end"] = end
        row["surface"] = surface
        row["context_before"] = text[:idx]
        row["context_after"] = text[end:]
        out.append(row)
    return out


def is_chinese_source_language(code: str) -> bool:
    """简体 zh、繁体 zt 等均走中文术语库（与语言包 code 一致）。"""
    c = (code or "").strip().lower()
    if not c:
        return False
    if c in ("zh", "zt", "zho"):
        return True
    if c.startswith("zh-") or c.startswith("zh_"):
        return True
    return False


def apply_glossary(
    translation,
    text: str,
    from_code: str,
    to_code: str,
    *,
    on_progress=None,
) -> str:
    return apply_glossary_with_spans(
        translation, text, from_code, to_code, on_progress=on_progress
    )[0]


def apply_glossary_with_spans(
    translation,
    text: str,
    from_code: str,
    to_code: str,
    *,
    on_progress=None,
) -> tuple[str, list[dict[str, Any]]]:
    def tr(s: str) -> str:
        prepared = _prepare_for_argos_engine(s)
        fn = translation.translate
        if on_progress is not None:
            try:
                return fn(prepared, on_progress=on_progress)
            except TypeError:
                pass
        return fn(prepared)

    if not (text or "").strip():
        return tr(text), []
    if not should_apply_glossary(from_code, to_code):
        return tr(text), []
    glossary = load_glossary()
    masked, slots = mask_source_terms(text, glossary, to_code)
    if not slots:
        return tr(text), []
    raw = tr(masked)
    out, spans = restore_markers_with_spans(raw, slots, to_code=to_code)
    return out, spans
