"""
术语库：键为源语词条，值为各目标语字段（ru / uk / en …），JSON 持久化；支持 CSV / XLSX 导入。
"""
from __future__ import annotations

import csv
import json
import re
import threading
from pathlib import Path
from typing import Any

from terminology_bridge import glossary_path, portable_root


def _normalize_pos_import(raw_pos: str) -> str:
    value = (raw_pos or "").strip().lower()
    if value in {"verb", "v", "动词"}:
        return "verb"
    if value in {"adj", "adjective", "a", "形容词"}:
        return "adj"
    if value in {"other", "phrase", "短语", "其他"}:
        return "other"
    return "noun"


_SKIP_INFER_POS = frozenset({"PREP", "CONJ", "PRCL", "INTJ"})

# pymorphy2 初始化很重：批量导入时绝不可每行 new MorphAnalyzer()，否则界面长时间无响应。
_morph_singleton: Any = False  # False=未尝试；None=不可用
_morph_preload_lock = threading.Lock()
_morph_preload_started = False

# 俄语→中文键反向索引：全表 pymorphy2 扫描很重，按 zh_glossary.json 路径 + mtime 缓存。
_lemma_index_cache: tuple[str, int, dict[str, list[str]]] | None = None
_LEMMA_INDEX_DISK = portable_root() / "data" / "cache" / "glossary_ru_lemma_index_v1.json"


def _lemma_index_disk_path() -> Path:
    return _LEMMA_INDEX_DISK


def _load_lemma_index_from_disk(pkey: str, mt: int) -> dict[str, list[str]] | None:
    path = _lemma_index_disk_path()
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if data.get("pkey") != pkey or int(data.get("mtime") or 0) != mt:
            return None
        idx = data.get("index")
        if not isinstance(idx, dict):
            return None
        return {str(k): list(v) for k, v in idx.items() if isinstance(v, list)}
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _save_lemma_index_to_disk(
    pkey: str, mt: int, rev: dict[str, list[str]]
) -> None:
    path = _lemma_index_disk_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        payload = {"pkey": pkey, "mtime": mt, "index": rev}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        tmp.replace(path)
    except OSError:
        pass


def _shared_morph_analyzer() -> Any | None:
    """返回进程内复用的 MorphAnalyzer，失败时缓存为 None。"""
    global _morph_singleton
    if _morph_singleton is not False:
        return _morph_singleton
    with _morph_preload_lock:
        if _morph_singleton is not False:
            return _morph_singleton
        try:
            from pymorphy2 import MorphAnalyzer

            _morph_singleton = MorphAnalyzer()
            try:
                _morph_singleton.parse("тест")
            except Exception:
                pass
        except ImportError:
            _morph_singleton = None
    return _morph_singleton


def shared_morph_analyzer() -> Any | None:
    """供查词、维基、术语桥等共用的 MorphAnalyzer 单例（避免重复初始化）。"""
    return _shared_morph_analyzer()


def _plain_ru_surface(surface: str) -> str:
    return re.sub(r"[\u0301\u0300\u030f]", "", (surface or "").strip()).lower()


def safe_parse_pos(parse) -> str:
    """
    读取 pymorphy2 词性。OpenCorpora 标签集无 PROPN，与 PROPN 比较会抛 ValueError。
    """
    try:
        tag = parse.tag
        if tag is None:
            return ""
        pos = tag.POS
        return str(pos) if pos is not None else ""
    except (ValueError, AttributeError, TypeError):
        return ""


def pick_morph_parse(parses: list, surface: str):
    """
    在 pymorphy2 多解中择优。避免「суть/Суть」被当成动词「быть」等远距原形。
    """
    if not parses:
        return None
    if len(parses) == 1:
        return parses[0]
    plain = _plain_ru_surface(surface)
    if not plain:
        return parses[0]

    same_lemma = [p for p in parses if (p.normal_form or "").lower() == plain]
    if same_lemma:
        return max(same_lemma, key=lambda p: p.score)

    top = parses[0]
    top_nf = (top.normal_form or "").lower()
    top_pos = safe_parse_pos(top)
    if top_pos == "VERB" and top_nf and top_nf != plain:
        for pos in ("NOUN", "ADJF", "ADJS", "NUMR"):
            pool = [p for p in parses if safe_parse_pos(p) == pos]
            if not pool:
                continue
            best = max(pool, key=lambda p: p.score)
            if best.score >= top.score * 0.45:
                return best
    return top


# 前置词 → 常见支配格（OpenCorpora case tag）
# 完整表见 slavic_grammar_rules.py（Sussex Blok / Wikibooks 等）
try:
    from slavic_grammar_rules import RU_PREP_GOVERNS as _RU_PREP_GOVERNS
except ImportError:
    _RU_PREP_GOVERNS: dict[str, tuple[str, ...]] = {
        "без": ("gent",),
        "благодаря": ("datv",),
        "в": ("loct", "accs"),
        "во": ("loct", "accs"),
        "вместо": ("gent",),
        "вне": ("gent",),
        "для": ("gent",),
        "до": ("gent",),
        "за": ("accs", "ablt", "gent"),
        "из": ("gent",),
        "изза": ("gent",),
        "из-за": ("gent",),
        "к": ("datv",),
        "ко": ("datv",),
        "кроме": ("gent",),
        "мимо": ("gent",),
        "на": ("accs", "loct"),
        "над": ("ablt", "loct"),
        "о": ("loct",),
        "об": ("loct",),
        "обо": ("loct",),
        "от": ("gent",),
        "ото": ("gent",),
        "перед": ("ablt", "loct"),
        "по": ("datv", "accs", "loct"),
        "под": ("ablt", "loct", "accs"),
        "при": ("loct",),
        "про": ("accs",),
        "ради": ("gent",),
        "с": ("ablt", "gent"),
        "со": ("ablt", "gent"),
        "у": ("gent",),
        "через": ("accs",),
    }


def _ru_tokens_before(sentence: str, rel_start: int, *, max_tokens: int = 4) -> list[str]:
    before = (sentence or "")[: max(0, rel_start)]
    raw = re.findall(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*", before)
    out: list[str] = []
    for w in raw[-max_tokens:]:
        plain = _plain_ru_surface(w)
        if plain:
            out.append(plain)
    return out


def pick_morph_parse_in_sentence(
    parses: list,
    surface: str,
    sentence: str = "",
    rel_start: int = 0,
    rel_end: int = 0,
):
    """
    结合句中前置词等上下文，在 pymorphy2 多解中择优（格/词性）。
    无句上下文时等同 pick_morph_parse。
    """
    if not parses:
        return None
    if len(parses) == 1:
        return parses[0]
    base = pick_morph_parse(parses, surface)
    sent = (sentence or "").strip()
    if not sent:
        return base

    prev_tokens = _ru_tokens_before(sent, rel_start)
    if not prev_tokens:
        return base

    expected: set[str] = set()
    for prep in reversed(prev_tokens):
        cases = _RU_PREP_GOVERNS.get(prep)
        if cases:
            expected.update(cases)
            break

    if not expected:
        return base

    best = base
    best_score = float("-inf")
    for p in parses:
        sc = float(p.score)
        case = None
        try:
            if p.tag.case is not None:
                case = str(p.tag.case)
        except (ValueError, AttributeError, TypeError):
            case = None
        if case and case in expected:
            sc += 18.0
        pos = safe_parse_pos(p)
        if pos == "NOUN" and case:
            sc += 2.0
        if sc > best_score:
            best_score = sc
            best = p
    return best


def preload_morph_analyzer() -> Any | None:
    """后台预热 pymorphy2（与翻译模型加载可并行）。"""
    return _shared_morph_analyzer()


def preload_morph_analyzer_async() -> None:
    """进程内只启动一次后台线程加载 pymorphy2。"""
    global _morph_preload_started
    with _morph_preload_lock:
        if _morph_preload_started:
            return
        _morph_preload_started = True

    def _run() -> None:
        preload_morph_analyzer()

    threading.Thread(
        target=_run, name="pymorphy2-preload", daemon=True
    ).start()


def _opencorpora_pos_to_bucket(pos: str | None) -> str:
    if not pos:
        return "noun"
    if pos == "NOUN":
        return "noun"
    if pos in {"VERB", "INFN", "GRND", "PRTS"}:
        return "verb"
    if pos in {"ADJF", "ADJS", "COMP", "ADJD"}:
        return "adj"
    return "other"


def infer_pos_from_russian(ru: str) -> str:
    """
    用 pymorphy2（OpenCorpora）对俄语侧做粗粒度词类，映射到术语库四类：noun / verb / adj / other。
    多词时跳过前置词、连词等闭类，取第一个实词；无法分析时默认为名词。
    """
    morph = _shared_morph_analyzer()
    if morph is None:
        return "noun"
    tokens = re.findall(r"[А-Яа-яЁёA-Za-z-]+", (ru or "").strip())
    if not tokens:
        return "noun"
    for w in tokens[:8]:
        parses = morph.parse(w)
        if not parses:
            continue
        pos = safe_parse_pos(pick_morph_parse(parses, w))
        if pos in _SKIP_INFER_POS:
            continue
        if pos is None:
            continue
        return _opencorpora_pos_to_bucket(pos)
    parses0 = morph.parse(tokens[0])
    if not parses0:
        return "noun"
    pos0 = safe_parse_pos(pick_morph_parse(parses0, tokens[0]))
    return _opencorpora_pos_to_bucket(pos0)


def _entry_merge_ru(prev: dict[str, Any] | None, ru: str) -> dict[str, Any]:
    if prev is None:
        return {"ru": ru}
    if not isinstance(prev, dict):
        return {"ru": ru}
    out = {**prev, "ru": ru}
    return out


def _normalize_entry(prev: Any) -> dict[str, Any]:
    if isinstance(prev, dict):
        return dict(prev)
    if isinstance(prev, str):
        return {"ru": prev}
    return {}


def infer_pos_for_target(target: str, target_lang: str) -> str:
    code = (target_lang or "").strip().lower()
    if code in ("ru", "uk"):
        return infer_pos_from_russian(target)
    return "noun"


def _entry_merge_target(
    prev: dict[str, Any] | None, target_lang: str, target_val: Any
) -> dict[str, Any]:
    code = (target_lang or "").strip().lower()
    out = _normalize_entry(prev) if prev is not None else {}
    out[code] = target_val
    return out


class GlossaryStore:
    """内存中的术语表，与 zh_glossary.json 同步。"""

    def __init__(self, path: Path | None = None):
        self.path = path or glossary_path()
        self._data: dict[str, dict[str, Any]] = {}

    def load(self) -> GlossaryStore:
        self._data = {}
        if not self.path.is_file():
            return self
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if not isinstance(k, str) or not k.strip():
                        continue
                    if isinstance(v, dict):
                        self._data[k.strip()] = v
                    elif isinstance(v, str):
                        self._data[k.strip()] = {"ru": v}
        except (json.JSONDecodeError, OSError):
            self._data = {}
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)

    def as_dict(self) -> dict[str, Any]:
        return {**self._data}

    def replace_all(self, data: dict[str, Any]) -> None:
        self._data = {}
        for k, v in data.items():
            if isinstance(k, str) and k.strip() and isinstance(v, dict):
                self._data[k.strip()] = v

    def upsert_term(
        self,
        source: str,
        target_lang: str,
        target: str,
        pos: str | None = None,
    ) -> GlossaryStore:
        """合并写入一条源语→目标语（保留同键下其它语言字段）。"""
        from terminology_bridge import parse_target_cell

        source = (source or "").strip()
        target_lang = (target_lang or "").strip().lower()
        target = (target or "").strip()
        if not source or not target_lang or not target:
            return self
        prev = self._data.get(source)
        val = parse_target_cell(target, target_lang)
        entry = _normalize_entry(prev) if prev is not None else {}
        prev_val = entry.get(target_lang)
        if prev_val is None:
            new_val: Any = val
        elif isinstance(prev_val, list):
            new_val = list(prev_val)
            if val not in new_val:
                new_val.append(val)
        else:
            if prev_val == val:
                new_val = prev_val
            else:
                new_val = [prev_val, val]
        entry[target_lang] = new_val
        if pos is not None and str(pos).strip() != "":
            entry["pos"] = _normalize_pos_import(str(pos))
        elif target_lang in ("ru", "uk"):
            entry["pos"] = infer_pos_for_target(target, target_lang)
        self._data[source] = entry
        return self

    def upsert_zh_ru(
        self, zh: str, ru: str, pos: str | None = None
    ) -> GlossaryStore:
        """兼容：中文→俄语。"""
        return self.upsert_term(zh, "ru", ru, pos=pos)

    def remove_target(self, source: str, target_lang: str) -> GlossaryStore:
        source = (source or "").strip()
        target_lang = (target_lang or "").strip().lower()
        prev = self._data.get(source)
        if not isinstance(prev, dict):
            self._data.pop(source, None)
            return self
        entry = dict(prev)
        entry.pop(target_lang, None)
        if not any(
            k not in ("pos", "grammemes", "gram")
            and entry.get(k) not in (None, "")
            for k in entry
        ):
            self._data.pop(source, None)
        else:
            self._data[source] = entry
        return self

    def remove_target_variant(
        self, source: str, target_lang: str, target_text: str
    ) -> GlossaryStore:
        """删除同键下某一译法（多行外语时只删对应行）。"""
        from terminology_bridge import target_cell_text

        source = (source or "").strip()
        target_lang = (target_lang or "").strip().lower()
        needle = (target_text or "").strip()
        if not source or not target_lang or not needle:
            return self
        prev = self._data.get(source)
        if not isinstance(prev, dict):
            return self
        val = prev.get(target_lang)
        if isinstance(val, list):
            kept: list[Any] = []
            for item in val:
                show = target_cell_text({target_lang: item}, target_lang)
                if show.strip().casefold() != needle.casefold():
                    kept.append(item)
            entry = dict(prev)
            if not kept:
                entry.pop(target_lang, None)
            elif len(kept) == 1:
                entry[target_lang] = kept[0]
            else:
                entry[target_lang] = kept
            if not any(
                k not in ("pos", "grammemes", "gram")
                and entry.get(k) not in (None, "")
                for k in entry
            ):
                self._data.pop(source, None)
            else:
                self._data[source] = entry
            return self
        show = target_cell_text(prev, target_lang)
        if show.strip().casefold() == needle.casefold():
            return self.remove_target(source, target_lang)
        return self

    def clear_all(self) -> GlossaryStore:
        """清空内存中的全部术语（调用 save() 后写入文件）。"""
        self._data = {}
        return self

    def import_csv(
        self,
        file_path: Path,
        encoding: str = "utf-8-sig",
        merge: bool = True,
        *,
        target_lang: str = "ru",
    ) -> int:
        """第一列源语、第二列目标语；第三列词性可选。返回导入行数。"""
        return self.import_csv_pair(
            file_path, target_lang=target_lang, encoding=encoding, merge=merge
        )

    def import_csv_pair(
        self,
        file_path: Path,
        *,
        target_lang: str = "ru",
        encoding: str = "utf-8-sig",
        merge: bool = True,
    ) -> int:
        count = 0
        tgt_lang = (target_lang or "ru").strip().lower()
        with open(file_path, newline="", encoding=encoding) as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 2:
                    continue
                src, tgt = row[0].strip(), row[1].strip()
                if not src or not tgt:
                    continue
                if src.lower() in ("中文", "源语", "source", "src"):
                    continue
                pos_raw = row[2].strip() if len(row) > 2 else ""
                pos = (
                    _normalize_pos_import(pos_raw)
                    if pos_raw
                    else infer_pos_for_target(tgt, tgt_lang)
                )
                if merge:
                    self.upsert_term(src, tgt_lang, tgt, pos=pos)
                else:
                    self._data[src] = {
                        tgt_lang: tgt,
                        "pos": pos,
                    }
                count += 1
        return count

    def import_xlsx(
        self, file_path: Path, merge: bool = True, *, target_lang: str = "ru"
    ) -> int:
        import openpyxl

        count = 0
        tgt_lang = (target_lang or "ru").strip().lower()
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        try:
            ws = wb.active
            for row in ws.iter_rows(min_row=1, values_only=True):
                if not row or len(row) < 2:
                    continue
                src = str(row[0]).strip() if row[0] is not None else ""
                tgt = str(row[1]).strip() if row[1] is not None else ""
                if not src or not tgt:
                    continue
                if src.lower() in ("中文", "源语", "source", "src"):
                    continue
                pos_raw = (
                    str(row[2]).strip()
                    if len(row) > 2 and row[2] is not None
                    else ""
                )
                pos = (
                    _normalize_pos_import(pos_raw)
                    if pos_raw
                    else infer_pos_for_target(tgt, tgt_lang)
                )
                if merge:
                    self.upsert_term(src, tgt_lang, tgt, pos=pos)
                else:
                    self._data[src] = {tgt_lang: tgt, "pos": pos}
                count += 1
        finally:
            wb.close()
        return count


def _ru_tokens(text: str) -> list[str]:
    return re.findall(r"[А-Яа-яЁёA-Za-z]+", text or "")


def build_ru_lemma_index(glossary: dict[str, Any]) -> dict[str, list[str]]:
    """俄语词原形 -> 可能对应的中文术语列表（用于点击译文反查）。"""
    global _lemma_index_cache
    if not isinstance(glossary, dict):
        glossary = {}
    path = glossary_path()
    pkey = str(path.resolve())
    try:
        mt = int(path.stat().st_mtime_ns) if path.is_file() else 0
    except OSError:
        mt = 0
    if (
        _lemma_index_cache is not None
        and _lemma_index_cache[0] == pkey
        and _lemma_index_cache[1] == mt
    ):
        return _lemma_index_cache[2]
    disk = _load_lemma_index_from_disk(pkey, mt)
    if disk is not None:
        _lemma_index_cache = (pkey, mt, disk)
        return disk
    morph = _shared_morph_analyzer()
    if morph is None:
        return {}
    rev: dict[str, list[str]] = {}
    for zh, entry in glossary.items():
        if not isinstance(zh, str) or not zh.strip():
            continue
        surfaces: list[str] = []
        try:
            import glossary_inflection as gi

            meta = gi.extract_term_meta(entry, "ru")
            lem = (meta.get("lemma") or "").strip()
            if lem:
                surfaces.append(lem)
            for w in meta.get("words") or []:
                if not isinstance(w, dict):
                    continue
                for key in ("lemma", "surface"):
                    s = str(w.get(key) or "").strip()
                    if s:
                        surfaces.append(s)
        except ImportError:
            surfaces = []
        if not surfaces:
            ru_surface = ""
            if isinstance(entry, str):
                ru_surface = entry
            elif isinstance(entry, dict):
                r = entry.get("ru")
                if isinstance(r, str):
                    ru_surface = r
                elif isinstance(r, dict) and "lemma" in r:
                    ru_surface = str(r["lemma"])
            surfaces = [ru_surface] if ru_surface else []
        seen_tok: set[str] = set()
        for ru_surface in surfaces:
            for tok in _ru_tokens(ru_surface):
                if tok.lower() in seen_tok:
                    continue
                seen_tok.add(tok.lower())
                p = morph.parse(tok)
                if not p:
                    continue
                nf = pick_morph_parse(p, tok).normal_form
                rev.setdefault(nf, []).append(zh)
    _lemma_index_cache = (pkey, mt, rev)
    _save_lemma_index_to_disk(pkey, mt, rev)
    return rev


def glossary_zh_for_russian_click(
    word: str, glossary: dict[str, Any]
) -> list[str]:
    """根据点击的俄语词形，返回可能对应的中文术语（去重）。"""
    morph = _shared_morph_analyzer()
    if morph is None:
        return []
    if not isinstance(glossary, dict):
        glossary = {}
    clean = re.sub(r"^[^\wА-Яа-яЁё]+|[^\wА-Яа-яЁё]+$", "", word or "")
    clean = re.sub(r"[\u0301\u0300\u030f]", "", clean)
    if not clean:
        return []
    parses = morph.parse(clean)
    if not parses:
        return []
    nf = pick_morph_parse(parses, clean).normal_form
    idx = build_ru_lemma_index(glossary)
    zhs = idx.get(nf, [])
    seen = set()
    out = []
    for z in zhs:
        if z not in seen:
            seen.add(z)
            out.append(z)
    return out
