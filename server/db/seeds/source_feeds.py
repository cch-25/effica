"""Reviewed, bounded first-party feeds used by scheduled metadata ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ScheduledRSSSource:
    name: str
    home_url: str
    feed_url: str
    policy_reference: str
    bootstrap: bool = False


# Keep one broad feed per publisher until the adapter schema supports multiple
# RSS adapters per source. The previous entries both pointed at politics,
# which made every other public topic structurally sparse. Scheduled ingestion
# hydrates each bounded feed item from its approved publisher domain so the
# analysis pipeline receives article bodies instead of RSS summaries.
SCHEDULED_RSS_SOURCES = (
    ScheduledRSSSource(
        "뉴시스",
        "https://www.newsis.com/",
        "https://nwww.newsis.com/RSS/sokbo.xml",
        "https://nwww.newsis.com/RSS/",
    ),
    ScheduledRSSSource(
        "이투데이",
        "https://www.etoday.co.kr/",
        "https://rss.etoday.co.kr/eto/etoday_news_all.xml",
        "https://www.etoday.co.kr/rss/",
    ),
    ScheduledRSSSource(
        "금융위원회",
        "https://www.fsc.go.kr/",
        "https://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111",
        "https://www.fsc.go.kr/ut060101",
    ),
    ScheduledRSSSource(
        "행정안전부",
        "https://www.mois.go.kr/",
        "https://www.mois.go.kr/gpms/view/jsp/rss/rss.jsp?ctxCd=1012",
        "https://www.mois.go.kr/frt/sub/a08/rss/screen.do",
        bootstrap=True,
    ),
    ScheduledRSSSource(
        "중소벤처기업부",
        "https://www.mss.go.kr/",
        "https://mss.go.kr/rss/smba/board/86.do",
        "https://www.mss.go.kr/site/smba/contents/view.do?menuCd=20905000000002024122902&siteCd=smba",
        bootstrap=True,
    ),
    ScheduledRSSSource(
        "농림축산식품부",
        "https://www.mafra.go.kr/",
        "https://www.mafra.go.kr/bbs/home/792/rssList.do?row=50",
        "https://www.mafra.go.kr/home/5327/subview.do",
        bootstrap=True,
    ),
    ScheduledRSSSource(
        "국가데이터처",
        "https://mods.go.kr/",
        "https://mods.go.kr/board.es?mid=a10301010000&bid=a103010100&act=rss",
        "https://mods.go.kr/menu.es?mid=a10707000000",
        bootstrap=True,
    ),
    ScheduledRSSSource(
        "관세청",
        "https://www.customs.go.kr/",
        "https://www.customs.go.kr/kcs/selectBoardRss.do?mi=15265&bbsId=1362",
        "https://www.customs.go.kr/kcs/selectBoardRssList.do?mi=7424",
        bootstrap=True,
    ),
)


def _canonical_home(value: str) -> str:
    return f"{value.rstrip('/')}/"


_SOURCES_BY_HOME = {
    _canonical_home(source.home_url): source for source in SCHEDULED_RSS_SOURCES
}
SCHEDULED_RSS_FEEDS = {
    source.home_url: source.feed_url for source in SCHEDULED_RSS_SOURCES
}
# Eight scheduled publishers run every 15 minutes with a polite per-source
# request rate. Thirty fully hydrated articles per source keeps one cycle well
# inside the schedule while still providing a broad, fresh homepage corpus.
SCHEDULED_RSS_MAX_ITEMS = 30


def bootstrap_scheduled_rss_sources() -> tuple[ScheduledRSSSource, ...]:
    return tuple(source for source in SCHEDULED_RSS_SOURCES if source.bootstrap)


def scheduled_rss_config(
    source_home_url: str, *, policy_reference: str | None = None
) -> dict[str, Any] | None:
    source = _SOURCES_BY_HOME.get(_canonical_home(source_home_url))
    if source is None:
        return None
    article_domain = (urlsplit(source.home_url).hostname or "").lower().removeprefix(
        "www."
    )
    return {
        "scheduled": True,
        "feed_url": source.feed_url,
        "hydrate_article_links": True,
        "require_hydrated_body": True,
        "hydrate_min_body_chars": 100_000,
        "max_hydration_fetches": SCHEDULED_RSS_MAX_ITEMS,
        "allowed_domains": [article_domain],
        "metadata_only": False,
        "max_items": SCHEDULED_RSS_MAX_ITEMS,
        "allow_empty_result": False,
        "policy_reference": policy_reference or source.policy_reference,
    }


__all__ = [
    "SCHEDULED_RSS_FEEDS",
    "SCHEDULED_RSS_MAX_ITEMS",
    "SCHEDULED_RSS_SOURCES",
    "ScheduledRSSSource",
    "bootstrap_scheduled_rss_sources",
    "scheduled_rss_config",
]
