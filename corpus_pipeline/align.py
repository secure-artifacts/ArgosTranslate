"""段落级 + 句子级对齐（长度 DP，非按行硬对齐）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_ZH_SENT = re.compile(r"(?<=[。！？!?…])\s*")
_CYR_SENT = re.compile(r"(?<=[.!?…])\s+")


@dataclass
class SentencePair:
    source: str
    target: str
    confidence: float


@dataclass
class AlignmentResult:
    paragraph_pairs: list[SentencePair] = field(default_factory=list)
    sentence_pairs: list[SentencePair] = field(default_factory=list)
    source_sent_count: int = 0
    target_sent_count: int = 0
    aligned_sent_count: int = 0
    long_splits: int = 0
    short_merges: int = 0


def split_sentences(text: str, lang: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    code = (lang or "").strip().lower()
    if code in ("zh", "zt", "cn"):
        parts = _ZH_SENT.split(t)
    else:
        parts = _CYR_SENT.split(t)
    out = [p.strip() for p in parts if p.strip()]
    if len(out) <= 1 and "\n" in t:
        out = [ln.strip() for ln in t.split("\n") if ln.strip()]
    return out


def _unit_len(s: str, lang: str) -> int:
    if lang in ("zh", "zt", "cn"):
        return len(re.sub(r"\s+", "", s))
    return len(s.split())


def _pair_cost(a: str, b: str, la: str, lb: str) -> float:
    la_u = max(_unit_len(a, la), 1)
    lb_u = max(_unit_len(b, lb), 1)
    r = la_u / lb_u if la_u > lb_u else lb_u / la_u
    if r > 2.8 or r < 0.35:
        return 10.0 + abs(r - 1.0)
    return abs(r - 1.0)


def align_sentences(
    source_sents: list[str],
    target_sents: list[str],
    source_lang: str,
    target_lang: str,
) -> tuple[list[SentencePair], int, int]:
    """1:1 / skip 对齐；返回 (pairs, long_splits, short_merges)。"""
    if not source_sents or not target_sents:
        return [], 0, 0
    n, m = len(source_sents), len(target_sents)
    long_splits = 0
    short_merges = 0
    if n == m:
        pairs = [
            SentencePair(source_sents[i], target_sents[i], 0.92)
            for i in range(n)
            if source_sents[i] and target_sents[i]
        ]
        return pairs, 0, 0

    inf = 1e9
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    back: list[list[tuple[str, int, int] | None]] = [
        [None] * (m + 1) for _ in range(n + 1)
    ]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if i < n and j < m:
                c = _pair_cost(
                    source_sents[i], target_sents[j], source_lang, target_lang
                )
                if dp[i][j] + c < dp[i + 1][j + 1]:
                    dp[i + 1][j + 1] = dp[i][j] + c
                    back[i + 1][j + 1] = ("pair", i, j)
            if i < n and dp[i][j] + 0.6 < dp[i + 1][j]:
                dp[i + 1][j] = dp[i][j] + 0.6
                back[i + 1][j] = ("skip_src", i, j)
            if j < m and dp[i][j] + 0.6 < dp[i][j + 1]:
                dp[i][j + 1] = dp[i][j] + 0.6
                back[i][j + 1] = ("skip_tgt", i, j)

    pairs: list[SentencePair] = []
    i, j = n, m
    while i > 0 or j > 0:
        step = back[i][j] if i >= 0 and j >= 0 else None
        if step is None:
            break
        kind, pi, pj = step
        if kind == "pair":
            cost = _pair_cost(
                source_sents[pi], target_sents[pj], source_lang, target_lang
            )
            if cost > 2.5:
                long_splits += 1
            conf = max(0.55, 0.95 - cost * 0.2)
            pairs.append(SentencePair(source_sents[pi], target_sents[pj], conf))
            i, j = pi, pj
        elif kind == "skip_src":
            short_merges += 1
            i, j = pi, pj
        else:
            short_merges += 1
            i, j = pi, pj

    pairs.reverse()
    if not pairs and n == 1 and m == 1:
        pairs.append(SentencePair(source_sents[0], target_sents[0], 0.75))
    return pairs, long_splits, short_merges


def _align_para_pair(
    src_para: str,
    tgt_para: str,
    source_lang: str,
    target_lang: str,
) -> tuple[SentencePair | None, list[SentencePair], int, int]:
    sp = src_para.strip()
    tp = tgt_para.strip()
    if not sp or not tp:
        return None, [], 0, 0
    para_conf = max(0.5, 0.9 - _pair_cost(sp, tp, source_lang, target_lang) * 0.15)
    para_pair = SentencePair(sp, tp, para_conf)
    ss = split_sentences(sp, source_lang)
    ts = split_sentences(tp, target_lang)
    sent_pairs, ls, sm = align_sentences(ss, ts, source_lang, target_lang)
    return para_pair, sent_pairs, ls, sm


def align_document(
    source_text: str,
    target_text: str,
    source_lang: str,
    target_lang: str,
) -> AlignmentResult:
    src_paras = [p.strip() for p in source_text.split("\n\n") if p.strip()]
    tgt_paras = [p.strip() for p in target_text.split("\n\n") if p.strip()]
    if not src_paras:
        src_paras = [source_text.strip()] if source_text.strip() else []
    if not tgt_paras:
        tgt_paras = [target_text.strip()] if target_text.strip() else []

    result = AlignmentResult()
    src_sent_total = 0
    tgt_sent_total = 0

    for k in range(min(len(src_paras), len(tgt_paras))):
        para_pair, sents, ls, sm = _align_para_pair(
            src_paras[k], tgt_paras[k], source_lang, target_lang
        )
        if para_pair:
            result.paragraph_pairs.append(para_pair)
        result.sentence_pairs.extend(sents)
        result.long_splits += ls
        result.short_merges += sm
        src_sent_total += len(split_sentences(src_paras[k], source_lang))
        tgt_sent_total += len(split_sentences(tgt_paras[k], target_lang))

    if not result.sentence_pairs and source_text.strip() and target_text.strip():
        para_pair, sents, ls, sm = _align_para_pair(
            source_text, target_text, source_lang, target_lang
        )
        if para_pair:
            result.paragraph_pairs.append(para_pair)
        result.sentence_pairs = sents
        result.long_splits += ls
        result.short_merges += sm
        src_sent_total = len(split_sentences(source_text, source_lang))
        tgt_sent_total = len(split_sentences(target_text, target_lang))

    result.source_sent_count = src_sent_total
    result.target_sent_count = tgt_sent_total
    result.aligned_sent_count = len(result.sentence_pairs)
    return result


def align_paragraphs(
    source_text: str,
    target_text: str,
    source_lang: str,
    target_lang: str,
) -> list[SentencePair]:
    """兼容旧接口：仅返回句级对齐。"""
    return align_document(
        source_text, target_text, source_lang, target_lang
    ).sentence_pairs
