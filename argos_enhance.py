"""
Argos 强化栈（本软件唯一翻译路径，默认开启）。

组件：
  · argos_cpu_tuning      — 多核 CT2 并行
  · argos_inference_tuning — 短/中/长句分档 beam 与解码上限
  · slavic_translation_enhance — 源语整理 + 推理 + 俄/乌后处理入口
  · slavic_idioms / translation_quality — 宗教、口语、变格、搭配
  · argos_quality_guard — 劣质句规则修补 / 必要时单次重译
  · terminology_registry + slavic_to_zh_enhance — 俄/乌→中：专名/军政术语、分轨译名、新闻体中文
  · bidirectional_terminology + zh_to_slavic_enhance — 中→俄/乌：双向术语、外交句式、禁跨轨混用
  · corpus_pipeline + translation_memory — 四向 TM（ru/uk↔zh）、语料采集
"""
from __future__ import annotations

import os


def bootstrap_on_startup() -> None:
    """进程启动时调用一次。"""
    os.environ.setdefault("ARGOS_SLAVIC_ENHANCE", "1")
    os.environ.setdefault("ARGOS_FAST_STARTUP", "1")
    try:
        import argos_cpu_tuning as act

        act.apply_cpu_defaults()
    except ImportError:
        pass


def is_primary_backend() -> bool:
    return True
