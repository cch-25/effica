"""Content ingestion, normalisation and article versioning primitives.

The domain modules deliberately contain no HTTP client or persistence code.  An
adapter receives a fixture (or an already fetched payload) and returns stable
article candidates; the worker/API layer decides how those candidates are
stored.
"""

from .adapters import (
    AdapterType,
    APIAdapter,
    ArticleCandidate,
    CrawlerAdapter,
    RSSAdapter,
    SourceAdapter,
    parse_api_fixture,
    parse_html_fixture,
    parse_rss_fixture,
)
from .canonical import (
    canonicalize_url,
    content_hash,
    normalize_text,
    url_hash,
)
from .policy import CrawlerPolicyError, CrawlerPolicyGuard, SourcePolicy
from .versioning import (
    AnalysisStatus,
    ArticleVersion,
    VersionDecision,
    analysis_is_stale,
    decide_version,
)

__all__ = [
    "AdapterType",
    "APIAdapter",
    "ArticleCandidate",
    "CrawlerAdapter",
    "RSSAdapter",
    "SourceAdapter",
    "parse_api_fixture",
    "parse_html_fixture",
    "parse_rss_fixture",
    "canonicalize_url",
    "url_hash",
    "normalize_text",
    "content_hash",
    "CrawlerPolicyError",
    "CrawlerPolicyGuard",
    "SourcePolicy",
    "AnalysisStatus",
    "ArticleVersion",
    "VersionDecision",
    "decide_version",
    "analysis_is_stale",
]
