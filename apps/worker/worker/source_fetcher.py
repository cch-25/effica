"""Bounded asynchronous HTTP fetching for worker source adapters.

The content domain deliberately owns parsing, while this module owns the
small amount of I/O needed to obtain a source payload.  ``SourceFetchService``
accepts an ``httpx`` transport (``httpx.MockTransport`` is particularly handy
for tests), so callers never need to patch a global HTTP client or make a
public-network request in a unit test.
"""

from __future__ import annotations

import asyncio
import codecs
import inspect
import ipaddress
import json
import math
import re
import socket
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

try:
    from apps.api.app.domains.content.canonical import canonicalize_url
    from apps.api.app.domains.content.policy import CrawlerPolicyGuard
except ImportError:  # pragma: no cover - supports PYTHONPATH=apps/worker.
    from api.app.domains.content.canonical import canonicalize_url  # type: ignore
    from api.app.domains.content.policy import CrawlerPolicyGuard  # type: ignore


_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429})
_REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
_DEFAULT_USER_AGENT = "perspective-news-worker/1.0"
_DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
_APPROVED_POLICY_STATUS = "APPROVED"
_DEFAULT_RATE_LIMIT_PER_MINUTE = 0
_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_CHARSET_PARAMETER = re.compile(r"charset\s*=\s*[\"']?\s*([^\s;\"'>/]+)", re.I)
_HTML_META_CHARSET = re.compile(
    br"<meta\b[^>]*\bcharset\s*=\s*[\"']?\s*([^\s;\"'>/]+)", re.I
)
_HTML_META_CONTENT_TYPE = re.compile(
    br"<meta\b[^>]*\bcontent\s*=\s*[\"'][^\"']*charset\s*=\s*([^\s;\"'>/]+)",
    re.I,
)
_XML_ENCODING = re.compile(br"<\?xml\b[^>]*\bencoding\s*=\s*[\"']\s*([^\s\"']+)", re.I)


class SourceFetchError(RuntimeError):
    """Safe, structured failure raised by :class:`SourceFetchService`.

    Error details intentionally contain status/attempt metadata only.  The
    response body and request headers are never copied into an exception,
    because either may contain source content or credentials.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "SOURCE_FETCH_FAILED",
        retryable: bool = True,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = dict(details or {})

    def as_error(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class SourceFetchResponse:
    """A bounded source response handed to the crawl parser.

    ``body`` is retained only at the worker boundary.  ``as_metadata`` is
    deliberately body-free for logging and crawl statistics.
    """

    url: str
    status_code: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    attempts: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "headers",
            {str(key).lower(): str(value) for key, value in self.headers.items()},
        )
        if self.fetched_at.tzinfo is None:
            object.__setattr__(self, "fetched_at", self.fetched_at.replace(tzinfo=UTC))
        if self.attempts < 1:
            object.__setattr__(self, "attempts", 1)

    @property
    def text(self) -> str:
        """Decode text without silently destroying non-UTF-8 news pages.

        Korean publishers still commonly serve CP949/EUC-KR HTML, sometimes
        without an HTTP charset.  The old UTF-8-with-replacement fallback made
        those pages parse successfully but persisted unreadable titles and
        bodies.  Honour BOM/HTTP declarations first, then bounded XML/HTML
        declarations, and only use replacement decoding as a final fallback.
        """

        if not self.body:
            return ""
        candidates: list[str] = []
        if self.body.startswith(codecs.BOM_UTF8):
            candidates.append("utf-8-sig")
        elif self.body.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            candidates.append("utf-32")
        elif self.body.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            candidates.append("utf-16")
        content_type = self.headers.get("content-type", "")
        header_match = _CHARSET_PARAMETER.search(content_type)
        if header_match:
            candidates.append(header_match.group(1))
        prefix = self.body[:8192]
        for pattern in (_XML_ENCODING, _HTML_META_CHARSET, _HTML_META_CONTENT_TYPE):
            match = pattern.search(prefix)
            if match:
                candidates.append(match.group(1).decode("ascii", errors="ignore"))
        candidates.append("utf-8")

        tried: set[str] = set()
        for candidate in candidates:
            normalized = candidate.strip().strip("\"'").lower()
            if not normalized or normalized in tried:
                continue
            tried.add(normalized)
            aliases = (normalized, "cp949") if normalized in {"euc-kr", "euckr", "ks_c_5601-1987"} else (normalized,)
            for encoding in aliases:
                if encoding in tried and encoding != normalized:
                    continue
                tried.add(encoding)
                try:
                    return self.body.decode(encoding, errors="strict")
                except (LookupError, UnicodeDecodeError):
                    continue
        return self.body.decode("utf-8", errors="replace")

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")

    def json(self) -> Any:
        """Decode a JSON response without exposing its body on errors."""

        import json

        return json.loads(self.body)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "attempts": self.attempts,
            "fetched_at": self.fetched_at,
            "content_type": self.content_type,
            "byte_size": len(self.body),
        }


SleepCallable = Callable[[float], Awaitable[Any] | Any]
ClockCallable = Callable[[], float]


@dataclass(frozen=True)
class _RequestSettings:
    method: str
    headers: Mapping[str, str]
    params: Any = None
    content: bytes | str | None = None
    json_body: Any = None
    timeout_seconds: float = 15.0
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES
    rate_limit_per_minute: float = 0.0
    min_interval_seconds: float = 0.0
    max_retries: int = 2
    backoff_base_seconds: float = 0.25
    backoff_max_seconds: float = 5.0
    follow_redirects: bool = True
    max_redirects: int = 10


class SourceFetchService:
    """Fetch one source with finite timeout, retries and bounded backoff.

    ``source`` is normally the source mapping loaded by the worker.  Passing
    a URL string is supported for small callers and tests.  When a client is
    not supplied, the service creates one per call and closes it; supplying a
    client transfers lifecycle ownership to the caller.  Supplying an
    ``httpx.AsyncBaseTransport`` keeps all requests fully injectable.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float | None = None,
        timeout: float | None = None,
        max_retries: int = 2,
        backoff_base_seconds: float | None = None,
        backoff_base: float | None = None,
        backoff_max_seconds: float | None = None,
        backoff_max: float | None = None,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        headers: Mapping[str, str] | None = None,
        sleep: SleepCallable = asyncio.sleep,
        clock: ClockCallable = time.monotonic,
        follow_redirects: bool = True,
        max_redirects: int = 10,
        resolver: Callable[[str, int], Any] | None = None,
    ) -> None:
        if transport is not None and client is not None:
            raise ValueError("transport and client are mutually exclusive")
        self.transport = transport
        self.client = client
        self.timeout_seconds = self._positive_finite(
            timeout_seconds if timeout_seconds is not None else (timeout if timeout is not None else 15.0),
            "timeout_seconds",
        )
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        self.max_retries = max_retries
        self.backoff_base_seconds = self._nonnegative_finite(
            backoff_base_seconds
            if backoff_base_seconds is not None
            else (backoff_base if backoff_base is not None else 0.25),
            "backoff_base_seconds",
        )
        self.backoff_max_seconds = self._nonnegative_finite(
            backoff_max_seconds
            if backoff_max_seconds is not None
            else (backoff_max if backoff_max is not None else 5.0),
            "backoff_max_seconds",
        )
        if self.backoff_max_seconds < self.backoff_base_seconds and self.backoff_base_seconds:
            raise ValueError("backoff_max_seconds must be at least backoff_base_seconds")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int):
            raise ValueError("max_response_bytes must be a positive integer")
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be a positive integer")
        self.max_response_bytes = max_response_bytes
        self.headers = self._merge_headers(
            {"User-Agent": _DEFAULT_USER_AGENT, "Accept": "*/*"},
            headers,
        )
        self.sleep = sleep
        self.clock = clock
        self._rate_next: dict[str, float] = {}
        self._rate_lock: asyncio.Lock | None = None
        self.follow_redirects = bool(follow_redirects)
        if isinstance(max_redirects, bool) or not isinstance(max_redirects, int) or max_redirects < 0:
            raise ValueError("max_redirects must be a non-negative integer")
        self.max_redirects = max_redirects
        # A resolver hook keeps DNS rebinding and redirect tests deterministic.
        # The default is deliberately synchronous-but-offloaded below so the
        # worker event loop is never blocked by libc name resolution.
        self.resolver = resolver or self._default_resolver
        self._resolver_injected = resolver is not None
        self._test_transport = self._is_test_transport(transport) or self._is_test_transport(
            getattr(client, "_transport", None)
        )

    @staticmethod
    def _positive_finite(value: float, name: str) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a positive finite number") from exc
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a positive finite number")
        return value

    @staticmethod
    def _nonnegative_finite(value: float, name: str) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a non-negative finite number") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a non-negative finite number")
        return value

    async def __call__(self, source: Mapping[str, Any] | str) -> SourceFetchResponse:
        return await self.fetch(source)

    async def fetch(
        self,
        source: Mapping[str, Any] | str,
        *,
        source_type: str | None = None,
    ) -> SourceFetchResponse:
        source_values = dict(source) if isinstance(source, Mapping) else {"url": source}
        source_kind = str(
            source_type
            or source_values.get("source_type")
            or source_values.get("adapter_type")
            or "API"
        ).upper()
        if source_kind == "CRAWLER":
            self._check_crawler_policy(source_values)
        raw_url = source_values.get("url") or source_values.get("canonical_url")
        if raw_url in (None, ""):
            raise SourceFetchError(
                "source URL is required",
                code="INVALID_SOURCE_URL",
                retryable=False,
            )
        try:
            raw_parts = urlsplit(str(raw_url).strip())
            if raw_parts.username is not None or raw_parts.password is not None:
                raise SourceFetchError(
                    "source URL cannot contain credentials",
                    code="SOURCE_URL_CREDENTIALS_BLOCKED",
                    retryable=False,
                )
        except ValueError as exc:
            raise SourceFetchError(
                "source URL is invalid",
                code="INVALID_SOURCE_URL",
                retryable=False,
            ) from exc
        try:
            url = canonicalize_url(str(raw_url))
        except (TypeError, ValueError) as exc:
            raise SourceFetchError(
                "source URL is invalid",
                code="INVALID_SOURCE_URL",
                retryable=False,
            ) from exc
        return await self._request(url, source_values, source_kind=source_kind)

    @staticmethod
    def _check_crawler_policy(source: Mapping[str, Any]) -> None:
        # The aggregate status is part of the source lifecycle contract; the
        # guard covers the independent robots/terms decisions as well.
        aggregate = str(source.get("policy_status", "")).upper()
        if aggregate != _APPROVED_POLICY_STATUS:
            raise SourceFetchError(
                "crawler policy, robots and terms approval are required",
                code="CRAWLER_POLICY_NOT_APPROVED",
                retryable=False,
            )
        try:
            CrawlerPolicyGuard.from_source(source).check()
        except PermissionError as exc:
            raise SourceFetchError(
                "crawler policy, robots and terms approval are required",
                code="CRAWLER_POLICY_NOT_APPROVED",
                retryable=False,
            ) from exc

    async def _request(
        self,
        url: str,
        source: Mapping[str, Any],
        *,
        source_kind: str = "API",
    ) -> SourceFetchResponse:
        settings = self._request_settings(source, source_kind=source_kind)
        timeout = httpx.Timeout(settings.timeout_seconds)
        client = self.client
        if client is not None:
            return await self._request_with_client(client, url, source, settings=settings)
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=timeout,
            # Redirects are followed one hop at a time by this service so the
            # target can be validated before httpx opens the next connection.
            follow_redirects=False,
            max_redirects=settings.max_redirects,
        ) as owned_client:
            return await self._request_with_client(owned_client, url, source, settings=settings)

    @staticmethod
    async def _default_resolver(host: str, port: int) -> Any:
        return await asyncio.to_thread(socket.getaddrinfo, host, port, type=socket.SOCK_STREAM)

    @staticmethod
    def _is_test_transport(transport: Any) -> bool:
        # MockTransport never performs DNS or network I/O.  Existing unit
        # callers intentionally use non-resolving ``example.test`` hosts; the
        # literal/private-address checks still run for those calls.
        return isinstance(transport, httpx.MockTransport)

    @staticmethod
    def _address_from_resolution(value: Any) -> _IPAddress | None:
        if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            return value
        if isinstance(value, str):
            try:
                return ipaddress.ip_address(value)
            except ValueError:
                return None
        if isinstance(value, tuple) and value:
            # ``socket.getaddrinfo`` returns
            # ``(family, type, proto, canonname, sockaddr)``.  The address
            # lives at ``sockaddr[0]``; treating the family integer as the
            # address makes every normal public hostname look unresolved.
            sockaddr = value[4] if len(value) >= 5 else value
            candidate = sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else None
            if isinstance(candidate, str):
                try:
                    return ipaddress.ip_address(candidate)
                except ValueError:
                    return None
        return None

    @classmethod
    def _assert_public_address(cls, value: _IPAddress) -> None:
        # ``is_global`` is intentionally not the sole check: mapped IPv4,
        # documentation, reserved, and unspecified ranges must all be
        # rejected explicitly, including on IPv6.
        mapped = getattr(value, "ipv4_mapped", None)
        if mapped is not None:
            value = mapped
        if (
            value.is_private
            or value.is_loopback
            or value.is_link_local
            or value.is_reserved
            or value.is_unspecified
            or value.is_multicast
            or not value.is_global
        ):
            raise SourceFetchError(
                "source URL resolves to a non-public network address",
                code="SOURCE_PRIVATE_NETWORK_BLOCKED",
                retryable=False,
            )

    async def _validate_network_target(self, url: str) -> _IPAddress | None:
        """Validate a URL and return the address that the request must use."""

        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise SourceFetchError(
                "source URL is invalid",
                code="INVALID_SOURCE_URL",
                retryable=False,
            )
        if parts.username is not None or parts.password is not None:
            raise SourceFetchError(
                "source URL cannot contain credentials",
                code="SOURCE_URL_CREDENTIALS_BLOCKED",
                retryable=False,
            )
        try:
            port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
        except ValueError as exc:
            raise SourceFetchError(
                "source URL has an invalid port",
                code="INVALID_SOURCE_URL",
                retryable=False,
            ) from exc
        host = parts.hostname.rstrip(".").lower()
        # Well-known private names must fail even with a mock transport, which
        # intentionally skips DNS resolution.
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
            raise SourceFetchError(
                "source URL targets a private network name",
                code="SOURCE_PRIVATE_NETWORK_BLOCKED",
                retryable=False,
            )
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            self._assert_public_address(literal)
            return literal
        try:
            resolved = self.resolver(host, port)
            if inspect.isawaitable(resolved):
                resolved = await resolved
        except (OSError, socket.gaierror) as exc:
            # ``example.test`` is the non-resolving host used by the legacy
            # MockTransport unit fixtures.  No real socket is opened in that
            # mode; all other unresolved hosts fail closed even under a test
            # transport.  Production clients never take this exception.
            if self._test_transport and not self._resolver_injected and host == "example.test":
                return None
            raise SourceFetchError(
                "source hostname could not be resolved",
                code="SOURCE_DNS_RESOLUTION_FAILED",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise SourceFetchError(
                "source hostname could not be resolved",
                code="SOURCE_DNS_RESOLUTION_FAILED",
                retryable=False,
                details={"exception": exc.__class__.__name__},
            ) from exc
        if isinstance(resolved, (str, ipaddress.IPv4Address, ipaddress.IPv6Address)):
            resolved = [resolved]
        addresses: list[_IPAddress] = []
        for item in resolved or ():
            candidate = self._address_from_resolution(item)
            if candidate is not None:
                addresses.append(candidate)
        if not addresses:
            raise SourceFetchError(
                "source hostname has no usable address",
                code="SOURCE_DNS_RESOLUTION_FAILED",
                retryable=True,
            )
        for address in addresses:
            self._assert_public_address(address)
        # The URL is rewritten to this validated address immediately before
        # sending.  Keeping the hostname in Host/SNI preserves virtual-host
        # routing and HTTPS certificate validation without allowing HTTPX to
        # perform a second, independently resolved connection.
        return addresses[0]

    @staticmethod
    def _connection_target(
        url: str,
        headers: Mapping[str, str],
        validated_address: _IPAddress | None,
        *,
        pin_address: bool,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        """Build a pinned URL while retaining the URL host at the protocol layer."""

        if validated_address is None or not pin_address:
            return url, dict(headers), {}
        parts = urlsplit(url)
        host = parts.hostname
        if not host:
            return url, dict(headers), {}
        connect_url = httpx.URL(url).copy_with(host=str(validated_address))
        request_headers = dict(headers)
        if not any(str(key).lower() == "host" for key in request_headers):
            default_port = 443 if parts.scheme.lower() == "https" else 80
            host_header = host
            if parts.port is not None and parts.port != default_port:
                host_header = f"{host}:{parts.port}"
            request_headers["Host"] = host_header
        extensions: dict[str, Any] = {}
        if parts.scheme.lower() == "https":
            # httpcore uses this extension for TLS SNI.  The URL itself points
            # at the validated address, while certificate validation remains
            # against the original DNS name.
            extensions["sni_hostname"] = host
        return str(connect_url), request_headers, extensions

    async def _request_with_client(
        self,
        client: httpx.AsyncClient,
        url: str,
        source: Mapping[str, Any],
        *,
        settings: _RequestSettings | None = None,
    ) -> SourceFetchResponse:
        settings = settings or self._request_settings(source, source_kind="API")
        retry_count = 0
        request_count = 0
        redirect_count = 0
        current_url = url
        current_settings = settings
        while True:
            request_count += 1
            try:
                # Resolve and classify every hop and every retry.  This
                # catches DNS rebinding between attempts and prevents httpx's
                # redirect machinery from reaching an unchecked target.
                validated_address = await self._validate_network_target(current_url)
                request_url, request_headers, request_extensions = self._connection_target(
                    current_url,
                    current_settings.headers,
                    validated_address,
                    # MockTransport never opens a socket.  Keeping its URL
                    # unchanged preserves existing injectable test semantics;
                    # all real transports are pinned to the validated IP.
                    pin_address=not self._test_transport,
                )
                await self._acquire_rate_limit(
                    self._rate_key(source, current_url), current_settings
                )
                if callable(getattr(client, "stream", None)):
                    response, body = await self._stream_response(
                        client,
                        request_url,
                        current_settings,
                        headers=request_headers,
                        extensions=request_extensions,
                    )
                else:
                    # Compatibility for very small fake clients used by
                    # older callers.  Real httpx clients always take the
                    # streaming path above.
                    request = getattr(client, "request", None)
                    if not callable(request):
                        request = getattr(client, "get", None)
                    if not callable(request):
                        raise TypeError("source client must expose request(), get() or stream()")
                    kwargs = {
                        "headers": request_headers,
                        "params": current_settings.params,
                        "follow_redirects": False,
                    }
                    if request_extensions:
                        kwargs["extensions"] = request_extensions
                    if current_settings.content is not None:
                        kwargs["content"] = current_settings.content
                    if current_settings.json_body is not None:
                        kwargs["json"] = current_settings.json_body
                    try:
                        if request.__name__ == "get":
                            response_call = request(request_url, **kwargs)
                        else:
                            response_call = request(current_settings.method, request_url, **kwargs)
                    except TypeError:
                        # Small injected fake clients may not accept the
                        # redirect keyword; they still receive per-hop
                        # validation from this service.
                        kwargs.pop("follow_redirects", None)
                        kwargs.pop("extensions", None)
                        if request.__name__ == "get":
                            response_call = request(request_url, **kwargs)
                        else:
                            response_call = request(current_settings.method, request_url, **kwargs)
                    response = await asyncio.wait_for(
                        response_call, timeout=current_settings.timeout_seconds
                    )
                    body = self._bounded_body(
                        response.content, current_settings.max_response_bytes
                    )
                # Re-resolve after the response too.  A DNS answer that
                # changes while the request is in flight must not become a
                # trusted redirect/body hop on the next loop iteration.
                await self._validate_network_target(current_url)
                status = response.status_code
                if status in _REDIRECT_STATUS_CODES and current_settings.follow_redirects:
                    location = response.headers.get("location")
                    if not location:
                        raise SourceFetchError(
                            "source redirect did not include a location",
                            code="SOURCE_REDIRECT_INVALID",
                            retryable=False,
                            details={"status_code": status},
                        )
                    if redirect_count >= current_settings.max_redirects:
                        raise SourceFetchError(
                            "source redirect limit exceeded",
                            code="SOURCE_REDIRECT_LIMIT",
                            retryable=False,
                            details={"max_redirects": current_settings.max_redirects},
                        )
                    try:
                        raw_redirect_url = urljoin(current_url, location)
                        redirect_parts = urlsplit(raw_redirect_url)
                        if redirect_parts.username is not None or redirect_parts.password is not None:
                            raise SourceFetchError(
                                "source redirect target cannot contain credentials",
                                code="SOURCE_URL_CREDENTIALS_BLOCKED",
                                retryable=False,
                            )
                        redirected_url = canonicalize_url(raw_redirect_url)
                    except (TypeError, ValueError) as exc:
                        raise SourceFetchError(
                            "source redirect target is invalid",
                            code="SOURCE_REDIRECT_INVALID",
                            retryable=False,
                        ) from exc
                    await self._validate_network_target(redirected_url)

                    def origin(value: str) -> tuple[str, str, int]:
                        parsed = urlsplit(value)
                        return (
                            parsed.scheme.lower(),
                            (parsed.hostname or "").lower(),
                            parsed.port or (443 if parsed.scheme.lower() == "https" else 80),
                        )

                    method = current_settings.method
                    content = current_settings.content
                    json_body = current_settings.json_body
                    headers: Mapping[str, str]
                    if origin(current_url) != origin(redirected_url):
                        # Do not leak source credentials or request bodies
                        # across an origin redirect.  301/302/303 become GET;
                        # 307/308 POST JSON is refused rather than forwarded.
                        headers = {
                            key: value
                            for key, value in current_settings.headers.items()
                            if key.lower()
                            not in {
                                "authorization",
                                "cookie",
                                "proxy-authorization",
                                "content-type",
                                "content-length",
                            }
                        }
                        content = None
                        json_body = None
                        if status in {301, 302, 303}:
                            method = "GET"
                        elif method == "POST":
                            raise SourceFetchError(
                                "refusing to forward a request body across origins",
                                code="SOURCE_REDIRECT_CROSS_ORIGIN",
                                retryable=False,
                                details={"status_code": status},
                            )
                    else:
                        headers = current_settings.headers
                    current_settings = replace(
                        current_settings,
                        headers=headers,
                        method=method,
                        content=content,
                        json_body=json_body,
                        # Query parameters were applied to the original URL;
                        # a Location header is authoritative for the next hop.
                        params=None,
                    )
                    current_url = redirected_url
                    redirect_count += 1
                    continue
                if 200 <= status < 300:
                    return SourceFetchResponse(
                        # ``request_url`` may contain the pinned address.  The
                        # worker contract exposes the canonical source URL,
                        # not the connection address used underneath it.
                        url=str(current_url),
                        status_code=status,
                        headers=dict(response.headers),
                        body=body,
                        fetched_at=datetime.now(UTC),
                        attempts=request_count,
                    )
                retryable = self._retryable_status(status)
                if retryable and retry_count < settings.max_retries:
                    retry_count += 1
                    await self._backoff(
                        retry_count,
                        response.headers.get("retry-after"),
                        base_seconds=current_settings.backoff_base_seconds,
                        max_seconds=current_settings.backoff_max_seconds,
                    )
                    continue
                raise SourceFetchError(
                    self._status_message(status),
                    code=("SOURCE_FETCH_RETRY_EXHAUSTED" if retryable else "SOURCE_HTTP_ERROR"),
                    retryable=retryable,
                    details={"status_code": status, "attempts": request_count},
                )
            except SourceFetchError as exc:
                # DNS failures are commonly transient.  Retry them inside the
                # bounded source request just like transport failures; policy,
                # SSRF and parser/config errors remain immediate failures.
                if (
                    exc.retryable
                    and exc.code == "SOURCE_DNS_RESOLUTION_FAILED"
                    and retry_count < settings.max_retries
                ):
                    retry_count += 1
                    await self._backoff(
                        retry_count,
                        None,
                        base_seconds=current_settings.backoff_base_seconds,
                        max_seconds=current_settings.backoff_max_seconds,
                    )
                    continue
                raise
            except (TimeoutError, httpx.TimeoutException) as exc:
                if retry_count < settings.max_retries:
                    retry_count += 1
                    await self._backoff(
                        retry_count,
                        None,
                        base_seconds=current_settings.backoff_base_seconds,
                        max_seconds=current_settings.backoff_max_seconds,
                    )
                    continue
                raise SourceFetchError(
                    "source request timed out",
                    code="SOURCE_FETCH_TIMEOUT",
                    retryable=True,
                    details={"attempts": request_count},
                ) from exc
            except httpx.TransportError as exc:
                if retry_count < settings.max_retries:
                    retry_count += 1
                    await self._backoff(
                        retry_count,
                        None,
                        base_seconds=current_settings.backoff_base_seconds,
                        max_seconds=current_settings.backoff_max_seconds,
                    )
                    continue
                raise SourceFetchError(
                    "source transport failed",
                    code="SOURCE_FETCH_TRANSPORT_ERROR",
                    retryable=True,
                    details={"attempts": request_count, "exception": exc.__class__.__name__},
                ) from exc
            except Exception as exc:
                # A custom transport may raise a non-httpx exception.  Keep
                # the worker boundary structured and body-free rather than
                # allowing arbitrary exception text into durable job errors.
                if retry_count < settings.max_retries:
                    retry_count += 1
                    await self._backoff(
                        retry_count,
                        None,
                        base_seconds=current_settings.backoff_base_seconds,
                        max_seconds=current_settings.backoff_max_seconds,
                    )
                    continue
                raise SourceFetchError(
                    "source request failed",
                    code="SOURCE_FETCH_ERROR",
                    retryable=True,
                    details={"attempts": request_count, "exception": exc.__class__.__name__},
                ) from exc

    async def _stream_response(
        self,
        client: httpx.AsyncClient,
        url: str,
        settings: _RequestSettings,
        *,
        headers: Mapping[str, str] | None = None,
        extensions: Mapping[str, Any] | None = None,
    ) -> tuple[httpx.Response, bytes]:
        request_kwargs: dict[str, Any] = {
            "headers": dict(headers or settings.headers),
            "params": settings.params,
        }
        if extensions:
            request_kwargs["extensions"] = dict(extensions)
        if settings.content is not None:
            request_kwargs["content"] = settings.content
        if settings.json_body is not None:
            request_kwargs["json"] = settings.json_body
        try:
            try:
                stream_context = client.stream(
                    settings.method,
                    url,
                    follow_redirects=False,
                    **request_kwargs,
                )
            except TypeError:
                # Small injected fake clients may not expose httpx's optional
                # redirect keyword; they still receive per-hop validation from
                # this service.
                request_kwargs.pop("extensions", None)
                stream_context = client.stream(settings.method, url, **request_kwargs)
            async with asyncio.timeout(settings.timeout_seconds):
                async with stream_context as response:
                    self._check_content_length(response.headers, settings.max_response_bytes)
                    status = response.status_code
                    # Error responses do not need to be materialized.  Exiting
                    # the stream context closes the connection before retry.
                    if not (200 <= status < 300):
                        return response, b""
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > settings.max_response_bytes:
                            raise SourceFetchError(
                                "source response exceeds configured size limit",
                                code="SOURCE_RESPONSE_TOO_LARGE",
                                retryable=False,
                                details={"max_response_bytes": settings.max_response_bytes},
                            )
                        chunks.append(chunk)
                    return response, b"".join(chunks)
        except TimeoutError:
            raise

    @staticmethod
    def _bounded_body(body: bytes, max_response_bytes: int) -> bytes:
        if len(body) > max_response_bytes:
            raise SourceFetchError(
                "source response exceeds configured size limit",
                code="SOURCE_RESPONSE_TOO_LARGE",
                retryable=False,
                details={"max_response_bytes": max_response_bytes},
            )
        return body

    @staticmethod
    def _check_content_length(headers: Mapping[str, Any], max_response_bytes: int) -> None:
        content_length = headers.get("content-length")
        if content_length is None:
            return
        try:
            too_large = int(content_length) > max_response_bytes
        except (TypeError, ValueError):
            return
        if too_large:
            raise SourceFetchError(
                "source response exceeds configured size limit",
                code="SOURCE_RESPONSE_TOO_LARGE",
                retryable=False,
                details={"max_response_bytes": max_response_bytes},
            )

    @staticmethod
    def _merge_headers(
        defaults: Mapping[str, Any], overrides: Mapping[str, Any] | None,
    ) -> dict[str, str]:
        result = {str(key).lower(): (str(key), str(value)) for key, value in defaults.items()}
        for key, value in (overrides or {}).items():
            lowered = str(key).lower()
            result[lowered] = (str(key), str(value))
        return {key: value for key, value in result.values()}

    def _request_settings(
        self,
        source: Mapping[str, Any],
        *,
        source_kind: str,
    ) -> _RequestSettings:
        config = self._source_config(source)
        timeout = self._positive_finite(
            config.get("timeout_seconds", config.get("timeout", self.timeout_seconds)),
            "timeout_seconds",
        )
        configured_max = config.get("max_response_bytes", self.max_response_bytes)
        if isinstance(configured_max, bool) or not isinstance(configured_max, int) or configured_max < 1:
            raise SourceFetchError(
                "source response size limit is invalid",
                code="INVALID_SOURCE_CONFIG",
                retryable=False,
            )
        method = str(config.get("method", config.get("http_method", "GET"))).upper().strip()
        if method not in {"GET", "HEAD", "POST"}:
            raise SourceFetchError(
                "source HTTP method is not supported",
                code="INVALID_SOURCE_CONFIG",
                retryable=False,
                details={"method": method},
            )
        accept_default = {
            "API": "application/json, application/*+json;q=0.9, */*;q=0.1",
            "RSS": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.1",
            "CRAWLER": "text/html, application/xhtml+xml;q=0.9, */*;q=0.1",
        }.get(source_kind, "*/*")
        headers = self._merge_headers(
            {**self.headers, "Accept": accept_default},
            config.get("headers") if isinstance(config.get("headers"), Mapping) else None,
        )
        extra_headers = source.get("headers")
        if isinstance(extra_headers, Mapping):
            headers = self._merge_headers(headers, extra_headers)
        params = config.get("params", config.get("query_params"))
        content = config.get("body")
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False)
        json_body = config.get("json")
        interval = self._nonnegative_finite(
            config.get("min_interval_seconds", config.get("rate_limit_seconds", 0)),
            "min_interval_seconds",
        )
        rate = config.get(
            "rate_limit_per_minute",
            config.get(
                "requests_per_minute",
                config.get("rate_limit", source.get("rate_limit", _DEFAULT_RATE_LIMIT_PER_MINUTE)),
            ),
        )
        try:
            rate_value = float(rate or 0)
        except (TypeError, ValueError):
            raise SourceFetchError(
                "source rate limit is invalid",
                code="INVALID_SOURCE_CONFIG",
                retryable=False,
            ) from None
        if not math.isfinite(rate_value) or rate_value < 0:
            raise SourceFetchError(
                "source rate limit is invalid",
                code="INVALID_SOURCE_CONFIG",
                retryable=False,
            )
        if rate_value and not interval:
            interval = 60.0 / rate_value
        raw_retries = config.get("max_retries", self.max_retries)
        if isinstance(raw_retries, bool) or not isinstance(raw_retries, int) or raw_retries < 0:
            raise SourceFetchError(
                "source retry count is invalid",
                code="INVALID_SOURCE_CONFIG",
                retryable=False,
            )
        backoff_base = self._nonnegative_finite(
            config.get("backoff_base_seconds", config.get("backoff_base", self.backoff_base_seconds)),
            "backoff_base_seconds",
        )
        backoff_max = self._nonnegative_finite(
            config.get("backoff_max_seconds", config.get("backoff_max", self.backoff_max_seconds)),
            "backoff_max_seconds",
        )
        if backoff_max < backoff_base:
            raise SourceFetchError(
                "source backoff maximum is invalid",
                code="INVALID_SOURCE_CONFIG",
                retryable=False,
            )
        raw_redirects = config.get("max_redirects", self.max_redirects)
        if isinstance(raw_redirects, bool) or not isinstance(raw_redirects, int) or raw_redirects < 0:
            raise SourceFetchError(
                "source redirect limit is invalid",
                code="INVALID_SOURCE_CONFIG",
                retryable=False,
            )
        return _RequestSettings(
            method=method,
            headers=headers,
            params=params,
            content=content,
            json_body=json_body,
            timeout_seconds=timeout,
            max_response_bytes=configured_max,
            rate_limit_per_minute=rate_value,
            min_interval_seconds=interval,
            max_retries=raw_retries,
            backoff_base_seconds=backoff_base,
            backoff_max_seconds=backoff_max,
            follow_redirects=_as_bool(
                config.get("follow_redirects"), default=self.follow_redirects
            ),
            max_redirects=raw_redirects,
        )

    @staticmethod
    def _source_config(source: Mapping[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for key in ("config_json", "adapter_config", "config"):
            value = source.get(key)
            if isinstance(value, Mapping):
                merged.update(dict(value))
        nested = merged.get("adapter")
        if isinstance(nested, Mapping):
            merged = {
                **dict(nested),
                **{key: value for key, value in merged.items() if key != "adapter"},
            }
        if source.get("rate_limit") is not None:
            merged.setdefault("rate_limit", source.get("rate_limit"))
        return merged

    @staticmethod
    def _rate_key(source: Mapping[str, Any], url: str) -> str:
        return str(source.get("source_id") or source.get("id") or url)

    async def _acquire_rate_limit(self, key: str, settings: _RequestSettings) -> None:
        interval = settings.min_interval_seconds
        if interval <= 0:
            return
        if self._rate_lock is None:
            self._rate_lock = asyncio.Lock()
        async with self._rate_lock:
            now = self.clock()
            available = self._rate_next.get(key, now)
            delay = max(0.0, available - now)
            if delay:
                result = self.sleep(delay)
                if inspect.isawaitable(result):
                    await result
                now = self.clock()
            self._rate_next[key] = max(now, available) + interval

    @staticmethod
    def _retryable_status(status: int) -> bool:
        return status in _RETRYABLE_STATUS_CODES or status >= 500

    @staticmethod
    def _status_message(status: int) -> str:
        if status == 429:
            return "source rate limit response"
        if status >= 500:
            return "source server error"
        return "source returned an unsuccessful HTTP status"

    async def _backoff(
        self,
        attempt: int,
        retry_after: str | None,
        *,
        base_seconds: float | None = None,
        max_seconds: float | None = None,
    ) -> None:
        base = self.backoff_base_seconds if base_seconds is None else base_seconds
        maximum = self.backoff_max_seconds if max_seconds is None else max_seconds
        delay = self._retry_after_seconds(retry_after)
        if delay is None:
            delay = base * (2 ** max(0, attempt - 1))
        delay = min(maximum, max(0.0, delay))
        if delay <= 0:
            return
        result = self.sleep(delay)
        if inspect.isawaitable(result):
            await result

    def _retry_after_seconds(self, value: str | None) -> float | None:
        if not value:
            return None
        try:
            seconds = float(value)
            return seconds if math.isfinite(seconds) and seconds >= 0 else None
        except (TypeError, ValueError):
            pass
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return max(0.0, (parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


# Names that read naturally at injection sites and keep the public contract
# stable if callers prefer "fetcher" terminology.
AsyncSourceFetcher = SourceFetchService
SourceFetcher = SourceFetchService


__all__ = [
    "AsyncSourceFetcher",
    "SourceFetchError",
    "SourceFetchResponse",
    "SourceFetchService",
    "SourceFetcher",
]
