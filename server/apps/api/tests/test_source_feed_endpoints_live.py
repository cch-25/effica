from __future__ import annotations

import asyncio
import os
import socket
from urllib.parse import urlsplit

import httpx
import pytest

from apps.api.app.domains.content import RSSAdapter
from apps.worker.worker.handlers.base import HandlerContext
from apps.worker.worker.handlers.crawl import handle
from apps.worker.worker.source_fetcher import SourceFetchService
from db.seeds.source_feeds import scheduled_publisher_sources, scheduled_rss_config


def _article_host_is_allowed(article_url: str, allowed_domains: object) -> bool:
    host = (urlsplit(article_url).hostname or "").lower().rstrip(".")
    host = host.removeprefix("www.")
    if not isinstance(allowed_domains, (list, tuple, set)):
        return False
    for item in allowed_domains:
        domain = str(item).strip().lower().rstrip(".").removeprefix("www.").lstrip(".")
        if domain and (host == domain or host.endswith(f".{domain}")):
            return True
    return False


@pytest.mark.parametrize(
    ("article_url", "expected"),
    [
        ("https://ohmynews.com/article", True),
        ("https://star.ohmynews.com/article", True),
        ("https://www.ohmynews.com/article", True),
        ("https://notohmynews.com/article", False),
        ("https://ohmynews.com.evil.test/article", False),
    ],
)
def test_article_host_allowlist_uses_dns_label_boundaries(
    article_url: str, expected: bool
) -> None:
    assert _article_host_is_allowed(article_url, ["ohmynews.com"]) is expected


async def _resolve_public_ipv4(host: str, port: int) -> object:
    return await asyncio.to_thread(
        socket.getaddrinfo,
        host,
        port,
        socket.AF_INET,
        socket.SOCK_STREAM,
    )


@pytest.mark.skipif(
    os.getenv("EFFICA_RUN_LIVE_SOURCE_FEEDS") != "1",
    reason="set EFFICA_RUN_LIVE_SOURCE_FEEDS=1 for publisher endpoint checks",
)
def test_all_publisher_discovery_feeds_are_live_and_parseable() -> None:
    headers = {"user-agent": "Effica source endpoint verification/1.0"}

    with httpx.Client(headers=headers, follow_redirects=True, timeout=20) as client:
        for source in scheduled_publisher_sources():
            response = client.get(source.feed_url)
            response.raise_for_status()
            config = scheduled_rss_config(source.home_url)
            assert config is not None
            articles = RSSAdapter(source.name, config).parse(response.content)

            assert articles, source.name
            assert all(article.title for article in articles)
            if source.feed_format == "news_sitemap":
                assert all(article.published_at is not None for article in articles)
            assert all(
                _article_host_is_allowed(article.url, config["allowed_domains"])
                for article in articles
            )
            print(
                f"{source.name}: status={response.status_code} "
                f"format={source.feed_format} items={len(articles)} "
                f"endpoint={source.feed_url}"
            )


@pytest.mark.skipif(
    os.getenv("EFFICA_RUN_LIVE_SOURCE_FEEDS") != "1",
    reason="set EFFICA_RUN_LIVE_SOURCE_FEEDS=1 for publisher endpoint checks",
)
def test_chosun_first_article_hydrates_through_worker_transport() -> None:
    source = next(
        item for item in scheduled_publisher_sources() if item.name == "조선일보"
    )
    config = scheduled_rss_config(source.home_url)
    assert config is not None

    async def scenario() -> None:
        service = SourceFetchService(
            resolver=_resolve_public_ipv4,
            max_retries=0,
            timeout_seconds=20,
        )
        result = await handle(
            {
                "source_id": "live-chosun",
                "url": source.feed_url,
                "source_type": "RSS",
                "mode": "live",
                "policy_status": "APPROVED",
                "robots_status": "APPROVED",
                "terms_status": "APPROVED",
                "config": {
                    **config,
                    "max_items": 1,
                    "max_hydration_fetches": 1,
                    "timeout_seconds": 20,
                },
            },
            HandlerContext(services={"source_fetcher": service}),
        )
        assert len(result.value["articles"]) == 1
        assert result.value["stats"]["hydration_attempted"] == 1
        assert result.value["stats"]["hydration_succeeded"] == 1
        assert result.value["articles"][0]["content"].strip()
        print(
            "조선일보: worker_hydration=success "
            f"article={result.value['articles'][0]['url']}"
        )

    asyncio.run(scenario())
