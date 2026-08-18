from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from apps.worker.worker.source_fetcher import SourceFetchError, SourceFetchService


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses: list[httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = responses or []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._responses:
            response = self._responses.pop(0)
            response.request = request
            return response
        return httpx.Response(200, request=request, content=b"ok")


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


def test_fetcher_blocks_private_addresses_credentials_and_redirect_targets() -> None:
    seen: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://private.test/metadata"},
        )

    def resolver(host: str, _port: int) -> list[str]:
        return ["93.184.216.34"] if host == "public.test" else ["10.0.0.1"]

    async def scenario() -> None:
        service = SourceFetchService(
            transport=httpx.MockTransport(transport),
            resolver=resolver,
            max_retries=0,
        )
        with pytest.raises(SourceFetchError) as redirect_error:
            await service.fetch("https://public.test/start")
        assert redirect_error.value.code == "SOURCE_PRIVATE_NETWORK_BLOCKED"
        assert seen == ["https://public.test/start"]

        for url in ("http://127.0.0.1/", "http://[::1]/"):
            with pytest.raises(SourceFetchError) as private_error:
                await service.fetch(url)
            assert private_error.value.code == "SOURCE_PRIVATE_NETWORK_BLOCKED"

        with pytest.raises(SourceFetchError) as credential_error:
            await service.fetch("https://user:password@public.test/private")
        assert credential_error.value.code == "SOURCE_URL_CREDENTIALS_BLOCKED"

    asyncio.run(scenario())


def test_default_resolver_getaddrinfo_tuples_are_parsed_from_sockaddr(monkeypatch) -> None:
    expected = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)),
        (
            socket.AF_INET6,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("2606:4700:4700::1111", 443, 0, 0),
        ),
    ]

    def getaddrinfo(_host: str, _port: int, **_kwargs):
        return expected

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)

    async def scenario() -> None:
        resolved = await SourceFetchService._default_resolver("public.test", 443)
        assert SourceFetchService._address_from_resolution(resolved[0]) is not None
        assert str(SourceFetchService._address_from_resolution(resolved[0])) == "93.184.216.34"
        assert str(SourceFetchService._address_from_resolution(resolved[1])) == (
            "2606:4700:4700::1111"
        )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("resolved_address", "expected_url"),
    [
        ("93.184.216.34", "https://93.184.216.34/path"),
        ("2606:4700:4700::1111", "https://[2606:4700:4700::1111]/path"),
    ],
)
def test_public_hostname_uses_validated_address_with_original_host_and_sni(
    resolved_address: str, expected_url: str
) -> None:
    transport = _RecordingTransport()

    def resolver(_host: str, _port: int) -> list[str]:
        return [resolved_address]

    async def scenario() -> None:
        service = SourceFetchService(
            transport=transport,
            resolver=resolver,
            max_retries=0,
        )
        response = await service.fetch("https://public.test/path")
        assert response.url == "https://public.test/path"

    asyncio.run(scenario())
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert str(request.url) == expected_url
    assert request.headers["host"] == "public.test"
    assert request.extensions["sni_hostname"] == "public.test"


def test_fetcher_blocks_public_to_private_dns_rebinding_before_following_redirect() -> None:
    transport = _RecordingTransport(
        [httpx.Response(302, headers={"location": "https://public.test/next"})]
    )
    answers = iter([["93.184.216.34"], ["10.0.0.1"]])

    def resolver(_host: str, _port: int) -> list[str]:
        return next(answers)

    async def scenario() -> None:
        service = SourceFetchService(
            transport=transport,
            resolver=resolver,
            max_retries=0,
        )
        with pytest.raises(SourceFetchError) as raised:
            await service.fetch("https://public.test/start")
        assert raised.value.code == "SOURCE_PRIVATE_NETWORK_BLOCKED"

    asyncio.run(scenario())
    assert len(transport.requests) == 1
    assert str(transport.requests[0].url) == "https://93.184.216.34/start"


def test_fetcher_blocks_credentials_in_redirect_targets() -> None:
    transport = _RecordingTransport(
        [httpx.Response(302, headers={"location": "https://user:password@public.test/next"})]
    )

    async def scenario() -> None:
        service = SourceFetchService(
            transport=transport,
            resolver=lambda _host, _port: ["93.184.216.34"],
            max_retries=0,
        )
        with pytest.raises(SourceFetchError) as raised:
            await service.fetch("https://public.test/start")
        assert raised.value.code == "SOURCE_URL_CREDENTIALS_BLOCKED"

    asyncio.run(scenario())
    assert len(transport.requests) == 1
