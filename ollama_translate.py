"""
本地翻译引擎：Ollama + Qwen 2.5（100% 本机推理，数据不上传云端）。
与 Argos 的 translation.translate(text) 接口兼容，供术语库与翻译页复用。
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

_DEFAULT_MODEL = "qwen2.5:7b"
_DEFAULT_URL = "http://127.0.0.1:11434"
_SETTINGS_CACHE: dict[str, str] | None = None

# Argos 语言 code → Qwen 提示词中的语言名
_CODE_TO_QWEN: dict[str, str] = {
    "zh": "Simplified Chinese",
    "zt": "Traditional Chinese",
    "en": "English",
    "ru": "Russian",
    "uk": "Ukrainian",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "pb": "Brazilian Portuguese",
    "ar": "Arabic",
    "hi": "Hindi",
    "tr": "Turkish",
    "pl": "Polish",
    "nl": "Dutch",
    "sv": "Swedish",
    "cs": "Czech",
    "ro": "Romanian",
    "hu": "Hungarian",
    "el": "Greek",
    "he": "Hebrew",
    "th": "Thai",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ms": "Malay",
    "fa": "Persian",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "ur": "Urdu",
    "kk": "Kazakh",
    "uz": "Uzbek",
    "ky": "Kyrgyz",
    "tg": "Tajik",
    "az": "Azerbaijani",
    "ka": "Georgian",
    "hy": "Armenian",
    "be": "Belarusian",
    "bg": "Bulgarian",
    "sr": "Serbian",
    "hr": "Croatian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "et": "Estonian",
    "fi": "Finnish",
    "da": "Danish",
    "no": "Norwegian",
    "nb": "Norwegian",
    "nn": "Norwegian",
    "ca": "Catalan",
    "gl": "Galician",
    "eu": "Basque",
    "sq": "Albanian",
    "mk": "Macedonian",
    "sw": "Swahili",
    "af": "Afrikaans",
    "eo": "Esperanto",
    "la": "Latin",
    "mn": "Mongolian",
    "my": "Burmese",
    "km": "Khmer",
    "lo": "Lao",
    "ne": "Nepali",
    "si": "Sinhala",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "tl": "Tagalog",
    "jv": "Javanese",
    "su": "Sundanese",
    "yi": "Yiddish",
    "ga": "Irish",
    "cy": "Welsh",
    "is": "Icelandic",
    "mt": "Maltese",
    "lb": "Luxembourgish",
}

# Ollama 模式下 UI 语言列表（与 Argos 常用 code 对齐）
_OLLAMA_UI_LANGS: tuple[tuple[str, str], ...] = (
    ("en", "English"),
    ("zh", "Chinese"),
    ("zt", "Chinese (traditional)"),
    ("ru", "Russian"),
    ("uk", "Ukrainian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("fr", "French"),
    ("de", "German"),
    ("es", "Spanish"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("pb", "Portuguese (Brazil)"),
    ("ar", "Arabic"),
    ("pl", "Polish"),
    ("tr", "Turkish"),
    ("nl", "Dutch"),
    ("sv", "Swedish"),
    ("cs", "Czech"),
    ("ro", "Romanian"),
    ("hu", "Hungarian"),
    ("el", "Greek"),
    ("he", "Hebrew"),
    ("hi", "Hindi"),
    ("th", "Thai"),
    ("vi", "Vietnamese"),
    ("id", "Indonesian"),
    ("fa", "Persian"),
    ("kk", "Kazakh"),
    ("be", "Belarusian"),
    ("bg", "Bulgarian"),
    ("hr", "Croatian"),
    ("sk", "Slovak"),
    ("sl", "Slovenian"),
    ("lt", "Lithuanian"),
    ("lv", "Latvian"),
    ("et", "Estonian"),
    ("fi", "Finnish"),
    ("da", "Danish"),
    ("no", "Norwegian"),
    ("ca", "Catalan"),
    ("eo", "Esperanto"),
    ("sw", "Swahili"),
    ("mn", "Mongolian"),
    ("my", "Burmese"),
    ("km", "Khmer"),
    ("ne", "Nepali"),
    ("bn", "Bengali"),
    ("ta", "Tamil"),
    ("te", "Telugu"),
    ("ur", "Urdu"),
    ("pa", "Punjabi"),
    ("gu", "Gujarati"),
    ("tl", "Tagalog"),
    ("ga", "Irish"),
    ("cy", "Welsh"),
    ("is", "Icelandic"),
    ("mt", "Maltese"),
    ("lb", "Luxembourgish"),
    ("la", "Latin"),
)

_GLOSSA_ANY = re.compile(
    r"(?:GLOSSA\d{3,4}|ＧＬＯＳＳＡ[０-９]{3,4}|[Гг][Лл][Оо][Сс][Сс][Аа]\d{3,4})"
)


def portable_root() -> Path:
    return Path(__file__).resolve().parent


def _settings_path() -> Path:
    custom = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if custom:
        return Path(custom) / "argos-translate" / "settings.json"
    return portable_root() / "data" / "config" / "argos-translate" / "settings.json"


def _load_settings() -> dict[str, str]:
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is not None:
        return _SETTINGS_CACHE
    out: dict[str, str] = {}
    path = _settings_path()
    if path.is_file():
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                out = {str(k): str(v) for k, v in raw.items()}
        except (OSError, json.JSONDecodeError):
            pass
    _SETTINGS_CACHE = out
    return out


def _setting(key: str, default: str = "") -> str:
    env_key = key
    if os.environ.get(env_key, "").strip():
        return os.environ.get(env_key, "").strip()
    return _load_settings().get(key, default).strip()


def use_ollama_backend() -> bool:
    flag = _setting("ARGOS_USE_OLLAMA", "1")
    return flag.lower() in ("1", "true", "yes", "on")


def model_name() -> str:
    return _setting("OLLAMA_MODEL", _DEFAULT_MODEL) or _DEFAULT_MODEL


def base_url() -> str:
    url = _setting("OLLAMA_URL", _DEFAULT_URL) or _DEFAULT_URL
    return url.rstrip("/")


def _qwen_lang(code: str) -> str:
    c = (code or "").strip().lower()
    if c in _CODE_TO_QWEN:
        return _CODE_TO_QWEN[c]
    if c.startswith("zh"):
        return "Simplified Chinese"
    return c or "the target language"


_TRANSLATOR_SYSTEM = """\
You are an expert literary and professional translator.

Prioritize meaning, tone, and natural native expression over word-for-word rendering.

Figurative and abstract language:
- Metaphors, similes, idioms, proverbs, slang, irony, and rhetorical figures: use \
equivalent expressions in the target language that convey the same intent and \
register. Do NOT translate figurative images literally when they would sound \
unnatural or misleading in the target culture.
- Abstract, philosophical, emotional, or literary wording: preserve the underlying \
idea and nuance; adapt phrasing so it reads naturally to native speakers.
- Ambiguous or context-dependent wording: infer the intended sense from context \
and translate that meaning, not a naive literal reading.

Output rules:
- Output ONLY the translation. No explanations, notes, alternatives, or markdown.
- Preserve placeholders like GLOSSA0001 exactly as they appear — do NOT translate, \
inflect, split, or add case endings to them.
- Preserve numbers, names, and formatting when appropriate.
- Match the original register (formal / informal / poetic / technical).
- Do not add, omit, summarize, or truncate any part of the source.
- Translate the COMPLETE input from start to finish; output must cover all source content."""

_SLAVIC_GRAMMAR_RU = """

Russian morphology (mandatory — Sussex Blok / Wikibooks / MasterRussian):
- Six cases: every noun, adjective, pronoun must agree in gender, number, and case.
- Prepositions (case is mandatory):
  • Genitive: без, для, до, из, от, у (possession), после, около, возле, вокруг, \
среди, против, ради, кроме, мimo, из-за, из-под, с (from a place/time)
  • Dative: к/ко, по (along/distributive), благодаря, согласно, вопреки
  • Accusative: в/на (motion into/onto), за (thanks/reward/motion behind), про, через, \
под (motion under), о (against)
  • Instrumental: с/со (with), за (static behind), под/над/перед/между (static position), \
по (manner)
  • Prepositional/Locative: в/на (static location), о/об/обо, при
  • у+есть → possessed item stays nominative; нет/много/несколько → genitive (plural after quantity)
- Verbs governing case:
  • Dative object (person only): помогать кому, верить кому, мешать кому; \
говорить/писать/дать → person dative OR thing accusative (написал письмо, сказал правду)
  • Genitive object: хотеть, ждать, бояться, искать, добиваться, лишать, требовать
  • Instrumental predicate/complement: стать инженером, работать инженером (profession); \
NOT location — работает в библиотеке (prepositional), not *библиотекой
  • Impersonal (theme = nominative): нравится, нужно, можно, жаль + dative experiencer (Мне нравится)
  • Transitive → accusative; animate accusative = genitive (вижу студента / студентов)
  • Coordinated objects share case: вижу студента и учителя
  • Static location: в/на + prepositional (работает в библиотеке); motion: в/на + accusative (идет в библиотеку)
- Partial genitive: немного/чуть + genitive singular
- Comparison: лучше/хуже + genitive (лучше меня); лучше, чем + nominative
- Numeral one: один/одна/одne + matching noun (одна книга, not один книга)
- Numerals: 2–4 + genitive singular (два студента); 5+ + genitive plural (пять книг); \
5+ numeral stays nominative (пять, not пяти)
- Negation: не + verb + direct object → genitive/partial genitive (не купил хлеба)
- Never leave nouns in dictionary nominative when syntax requires another case.
- Double-object verbs: сказать/дать/писать + dative person + accusative thing (сказал другу правду).
- Relative pronouns agree with antecedent gender/number (книга, которая — not который).
- Avoid calques: take place → происходить (not принимать место); take a photo → фотографировать.
- Formal phrases: в соответствии с + instrumental; на основе + genitive; в настоящее время (invariable).
- Coordinated subjects take plural verb: Он и она работают."""

_SLAVIC_GRAMMAR_UK = """

Ukrainian morphology (mandatory — Read Ukrainian! 14.7 / 16.4–16.5):
- Full agreement in gender, number, and case for adjectives, pronouns, and nouns.
- Prepositions (see ukrainianlanguage.org.uk case charts):
  • Genitive: без, біля, від, для, до, з/із/зі (from), замість, після, серед, проти, навколо
  • Dative: завдяки, к, наперекір, всупереч
  • Accusative: про, через, в/у/на (motion), за (thanks/exchange), крізь
  • Instrumental: з/із/зі (with), за (static behind), під/над/перед/між (static position)
  • Locative: в/у/на (static in/on), при, по (along/about)
  • у+є → possessed item nominative; немає/багато/кілька → genitive plural
- Numerals: 2–4 + genitive singular; 5+ + genitive plural; 5+ numeral unchanged
- Negation: не/ні + verb → object genitive (не написали листа)
- Partial genitive: трохи/дещо + genitive
- Comparison: краще/гірше + genitive (краще мене); краще, ніж + nominative
- Animate accusative = genitive form (бачу студента / студентів)
- Numeral one: один/одна + noun agrees (одна книжка)
- Verbs: dative to person (допомагати кому, дякувати кому); \
write/say/give thing → accusative; genitive (хотіти, боятися, шукати); \
instrumental profession (працювати інженером), NOT location (працює в бібліотеці); \
займатися + instrumental reflexive (собою); \
подобається + dative experiencer (Мені) + nominative theme; transitive → accusative; \
negation → genitive object (не написали листа).
- Avoid calques: take place → відбуватися; double-object verbs like сказати кому що."""


def _system_prompt_for(to_code: str) -> str:
    tgt = (to_code or "").strip().lower()
    if tgt == "ru":
        return _TRANSLATOR_SYSTEM + _SLAVIC_GRAMMAR_RU
    if tgt == "uk":
        return _TRANSLATOR_SYSTEM + _SLAVIC_GRAMMAR_UK
    return _TRANSLATOR_SYSTEM


def _pair_specific_hints(from_code: str, to_code: str) -> str:
    """语言对补充说明（文学/比喻类文本常见方向）。"""
    src = (from_code or "").strip().lower()
    tgt = (to_code or "").strip().lower()
    hints: list[str] = []
    if src in ("zh", "zt") and tgt in ("ru", "uk"):
        hints.append(
            "Chinese→Slavic: chengyu, classical allusions, and poetic imagery "
            "need idiomatic target-language equivalents, not character-by-character "
            "or image-by-image calques."
        )
        hints.append(
            "Pay strict attention to Russian/Ukrainian case government, "
            "adjective–noun agreement, and verb conjugation in every sentence—not only "
            "for terminology placeholders."
        )
        hints.append(
            "Christian religious text (Orthodox / Catholic / Protestant): choose "
            "register by context. Orthodox: Божественная литургия, храм, Богородица, "
            "Причастие, Пасха, патриарх. Catholic: месса, папа римский, кардинал, "
            "Ватикан; still молиться (not делать молитву). Protestant: пастор, "
            "проповедь, церковь. Capitalize theonyms and fixed phrases (Слава Богу, "
            "Господи, помилуй, Иисус Христос). 福音 = Евангелие (Gospel), not "
            "'good news'."
        )
    elif tgt in ("zh", "zt") and src in ("ru", "uk", "en", "fr", "de", "es"):
        hints.append(
            "When the source uses culture-specific idioms or figurative speech, "
            "render the pragmatic meaning in natural Simplified Chinese."
        )
    elif src == "en" or tgt == "en":
        hints.append(
            "English phrasal verbs, idioms, and figurative compounds require "
            "sense-based translation, not literal decomposition."
        )
    return "\n".join(hints)


def _build_prompt(
    text: str,
    from_code: str,
    to_code: str,
    *,
    prev_src_tail: str = "",
    prev_tgt_tail: str = "",
) -> str:
    target = _qwen_lang(to_code)
    src = (from_code or "").strip().lower()
    if not src or src == "auto":
        source_hint = "Detect the source language automatically."
    else:
        source_hint = f"The source language is {_qwen_lang(src)}."
    pair_hint = _pair_specific_hints(from_code, to_code)
    extra = f"\n{pair_hint}\n" if pair_hint else "\n"
    continuity = ""
    if prev_src_tail.strip() and prev_tgt_tail.strip():
        continuity = (
            "\nContinuity — the passage below continues immediately after this "
            "(keep names, terms, and register consistent):\n"
            f"Previous source ending:\n{prev_src_tail.strip()}\n"
            f"Previous translation ending:\n{prev_tgt_tail.strip()}\n"
        )
    return (
        f"{source_hint}\n"
        f"Translate into {target}.{extra}{continuity}\n"
        f"Text:\n{text}"
    )


_CONTEXT_TAIL_CHARS = 420
_CJK_CHAR = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def _cjk_ratio(text: str) -> float:
    t = text or ""
    if not t:
        return 0.0
    return len(_CJK_CHAR.findall(t)) / len(t)


def _num_predict_for_chunk(chunk: str, to_code: str) -> int:
    base = int(_setting("OLLAMA_NUM_PREDICT", "2048") or "2048")
    cap = int(_setting("OLLAMA_NUM_PREDICT_MAX", "8192") or "8192")
    cap = max(2048, min(cap, 16384))
    n = len(chunk or "")
    if _cjk_ratio(chunk) >= 0.25 or (to_code or "").strip().lower() in ("ru", "uk"):
        est = int(n * 2.0) + 512
    else:
        est = int(n * 1.35) + 384
    return max(base, min(cap, est))


def _looks_truncated(src: str, out: str) -> bool:
    src = (src or "").strip()
    out = (out or "").strip()
    if not src:
        return False
    if not out:
        return True
    if len(src) > 300 and len(out) < len(src) * 0.12:
        return True
    if len(src) > 600 and len(out) < len(src) * 0.22:
        return True
    src_end = bool(re.search(r"[。！？.!?…][\"'»」)\]}\s]*$", src))
    out_end = bool(re.search(r"[.!?…][\"'»」)\]}\s]*$", out))
    if src_end and not out_end and len(out) < len(src) * 0.55:
        return True
    return False


def _tail_context(text: str, n: int = _CONTEXT_TAIL_CHARS) -> str:
    t = (text or "").strip()
    if len(t) <= n:
        return t
    return t[-n:].lstrip()


def _join_chunk_outputs(parts: list[str], source: str) -> str:
    cleaned = [p for p in parts if (p or "").strip()]
    if not cleaned:
        return ""
    if re.search(r"\n\s*\n", source or ""):
        return "\n\n".join(cleaned)
    return "\n".join(cleaned)


def _split_at_sentence_boundary(text: str, max_chunk: int) -> list[str]:
    """在句末标点处切分超长块，避免半句截断。"""
    t = (text or "").strip()
    if len(t) <= max_chunk:
        return [t] if t else []
    seps = "。！？.!?…"
    out: list[str] = []
    buf = ""
    i = 0
    while i < len(t):
        ch = t[i]
        buf += ch
        at_sep = ch in seps
        if at_sep and len(buf) >= int(max_chunk * 0.45):
            if buf.strip():
                out.append(buf.strip())
            buf = ""
        elif len(buf) >= max_chunk:
            cut = -1
            for j in range(len(buf) - 1, int(max_chunk * 0.3), -1):
                if buf[j] in seps:
                    cut = j + 1
                    break
            if cut > 0:
                out.append(buf[:cut].strip())
                buf = buf[cut:]
            else:
                out.append(buf[:max_chunk].strip())
                buf = buf[max_chunk:]
        i += 1
    if buf.strip():
        out.append(buf.strip())
    return out


def _split_llm_chunks(text: str) -> list[str]:
    """
    按段落/长度分块，避免逐行翻译丢失比喻与上下文。
    短于 OLLAMA_MAX_CHUNK_CHARS 的整段一次送入模型。
    """
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return []
    max_chunk = int(_setting("OLLAMA_MAX_CHUNK_CHARS", "3500") or "3500")
    max_chunk = max(800, min(max_chunk, 12000))

    if len(raw) <= max_chunk:
        return [raw]

    paragraphs = re.split(r"\n\s*\n", raw)
    chunks: list[str] = []
    buf = ""

    def _flush() -> None:
        nonlocal buf
        if buf.strip():
            chunks.append(buf)
        buf = ""

    def _split_oversized(block: str) -> list[str]:
        block = block.strip("\n")
        if len(block) <= max_chunk:
            return [block] if block.strip() else []
        try:
            from bulk_text import prepare_long_translation_input

            split = prepare_long_translation_input(block, for_llm=True)
        except ImportError:
            split = block
        parts = split.split("\n")
        out: list[str] = []
        acc = ""
        for part in parts:
            if not part.strip():
                continue
            if len(part) > max_chunk:
                if acc.strip():
                    out.append(acc)
                    acc = ""
                out.extend(_split_at_sentence_boundary(part, max_chunk))
                continue
            candidate = f"{acc}\n{part}" if acc else part
            if len(candidate) <= max_chunk:
                acc = candidate
            else:
                if acc.strip():
                    out.append(acc)
                acc = part
        if acc.strip():
            out.append(acc)
        return out

    for para in paragraphs:
        para = para.strip("\n")
        if not para.strip():
            continue
        if len(para) > max_chunk:
            _flush()
            chunks.extend(_split_oversized(para))
            continue
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) <= max_chunk:
            buf = candidate
        else:
            _flush()
            buf = para
    _flush()
    return chunks if chunks else [raw[:max_chunk]]


def _api_generate(
    prompt: str,
    *,
    to_code: str = "",
    num_predict: int | None = None,
) -> str:
    temperature = float(_setting("OLLAMA_TEMPERATURE", "0.35") or "0.35")
    if num_predict is None:
        num_predict = int(_setting("OLLAMA_NUM_PREDICT", "2048") or "2048")
    top_p = float(_setting("OLLAMA_TOP_P", "0.92") or "0.92")
    payload: dict[str, Any] = {
        "model": model_name(),
        "prompt": prompt,
        "system": _system_prompt_for(to_code),
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            "top_p": top_p,
        },
    }
    request = Request(
        f"{base_url()}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=600) as response:
        data = json.loads(response.read().decode("utf-8"))
    return (data.get("response") or "").strip()


def check_available() -> None:
    request = Request(f"{base_url()}/api/tags", method="GET")
    with urlopen(request, timeout=5):
        pass


def ollama_error_hint(exc: BaseException | None = None) -> str:
    model = model_name()
    extra = f"\n\n错误: {exc}" if exc else ""
    return (
        "无法连接本地 Ollama 翻译引擎。\n\n"
        "请确认：\n"
        "1. Ollama 已安装并在运行（系统托盘有图标）\n"
        f"2. 已下载模型：ollama pull {model}\n"
        "3. 本机防火墙未阻止 127.0.0.1:11434"
        f"{extra}"
    )


class OllamaTranslation:
    """与 argostranslate.translate.ITranslation 用法兼容：.translate(text) -> str"""

    def __init__(self, from_code: str, to_code: str) -> None:
        self.from_code = (from_code or "").strip().lower()
        self.to_code = (to_code or "").strip().lower()

    def translate(
        self,
        text: str,
        *,
        on_progress: Callable[[str], None] | None = None,
    ) -> str:
        if not (text or "").strip():
            return text or ""
        prepared = _prepare_input(text)
        chunks = _split_llm_chunks(prepared)
        total = len(chunks)
        out: list[str] = []
        prev_src_tail = ""
        prev_tgt_tail = ""

        def _emit_partial() -> None:
            if on_progress is None or not out:
                return
            merged = _join_chunk_outputs(out, prepared)
            if total > 1 and len(out) < total:
                merged = (
                    f"{merged}\n\n— 已译 {len(out)}/{total} 段，继续中…"
                )
            on_progress(merged)

        for idx, chunk in enumerate(chunks):
            if not chunk.strip():
                out.append("")
                continue
            prompt = _build_prompt(
                chunk,
                self.from_code,
                self.to_code,
                prev_src_tail=prev_src_tail,
                prev_tgt_tail=prev_tgt_tail,
            )
            predict = _num_predict_for_chunk(chunk, self.to_code)
            raw = _api_generate(prompt, to_code=self.to_code, num_predict=predict)
            if _looks_truncated(chunk, raw):
                half = max(400, len(chunk) // 2)
                subchunks = _split_at_sentence_boundary(chunk, half) or [chunk]
                if len(subchunks) > 1:
                    sub_out: list[str] = []
                    for sub in subchunks:
                        sub_prompt = _build_prompt(
                            sub,
                            self.from_code,
                            self.to_code,
                            prev_src_tail=prev_src_tail,
                            prev_tgt_tail=prev_tgt_tail,
                        )
                        sub_raw = _api_generate(
                            sub_prompt,
                            to_code=self.to_code,
                            num_predict=_num_predict_for_chunk(sub, self.to_code),
                        )
                        sub_out.append(sub_raw)
                        prev_src_tail = _tail_context(sub)
                        prev_tgt_tail = _tail_context("\n".join(sub_out))
                    raw = "\n".join(sub_out)
                else:
                    raw = _api_generate(
                        prompt,
                        to_code=self.to_code,
                        num_predict=min(
                            int(_setting("OLLAMA_NUM_PREDICT_MAX", "8192") or "8192"),
                            predict * 2,
                        ),
                    )
            try:
                from translation_quality import (
                    postprocess_translation_target,
                    sanitize_llm_translation_output,
                )

                raw = sanitize_llm_translation_output(raw)
                if self.to_code in ("ru", "uk"):
                    raw = postprocess_translation_target(
                        raw,
                        self.to_code,
                        source_text=chunk,
                        source_lang_code=self.from_code,
                    )
            except ImportError:
                raw = strip_model_chatter(raw)
            out.append(raw)
            prev_src_tail = _tail_context(chunk)
            prev_tgt_tail = _tail_context(raw)
            _emit_partial()

        if not out:
            return ""
        if len(chunks) == 1:
            return out[0] if out else ""
        return _join_chunk_outputs(out, prepared)


def _prepare_input(text: str) -> str:
    try:
        from translation_quality import sanitize_source_text

        text = sanitize_source_text(text, for_llm=True)
    except ImportError:
        pass
    try:
        from bulk_text import prepare_long_translation_input

        return prepare_long_translation_input(text, for_llm=True)
    except ImportError:
        return text


def make_translation(from_code: str, to_code: str) -> OllamaTranslation:
    src = (from_code or "").strip().lower()
    tgt = (to_code or "").strip().lower()
    if not src or not tgt:
        raise ValueError("语言 code 无效")
    if src == tgt:
        raise ValueError("源语言与目标语言相同")
    return OllamaTranslation(src, tgt)


def load_languages() -> list[Any]:
    """返回与 language_catalog.Language 兼容的语言列表（Ollama 支持任意语言对）。"""
    from language_catalog import Language

    langs = [Language(code, name) for code, name in _OLLAMA_UI_LANGS]
    en_index = next((i for i, l in enumerate(langs) if l.code == "en"), None)
    if en_index is not None and en_index > 0:
        english = langs.pop(en_index)
        langs.sort(key=lambda x: x.name)
        langs.insert(0, english)
    else:
        langs.sort(key=lambda x: x.name)
        if en_index is None:
            langs.insert(0, Language("en", "English"))
    return langs


def strip_model_chatter(text: str) -> str:
    """去掉模型偶发的前缀说明。"""
    t = (text or "").strip()
    for prefix in (
        "Translation:",
        "译文：",
        "翻译：",
        "Translated text:",
        "Natural translation:",
        "更自然的翻译：",
        "意译：",
    ):
        if t.startswith(prefix):
            t = t[len(prefix) :].strip()
    return t
