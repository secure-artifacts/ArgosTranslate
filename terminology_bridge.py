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
    """表格目标语列：优先显示用户变格短语 surface，其次 lemma。"""
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
        if code in ("ru", "uk"):
            shown = gi.phrase_display_from_value(val, code)
            if shown:
                return shown
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
    return _parse_slavic_cell_alternatives(ru_raw, "ru")


def _parse_slavic_cell_alternatives(raw: str, lang: str) -> Any:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if raw.startswith("{") and raw.endswith("}"):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    try:
        import glossary_alternatives as ga

        opts = ga.list_all_options(raw)
    except ImportError:
        opts = [raw]
    if len(opts) <= 1:
        return gi.normalize_for_glossary_storage(raw, lang)
    normalized: list[Any] = []
    seen: set[str] = set()
    for opt in opts:
        piece = (opt or "").strip()
        if not piece:
            continue
        key = piece.casefold()
        if key in seen:
            continue
        seen.add(key)
        val = gi.normalize_for_glossary_storage(piece, lang)
        normalized.append(val if val else piece)
    if not normalized:
        return gi.normalize_for_glossary_storage(raw, lang)
    if len(normalized) == 1:
        return normalized[0]
    return normalized


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
        return _parse_slavic_cell_alternatives(raw, "uk")
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
            if alias and _alias_ok_for_match(alias, storage_key):
                pairs.append((alias, storage_key))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def _alias_ok_for_match(alias: str, storage_key: str) -> bool:
    """避免单字别名误匹配（如「年」→ 年份）；整键为单字时仍允许。"""
    a = (alias or "").strip()
    key = (storage_key or "").strip()
    if not a:
        return False
    if len(a) >= 2:
        return True
    return a == key and len(key) == 1


def mask_source_terms(
    text: str,
    glossary: dict[str, Any],
    to_code: str,
    *,
    forced_by_key: dict[str, str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    to_code = (to_code or "").strip().lower()
    forced = {
        (k or "").strip(): (v or "").strip()
        for k, v in (forced_by_key or {}).items()
        if (k or "").strip() and (v or "").strip()
    }
    slots: list[dict[str, Any]] = []
    out = text
    used = 0
    for alias, key in _glossary_alias_matches(glossary):
        entry = glossary[key]
        raw_cell = _raw_target_string(entry, to_code) or ""
        search_from = 0
        while True:
            idx = out.find(alias, search_from)
            if idx < 0:
                break
            zh_before = out[:idx]
            zh_after = out[idx + len(alias) :]
            try:
                forced_surface = forced.get(key, "").strip()
                lock_alternative = False
                gloss_role = gi.infer_zh_glossary_role(zh_before, zh_after)
                if ga is not None:
                    alternatives = ga.list_options_from_entry(entry, to_code)
                    if forced_surface:
                        chosen_surface = forced_surface
                        chosen_index = 0
                        for i, alt in enumerate(alternatives):
                            if (
                                (alt or "").strip().casefold()
                                == forced_surface.casefold()
                            ):
                                chosen_index = i
                                break
                        fb = ga.pos_bucket_for_option(forced_surface, to_code)
                        if fb == "verb" and gloss_role == "object":
                            gloss_role = "predicate"
                        lock_alternative = True
                    else:
                        chosen_surface, alternatives, chosen_index = (
                            ga.pick_for_translation_by_role(
                                entry, to_code, gloss_role
                            )
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
                search_from = idx + len(alias)
                continue
            if not repl:
                search_from = idx + len(alias)
                continue
            meta = gi.extract_term_meta(entry, to_code)
            if chosen_surface:
                meta["lemma"] = _lemma_for_chosen(chosen_surface, to_code)
                analysis = gi.analyze_slavic_phrase(chosen_surface, to_code)
                meta["words"] = analysis.get("words") or meta.get("words") or []
                if lock_alternative:
                    try:
                        from glossary_manager import infer_pos_for_target

                        meta["pos"] = infer_pos_for_target(chosen_surface, to_code)
                    except ImportError:
                        pass
            if not meta.get("lemma"):
                meta["lemma"] = repl
            if ga is not None and not alternatives:
                alternatives = ga.list_options_from_entry(entry, to_code) or [repl]
            if not raw_cell:
                raw_cell = repl or ""
            surface, ascii_m = _glossary_surface_marker(used)
            used += 1
            out = out[:idx] + surface + out[idx + len(alias) :]
            search_from = idx + len(surface)
            slots.append(
                {
                    "marker": surface,
                    "marker_ascii": ascii_m,
                    "lemma": meta.get("lemma") or repl,
                    "fixed_grammemes": meta.get("fixed_grammemes"),
                    "pos": meta.get("pos"),
                    "words": meta.get("words") or [],
                    "pred_lemma": meta.get("pred_lemma") or "",
                    "replacement": repl,
                    "zh_source": key,
                    "zh_matched": alias,
                    "zh_context_before": zh_before,
                    "zh_context_after": zh_after,
                    "raw_cell": raw_cell,
                    "alternatives": alternatives,
                    "chosen_index": chosen_index,
                    "lock_alternative": lock_alternative,
                    "glossary_role": gloss_role if lock_alternative else "",
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
    lemma, pos_hint, words, role = gi.resolve_term_lemma_for_context(
        slot,
        code,
        target_before=context_before,
        target_after=context_after,
    )
    if not lemma:
        return ""
    if code in ("ru", "uk"):
        return gi.inflect_glossary_term(
            lemma,
            code,
            context_before,
            context_after,
            fixed_grammemes=slot.get("fixed_grammemes"),
            pos_hint=pos_hint or slot.get("pos"),
            words=words if isinstance(words, list) else None,
            glossary_role=role,
        )
    return str(slot.get("replacement") or lemma)


_GLOSSA_MARKER_RE = re.compile(
    r"G[\s\u200b-\u200d\ufeff\u00a0]*L[\s\u200b-\u200d\ufeff\u00a0]*O[\s\u200b-\u200d\ufeff\u00a0]*"
    r"S[\s\u200b-\u200d\ufeff\u00a0]*S[\s\u200b-\u200d\ufeff\u00a0]*A[\s\u200b-\u200d\ufeff\u00a0]*\d{3,4}",
    re.IGNORECASE,
)

_MODAL_VERB_SLOT_RE = re.compile(
    r"((?:не\s+)?(?:"
    r"можете|можешь|может|могут|можем|можу|можно|нельзя|"
    r"надо|нужно|следует|должен|должна|должно|должны|"
    r"умеете|умеешь|умеет|умеют"
    r")\s+)([А-Яа-яЁё][А-Яа-яЁё-]*(?:ть|ться|ти|чь)?)(\s+)",
    re.IGNORECASE,
)


def _glossary_term_visible(out: str, slot: dict[str, Any]) -> bool:
    norm = unicodedata.normalize("NFKC", out or "")
    low = norm.casefold()
    for alt in slot.get("alternatives") or []:
        a = (alt or "").strip()
        if a and a.casefold() in low:
            return True
    lem = str(slot.get("lemma") or slot.get("replacement") or "").strip()
    if lem and lem.casefold() in low:
        return True
    return False


def _glossary_marker_still_present(out: str) -> bool:
    norm = unicodedata.normalize("NFKC", out or "")
    if _GLOSSA_MARKER_RE.search(norm):
        return True
    if "ＧＬＯＳＳＡ" in norm:
        return True
    return False


def _repair_lost_glossary_slot(out: str, slot: dict[str, Any], code: str) -> str:
    """
    机器翻译未保留 GLOSSA 占位符时，在本地根据已译上下文插入术语（仅替换动词位）。
    不上传中文整句，仅使用已有俄/乌译文与术语 slot 元数据。
    """
    if code not in ("ru", "uk"):
        return out
    if _glossary_term_visible(out, slot):
        return out
    pos_raw = str(slot.get("pos") or "").strip().lower()
    if pos_raw in ("noun", "n", "名词", "adj", "adjective", "形容词", "other", "其他"):
        return out
    m = _MODAL_VERB_SLOT_RE.search(out or "")
    if not m:
        return out
    before = out[: m.start(2)]
    after = out[m.end(2) :]
    repl = _slot_replacement(slot, before, after, code)
    if not repl or repl.casefold() == m.group(2).casefold():
        return out
    return before + repl + after


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

    def _record_span(
        start: int,
        end: int,
        slot: dict[str, Any],
        surface: str,
        *,
        context_before: str | None = None,
        context_after: str | None = None,
    ) -> None:
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
                "context_before": (
                    context_before if context_before is not None else out[:start]
                ),
                "context_after": (
                    context_after if context_after is not None else out[end:]
                ),
                "target_lang": code,
            }
        )

    def _repl_at(match: re.Match[str], slot: dict[str, Any]) -> str:
        before = out[: match.start()]
        after = out[match.end() :]
        repl = _slot_replacement(slot, before, after, code)
        _record_span(
            match.start(),
            match.start() + len(repl),
            slot,
            repl,
            context_before=before,
            context_after=after,
        )
        return repl

    def _insert_repl(start: int, end: int, repl: str, slot: dict[str, Any]) -> None:
        nonlocal out
        before = out[:start]
        after = out[end:]
        _record_span(
            len(before),
            len(before) + len(repl),
            slot,
            repl,
            context_before=before,
            context_after=after,
        )
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

    if not _glossary_marker_still_present(out):
        for s in ordered:
            if not _glossary_term_visible(out, s):
                prev = out
                out = _repair_lost_glossary_slot(out, s, code)
                if out != prev:
                    _append_modal_verb_span(out, s, code, spans)
    return out, spans


def glossary_slots_satisfied(
    target_text: str,
    slots: list[dict[str, Any]],
    *,
    to_code: str = "",
) -> bool:
    """译文是否已含全部术语（无 GLOSSA 泄漏、无缺失 slot）。"""
    if not slots:
        return True
    out = (target_text or "").strip()
    if not out:
        return False
    if _GLOSSA_MARKER_RE.search(out) or _glossary_marker_still_present(out):
        return False
    for slot in slots:
        if not _glossary_term_visible(out, slot):
            return False
    return True


def count_missing_glossary_slots(
    target_text: str,
    slots: list[dict[str, Any]],
) -> int:
    if not slots:
        return 0
    out = (target_text or "").strip()
    if _GLOSSA_MARKER_RE.search(out) or _glossary_marker_still_present(out):
        return len(slots)
    return sum(1 for s in slots if not _glossary_term_visible(out, s))


def mask_and_slots_for_source(
    source_text: str,
    to_code: str,
) -> tuple[str, list[dict[str, Any]]]:
    """源文术语掩码与 slot 列表。"""
    glossary = load_glossary()
    return mask_source_terms(source_text, glossary, to_code)


def translate_with_glossary_slots(
    translation,
    source_text: str,
    from_code: str,
    to_code: str,
    *,
    on_progress=None,
) -> tuple[str, list[dict[str, Any]]]:
    """带术语掩码的完整翻译（供质量重试等复用）。"""
    return apply_glossary_with_spans(
        translation,
        source_text,
        from_code,
        to_code,
        on_progress=on_progress,
    )


def _infer_chosen_index_for_surface(
    surface: str,
    alternatives: list[str],
    *,
    context_before: str = "",
    context_after: str = "",
    to_code: str = "",
    pos_hint: str | None = None,
) -> int:
    """按译文中实际词形推断当前选中的备选下标。"""
    surf = (surface or "").strip()
    if not surf:
        return 0
    surf_cf = surf.casefold()
    for i, alt in enumerate(alternatives):
        if (alt or "").strip().casefold() == surf_cf:
            return i
    code = (to_code or "").strip().lower()
    if code in ("ru", "uk"):
        try:
            import glossary_alternatives as ga

            for i, alt in enumerate(alternatives):
                inf = ga.inflect_option(
                    alt,
                    code,
                    context_before,
                    context_after,
                    pos_hint=pos_hint,
                )
                if (inf or "").strip().casefold() == surf_cf:
                    return i
        except Exception:
            pass
    return 0


def _words_for_surface(surface: str, to_code: str) -> list[dict[str, Any]]:
    try:
        import glossary_inflection as gi

        phrase = gi.analyze_slavic_phrase((surface or "").strip(), to_code)
        words = phrase.get("words")
        if isinstance(words, list):
            return [dict(w) for w in words if isinstance(w, dict)]
    except Exception:
        pass
    return []


def _append_modal_verb_span(
    text: str,
    slot: dict[str, Any],
    to_code: str,
    spans: list[dict[str, Any]],
) -> None:
    """术语占位符丢失、本地补动词后，记录高亮区间。"""
    m = _MODAL_VERB_SLOT_RE.search(text or "")
    if not m:
        return
    start = m.start(2)
    end = m.end(2)
    surface = (text or "")[start:end]
    if not surface or not _glossary_term_visible(surface, slot):
        return
    alts = slot.get("alternatives")
    if not isinstance(alts, list) or len(alts) < 2:
        return
    for existing in spans:
        if int(existing.get("start") or -1) == start:
            return
    ctx_before = text[:start]
    ctx_after = text[end:]
    chosen_index = _infer_chosen_index_for_surface(
        surface,
        alts,
        context_before=ctx_before,
        context_after=ctx_after,
        to_code=to_code,
        pos_hint=slot.get("pos"),
    )
    lemma = (alts[chosen_index] or "").strip() if alts else surface
    word_meta = _words_for_surface(surface, to_code) or _words_for_surface(
        lemma, to_code
    )
    spans.append(
        {
            "start": start,
            "end": end,
            "surface": surface,
            "zh_source": str(slot.get("zh_source") or ""),
            "raw_cell": str(slot.get("raw_cell") or ""),
            "alternatives": list(alts),
            "chosen_index": chosen_index,
            "lemma": lemma,
            "fixed_grammemes": slot.get("fixed_grammemes"),
            "pos": slot.get("pos"),
            "words": word_meta,
            "context_before": ctx_before,
            "context_after": ctx_after,
            "target_lang": (to_code or "").strip().lower(),
        }
    )


def find_glossary_spans_in_target(
    source_text: str,
    target_text: str,
    from_code: str,
    to_code: str,
) -> list[dict[str, Any]]:
    """在最终译文中推断术语高亮区间（占位符丢失或后处理改形时补全）。"""
    if not (source_text or "").strip() or not (target_text or "").strip():
        return []
    if not should_apply_glossary(from_code, to_code):
        return []
    glossary = load_glossary()
    _, slots = mask_source_terms(source_text, glossary, to_code)
    if not slots:
        return []
    spans: list[dict[str, Any]] = []
    for slot in slots:
        _append_modal_verb_span(target_text, slot, to_code, spans)
    return relocate_glossary_spans(target_text, spans)


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


_CJK_TAIL_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_CYR_WORD_RE = re.compile(r"[а-яёіїєґ]+", re.I)


class _ZhFragment:
    __slots__ = ("start", "end", "text")

    def __init__(self, start: int, end: int, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


def unmasked_zh_fragments(
    source_text: str, slots: list[dict[str, Any]]
) -> list[_ZhFragment]:
    """源文中未被术语替换的中文片段（保序、去重）。"""
    src = source_text or ""
    if not src or not _CJK_TAIL_RE.search(src):
        return []
    n = len(src)
    masked = [False] * n
    aliases: list[str] = []
    for slot in slots:
        alias = str(slot.get("zh_matched") or slot.get("zh_source") or "").strip()
        if alias and alias not in aliases:
            aliases.append(alias)
    aliases.sort(key=len, reverse=True)
    for alias in aliases:
        start = 0
        while True:
            idx = src.find(alias, start)
            if idx < 0:
                break
            for i in range(idx, min(n, idx + len(alias))):
                masked[i] = True
            start = idx + len(alias)
    fragments: list[_ZhFragment] = []
    seen: set[str] = set()
    i = 0
    while i < n:
        if masked[i] or not _CJK_TAIL_RE.match(src[i]):
            i += 1
            continue
        j = i
        while j < n and not masked[j] and _CJK_TAIL_RE.match(src[j]):
            j += 1
        seg = src[i:j].strip()
        if seg and seg not in seen:
            seen.add(seg)
            fragments.append(_ZhFragment(i, j, seg))
        i = j
    return fragments


def has_untranslated_zh_beside_glossary(
    source_text: str, from_code: str, to_code: str
) -> bool:
    """术语掩码旁是否仍有未替换的中文（前/中/后均算）。"""
    if not is_chinese_source_language(from_code):
        return False
    if not should_apply_glossary(from_code, to_code):
        return False
    glossary = load_glossary()
    _, slots = mask_source_terms(source_text, glossary, to_code)
    return bool(unmasked_zh_fragments(source_text, slots))


def has_untranslated_zh_after_glossary(
    source_text: str, from_code: str, to_code: str
) -> bool:
    """兼容旧名。"""
    return has_untranslated_zh_beside_glossary(source_text, from_code, to_code)


def _zh_char_count(text: str) -> int:
    return len(_CJK_TAIL_RE.findall(text or ""))


def _tail_probe_words(zh_tail: str, translation) -> list[str]:
    try:
        raw = translation.translate(_prepare_for_argos_engine(zh_tail))
    except Exception:
        return []
    return [w for w in _CYR_WORD_RE.findall((raw or "").strip()) if len(w) >= 3]


def _fragment_missing_in_target(
    zh_fragment: str, target: str, translation
) -> bool:
    frag = (zh_fragment or "").strip()
    if not frag:
        return False
    tgt = (target or "").casefold()
    words = _tail_probe_words(frag, translation)
    if not words:
        return _zh_char_count(frag) >= 1
    return not any(w.casefold() in tgt for w in words)


def _restore_glossary_target(
    source_text: str,
    raw_target: str,
    to_code: str,
    slots: list[dict[str, Any]],
) -> str:
    out, _ = restore_markers_with_spans(raw_target, slots, to_code=to_code)
    ordered = sorted(slots, key=_slot_sort_key, reverse=True)
    for slot in ordered:
        if not _glossary_term_visible(out, slot):
            prev = out
            out = _repair_lost_glossary_slot(out, slot, to_code)
            if out != prev and not _glossary_term_visible(out, slot):
                out = prev
    return out


def _append_fragment_translation(
    out: str,
    frag: _ZhFragment,
    src_rstrip_len: int,
    translation,
) -> str:
    """补译未掩码中文片段；过滤年份/纯数字等明显误译。"""
    frag_text = (frag.text or "").strip()
    if not frag_text or _zh_char_count(frag_text) < 2:
        return out
    try:
        chunk = translation.translate(_prepare_for_argos_engine(frag_text))
    except Exception:
        return out
    chunk = (chunk or "").strip().strip(".,;:!?")
    if not chunk or chunk.casefold() in out.casefold():
        return out
    if re.fullmatch(r"[\d\s\.\-]+", chunk):
        return out
    if re.search(r"\b\d{4}\b", chunk) and _zh_char_count(frag_text) <= 3:
        return out
    if frag.start == 0:
        return f"{chunk} {out.lstrip()}".strip()
    if frag.end >= src_rstrip_len:
        return f"{out.rstrip()} {chunk}".strip()
    return out


def _full_retranslate_zh_slavic(
    source_text: str,
    to_code: str,
    translation,
    slots: list[dict[str, Any]],
    *,
    use_glossary: bool,
    masked_text: str | None = None,
) -> str:
    src = (source_text or "").strip()
    if not src:
        return ""
    if use_glossary and slots:
        text_for_mt = (masked_text or "").strip()
        if not text_for_mt:
            text_for_mt, slots = mask_and_slots_for_source(src, to_code)
        try:
            full_raw = translation.translate(
                _prepare_for_argos_engine(text_for_mt)
            )
        except Exception:
            return ""
        full_raw = (full_raw or "").strip()
        return _restore_glossary_target(
            src, full_raw, to_code, slots
        ).strip()
    try:
        return translation.translate(_prepare_for_argos_engine(src)).strip()
    except Exception:
        return ""


def _full_sentence_likely_incomplete(
    source_text: str, target_text: str, translation
) -> bool:
    """无术语掩码时：整句译文明显短于独立重译结果。"""
    src = (source_text or "").strip()
    tgt = (target_text or "").strip()
    if not src or not tgt:
        return False
    if _GLOSSA_MARKER_RE.search(tgt):
        return True
    zh_n = _zh_char_count(src)
    if zh_n < 6:
        return False
    try:
        probe = translation.translate(_prepare_for_argos_engine(src)).strip()
    except Exception:
        return False
    if not probe or len(probe) <= len(tgt) + 6:
        return False
    probe_words = {
        w.casefold() for w in _CYR_WORD_RE.findall(probe) if len(w) >= 3
    }
    tgt_words = {
        w.casefold() for w in _CYR_WORD_RE.findall(tgt) if len(w) >= 3
    }
    return len(probe_words - tgt_words) >= 2


def ensure_zh_to_slavic_translation_complete(
    source_text: str,
    target_text: str,
    from_code: str,
    to_code: str,
    translation,
    *,
    use_glossary: bool = True,
) -> str:
    """
    补全 zh→俄/乌 漏译片段：
    - 术语掩码旁未译中文（前/中/后）；
    - GLOSSA 占位符泄漏；
    - 无术语时整句明显偏短。
    """
    if translation is None:
        return target_text
    src = (source_text or "").strip()
    out = (target_text or "").strip()
    if not src:
        return target_text
    if not is_chinese_source_language(from_code):
        return target_text
    code = (to_code or "").strip().lower()
    if code not in ("ru", "uk"):
        return target_text

    slots: list[dict[str, Any]] = []
    masked_src: str | None = None
    apply_gloss = bool(
        use_glossary and should_apply_glossary(from_code, to_code)
    )
    if apply_gloss:
        masked_src, slots = mask_and_slots_for_source(src, code)

    if _GLOSSA_MARKER_RE.search(out):
        full_out = _full_retranslate_zh_slavic(
            src,
            code,
            translation,
            slots,
            use_glossary=apply_gloss,
            masked_text=masked_src,
        )
        if full_out:
            out = full_out

    fragments = unmasked_zh_fragments(src, slots) if slots else []
    if not fragments and not slots:
        fragments = [
            _ZhFragment(0, len(src), src)
        ] if _zh_char_count(src) >= 6 else []

    missing = [
        f
        for f in fragments
        if _fragment_missing_in_target(f.text, out, translation)
    ]
    if not missing and not slots:
        if _full_sentence_likely_incomplete(src, out, translation):
            full_out = _full_retranslate_zh_slavic(
                src, code, translation, slots, use_glossary=False
            )
            if full_out:
                return full_out.strip()
        return out

    if not missing:
        return out

    has_middle = any(0 < f.start and f.end < len(src.rstrip()) for f in missing)
    if has_middle or len(missing) >= 2:
        full_out = _full_retranslate_zh_slavic(
            src,
            code,
            translation,
            slots,
            use_glossary=apply_gloss,
            masked_text=masked_src,
        )
        if full_out and (
            len(full_out) > len(out)
            or not any(
                _fragment_missing_in_target(f.text, full_out, translation)
                for f in missing
            )
        ):
            out = full_out

    missing = [
        f
        for f in fragments
        if _fragment_missing_in_target(f.text, out, translation)
    ]
    missing.sort(key=lambda f: f.start)
    src_rstrip_len = len(src.rstrip())
    for frag in missing:
        out = _append_fragment_translation(out, frag, src_rstrip_len, translation)

    still = [
        f
        for f in fragments
        if _fragment_missing_in_target(f.text, out, translation)
    ]
    if still:
        full_out = _full_retranslate_zh_slavic(
            src,
            code,
            translation,
            slots,
            use_glossary=apply_gloss,
            masked_text=masked_src,
        )
        if full_out:
            return full_out.strip()
    return out.strip()


def prefers_full_decode_for_zh_slavic(
    source_text: str, from_code: str, to_code: str
) -> bool:
    """中→俄/乌：含术语旁中文或较长短句时不宜极短句快路径（易漏词）。"""
    if not is_chinese_source_language(from_code):
        return False
    code = (to_code or "").strip().lower()
    if code not in ("ru", "uk"):
        return False
    if _zh_char_count(source_text) >= 6:
        return True
    return has_untranslated_zh_beside_glossary(source_text, from_code, to_code)


def ensure_glossary_zh_tails_translated(
    source_text: str,
    target_text: str,
    from_code: str,
    to_code: str,
    translation,
) -> str:
    """兼容旧名。"""
    return ensure_zh_to_slavic_translation_complete(
        source_text,
        target_text,
        from_code,
        to_code,
        translation,
        use_glossary=True,
    )


def enforce_glossary_in_target(
    source_text: str,
    target_text: str,
    from_code: str,
    to_code: str,
) -> str:
    """
    质量重译等步骤可能冲掉术语占位符；在最终译文上按源语术语 slot 补回（本地，不上传整句）。
    """
    if not (source_text or "").strip() or not (target_text or "").strip():
        return target_text
    if not should_apply_glossary(from_code, to_code):
        return target_text
    glossary = load_glossary()
    _, slots = mask_source_terms(source_text, glossary, to_code)
    if not slots:
        return target_text
    out, _ = restore_markers_with_spans(target_text, slots, to_code=to_code)
    ordered = sorted(slots, key=_slot_sort_key, reverse=True)
    for slot in ordered:
        if not _glossary_term_visible(out, slot):
            prev = out
            out = _repair_lost_glossary_slot(out, slot, to_code)
            if out != prev and not _glossary_term_visible(out, slot):
                out = prev
    return out


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
    forced_by_key: dict[str, str] | None = None,
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
    masked, slots = mask_source_terms(
        text, glossary, to_code, forced_by_key=forced_by_key
    )
    if not slots:
        return tr(text), []
    raw = tr(masked)
    out, spans = restore_markers_with_spans(raw, slots, to_code=to_code)
    return out, spans


def _append_swapped_term_span(
    target: str,
    spans: list[dict[str, Any]],
    *,
    zh_source: str,
    alternatives: list[str],
    chosen_index: int,
    option_lemma: str,
    to_code: str,
) -> list[dict[str, Any]]:
    """整句改写后补回术语高亮（变位形可能不在 find 结果中）。"""
    if any((s.get("zh_source") or "").strip() == zh_source for s in spans):
        return spans
    alts = [(a or "").strip() for a in alternatives if (a or "").strip()]
    if len(alts) < 2:
        return spans
    code = (to_code or "").strip().lower()
    candidates: list[str] = []
    if 0 <= chosen_index < len(alts):
        candidates.append(alts[chosen_index])
    try:
        bucket = ga.pos_bucket_for_option(option_lemma, code) if ga else "noun"
    except Exception:
        bucket = "noun"
    if bucket == "verb":
        try:
            words = gi._word_re(code).findall(target or "")
            subj = words[0] if words else ""
            number = gi._subject_grammatical_number(subj, code)
            candidates.append(
                gi._verb_present_third_person(option_lemma, number, code)
            )
        except Exception:
            pass
    for cand in candidates:
        surf = (cand or "").strip()
        if not surf:
            continue
        for probe in (surf, surf.lower(), surf.capitalize()):
            pos = (target or "").find(probe)
            if pos < 0:
                continue
            start, end = pos, pos + len(probe)
            if any(
                not (end <= int(s.get("start") or 0) or start >= int(s.get("end") or 0))
                for s in spans
            ):
                continue
            ctx_before = target[:start]
            ctx_after = target[end:]
            spans.append(
                {
                    "start": start,
                    "end": end,
                    "surface": probe,
                    "zh_source": zh_source,
                    "alternatives": alts,
                    "chosen_index": chosen_index,
                    "lemma": option_lemma,
                    "pos": bucket,
                    "words": gi.analyze_slavic_phrase(probe, code).get("words")
                    or [],
                    "context_before": ctx_before,
                    "context_after": ctx_after,
                    "target_lang": code,
                }
            )
            return spans
    return spans


def swap_glossary_alternative_in_target(
    source_text: str,
    target_text: str,
    spans: list[dict[str, Any]],
    span_index: int,
    option_index: int,
    from_code: str,
    to_code: str,
    translation,
    *,
    on_progress=None,
) -> tuple[str | None, list[dict[str, Any]] | None]:
    """
    用户在译文区切换术语译法时：若词性桶变化（名↔动等），整句重译并调整句法；
    同词性则返回 (None, None) 由 UI 做局部变格替换。
    """
    if span_index < 0 or span_index >= len(spans):
        return None, None
    sp = spans[span_index]
    alts = sp.get("alternatives")
    if not isinstance(alts, list) or option_index < 0 or option_index >= len(
        alts
    ):
        return None, None
    new_option = (alts[option_index] or "").strip()
    old_index = int(sp.get("chosen_index") or 0)
    old_option = (alts[old_index] or "").strip() if old_index < len(alts) else ""
    if not new_option:
        return None, None
    if ga is None:
        return None, None
    if not ga.pos_bucket_changed(old_option, new_option, to_code):
        return None, None

    forced: dict[str, str] = {}
    forced_indices: dict[str, int] = {}
    for i, slot_sp in enumerate(spans):
        zh = (slot_sp.get("zh_source") or "").strip()
        if not zh:
            continue
        slot_alts = slot_sp.get("alternatives")
        if not isinstance(slot_alts, list):
            continue
        pick = option_index if i == span_index else int(
            slot_sp.get("chosen_index") or 0
        )
        if pick < 0 or pick >= len(slot_alts):
            continue
        opt = (slot_alts[pick] or "").strip()
        if opt:
            forced[zh] = opt
            forced_indices[zh] = pick

    new_bucket = ga.pos_bucket_for_option(new_option, to_code)
    if new_bucket == "verb":
        try:
            direct = gi.rewrite_esto_ot_for_verb_glossary(
                target_text, new_option, to_code
            )
        except Exception:
            direct = None
        if direct and direct.strip():
            new_target = direct.strip()
            new_spans = find_glossary_spans_in_target(
                source_text, new_target, from_code, to_code
            )
            new_spans = _append_swapped_term_span(
                new_target,
                new_spans,
                zh_source=(sp.get("zh_source") or "").strip(),
                alternatives=alts,
                chosen_index=option_index,
                option_lemma=new_option,
                to_code=to_code,
            )
            for slot_sp in new_spans:
                zh = (slot_sp.get("zh_source") or "").strip()
                if zh in forced_indices:
                    slot_sp["chosen_index"] = forced_indices[zh]
            return new_target, new_spans

    new_target, new_spans = apply_glossary_with_spans(
        translation,
        source_text,
        from_code,
        to_code,
        on_progress=on_progress,
        forced_by_key=forced or None,
    )
    if ga.pos_bucket_for_option(new_option, to_code) == "verb":
        try:
            rewritten = gi.rewrite_esto_ot_for_verb_glossary(
                new_target, new_option, to_code
            )
        except Exception:
            rewritten = None
        if rewritten and rewritten.strip() and rewritten != new_target:
            new_target = rewritten.strip()
            new_spans = find_glossary_spans_in_target(
                source_text, new_target, from_code, to_code
            )

    for slot_sp in new_spans:
        zh = (slot_sp.get("zh_source") or "").strip()
        if zh in forced_indices:
            slot_sp["chosen_index"] = forced_indices[zh]

    return new_target, new_spans
