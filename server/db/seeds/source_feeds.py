"""Bounded first-party feeds with explicit policy-review bootstrap metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ScheduledRSSSource:
    name: str
    home_url: str
    feed_url: str
    policy_reference: str
    bootstrap: bool = False
    approve_on_bootstrap: bool = False
    publisher: bool = False
    feed_format: Literal["rss", "news_sitemap"] = "rss"
    review_note: str | None = None


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
        "https://nwww.newsis.com/contents/copyright",
        bootstrap=True,
        publisher=True,
        review_note=(
            "공식 저작권 규약이 비영리 정보서비스도 사전 서면 허가 대상으로 "
            "명시하므로 서비스 수집 승인이 필요합니다."
        ),
    ),
    ScheduledRSSSource(
        "이투데이",
        "https://www.etoday.co.kr/",
        "https://rss.etoday.co.kr/eto/etoday_news_all.xml",
        "https://www.etoday.co.kr/rss/",
        bootstrap=True,
        approve_on_bootstrap=True,
        publisher=True,
    ),
    ScheduledRSSSource(
        "조선일보",
        "https://www.chosun.com/",
        "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml",
        "https://rssplus.chosun.com/",
        bootstrap=True,
        publisher=True,
        review_note=(
            "공식 RSS 안내가 개인 구독만 허용하고 상업적 이용은 사전 문의 대상으로 "
            "명시하므로 서비스 수집 승인이 필요합니다."
        ),
    ),
    ScheduledRSSSource(
        "문화일보",
        "https://www.munhwa.com/",
        "https://www.munhwa.com/sitemap/latest-articles",
        "https://www.munhwa.com/robots.txt",
        bootstrap=True,
        publisher=True,
        feed_format="news_sitemap",
        review_note=(
            "공식 robots.txt가 최신 기사 사이트맵을 공개하지만 서비스 내 기사 본문 "
            "수집 허락은 별도로 확인해야 합니다."
        ),
    ),
    ScheduledRSSSource(
        "세계일보",
        "https://www.segye.com/",
        "https://www.segye.com/sitemap_day0.xml",
        "https://www.segye.com/robots.txt",
        bootstrap=True,
        publisher=True,
        feed_format="news_sitemap",
        review_note=(
            "기존 RSS 호스트가 현재 502를 반환해 공식 일간 사이트맵을 사용합니다. "
            "서비스 내 기사 본문 수집 허락은 별도로 확인해야 합니다."
        ),
    ),
    ScheduledRSSSource(
        "경향신문",
        "https://www.khan.co.kr/",
        "https://www.khan.co.kr/rss/rssdata/total_news.xml",
        "https://www.khan.co.kr/help/help_rss.html",
        bootstrap=True,
        publisher=True,
        review_note=(
            "공식 RSS 안내가 개인 구독으로 범위를 한정하고 다수 공유나 영리 이용은 "
            "사전 허락 대상으로 명시하므로 서비스 수집 승인이 필요합니다."
        ),
    ),
    ScheduledRSSSource(
        "한겨레",
        "https://www.hani.co.kr/",
        "https://www.hani.co.kr/rss/",
        "https://www.hani.co.kr/robots.txt",
        bootstrap=True,
        publisher=True,
        review_note=(
            "공식 RSS와 기사 경로의 robots 허용은 확인됐지만 서비스 내 기사 본문 "
            "수집 허락 근거는 별도로 확인해야 합니다."
        ),
    ),
    ScheduledRSSSource(
        "오마이뉴스",
        "https://www.ohmynews.com/",
        "https://rss.ohmynews.com/rss/ohmynews.xml",
        "https://www.ohmynews.com/NWS_Web/Help/srv/h_help_rss.aspx",
        bootstrap=True,
        publisher=True,
        review_note=(
            "공식 RSS 안내가 개인 이용으로 한정하고 무단 배포와 재RSS를 금지하므로 "
            "서비스 수집 승인이 필요합니다."
        ),
    ),
    ScheduledRSSSource(
        "동아일보",
        "https://www.donga.com/",
        "https://rss.donga.com/total.xml",
        "https://rss.donga.com/",
        bootstrap=True,
        publisher=True,
        review_note=(
            "공식 RSS 안내가 개인 이용자의 비상업 사용으로 한정하므로 서비스 수집 "
            "승인이 필요합니다."
        ),
    ),
    ScheduledRSSSource(
        "중앙일보",
        "https://www.joongang.co.kr/",
        "https://www.joongang.co.kr/sitemap/latest-articles",
        "https://www.joongang.co.kr/robots.txt",
        bootstrap=True,
        publisher=True,
        feed_format="news_sitemap",
        review_note=(
            "기존 RSS 서비스가 종료되어 공식 최신 기사 사이트맵을 사용합니다. "
            "서비스 내 기사 본문 수집 허락은 별도로 확인해야 합니다."
        ),
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
        approve_on_bootstrap=True,
    ),
    ScheduledRSSSource(
        "중소벤처기업부",
        "https://www.mss.go.kr/",
        "https://mss.go.kr/rss/smba/board/86.do",
        "https://www.mss.go.kr/site/smba/contents/view.do?menuCd=20905000000002024122902&siteCd=smba",
        bootstrap=True,
        approve_on_bootstrap=True,
    ),
    ScheduledRSSSource(
        "농림축산식품부",
        "https://www.mafra.go.kr/",
        "https://www.mafra.go.kr/bbs/home/792/rssList.do?row=50",
        "https://www.mafra.go.kr/home/5327/subview.do",
        bootstrap=True,
        approve_on_bootstrap=True,
    ),
    ScheduledRSSSource(
        "국가데이터처",
        "https://mods.go.kr/",
        "https://mods.go.kr/board.es?mid=a10301010000&bid=a103010100&act=rss",
        "https://mods.go.kr/menu.es?mid=a10707000000",
        bootstrap=True,
        approve_on_bootstrap=True,
    ),
    ScheduledRSSSource(
        "관세청",
        "https://www.customs.go.kr/",
        "https://www.customs.go.kr/kcs/selectBoardRss.do?mi=15265&bbsId=1362",
        "https://www.customs.go.kr/kcs/selectBoardRssList.do?mi=7424",
        bootstrap=True,
        approve_on_bootstrap=True,
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
# A small fresh batch leaves capacity for other publishers and analysis.
SCHEDULED_RSS_MAX_ITEMS = 8


def bootstrap_scheduled_rss_sources() -> tuple[ScheduledRSSSource, ...]:
    return tuple(source for source in SCHEDULED_RSS_SOURCES if source.bootstrap)


def scheduled_publisher_sources() -> tuple[ScheduledRSSSource, ...]:
    return tuple(source for source in SCHEDULED_RSS_SOURCES if source.publisher)


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
        "feed_format": source.feed_format,
        "hydrate_article_links": True,
        "require_hydrated_body": True,
        "hydrate_min_body_chars": 100_000,
        "max_hydration_fetches": SCHEDULED_RSS_MAX_ITEMS,
        "allowed_domains": [article_domain],
        "metadata_only": False,
        "max_items": SCHEDULED_RSS_MAX_ITEMS,
        "max_retries": 0,
        "timeout_seconds": 10,
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
    "scheduled_publisher_sources",
]
