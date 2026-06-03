"""语料管线路径与来源配置。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "corpus"
RAW = DATA / "raw"
ALIGNED = DATA / "aligned"
TM_DB = DATA / "tm" / "corpus_tm.sqlite"
GLOSSARY_DIR = ROOT / "data" / "glossary" / "corpus"
GLOSSARY_PENDING = ROOT / "data" / "glossary" / "pending"
GLOSSARY_OUT = GLOSSARY_DIR
REPORTS = DATA / "reports"
TM_LOG = REPORTS / "tm_hits.log"
QUARANTINE_DIR = DATA / "quarantine"
CANDIDATE_PAIRS_DIR = DATA / "candidate_pairs"
MANUAL_REVIEW_DIR = DATA / "manual_review_queue"
PENDING_TM_DIR = DATA / "pending_tm"
GOLD_CORPUS_DIR = DATA / "gold_corpus"
TRANSLATION_EVAL_DIR = DATA / "translation_eval"
LOGS_DIR = ROOT / "logs"

LOCKED_GLOSSARY_DIR = ROOT / "data" / "glossary" / "locked_glossary"

UKRAINE_UA_ZH = "https://ukraine.ua/zh/"
UKRAINE_UA_UK = "https://ukraine.ua/"

UN_BASE_RU = "https://www.un.org/ru/"
UN_BASE_ZH = "https://www.un.org/zh/"

OPUS_LANG_PAIRS = (("ru", "zh"), ("uk", "zh"))

USER_AGENT = (
    "ArgosTranslate-CorpusBot/1.0 (+local research; contact: portable install)"
)

FETCH_DELAY_SEC = 1.0
MAX_PAGES_PER_SOURCE = 40
UKRAINE_FULL_CAP = 800
UN_FULL_CAP = 400

# Ukraine.ua：默认 offline；Wayback 已停用灌库（设 UKRAINE_UA_ALLOW_WAYBACK=1 才可用）
UKRAINE_UA_FETCH_MODE = os.environ.get("UKRAINE_UA_FETCH_MODE", "offline")
UKRAINE_UA_ALLOW_WAYBACK = os.environ.get("UKRAINE_UA_ALLOW_WAYBACK", "0").strip() in (
    "1",
    "true",
    "yes",
)
UKRAINE_WAYBACK_PREFIX = "https://web.archive.org/web/2024/"
UKRAINE_OFFLINE_DIR = RAW / "ukraine_ua" / "offline_html"

# 语料质量：低于此分的句对进入 quarantine，不入 TM
CORPUS_QUALITY_MIN = float(os.environ.get("CORPUS_QUALITY_MIN", "0.52"))
LOW_CONFIDENCE_THRESHOLD = 0.70

# UN 两阶段配对
RECALL_MIN_DELTA_SEC = int(os.environ.get("RECALL_MIN_DELTA_SEC", "0"))
RECALL_MAX_DELTA_SEC = int(os.environ.get("RECALL_MAX_DELTA_SEC", "300"))
MIN_PAIR_CONFIDENCE_TM = float(os.environ.get("MIN_PAIR_CONFIDENCE_TM", "0.80"))
RECALL_MIN_TOPIC_HITS = int(os.environ.get("RECALL_MIN_TOPIC_HITS", "1"))

# 人工白名单入库门槛（article 级）
REVIEW_PAIR_CONF_MIN = float(os.environ.get("REVIEW_PAIR_CONF_MIN", "0.90"))
REVIEW_TOPIC_HITS_MIN = int(os.environ.get("REVIEW_TOPIC_HITS_MIN", "3"))
REVIEW_TM_PURITY_MIN = float(os.environ.get("REVIEW_TM_PURITY_MIN", "0.75"))

# UN 默认不自动灌 TM（仅 candidate + manual_review）
UN_AUTO_TM = os.environ.get("UN_AUTO_TM", "0").strip() in ("1", "true", "yes")

# 用户反馈闭环（GUI 采纳 / 低分自动入队）
USER_FEEDBACK_SOURCE = "user"
USER_PROMOTE_TM_PURITY_MIN = float(os.environ.get("USER_PROMOTE_TM_PURITY_MIN", "0.75"))
USER_LOCK_TERM_PURITY_MIN = float(os.environ.get("USER_LOCK_TERM_PURITY_MIN", "0.82"))
USER_AUTO_REVIEW_QUEUE = os.environ.get("ARGOS_AUTO_REVIEW_QUEUE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
