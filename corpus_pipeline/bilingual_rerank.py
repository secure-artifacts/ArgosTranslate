"""跨语言 embedding 相似度（sentence-transformers，可选依赖）。"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

_CYR = re.compile(r"[А-Яа-яЁё]")
_HAN = re.compile(r"[\u4e00-\u9fff]")

_MODEL_CANDIDATES = (
    "intfloat/multilingual-e5-small",
    "sentence-transformers/LaBSE",
    "BAAI/bge-m3",
)


@lru_cache(maxsize=1)
def _load_model() -> Any | None:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    for name in _MODEL_CANDIDATES:
        try:
            return SentenceTransformer(name)
        except Exception:
            continue
    return None


def model_name() -> str:
    m = _load_model()
    if m is None:
        return "none"
    return getattr(m, "model_name_or_path", "") or "loaded"


def _prep_e5(text: str, model_id: str) -> str:
    t = (text or "").strip()[:800]
    low = (model_id or "").lower()
    if "e5" in low:
        return f"passage: {t}"
    return t


def _cosine(a, b) -> float:
    import numpy as np

    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _fallback_similarity(ru_text: str, zh_text: str) -> float:
    """无 embedding 模型时的轻量回退（字符脚本 + 长度结构）。"""
    ru, zh = ru_text or "", zh_text or ""
    if not ru or not zh:
        return 0.0
    cyr = len(_CYR.findall(ru)) / max(len(ru), 1)
    han = len(_HAN.findall(zh)) / max(len(zh), 1)
    script_ok = 0.5 if cyr > 0.25 and han > 0.12 else 0.2
    lr = len(ru) / max(len(zh), 1)
    lr = lr if lr <= 1 else 1 / lr
    struct = 1.0 if 0.3 <= lr <= 3.0 else 0.35
    return round(min(1.0, 0.4 * script_ok + 0.6 * struct * 0.5), 4)


def cross_lingual_similarity(ru_text: str, zh_text: str) -> float:
    model = _load_model()
    if model is None:
        return _fallback_similarity(ru_text, zh_text)
    mid = str(getattr(model, "model_name_or_path", ""))
    texts = [
        _prep_e5(ru_text, mid),
        _prep_e5(zh_text, mid),
    ]
    try:
        embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return round(max(0.0, min(1.0, _cosine(embs[0], embs[1]))), 4)
    except Exception:
        return _fallback_similarity(ru_text, zh_text)


def title_similarity(ru_title: str, zh_title: str) -> float:
    if not (ru_title or "").strip() or not (zh_title or "").strip():
        return 0.0
    return cross_lingual_similarity(ru_title, zh_title)


def body_similarity(ru_body: str, zh_body: str) -> float:
    ru = (ru_body or "")[:1200]
    zh = (zh_body or "")[:1200]
    return cross_lingual_similarity(ru, zh)


def combined_ru_zh_similarity(
    *,
    ru_title: str,
    zh_title: str,
    ru_body: str,
    zh_body: str,
) -> dict[str, float]:
    t_sim = title_similarity(ru_title, zh_title)
    b_sim = body_similarity(ru_body, zh_body)
    lead_ru = (ru_body or "").split("\n\n")[0][:400]
    lead_zh = (zh_body or "").split("\n\n")[0][:400]
    lead_sim = cross_lingual_similarity(lead_ru, lead_zh)
    combined = round(0.45 * t_sim + 0.40 * b_sim + 0.15 * lead_sim, 4)
    return {
        "embedding_title_similarity": t_sim,
        "embedding_body_similarity": b_sim,
        "embedding_lead_similarity": lead_sim,
        "embedding_combined": combined,
        "embedding_backend": model_name(),
    }
