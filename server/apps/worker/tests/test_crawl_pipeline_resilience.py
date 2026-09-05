from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from apps.worker.worker.handlers.base import (
    HandlerContext,
    NonRetryableHandlerError,
    RetryableHandlerError,
)
from apps.worker.worker.handlers.crawl import handle
from apps.worker.worker.source_fetcher import (
    SourceFetchError,
    SourceFetchResponse,
    SourceFetchService,
)
from db.seeds.source_feeds import SCHEDULED_RSS_MAX_ITEMS, scheduled_rss_config


def test_job_url_still_loads_adapter_config_and_paginates_with_partial_items() -> None:
    calls: list[dict[str, object]] = []
    adapter_config: dict[str, object] = {
        "items_path": "payload.records",
        "fields": {"url": "permalink", "title": "headline"},
        "max_pages": 5,
    }

    async def source_lookup(_identifier: str) -> dict[str, object]:
        return {
            "source_id": "source-1",
            "url": "https://news.test/api",
            "source_type": "API",
            "config": adapter_config,
        }

    async def source_fetcher(source: dict[str, object]) -> dict[str, object]:
        calls.append(source)
        body: dict[str, object]
        if str(source["url"]).endswith("page=2"):
            body = {
                "payload": {
                    "records": [
                        {
                            "permalink": "https://news.test/a",
                            "headline": "A",
                            "body": "a much richer second-page body",
                        },
                        {
                            "permalink": "https://news.test/b",
                            "headline": "B",
                            "body": "body b",
                        },
                    ]
                }
            }
        else:
            body = {
                "payload": {
                    "records": [
                        {
                            "permalink": "https://news.test/a",
                            "headline": "A",
                            "body": "short",
                        },
                        {"headline": "broken sibling"},
                    ]
                },
                "next": "/api?page=2",
            }
        return {
            "status_code": 200,
            "headers": {"content-type": "application/json"},
            "body": body,
        }

    async def scenario() -> None:
        result = await handle(
            {
                "source_id": "source-1",
                # This URL previously prevented source_lookup entirely.
                "url": "https://news.test/api",
                "source_type": "API",
                "mode": "live",
            },
            HandlerContext(
                services={
                    "source_lookup": source_lookup,
                    "source_fetcher": source_fetcher,
                }
            ),
        )
        assert [article["url"] for article in result.value["articles"]] == [
            "https://news.test/a",
            "https://news.test/b",
        ]
        assert result.value["articles"][0]["content"] == "a much richer second-page body"
        assert result.value["stats"]["pages_fetched"] == 2
        assert result.value["stats"]["parse_item_count"] == 4
        assert result.value["stats"]["parse_rejected_count"] == 1

    asyncio.run(scenario())
    assert len(calls) == 2
    assert calls[0]["config"] == adapter_config
    page_config = calls[1]["config"]
    assert isinstance(page_config, dict)
    assert page_config["method"] == "GET"


def test_rss_keeps_xml_bytes_so_euc_kr_feed_is_not_mojibake() -> None:
    xml = (
        '<?xml version="1.0" encoding="euc-kr"?>'
        "<rss><channel><item><title>한국 뉴스</title>"
        "<link>https://news.test/korea</link>"
        "<description>풍부한 기사 본문</description></item></channel></rss>"
    ).encode("cp949")

    async def source_fetcher(_source: object) -> SourceFetchResponse:
        return SourceFetchResponse(
            url="https://news.test/feed.xml",
            status_code=200,
            headers={"content-type": "application/rss+xml"},
            body=xml,
        )

    async def scenario() -> None:
        result = await handle(
            {
                "source_id": "source-rss",
                "url": "https://news.test/feed.xml",
                "source_type": "RSS",
                "mode": "live",
            },
            HandlerContext(services={"source_fetcher": source_fetcher}),
        )
        assert result.value["articles"][0]["title"] == "한국 뉴스"
        assert result.value["articles"][0]["content"] == "풍부한 기사 본문"

    asyncio.run(scenario())


def test_empty_rss_is_not_reported_as_a_successful_news_refresh() -> None:
    async def source_fetcher(_source: object) -> SourceFetchResponse:
        return SourceFetchResponse(
            url="https://news.test/feed.xml",
            status_code=200,
            headers={"content-type": "application/rss+xml"},
            body=b"<rss><channel></channel></rss>",
        )

    async def scenario() -> None:
        with pytest.raises(NonRetryableHandlerError) as raised:
            await handle(
                {
                    "source_id": "source-rss",
                    "url": "https://news.test/feed.xml",
                    "source_type": "RSS",
                    "mode": "live",
                },
                HandlerContext(services={"source_fetcher": source_fetcher}),
            )
        assert raised.value.code == "SOURCE_NO_ARTICLES"

    asyncio.run(scenario())


def test_crawler_fetches_discovered_article_bodies_and_keeps_partial_success() -> None:
    fetched: list[str] = []

    async def source_fetcher(source: dict[str, object]) -> dict[str, object]:
        url = str(source["url"])
        fetched.append(url)
        if url.endswith("/index"):
            return {
                "url": url,
                "html": '<a href="/good">Good story</a><a href="/bad">Bad story</a>',
            }
        if url.endswith("/bad"):
            raise SourceFetchError("temporary upstream failure", code="SOURCE_FETCH_TIMEOUT")
        return {
            "url": url,
            "html": (
                "<html><head><title>Good headline</title></head>"
                "<article><p>First complete paragraph.</p>"
                "<p>Second complete paragraph.</p></article></html>"
            ),
        }

    async def scenario() -> None:
        result = await handle(
            {
                "source_id": "source-crawler",
                "url": "https://news.test/index",
                "source_type": "CRAWLER",
                "mode": "live",
                "policy_status": "APPROVED",
                "robots_status": "APPROVED",
                "terms_status": "APPROVED",
                "config": {"max_links": 10, "fetch_concurrency": 2},
            },
            HandlerContext(services={"source_fetcher": source_fetcher}),
        )
        assert len(result.value["articles"]) == 1
        article = result.value["articles"][0]
        assert article["url"] == "https://news.test/good"
        assert article["title"] == "Good headline"
        assert "Second complete paragraph" in article["content"]
        assert result.value["stats"]["discovered_count"] == 2
        assert result.value["stats"]["article_fetch_succeeded"] == 1
        assert result.value["stats"]["article_fetch_failed"] == 1
        assert result.value["stats"]["article_fetch_failure_counts"] == {
            "SOURCE_FETCH_TIMEOUT": 1
        }

    asyncio.run(scenario())
    assert fetched == [
        "https://news.test/index",
        "https://news.test/good",
        "https://news.test/bad",
    ]


def test_opt_in_rss_hydration_fetches_same_origin_body_and_preserves_skipped_item() -> None:
    fetched: list[tuple[str, str]] = []
    feed = b"""<?xml version="1.0" encoding="utf-8"?>
    <rss><channel>
      <item><title>Local</title><link>https://news.test/local</link>
        <description>short local summary</description></item>
      <item><title>External</title><link>https://other.test/external</link>
        <description>short external summary</description></item>
    </channel></rss>"""

    async def source_fetcher(source: dict[str, object]) -> SourceFetchResponse:
        url = str(source["url"])
        fetched.append((url, str(source["source_type"])))
        if url.endswith("feed.xml"):
            return SourceFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/rss+xml"},
                body=feed,
            )
        return SourceFetchResponse(
            url=url,
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=(
                b"<html><head><title>Local full headline</title></head>"
                b"<article><p>This is the complete local article body with evidence.</p>"
                b"<p>It is substantially richer than the feed summary.</p></article></html>"
            ),
        )

    async def scenario() -> None:
        result = await handle(
            {
                "source_id": "rss-source",
                "url": "https://news.test/feed.xml",
                "source_type": "RSS",
                "mode": "live",
                "policy_status": "APPROVED",
                "robots_status": "APPROVED",
                "terms_status": "APPROVED",
                "config": {
                    "hydrate_article_links": True,
                    "hydrate_min_body_chars": 100,
                    "max_items": 2,
                },
            },
            HandlerContext(services={"source_fetcher": source_fetcher}),
        )
        assert len(result.value["articles"]) == 2
        assert "complete local article body" in result.value["articles"][0]["content"]
        assert result.value["articles"][0]["published_at"] is None
        assert result.value["articles"][1]["content"] == "short external summary"
        assert result.value["stats"]["hydration_attempted"] == 1
        assert result.value["stats"]["hydration_succeeded"] == 1
        assert result.value["stats"]["hydration_origin_skipped"] == 1

    asyncio.run(scenario())
    assert fetched == [
        ("https://news.test/feed.xml", "RSS"),
        ("https://news.test/local", "CRAWLER"),
    ]


def test_scheduled_rss_hydrates_approved_article_domain_with_bounded_partial_success() -> None:
    config = scheduled_rss_config("https://www.newsis.com/")
    assert config is not None
    assert config["hydrate_article_links"] is True
    assert config["require_hydrated_body"] is True
    assert config["metadata_only"] is False
    assert config["max_hydration_fetches"] == SCHEDULED_RSS_MAX_ITEMS
    assert config["max_items"] == SCHEDULED_RSS_MAX_ITEMS
    assert config["allowed_domains"] == ["newsis.com"]

    feed = b"""<?xml version="1.0" encoding="utf-8"?>
    <rss><channel>
      <item><title>Good</title><link>https://www.newsis.com/view/good</link>
        <description>short good summary</description></item>
      <item><title>Failed</title><link>https://www.newsis.com/view/failed</link>
        <description>short fallback summary</description></item>
      <item><title>Outside limit</title><link>https://www.newsis.com/view/third</link>
        <description>must not be persisted</description></item>
    </channel></rss>"""
    fetched: list[tuple[str, str, int]] = []

    async def source_fetcher(source: dict[str, object]) -> SourceFetchResponse:
        url = str(source["url"])
        rate_limit = source.get("rate_limit")
        assert isinstance(rate_limit, int)
        fetched.append((url, str(source["source_type"]), rate_limit))
        if url.endswith("sokbo.xml"):
            return SourceFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/rss+xml"},
                body=feed,
            )
        if url.endswith("/failed"):
            raise SourceFetchError(
                "temporary article failure",
                code="SOURCE_FETCH_TIMEOUT",
                retryable=True,
            )
        return SourceFetchResponse(
            url=url,
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=(
                b"<html><head><title>Hydrated headline</title></head><article>"
                b"<p>Complete approved publisher article body for analysis.</p>"
                b"</article></html>"
            ),
        )

    async def scenario() -> None:
        result = await handle(
            {
                "source_id": "scheduled-newsis",
                "url": str(config["feed_url"]),
                "source_type": "RSS",
                "mode": "live",
                "policy_status": "APPROVED",
                "robots_status": "APPROVED",
                "terms_status": "APPROVED",
                "rate_limit": 10,
                "config": {**config, "max_items": 2, "max_hydration_fetches": 2},
            },
            HandlerContext(services={"source_fetcher": source_fetcher}),
        )
        assert len(result.value["articles"]) == 1
        assert "Complete approved publisher" in result.value["articles"][0]["content"]
        assert result.value["stats"]["hydration_attempted"] == 2
        assert result.value["stats"]["hydration_succeeded"] == 1
        assert result.value["stats"]["hydration_failed"] == 1
        assert result.value["stats"]["hydration_failure_counts"] == {
            "SOURCE_FETCH_TIMEOUT": 1
        }

    asyncio.run(scenario())
    assert fetched == [
        (str(config["feed_url"]), "RSS", 10),
        ("https://www.newsis.com/view/good", "CRAWLER", 10),
        ("https://www.newsis.com/view/failed", "CRAWLER", 10),
    ]


def test_required_rss_hydration_raises_retryable_error_when_every_article_fails() -> None:
    feed = b"""<rss><channel><item><title>Failed</title>
    <link>https://news.test/failed</link><description>short summary</description>
    </item></channel></rss>"""

    async def source_fetcher(source: dict[str, object]) -> SourceFetchResponse:
        url = str(source["url"])
        if url.endswith("feed.xml"):
            return SourceFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "application/rss+xml"},
                body=feed,
            )
        raise SourceFetchError(
            "temporary article failure",
            code="SOURCE_FETCH_TIMEOUT",
            retryable=True,
        )

    async def scenario() -> None:
        with pytest.raises(RetryableHandlerError) as raised:
            await handle(
                {
                    "source_id": "required-rss",
                    "url": "https://news.test/feed.xml",
                    "source_type": "RSS",
                    "mode": "live",
                    "policy_status": "APPROVED",
                    "robots_status": "APPROVED",
                    "terms_status": "APPROVED",
                    "config": {
                        "hydrate_article_links": True,
                        "require_hydrated_body": True,
                    },
                },
                HandlerContext(services={"source_fetcher": source_fetcher}),
            )
        assert raised.value.code == "RSS_HYDRATION_FAILED"
        assert raised.value.details == {
            "failure_counts": {"SOURCE_FETCH_TIMEOUT": 1}
        }

    asyncio.run(scenario())


def test_crawler_all_discovered_fetches_failed_is_retryable_not_empty_success() -> None:
    async def source_fetcher(source: dict[str, object]) -> dict[str, object]:
        if str(source["url"]).endswith("/index"):
            return {"html": '<a href="/one">One</a>', "url": source["url"]}
        raise SourceFetchError("timeout", code="SOURCE_FETCH_TIMEOUT", retryable=True)

    async def scenario() -> None:
        with pytest.raises(RetryableHandlerError) as raised:
            await handle(
                {
                    "url": "https://news.test/index",
                    "source_type": "CRAWLER",
                    "mode": "live",
                    "policy_status": "APPROVED",
                    "robots_status": "APPROVED",
                    "terms_status": "APPROVED",
                },
                HandlerContext(services={"source_fetcher": source_fetcher}),
            )
        assert raised.value.code == "SOURCE_DISCOVERY_FETCH_FAILED"

    asyncio.run(scenario())


def test_response_text_sniffs_cp949_html_meta_charset() -> None:
    response = SourceFetchResponse(
        url="https://news.test/article",
        status_code=200,
        headers={"content-type": "text/html"},
        body=(
            '<html><head><meta charset="euc-kr"></head>'
            "<body>한국 기사 본문</body></html>"
        ).encode("cp949"),
    )
    assert "한국 기사 본문" in response.text


def test_transient_dns_failure_is_retried_within_fetch_budget() -> None:
    resolutions = 0

    def resolver(_host: str, _port: int) -> list[str]:
        nonlocal resolutions
        resolutions += 1
        if resolutions == 1:
            raise socket.gaierror("temporary DNS failure")
        return ["93.184.216.34"]

    async def scenario() -> None:
        service = SourceFetchService(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, content=b'{"items": []}')
            ),
            resolver=resolver,
            max_retries=1,
            backoff_base_seconds=0,
            backoff_max_seconds=0,
        )
        response = await service.fetch("https://news.test/api")
        assert response.status_code == 200
        assert response.attempts == 2

    asyncio.run(scenario())
    assert resolutions == 3
