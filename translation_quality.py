"""
翻译质量辅助：不改变术语与语义前提下的轻量规范化。
- 中文送入模型前：兼容字符归一、空白与换行整理；中→俄/乌时将《》等转为 «» 等目标语标点。
- 俄/乌译文：残留中文标点本地化、NBSP/控制符、标点/空白/引号/软连字符、分号/标签冒号、话语标记逗号、俄语「в течение」时长、高频硬错、重复主语等）。

离线小包无法达到云端大模型语义深度；本模块仅缩小**版面与高频硬错**与商用机译常见差距，不声称语义「媲美」在线 AI。
不能替代人工审校。
"""
from __future__ import annotations

import re
import unicodedata

# 零宽字符、BOM、词连接符等（模型或剪贴板偶发带入）
_ZERO_WIDTH_AND_BOM = (
    "\ufeff",  # BOM
    "\u200b",  # ZWSP
    "\u200c",  # ZWNJ
    "\u200d",  # ZWJ
    "\u2060",  # WORD JOINER
)

# Word / PDF / 网页粘贴常见隐藏字符
_PASTE_EXTRA_INVISIBLE = (
    "\u00ad",  # 软连字符
    "\ufffc",  # Word 对象占位符
    "\u200e",  # LTR mark
    "\u200f",  # RTL mark
    "\uFEFF",  # BOM 变体
)

_BIDI_CONTROL_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
_PRIVATE_USE_BOOK_MARKERS = ("\uE010", "\uE011")

# Argos 书名号占位（勿送入大模型）
_ARGOS_MT_PRIVATE_MARKERS = _PRIVATE_USE_BOOK_MARKERS


def sanitize_source_text(text: str, *, for_llm: bool = False) -> str:
    """
    外部粘贴文本送入翻译前的通用清理。
    Word/PDF/网页剪贴板常带零宽符、软连字符、控制符等，会导致 Qwen 输出乱码。
    for_llm=True 时不做 Argos 专用私有区书名号处理（留给 normalize_zh_for_mt 即可）。
    """
    if not text:
        return text
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\u2028", "\n").replace("\u2029", "\n\n")
    for ch in _ZERO_WIDTH_AND_BOM + _PASTE_EXTRA_INVISIBLE:
        t = t.replace(ch, "")
    t = _BIDI_CONTROL_RE.sub("", t)
    t = _strip_c0_controls_except_newlines(t)
    t = _normalize_nbsp_narrow_spaces(t)
    t = t.replace("\u2009", " ").replace("\u2002", " ").replace("\u2003", " ")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{5,}", "\n\n\n\n", t)
    if for_llm:
        for ch in _PRIVATE_USE_BOOK_MARKERS:
            t = t.replace(ch, "")
    t = _try_fix_mojibake_utf8(t)
    return t


def sanitize_llm_translation_output(text: str) -> str:
    """大模型译文：去掉偶发的控制符、私有区字符与前缀说明。"""
    if not text:
        return text
    t = unicodedata.normalize("NFC", text)
    for ch in _ZERO_WIDTH_AND_BOM + _PASTE_EXTRA_INVISIBLE + _PRIVATE_USE_BOOK_MARKERS:
        t = t.replace(ch, "")
    t = _BIDI_CONTROL_RE.sub("", t)
    t = _strip_c0_controls_except_newlines(t)
    t = _normalize_nbsp_narrow_spaces(t)
    for prefix in (
        "Translation:",
        "译文：",
        "翻译：",
        "Translated text:",
        "Here is the translation:",
    ):
        if t.startswith(prefix):
            t = t[len(prefix) :].lstrip()
    return t


def _cjk_or_cyrillic_score(s: str) -> int:
    n = 0
    for c in s or "":
        o = ord(c)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
            n += 2
        elif 0x0400 <= o <= 0x04FF:
            n += 2
    return n


def _try_fix_mojibake_utf8(text: str) -> str:
    """UTF-8 被误按 Latin-1/CP1252 解码时（粘贴自某些 PDF/旧系统），尝试还原。"""
    if not text:
        return text
    sample = text[:3000]
    sus = sum(1 for c in sample if c in "ÃÂæåäöüÐÑÒÐ")
    if sus < max(4, len(sample) // 50):
        return text
    for enc in ("cp1252", "latin-1"):
        try:
            fixed = text.encode(enc).decode("utf-8")
        except UnicodeError:
            continue
        if _cjk_or_cyrillic_score(fixed) > _cjk_or_cyrillic_score(text) + 2:
            return fixed
    return text


def normalize_zh_for_mt(text: str) -> str:
    """中文源文送入 Argos 前的安全整理（合同/长文可减少无谓噪声）。"""
    if not text:
        return text
    t = unicodedata.normalize("NFKC", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2009", " ")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{5,}", "\n\n\n\n", t)
    return t


# 中文成对标点 → 俄/乌书名号 «»（先成对替换，再单字符兜底）
_ZH_PAIRED_TO_GUILLEMET: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"《([^》]*)》"), r"«\1»"),
    (re.compile(r"〈([^〉]*)〉"), r"«\1»"),
    (re.compile(r"「([^」]*)」"), r"«\1»"),
    (re.compile(r"『([^』]*)』"), r"«\1»"),
    (re.compile(r"【([^】]*)】"), r"«\1»"),
    (re.compile(r"〔([^〕]*)〕"), r"«\1»"),
    (re.compile(r"“([^”]*)”"), r"«\1»"),
    (re.compile(r"‘([^’]*)’"), r"«\1»"),
    (re.compile(r"\"([^\"]+)\""), r"«\1»"),
    (re.compile(r"'([^']+)'"), r"«\1»"),
)

_ZH_PUNCT_TO_CYRILLIC = str.maketrans(
    {
        "《": "«",
        "》": "»",
        "〈": "‹",
        "〉": "›",
        "「": "«",
        "」": "»",
        "『": "«",
        "』": "»",
        "【": "«",
        "】": "»",
        "〔": "«",
        "〕": "»",
        "、": ",",
        "。": ".",
        "，": ",",
        "？": "?",
        "！": "!",
        "；": ";",
        "：": ":",
        "（": "(",
        "）": ")",
        "．": ".",
        "…": "…",
        "—": "—",
        "－": "-",
        "～": "~",
        "·": "·",
    }
)


# 送入 Argos 前包裹书名，避免 «» 被分词/机译丢掉（译后还原为 «»）
_BOOK_TITLE_OPEN = "\uE010"
_BOOK_TITLE_CLOSE = "\uE011"
_ZH_BOOK_TITLE_PAIR = re.compile(
    r"《([^》]*)》|"
    r"〈([^〉]*)〉|"
    r"「([^」]*)」|"
    r"『([^』]*)』|"
    r"【([^】]*)】|"
    r"〔([^〕]*)〕"
)


def _zh_book_title_inner(m: re.Match[str]) -> str:
    for g in m.groups():
        if g is not None:
            return g
    return ""


def _mask_zh_book_titles_for_mt(text: str) -> str:
    """《书名》→ 私有区标记对，机译更不易丢失边界。"""

    def repl(m: re.Match[str]) -> str:
        inner = _zh_book_title_inner(m)
        return f"{_BOOK_TITLE_OPEN}{inner}{_BOOK_TITLE_CLOSE}"

    return _ZH_BOOK_TITLE_PAIR.sub(repl, text or "")


def _unmask_book_title_sentinels(text: str) -> str:
    if not text:
        return text
    return text.replace(_BOOK_TITLE_OPEN, "«").replace(_BOOK_TITLE_CLOSE, "»")


def _zh_punctuation_to_cyrillic_style(text: str) -> str:
    """书名号、引号及常见中文标点 → 俄/乌排版用符号（«» 等）。"""
    if not text:
        return text
    t = text
    for pat, repl in _ZH_PAIRED_TO_GUILLEMET:
        t = pat.sub(repl, t)
    return t.translate(_ZH_PUNCT_TO_CYRILLIC)


def _wrap_line_in_guillemets_if_needed(line: str) -> str:
    """整行视为书名/作品名时，为俄/乌译文补上 « »。"""
    t = (line or "").strip()
    if not t or "«" in t or "»" in t:
        return line
    m = re.match(r"^(.+?)([.!?…]+)$", t)
    if m:
        body = m.group(1).strip()
        if body:
            return f"«{body}»{m.group(2)}"
    return f"«{t}»"


def _source_has_book_title_marks(source_zh: str) -> bool:
    s = source_zh or ""
    if _ZH_BOOK_TITLE_PAIR.search(s):
        return True
    if "«" in s and "»" in s:
        return True
    if _BOOK_TITLE_OPEN in s and _BOOK_TITLE_CLOSE in s:
        return True
    return False


def _source_book_title_covers_line(source_line: str) -> bool:
    """该行是否 essentially 只有一对书名号（含《》或 «»）。"""
    s = (source_line or "").strip()
    if not s:
        return False
    compact = re.sub(r"\s+", "", s)
    m = _ZH_BOOK_TITLE_PAIR.fullmatch(s)
    if m:
        return bool(_zh_book_title_inner(m).strip())
    m2 = re.fullmatch(r"«([^»]+)»", s)
    if m2 and m2.group(1).strip():
        return True
    m3 = re.fullmatch(
        rf"{re.escape(_BOOK_TITLE_OPEN)}([^{re.escape(_BOOK_TITLE_CLOSE)}]*)"
        rf"{re.escape(_BOOK_TITLE_CLOSE)}",
        s,
    )
    return bool(m3 and m3.group(1).strip())


def restore_guillemets_from_chinese_source(
    source_zh: str, target: str, *, target_lang: str = "ru"
) -> str:
    """
    机译常去掉 «»：根据原文书名号位置，为俄/乌译文补回 « »。
    支持《》、已转换的 «»、以及译前私有区标记。
    """
    _ = (target_lang or "").strip().lower()
    if not (source_zh or "").strip() or not (target or "").strip():
        return target
    if not _source_has_book_title_marks(source_zh):
        return target

    t = _unmask_book_title_sentinels(target)
    if t.count("«") >= 1 and t.count("»") >= 1:
        return _fix_guillemet_inner_spaces(t)

    src_lines = (source_zh or "").split("\n")
    tgt_lines = (target or "").split("\n")
    if len(src_lines) == len(tgt_lines) and len(src_lines) > 0:
        out: list[str] = []
        changed = False
        for s_line, t_line in zip(src_lines, tgt_lines):
            if _source_book_title_covers_line(s_line):
                fixed = _wrap_line_in_guillemets_if_needed(t_line)
                if fixed != t_line:
                    changed = True
                out.append(fixed)
            else:
                out.append(t_line)
        if changed:
            return "\n".join(out)

    src_stripped = (source_zh or "").strip()
    if _source_book_title_covers_line(src_stripped):
        return _wrap_line_in_guillemets_if_needed(t.strip())

    # 单行内仅一对书名号且占主体
    inners: list[str] = []
    for m in _ZH_BOOK_TITLE_PAIR.finditer(source_zh):
        inner = _zh_book_title_inner(m).strip()
        if inner:
            inners.append(inner)
    for m in re.finditer(r"«([^»]+)»", source_zh):
        inner = m.group(1).strip()
        if inner:
            inners.append(inner)
    if len(inners) == 1:
        src_compact = re.sub(r"\s+", "", source_zh)
        inner_c = re.sub(r"\s+", "", inners[0])
        if inner_c and len(inner_c) >= max(2, int(len(src_compact) * 0.35)):
            return _wrap_line_in_guillemets_if_needed(t.strip())

    return target


def prepare_zh_for_cyrillic_target(text: str, target_lang: str = "ru") -> str:
    """
    中→俄/乌：书名号用私有区标记保护 + 其余中文标点转俄/乌形式。
    """
    code = (target_lang or "").strip().lower()
    t = normalize_zh_for_mt(text)
    if code in ("ru", "uk"):
        t = _mask_zh_book_titles_for_mt(t)
        t = _zh_punctuation_to_cyrillic_style(t)
    return t


def localize_residual_cjk_punctuation_in_cyrillic(text: str) -> str:
    """译文里若仍残留《》等中文标点，统一为俄/乌形式。"""
    if not text:
        return text
    t = _zh_punctuation_to_cyrillic_style(text)
    return _unmask_book_title_sentinels(t)


def touchup_cyrillic_target_spacing(text: str) -> str:
    """
    西里尔文本：字母与后续标点之间不应有空格（机译常见）。
    仅匹配字母（不含数字），避免破坏「1 000」等写法。
    """
    if not text:
        return text
    letters = "А-Яа-яЁёІЇЄҐіїєґA-Za-z"
    t = text
    t = re.sub(rf"([{letters}]) ([,.;:!?%‰])", r"\1\2", t)
    t = re.sub(rf"([{letters}]) ([»\"'”’])", r"\1\2", t)
    t = re.sub(rf"([{letters}]) (\))", r"\1\2", t)
    t = re.sub(rf"([{letters}]) (\])", r"\1\2", t)
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\[\s+", "[", t)
    return t


def _strip_invisible_junk(s: str) -> str:
    for ch in _ZERO_WIDTH_AND_BOM:
        s = s.replace(ch, "")
    return s


def _strip_soft_hyphen(s: str) -> str:
    """软连字符 U+00AD：排版/模型偶发残留，译文里应去掉。"""
    return s.replace("\u00ad", "")


def _normalize_nbsp_narrow_spaces(s: str) -> str:
    """不换行空格/窄不换行空格 → 普通空格，避免与标点规则打架。"""
    return s.replace("\u00a0", " ").replace("\u202f", " ")


def _strip_c0_controls_except_newlines(s: str) -> str:
    """去掉除 \\t \\n \\r 外的 C0 控制符（剪贴板/PDF 偶发 U+0001 等）。"""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)


def _collapse_redundant_commas(s: str) -> str:
    """连续英文逗号压成单个（机译偶发）。"""
    return re.sub(r",{2,}", ",", s)


def _collapse_duplicate_spaces_lines(s: str) -> str:
    """行内连续空格压成单空格（保留换行）。"""
    lines = [re.sub(r" {2,}", " ", line) for line in s.split("\n")]
    return "\n".join(lines)


def _fix_guillemet_inner_spaces(s: str) -> str:
    """« 词 → «词；词 » → 词»（俄式引号与词之间不应有空格）。"""
    t = re.sub(r"«\s+", "«", s)
    t = re.sub(r"\s+»", "»", t)
    return t


def _comma_before_open_bracket(s: str) -> str:
    """`,(` → `, (` — 逗号后缺空格再接括号（机译常见）。"""
    return re.sub(r"([^\d\s]),(\()", r"\1, \2", s)


def _digit_tight_percent(s: str) -> str:
    """`5 %` → `5%`（俄/乌排版常见）。"""
    t = re.sub(r"(\d)\s+%", r"\1%", s)
    t = re.sub(r"(\d)\s+‰", r"\1‰", t)
    return t


def _clock_colon_tighten(s: str) -> str:
    """`12 : 30` → `12:30`（时间机译偶发）。"""
    return re.sub(r"(\d)\s*:\s*(\d)", r"\1:\2", s)


def _iso_date_tighten(s: str) -> str:
    """`2024 - 05 - 13` → `2024-05-13`（日期机译偶发）。"""
    return re.sub(
        r"(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})",
        r"\1-\2-\3",
        s,
    )


def _normalize_apostrophe_chars(s: str) -> str:
    """弯引号/修饰撇号 → ASCII '，减少乌语撇号与后缀粘连的视觉噪声。"""
    for u in ("\u2019", "\u2018", "\u02bc", "\u02b9"):
        s = s.replace(u, "'")
    return s


def _strip_trailing_spaces_lines(s: str) -> str:
    return "\n".join(line.rstrip() for line in s.split("\n"))


def _ru_fix_to_est(s: str) -> str:
    """常见合并误写 «тоесть» → «то есть»（即 i.e.）。"""
    return re.sub(
        r"(?<![а-яёіїєґA-Za-z])тоесть(?![а-яёіїєґA-Za-z])",
        "то есть",
        s,
        flags=re.IGNORECASE,
    )


def _cyrillic_space_before_comma_dot(s: str) -> str:
    """西里尔词与常见句读标点间误插空格；省略号 … 不动；分号、标签冒号一并收紧。"""
    cyr = r"А-Яа-яЁёІЇЄҐіїєґ"
    t = re.sub(rf"(?<=[{cyr}])\s+,", ",", s)
    t = re.sub(rf"(?<=[{cyr}])\s+\.(?!\.)", ".", t)
    t = re.sub(rf"(?<=[{cyr}])\s+\?", "?", t)
    t = re.sub(rf"(?<=[{cyr}])\s+!", "!", t)
    t = re.sub(rf"(?<=[{cyr}])\s+;", ";", t)
    t = re.sub(rf"(?<=[{cyr}])\s+:\s+(?=[{cyr}])", ": ", t)
    return t


def _ru_discourse_comma(s: str) -> str:
    """俄语话语标记与逗号间误空格（机译常见）。"""
    t = re.sub(r"(?i)\bтак\s+же\s+,", "так же,", s)
    t = re.sub(r"(?i)\bнапример\s+,", "например,", t)
    t = re.sub(r"(?i)\bоднако\s+,", "однако,", t)
    t = re.sub(r"(?i)\bкроме\s+того\s+,", "кроме того,", t)
    t = re.sub(r"(?i)\bследовательно\s+,", "следовательно,", t)
    t = re.sub(r"(?i)\bпоэтому\s+,", "поэтому,", t)
    t = re.sub(r"(?i)\bтем\s+не\s+менее\s+,", "тем не менее,", t)
    t = re.sub(r"(?i)\bименно\s+,", "именно,", t)
    return t


def _uk_discourse_comma(s: str) -> str:
    """乌克兰语话语标记与逗号间误空格（机译常见）。"""
    t = re.sub(r"(?i)\bтак\s+само\s+,", "так само,", s)
    t = re.sub(r"(?i)\bзокрема\s+,", "зокрема,", t)
    t = re.sub(r"(?i)\bвтім\s+,", "втім,", t)
    t = re.sub(r"(?i)\bпроте\s+,", "проте,", t)
    t = re.sub(r"(?i)\bнаприклад\s+,", "наприклад,", t)
    t = re.sub(r"(?i)\bтобто\s+,", "тобто,", t)
    t = re.sub(r"(?i)\bотже\s+,", "отже,", t)
    t = re.sub(r"(?i)\bтому\s+,", "тому,", t)
    return t


def _ru_fix_nesmotrya_na(s: str) -> str:
    """«не смотря на» → «несмотря на»（机译高频硬错）。"""
    return re.sub(r"(?i)\bне\s+смотря\s+на\b", "несмотря на", s)


def _ru_fix_v_techenie_time_span(s: str) -> str:
    """
    表时长时误写 «в течении года» 等；应为 «в течение года»。
    仅白名单时间名词，避免误伤 «в течении реки»（河流走向）等。
    """
    span_nouns = (
        "года|месяца|дня|дней|недели|недель|часа|часов|минут|минуты|"
        "секунд|секунды|квартала|кварталов|лет|годов|суток|смены|"
        "полугодия|полугодий|мгновения|мгновений"
    )
    return re.sub(
        rf"(?i)\bв\s+течении\s+({span_nouns})\b",
        r"в течение \1",
        s,
    )


def _ru_drop_redundant_subject_before_u_nego_net(s: str) -> str:
    """
    中文「他…人性…」经占位符译出时，模型常同时译出 «Он» 与 «У него нет…»，造成 *Он У него нет…*。
    仅在 «У … нет» 结构前删重复主语，避免误伤 «Он у него был» 等句。
    """
    t = re.sub(
        r"(?mi)^\s*Он\s+(?=у\s+него\s+нет\b)",
        "",
        s,
    )
    t = re.sub(
        r"(?mi)^\s*Она\s+(?=у\s+не[её]\s+нет\b)",
        "",
        t,
    )
    t = re.sub(
        r"([.!?…])([\"»\s]*)\s*Он\s+(?=у\s+него\s+нет\b)",
        r"\1\2 ",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(
        r"([.!?…])([\"»\s]*)\s*Она\s+(?=у\s+не[её]\s+нет\b)",
        r"\1\2 ",
        t,
        flags=re.IGNORECASE,
    )
    return t


def _uk_drop_redundant_subject_before_u_noho_nemaye(s: str) -> str:
    """
    与俄语类似：术语占位 + 整句译出时，易出现 *Він У нього немає…*（Він 与 У нього немає 重复指代）。
    仅在 «у нього/неї немає» 结构前删多余 Він/Вона。
    """
    t = re.sub(
        r"(?mi)^\s*Він\s+(?=у\s+нього\s+немає\b)",
        "",
        s,
    )
    t = re.sub(
        r"(?mi)^\s*Вона\s+(?=у\s+не[ії]\s+немає\b)",
        "",
        t,
    )
    t = re.sub(
        r"([.!?…])([\"»\s]*)\s*Він\s+(?=у\s+нього\s+немає\b)",
        r"\1\2 ",
        t,
        flags=re.IGNORECASE,
    )
    t = re.sub(
        r"([.!?…])([\"»\s]*)\s*Вона\s+(?=у\s+не[ії]\s+немає\b)",
        r"\1\2 ",
        t,
        flags=re.IGNORECASE,
    )
    return t


def _is_zh_family_lang(code: str) -> bool:
    """与 GUI / 术语桥一致：简体及常见变体代码视为中文源。"""
    c = (code or "").strip().lower().replace("_", "-")
    if not c:
        return False
    if c.startswith("zh"):
        return True
    return c in ("zt", "jy", "cn", "tw")


def _apply_zh_shi_me_definitional_fix(
    source_zh: str, target: str, tgt_lang: str
) -> str:
    """
    中文定义问句「什么是 X？」误译为性质问句时修正：
    - 俄语：«Какова/Каков/Каково/Каковы X?» → «Что такое X?»
    - 乌克兰语：«Яка/Який/Яке/Які X?» → «Що таке X?»

    仅在逐行对齐且该行中文匹配 ``^什么是…[？?]$`` 时替换，避免误伤真实 «какова погода» 等句
    （那些行在中文侧不会以「什么是」起句）。
    """
    if not source_zh.strip() or not target:
        return target

    _RU_KAKOV = re.compile(
        r"^(?i)(Какова|Каков|Каково|Каковы)\s+(.{1,150}?)\s*[？?]?\s*$"
    )
    _UK_YAK = re.compile(
        r"^(?i)(Яка|Який|Яке|Які)\s+(.{1,150}?)\s*[？?]?\s*$"
    )
    _SRC_SHI_ME = re.compile(r"^什么是\s*(.{1,80}?)\s*[？?]\s*$")

    src_lines = source_zh.split("\n")
    tgt_lines = target.split("\n")
    if len(src_lines) != len(tgt_lines):
        return target

    out_lines: list[str] = []
    for s_raw, t_raw in zip(src_lines, tgt_lines):
        s = s_raw.strip()
        tt = t_raw.strip()
        if not _SRC_SHI_ME.match(s):
            out_lines.append(t_raw)
            continue
        if tgt_lang == "ru":
            m = _RU_KAKOV.match(tt)
            if not m:
                out_lines.append(t_raw)
                continue
            rest = m.group(2).strip()
            out_lines.append(f"Что такое {rest}?")
        elif tgt_lang == "uk":
            m = _UK_YAK.match(tt)
            if not m:
                out_lines.append(t_raw)
                continue
            rest = m.group(2).strip()
            out_lines.append(f"Що таке {rest}?")
        else:
            out_lines.append(t_raw)
    return "\n".join(out_lines)


def _tgt_has_time_adverb(t: str, *, evening: bool, morning: bool, afternoon: bool) -> bool:
    if not t:
        return False
    if evening and re.search(
        r"(?i)\b(вечером|вечера|вечер|ночью|вечері|ввечері|вечора)\b", t
    ):
        return True
    if morning and re.search(r"(?i)\b(утром|утра|утро|рано\s+утром|вранці)\b", t):
        return True
    if afternoon and re.search(r"(?i)\b(днём|днем|дня|в\s+обед|в\s+полдень|вдень)\b", t):
        return True
    return False


def _inject_day_time_phrase(target: str, day_word: str, time_phrase: str) -> str:
    """在「сегодня/вчера…」后插入「вечером」等，若译文尚未包含该时段词。"""
    if not target or not day_word or not time_phrase:
        return target
    tw = time_phrase.strip()
    if re.search(rf"(?i)\b{re.escape(tw)}\b", target):
        return target
    pat = re.compile(rf"(?i)\b({re.escape(day_word)})\b")
    if not pat.search(target):
        return target
    if re.search(
        rf"(?i)\b{re.escape(day_word)}\s+{re.escape(tw)}\b", target
    ):
        return target
    return pat.sub(rf"\1 {tw}", target, count=1)


def _apply_zh_time_phrase_restore(
    source_zh: str, target: str, tgt_lang: str
) -> str:
    """
    中→俄/乌：机译（尤其经英语枢轴）常把「晚上/今早」等时段词丢掉，只留「今天/сегодня」。
    按原文保守补回 сегодня вечером、вчера вечером 等。
    """
    if not (source_zh or "").strip() or not (target or "").strip():
        return target
    code = (tgt_lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return target

    if code == "ru":
        cfg = (
            (re.compile(r"今天\s*晚上|今晚|今夜"), "сегодня", "вечером"),
            (re.compile(r"昨天\s*晚上|昨晚"), "вчера", "вечером"),
            (re.compile(r"明天\s*晚上|明晚"), "завтра", "вечером"),
            (re.compile(r"今天\s*早上|今早|今晨"), "сегодня", "утром"),
            (re.compile(r"昨天\s*早上|昨晨"), "вчера", "утром"),
            (re.compile(r"明天\s*早上|明早"), "завтра", "утром"),
            (re.compile(r"今天\s*下午|今天下午"), "сегодня", "днём"),
            (re.compile(r"今天\s*中午|今天中午"), "сегодня", "в обед"),
        )
        eve_rx = re.compile(r"(?i)\b(вечером|вечера|вечер|ночью)\b")
    else:
        cfg = (
            (re.compile(r"今天\s*晚上|今晚|今夜"), "сьогодні", "ввечері"),
            (re.compile(r"昨天\s*晚上|昨晚"), "вчора", "ввечері"),
            (re.compile(r"明天\s*晚上|明晚"), "завтра", "ввечері"),
            (re.compile(r"今天\s*早上|今早|今晨"), "сьогодні", "вранці"),
            (re.compile(r"昨天\s*早上|昨晨"), "вчора", "вранці"),
            (re.compile(r"明天\s*早上|明早"), "завтра", "вранці"),
            (re.compile(r"今天\s*下午|今天下午"), "сьогодні", "вдень"),
            (re.compile(r"今天\s*中午|今天中午"), "сьогодні", "в обід"),
        )
        eve_rx = re.compile(r"(?i)\b(ввечері|вечора|вечер|ночью)\b")

    src_lines = source_zh.split("\n")
    tgt_lines = target.split("\n")
    if len(src_lines) != len(tgt_lines):
        pairs = [(source_zh, target)]
    else:
        pairs = list(zip(src_lines, tgt_lines))

    out: list[str] = []
    for s_raw, t_raw in pairs:
        s = s_raw.strip()
        t = t_raw
        if not s:
            out.append(t_raw)
            continue
        for src_pat, day_w, time_p in cfg:
            if not src_pat.search(s):
                continue
            is_eve = "вечер" in time_p.lower() or "ввечер" in time_p.lower()
            is_morn = "утр" in time_p.lower() or "ранці" in time_p.lower()
            is_aft = time_p in ("днём", "вдень")
            if _tgt_has_time_adverb(
                t, evening=is_eve, morning=is_morn, afternoon=is_aft
            ):
                continue
            if is_eve and eve_rx.search(t):
                continue
            t = _inject_day_time_phrase(t, day_w, time_p)
        out.append(t)
    return "\n".join(out)


# 中文「你」→ 俄语 ты；「您/你们」→ Вы。机译（尤其 zh→en→ru）常一律用 Вы。
_ZH_FORMAL_OR_PLURAL_YOU = re.compile(r"您们?|你们")
_RU_VY_PRONOUN_MARK = re.compile(
    r"\b(Вы|вы|Вас|вас|Вам|вам|Вами|вами)\b"
)
_RU_VY_TO_TY_PAIRS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bВы\b"), "Ты"),
    (re.compile(r"\bвы\b"), "ты"),
    (re.compile(r"\bВас\b"), "тебя"),
    (re.compile(r"\bвас\b"), "тебя"),
    (re.compile(r"\bВам\b"), "тебе"),
    (re.compile(r"\bвам\b"), "тебе"),
    (re.compile(r"\bВами\b"), "тобой"),
    (re.compile(r"\bвами\b"), "тобой"),
    (re.compile(r"\bВаш\b"), "Твой"),
    (re.compile(r"\bваш\b"), "твой"),
    (re.compile(r"\bВаша\b"), "Твоя"),
    (re.compile(r"\bваша\b"), "твоя"),
    (re.compile(r"\bВаше\b"), "Твоё"),
    (re.compile(r"\bваше\b"), "твоё"),
    (re.compile(r"\bВаши\b"), "Твои"),
    (re.compile(r"\bваши\b"), "твои"),
)
_UK_VI_PRONOUN_MARK = re.compile(
    r"\b(Ви|ви|Вас|вас|Вам|вам|Вами|вами)\b"
)
_UK_VI_TO_TI_PAIRS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bВи\b"), "Ти"),
    (re.compile(r"\bви\b"), "ти"),
    (re.compile(r"\bВас\b"), "тебе"),
    (re.compile(r"\bвас\b"), "тебе"),
    (re.compile(r"\bВам\b"), "тобі"),
    (re.compile(r"\bвам\b"), "тобі"),
    (re.compile(r"\bВами\b"), "тобою"),
    (re.compile(r"\bвами\b"), "тобою"),
)
_UK_VERB_PLURAL_TO_TI: dict[str, str] = {
    "їли": "їв",
    "їсте": "їси",
    "були": "був",
    "будете": "будеш",
    "можете": "можеш",
    "знаєте": "знаєш",
    "хочете": "хочеш",
    "йдете": "йдеш",
    "робите": "робиш",
}


def _preserve_cyrillic_word_case(old: str, new: str) -> str:
    if not old or not new:
        return new
    if old[0].isupper():
        return new[0].upper() + new[1:]
    return new


def _zh_source_uses_informal_ni(source_zh: str) -> bool:
    """
    源文含第二人称「你」（非 你们/您的/你的/你好 等）。
    与「您/您们/你们」同现时不视为纯口语你。
    """
    s = source_zh or ""
    if not s.strip():
        return False
    if _ZH_FORMAL_OR_PLURAL_YOU.search(s) or "您" in s:
        return False
    for m in re.finditer("你", s):
        i = m.start()
        if i + 1 < len(s) and s[i + 1] == "们":
            continue
        if i + 1 < len(s) and s[i + 1] == "的":
            continue
        if i + 1 < len(s) and s[i + 1] == "好":
            j = i + 2
            if j >= len(s) or s[j] in "，,。.!！?？吗嘛呀啊 \n\r\t":
                continue
        return True
    return False


def _ru_verb_to_ty_form(verb: str, morph) -> str | None:
    """Вы+复数/敬称动词 → ты+单数（默认阳性过去式）。"""
    import glossary_manager as gm

    ps = [p for p in morph.parse(verb) if gm.safe_parse_pos(p) == "VERB"]
    if not ps:
        return None
    try:
        p = gm.pick_morph_parse(ps, verb)
    except Exception:
        p = max(ps, key=lambda x: x.score)
    if p is None:
        return None
    tag = p.tag
    inf = None
    if tag and "past" in tag and "plur" in tag:
        inf = p.inflect({"masc", "sing", "past"})
    elif tag and ("plur" in tag or ("2per" in tag and "pres" in tag)):
        inf = p.inflect({"2per", "sing"})
    elif tag and "2per" in tag:
        inf = p.inflect({"2per", "sing"})
    if inf is None or not getattr(inf, "word", None):
        return None
    return _preserve_cyrillic_word_case(verb, inf.word)


def _ru_line_vy_to_ty(line: str) -> str:
    if not _RU_VY_PRONOUN_MARK.search(line or ""):
        return line
    t = line
    for pat, repl in _RU_VY_TO_TY_PAIRS:
        t = pat.sub(lambda m, r=repl: _preserve_cyrillic_word_case(m.group(0), r), t)
    try:
        import glossary_manager as gm

        morph = gm.shared_morph_analyzer()
    except Exception:
        morph = None
    if morph is None:
        return t

    def _verb_sub(m: re.Match[str]) -> str:
        w = m.group(0)
        fixed = _ru_verb_to_ty_form(w, morph)
        return fixed if fixed else w

    return re.sub(r"\b[А-Яа-яЁё]+\b", _verb_sub, t)


def _uk_line_vi_to_ti(line: str) -> str:
    if not _UK_VI_PRONOUN_MARK.search(line or ""):
        return line
    t = line
    for pat, repl in _UK_VI_TO_TI_PAIRS:
        t = pat.sub(lambda m, r=repl: _preserve_cyrillic_word_case(m.group(0), r), t)

    def _uk_verb_sub(m: re.Match[str]) -> str:
        w = m.group(0)
        low = w.lower()
        repl = _UK_VERB_PLURAL_TO_TI.get(low)
        if repl:
            return _preserve_cyrillic_word_case(w, repl)
        return w

    if re.search(r"\b(ти|Ти)\b", t):
        t = re.sub(
            r"\b[А-Яа-яІіЇїЄєҐґ]+(?:-[А-Яа-яІіЇїЄєҐґ]+)*\b",
            _uk_verb_sub,
            t,
        )
    return t


def _apply_zh_ni_ty_pronoun_fix(
    source_zh: str, target: str, tgt_lang: str
) -> str:
    """
    中→俄/乌：源文为口语「你」时，将机译敬称 Вы/Ви 及复数动词改为 ты/ти。
    源文含「您/你们」时不改动（保留 Вы/Ви）。
    """
    if not _zh_source_uses_informal_ni(source_zh):
        return target
    if not (target or "").strip():
        return target
    code = (tgt_lang or "").strip().lower()
    if code not in ("ru", "uk"):
        return target

    src_lines = source_zh.split("\n")
    tgt_lines = target.split("\n")
    if len(src_lines) == len(tgt_lines) and len(src_lines) > 0:
        pairs = list(zip(src_lines, tgt_lines))
    else:
        pairs = [(source_zh, target)]

    out: list[str] = []
    fix_line = _ru_line_vy_to_ty if code == "ru" else _uk_line_vi_to_ti
    for s_raw, t_raw in pairs:
        if not _zh_source_uses_informal_ni(s_raw):
            out.append(t_raw)
            continue
        out.append(fix_line(t_raw))
    return "\n".join(out)


_UK_CYR_WORD = re.compile(
    r"[А-Яа-яІіЇїЄєҐґ]+(?:-[А-Яа-яІіЇїЄєҐґ]+)*"
)
_RU_CYR_WORD = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")

# 若未安装 translate-ru_uk，仍可能经 en 枢轴；直译包见 tools/build_ru_uk_from_opus_zip.py。
# 单行单词时优先用下列乌语不定式（与 Google 等对照一致的高频动词）。
_RU_UK_VERB_OVERRIDE: dict[str, str] = {
    "отключить": "відключити",
    "отключать": "відключати",
    "включить": "увімкнути",
    "включать": "увімкнути",
    "выключить": "вимкнути",
    "выключать": "вимкати",
    "подключить": "підключити",
    "подключать": "підключати",
    "открыть": "відкрити",
    "открывать": "відкривати",
    "закрыть": "закрити",
    "закрывать": "закривати",
    "войти": "увійти",
    "входить": "входити",
}


def _ru_lemma_key(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return ""
    try:
        import glossary_manager as gm

        morph = gm.shared_morph_analyzer()
        if morph is not None:
            parses = morph.parse(t)
            if parses:
                p = gm.pick_morph_parse(parses, t)
                return (p.normal_form or t).lower().replace("ё", "е")
    except Exception:
        pass
    return t.lower().replace("ё", "е")


def _ru_token_is_verb_infinitive(token: str) -> bool:
    t = (token or "").strip()
    if not t:
        return False
    try:
        import glossary_manager as gm

        morph = gm.shared_morph_analyzer()
        if morph is not None:
            parses = morph.parse(t)
            if parses:
                pos = gm.safe_parse_pos(gm.pick_morph_parse(parses, t))
                if pos in ("VERB", "INFN", "GRND"):
                    return True
    except Exception:
        pass
    low = t.lower().replace("ё", "е")
    return bool(re.search(r"(?:ть|ти|чь)$", low))


def _uk_token_is_deverbal_noun(token: str) -> bool:
    w = (token or "").strip().lower()
    if not w or not re.fullmatch(r"[а-яіїєґ'-]+", w):
        return False
    if re.search(r"(?:ти|ті|ч)$", w):
        return False
    return w.endswith(("ння", "ення", "ість", "ання", "зання", "іння"))


def _uk_token_is_verb_infinitive(token: str) -> bool:
    w = (token or "").strip().lower()
    if not w:
        return False
    return bool(re.search(r"(?:ти|ті|ч)$", w))


def _uk_verb_from_deverbal_noun_guess(uk_noun: str, ru_verb: str) -> str:
    """动名词 -ння/-ення → 不定式 -ити/-ати（如 відключення → відключити）。"""
    uk = (uk_noun or "").strip().lower()
    ru = (ru_verb or "").strip().lower().replace("ё", "е")
    if ru in _RU_UK_VERB_OVERRIDE:
        return _RU_UK_VERB_OVERRIDE[ru]
    if uk.endswith("ення"):
        cand = uk[:-4] + "ити"
    elif uk.endswith("ння"):
        cand = uk[:-3] + "ити"
    elif uk.endswith("ання"):
        cand = uk[:-3] + "ати"
    else:
        return ""
    return cand if _uk_token_is_verb_infinitive(cand) else ""


def _wiki_uk_verb_for_ru_lemma(ru_lemma: str) -> str:
    try:
        import wiktionary_parser as wp

        data = wp.get_russian_inflections(ru_lemma, timeout=6.0)
        for w in data.get("uk_equivalent_words") or []:
            ww = str(w).strip()
            if _uk_token_is_verb_infinitive(ww) and not _uk_token_is_deverbal_noun(ww):
                return ww
    except Exception:
        pass
    return ""


def _fix_ru_uk_single_word_pair(ru_word: str, uk_word: str) -> str:
    if not _ru_token_is_verb_infinitive(ru_word):
        return uk_word
    ru_lem = _ru_lemma_key(ru_word)
    canon = _RU_UK_VERB_OVERRIDE.get(ru_lem) or ""
    if canon:
        uk_low = (uk_word or "").strip().lower()
        if uk_low != canon.lower():
            return canon
        return uk_word
    if not _uk_token_is_deverbal_noun(uk_word):
        return uk_word
    repl = _wiki_uk_verb_for_ru_lemma(ru_word.strip())
    if not repl:
        repl = _uk_verb_from_deverbal_noun_guess(uk_word, ru_word)
    return repl or uk_word


def _fix_ru_uk_line_pair(ru_line: str, uk_line: str) -> str:
    ru_tokens = _RU_CYR_WORD.findall(ru_line or "")
    uk_tokens = _UK_CYR_WORD.findall(uk_line or "")
    if len(ru_tokens) != 1 or len(uk_tokens) != 1:
        return uk_line
    fixed = _fix_ru_uk_single_word_pair(ru_tokens[0], uk_tokens[0])
    if fixed == uk_tokens[0]:
        return uk_line
    return uk_line.replace(uk_tokens[0], fixed, 1)


def _fix_ru_to_uk_verb_deverbal_noun(source_ru: str, target_uk: str) -> str:
    """
    俄语→乌语：动词经 en 枢轴易变成动名词（отключить→відключення）或错义动词（включить→увійти）。
    单行单词时用语义对照表与形态规则修补。
    """
    if not (source_ru or "").strip() or not (target_uk or "").strip():
        return target_uk
    src_lines = source_ru.split("\n")
    tgt_lines = target_uk.split("\n")
    if len(src_lines) == len(tgt_lines):
        return "\n".join(
            _fix_ru_uk_line_pair(s, t) for s, t in zip(src_lines, tgt_lines)
        )
    if len(src_lines) == 1 and len(tgt_lines) == 1:
        return _fix_ru_uk_line_pair(src_lines[0], tgt_lines[0])
    return target_uk


_GLOSSA_MARK = re.compile(
    r"GLOSSA|ＧＬＯＳＳＡ|ГЛОССА",
    re.I,
)


def postprocess_translation_target(
    text: str,
    lang_code: str,
    *,
    source_text: str | None = None,
    source_lang_code: str | None = None,
    postprocess_depth: str = "normal",
) -> str:
    """
    俄/乌译文后处理链。lang_code: ``ru`` | ``uk``。

    若传入 ``source_text`` / ``source_lang_code`` 且源为中文，可对「什么是…？」类定义句做
    与原文对齐的保守修补（见 ``_apply_zh_shi_me_definitional_fix``）。
    """
    code = (lang_code or "").strip().lower()
    if code not in ("ru", "uk") or not text:
        return text

    t = _strip_invisible_junk(text)
    t = _strip_c0_controls_except_newlines(t)
    t = _normalize_nbsp_narrow_spaces(t)
    t = _strip_soft_hyphen(t)
    t = localize_residual_cjk_punctuation_in_cyrillic(t)
    if source_text and _is_zh_family_lang(source_lang_code or ""):
        t = restore_guillemets_from_chinese_source(
            source_text, t, target_lang=code
        )
        t = _apply_zh_shi_me_definitional_fix(source_text, t, code)
        t = _apply_zh_time_phrase_restore(source_text, t, code)
        t = _apply_zh_ni_ty_pronoun_fix(source_text, t, code)
    t = touchup_cyrillic_target_spacing(t)
    t = _collapse_duplicate_spaces_lines(t)
    t = _fix_guillemet_inner_spaces(t)
    t = _comma_before_open_bracket(t)
    t = _digit_tight_percent(t)
    t = _clock_colon_tighten(t)
    t = _iso_date_tighten(t)
    t = _normalize_apostrophe_chars(t)
    t = _collapse_redundant_commas(t)
    if code == "ru":
        t = _ru_discourse_comma(t)
    else:
        t = _uk_discourse_comma(t)
    t = _cyrillic_space_before_comma_dot(t)
    t = _strip_trailing_spaces_lines(t)

    if code == "ru":
        t = _ru_drop_redundant_subject_before_u_nego_net(t)
        t = _ru_fix_v_techenie_time_span(t)
        t = _ru_fix_nesmotrya_na(t)
        t = _ru_fix_to_est(t)
    elif code == "uk":
        t = _uk_drop_redundant_subject_before_u_noho_nemaye(t)
        if (source_lang_code or "").strip().lower() == "ru" and source_text:
            t = _fix_ru_to_uk_verb_deverbal_noun(source_text, t)

    try:
        import slavic_pro_register as spr

        if spr.pro_register_fix_enabled():
            t = spr.apply_pro_register_fixes(t, code)
    except ImportError:
        pass

    try:
        import slavic_idioms as si

        if si.slavic_idiom_fix_enabled():
            t = si.apply_idiom_fixes(
                t,
                code,
                source_text=source_text,
                source_lang=source_lang_code,
            )
    except ImportError:
        pass

    depth = (postprocess_depth or "normal").strip().lower()
    need_morph = depth not in ("fast",) or bool(_GLOSSA_MARK.search(t))
    if depth == "short":
        need_morph = True
    run_advanced = depth in ("full", "long")
    morph_passes = 1 if depth in ("short", "normal", "long") else 2
    advanced_passes = 1 if depth in ("long", "full") else 2

    try:
        import glossary_inflection as gi

        if need_morph and gi.slavic_morph_fix_enabled():
            t = gi.fix_text_slavic_morphology(
                t, code, passes=morph_passes
            )
    except ImportError:
        pass

    try:
        import slavic_advanced_morph as sam

        if run_advanced and sam.advanced_slavic_morph_enabled():
            t = sam.fix_text_advanced_slavic_morphology(
                t, code, passes=advanced_passes
            )
    except ImportError:
        pass

    try:
        import slavic_pro_register as spr

        t = spr.restore_frozen_professional_phrases(t, code)
    except ImportError:
        pass

    t = _collapse_duplicate_spaces_lines(t)
    t = _cyrillic_space_before_comma_dot(t)
    t = _strip_trailing_spaces_lines(t)
    return t
