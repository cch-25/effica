from __future__ import annotations

import asyncio

import httpx
import pytest

from apps.worker.worker.source_fetcher import SourceFetchError, SourceFetchService


def test_fetcher_applies_source_request_config_and_stream_limit() -> None:
    seen: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b'{"items": []}',
        )

    async def scenario() -> None:
        service = SourceFetchService(transport=httpx.MockTransport(transport))
        response = await service.fetch(
            {
                "source_id": "source-1",
                "source_type": "API",
                "url": "https://example.test/api",
                "config": {
                    "headers": {"X-Source": "configured"},
                    "params": {"q": "news"},
                    "max_response_bytes": 100,
                },
            }
        )
        assert response.body == b'{"items": []}'

    asyncio.run(scenario())
    assert len(seen) == 1
    assert seen[0].headers["x-source"] == "configured"
    assert str(seen[0].url.params) == "q=news"
    assert "application/json" in seen[0].headers["accept"]


def test_fetcher_enforces_unknown_length_stream_limit_without_buffering_all_body() -> None:
    async def scenario() -> None:
        service = SourceFetchService(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, content=b"123456789")
            ),
            max_response_bytes=5,
        )
        with pytest.raises(SourceFetchError) as raised:
            await service.fetch("https://example.test/large")
        assert raised.value.code == "SOURCE_RESPONSE_TOO_LARGE"
        assert raised.value.retryable is False

    asyncio.run(scenario())


def test_fetcher_rate_limit_is_per_source_and_honors_retry_config() -> None:
    now = [0.0]
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)
        now[0] += delay

    async def scenario() -> None:
        service = SourceFetchService(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"ok")),
            sleep=sleep,
            clock=lambda: now[0],
        )
        config = {"rate_limit_per_minute": 60, "max_retries": 0}
        await service.fetch({"source_id": "one", "url": "https://example.test/a", "config": config})
        await service.fetch({"source_id": "one", "url": "https://example.test/a", "config": config})
        await service.fetch({"source_id": "two", "url": "https://example.test/b", "config": config})

    asyncio.run(scenario())
    assert sleeps == [1.0]


def test_fetcher_preserves_crawler_policy_guard() -> None:
    async def scenario() -> None:
        service = SourceFetchService(transport=httpx.MockTransport(lambda _request: httpx.Response(200)))
        with pytest.raises(SourceFetchError) as raised:
            await service.fetch(
                {
                    "source_type": "CRAWLER",
                    "url": "https://example.test/article",
                    "policy_status": "APPROVED",
                    "robots_status": "APPROVED",
                    "terms_status": "PENDING",
                }
            )
        assert raised.value.code == "CRAWLER_POLICY_NOT_APPROVED"
        assert raised.value.retryable is False

    asyncio.run(scenario())
