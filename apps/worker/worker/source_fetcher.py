"""Bounded asynchronous HTTP fetching for worker source adapters.

The content domain deliberately owns parsing, while this module owns the
small amount of I/O needed to obtain a source payload.  ``SourceFetchService``
accepts an ``httpx`` transport (``httpx.MockTransport`` is particularly handy
for tests), so callers never need to patch a global HTTP client or make a
public-network request in a unit test.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

try:
    from apps.api.app.domains.content.canonical import canonicalize_url
    from apps.api.app.domains.content.policy import CrawlerPolicyGuard
except ImportError:  # pragma: no cover - supports PYTHONPATH=apps/worker.
    from api.app.domains.content.canonical import canonicalize_url  # type: ignore
    from api.app.domains.content.policy import CrawlerPolicyGuard  # type: ignore


_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429})
_DEFAULT_USER_AGENT = "perspective-news-worker/1.0"
_DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
_APPROVED_POLICY_STATUS = "APPROVED"
_DEFAULT_RATE_LIMIT_PER_MINUTE = 0


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
        content_type = self.headers.get("content-type", "")
        charset = "utf-8"
        marker = "charset="
        if marker in content_type.lower():
            candidate = content_type.lower().split(marker, 1)[1].split(";", 1)[0].strip()
            if candidate:
                charset = candidate
        try:
            return self.body.decode(charset, errors="replace")
        except (LookupError, UnicodeError):
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
            follow_redirects=settings.follow_redirects,
            max_redirects=settings.max_redirects,
        ) as owned_client:
            return await self._request_with_client(owned_client, url, source, settings=settings)

    async def _request_with_client(
        self,
        client: httpx.AsyncClient,
        url: str,
        source: Mapping[str, Any],
        *,
        settings: _RequestSettings | None = None,
    ) -> SourceFetchResponse:
        settings = settings or self._request_settings(source, source_kind="API")
        total_attempts = settings.max_retries + 1
        last_error: BaseException | None = None
        for attempt in range(1, total_attempts + 1):
            try:
                await self._acquire_rate_limit(self._rate_key(source, url), settings)
                if callable(getattr(client, "stream", None)):
                    response, body = await self._stream_response(client, url, settings)
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
                        "headers": dict(settings.headers),
                        "params": settings.params,
                    }
                    if settings.content is not None:
                        kwargs["content"] = settings.content
                    if settings.json_body is not None:
                        kwargs["json"] = settings.json_body
                    if request.__name__ == "get":
                        response_call = request(url, **kwargs)
                    else:
                        response_call = request(settings.method, url, **kwargs)
                    response = await asyncio.wait_for(response_call, timeout=settings.timeout_seconds)
                    body = self._bounded_body(response.content, settings.max_response_bytes)
                status = response.status_code
                if 200 <= status < 300:
                    return SourceFetchResponse(
                        url=str(response.url or url),
                        status_code=status,
                        headers=dict(response.headers),
                        body=body,
                        fetched_at=datetime.now(UTC),
                        attempts=attempt,
                    )
                if self._retryable_status(status) and attempt < total_attempts:
                    await self._backoff(
                        attempt,
                        response.headers.get("retry-after"),
                        base_seconds=settings.backoff_base_seconds,
                        max_seconds=settings.backoff_max_seconds,
                    )
                    continue
                raise SourceFetchError(
                    self._status_message(status),
                    code=("SOURCE_FETCH_RETRY_EXHAUSTED" if self._retryable_status(status) else "SOURCE_HTTP_ERROR"),
                    retryable=self._retryable_status(status),
                    details={"status_code": status, "attempts": attempt},
                )
            except SourceFetchError:
                raise
            except (TimeoutError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt < total_attempts:
                    await self._backoff(
                        attempt,
                        None,
                        base_seconds=settings.backoff_base_seconds,
                        max_seconds=settings.backoff_max_seconds,
                    )
                    continue
                raise SourceFetchError(
                    "source request timed out",
                    code="SOURCE_FETCH_TIMEOUT",
                    retryable=True,
                    details={"attempts": attempt},
                ) from exc
            except httpx.TransportError as exc:
                last_error = exc
                if attempt < total_attempts:
                    await self._backoff(
                        attempt,
                        None,
                        base_seconds=settings.backoff_base_seconds,
                        max_seconds=settings.backoff_max_seconds,
                    )
                    continue
                raise SourceFetchError(
                    "source transport failed",
                    code="SOURCE_FETCH_TRANSPORT_ERROR",
                    retryable=True,
                    details={"attempts": attempt, "exception": exc.__class__.__name__},
                ) from exc
            except Exception as exc:
                # A custom transport may raise a non-httpx exception.  Keep
                # the worker boundary structured and body-free rather than
                # allowing arbitrary exception text into durable job errors.
                last_error = exc
                if attempt < total_attempts:
                    await self._backoff(
                        attempt,
                        None,
                        base_seconds=settings.backoff_base_seconds,
                        max_seconds=settings.backoff_max_seconds,
                    )
                    continue
                raise SourceFetchError(
                    "source request failed",
                    code="SOURCE_FETCH_ERROR",
                    retryable=True,
                    details={"attempts": attempt, "exception": exc.__class__.__name__},
                ) from exc
        # The loop is finite by construction.  Keep a defensive boundary in
        # case a future change alters the control flow.
        raise SourceFetchError(
            "source request failed",
            code="SOURCE_FETCH_ERROR",
            retryable=True,
            details={"attempts": total_attempts, "exception": type(last_error).__name__ if last_error else None},
        )

    async def _stream_response(
        self,
        client: httpx.AsyncClient,
        url: str,
        settings: _RequestSettings,
    ) -> tuple[httpx.Response, bytes]:
        request_kwargs: dict[str, Any] = {
            "headers": dict(settings.headers),
            "params": settings.params,
        }
        if settings.content is not None:
            request_kwargs["content"] = settings.content
        if settings.json_body is not None:
            request_kwargs["json"] = settings.json_body
        try:
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
