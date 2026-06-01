from corpus_pipeline.fetchers.opus_local import OpusLocalFetcher
from corpus_pipeline.fetchers.ted_local import TedLocalFetcher
from corpus_pipeline.fetchers.ukraine_ua import UkraineUaFetcher
from corpus_pipeline.fetchers.un_org import UnOrgFetcher

FETCHERS = {
    "ukraine_ua": UkraineUaFetcher,
    "un": UnOrgFetcher,
    "opus": OpusLocalFetcher,
    "ted": TedLocalFetcher,
}
