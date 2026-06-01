"""俄语译后润色（新闻/外交母语化）。"""
from __future__ import annotations

from native_fluency_pipeline import post_edit_native


def post_edit_ru(
    text: str,
    *,
    source_text: str | None = None,
    domain: str | None = None,
) -> str:
    return post_edit_native(text, "ru", source_text=source_text, domain=domain)
