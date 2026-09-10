from __future__ import annotations

import os
from urllib.parse import urlsplit

import httpx
import pytest

from apps.api.app.domains.content import RSSAdapter
from db.seeds.source_feeds import scheduled_publisher_sources, scheduled_rss_config


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
                (urlsplit(article.url).hostname or "").lower().removeprefix("www.")
                in config["allowed_domains"]
                for article in articles
            )
            print(
                f"{source.name}: status={response.status_code} "
                f"format={source.feed_format} items={len(articles)} "
                f"endpoint={source.feed_url}"
            )
