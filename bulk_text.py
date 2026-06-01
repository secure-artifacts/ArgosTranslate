"""
长文本预处理：在送入翻译引擎前为超长单行插入换行，便于分段翻译、降低单次推理压力。
不修改界面上的原文，仅用于翻译管线中的字符串副本。
兼容术语占位符：半角 GLOSSA####、全角 ＧＬＯＳＳＡ####、或西里尔误译 ГЛОССА####（不会在标记中间切断）。

Argos：按句合并为较长「段」（每段约数百字），避免逐短句翻译丢失上下文。
Ollama：更大块、少换行，由 ollama_translate 二次按段落/长度分块。
"""
from __future__ import annotations

import re

_GLOSSA_ANY = re.compile(
    r"(?:GLOSSA\d{3,4}|ＧＬＯＳＳＡ[０-９]{3,4}|[Гг][Лл][Оо][Сс][Сс][Аа]\d{3,4})"
)

# 非 CJK 单行硬切上限
DEFAULT_MAX_RUN = 9000
# Argos + 中文：按句合并段长（更大段→更少 CT2 次推理；段内仍保留句界上下文）
CJK_MT_MAX_RUN = 1280
CJK_SPLIT_WHEN_LINE_GE = 600
# Ollama：尽量整段送入，由 LLM 侧再分块
LLM_CJK_MAX_RUN = 3200
LLM_SPLIT_WHEN_LINE_GE = 1400

_SENT_SPLIT = re.compile(r"(?<=[。！？!?…])\s*")


def _cjk_char_count(text: str) -> int:
    n = 0
    for c in text or "":
        o = ord(c)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            n += 1
    return n


def _looks_cjk_heavy(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    cjk = _cjk_char_count(t)
    return cjk >= max(16, len(t) // 4)


def _adjust_cut_outside_markers(s: str, cut: int) -> int:
    """若 cut 落在术语占位符内部，则移到标记之后。"""
    for m in _GLOSSA_ANY.finditer(s):
        if m.start() < cut < m.end():
            return m.end()
    return cut


def _split_long_line(line: str, max_run: int) -> str:
    if len(line) <= max_run:
        return line
    pieces: list[str] = []
    start = 0
    while start < len(line):
        if start + max_run >= len(line):
            pieces.append(line[start:])
            break
        win = line[start : start + max_run]
        cut_rel = -1
        for sep in (
            "。",
            "！",
            "？",
            "…",
            "．",
            ".",
            "!",
            "?",
            "；",
            ";",
            "：",
            ":",
            "，",
            ",",
            "、",
            " ",
            "\t",
        ):
            j = win.rfind(sep)
            if j > int(max_run * 0.35):
                cut_rel = j + (len(sep) if sep not in " \t" else 1)
                break
        if cut_rel < 0:
            cut_rel = max_run
        abs_cut = start + cut_rel
        abs_cut = _adjust_cut_outside_markers(line, abs_cut)
        if abs_cut <= start:
            abs_cut = min(start + max_run, len(line))
            abs_cut = _adjust_cut_outside_markers(line, abs_cut)
        if abs_cut <= start:
            abs_cut = min(start + max_run, len(line))
        pieces.append(line[start:abs_cut])
        start = abs_cut
    return "\n".join(pieces)


def _merge_sentences_to_runs(sentences: list[str], max_run: int) -> list[str]:
    """将句子列表合并为不超过 max_run 的段（Argos 每段独立译，段内保留上下文）。"""
    runs: list[str] = []
    buf = ""
    for sent in sentences:
        s = sent.strip()
        if not s:
            continue
        if len(s) > max_run:
            if buf.strip():
                runs.append(buf.strip())
                buf = ""
            runs.extend(_split_long_line(s, max_run).split("\n"))
            continue
        candidate = f"{buf}{s}" if buf else s
        if len(candidate) <= max_run:
            buf = candidate
        else:
            if buf.strip():
                runs.append(buf.strip())
            buf = s
    if buf.strip():
        runs.append(buf.strip())
    return runs


def _prepare_cjk_line(line: str, max_run: int, split_when: int) -> str:
    """中文行：够长则按句号拆句，再合并为较长段。"""
    line = line or ""
    if not line.strip():
        return line
    if len(line) >= split_when:
        parts = _SENT_SPLIT.split(line)
        parts = [p for p in parts if p.strip()]
        if len(parts) > 1:
            return "\n".join(_merge_sentences_to_runs(parts, max_run))
    if len(line) <= max_run:
        return line
    return _split_long_line(line, max_run)


def prepare_long_translation_input(
    text: str,
    max_run: int = DEFAULT_MAX_RUN,
    *,
    for_llm: bool = False,
) -> str:
    if not text:
        return text
    if for_llm:
        if not _looks_cjk_heavy(text):
            if len(text) <= max_run:
                return text
            return "\n".join(_split_long_line(line, max_run) for line in text.split("\n"))
        effective = min(max_run, LLM_CJK_MAX_RUN)
        split_when = LLM_SPLIT_WHEN_LINE_GE
        return "\n".join(
            _prepare_cjk_line(line, effective, split_when) for line in text.split("\n")
        )
    if _looks_cjk_heavy(text):
        effective = min(max_run, CJK_MT_MAX_RUN)
        return "\n".join(
            _prepare_cjk_line(line, effective, CJK_SPLIT_WHEN_LINE_GE)
            for line in text.split("\n")
        )
    if len(text) <= max_run:
        return text
    return "\n".join(_split_long_line(line, max_run) for line in text.split("\n"))
