"""Source crawl handler.

The handler keeps the historical deterministic fetch-plan behaviour when a
job is in fixture mode without a fixture payload.  A live-mode job uses the
injected ``source_fetcher`` service, then hands its bounded response to the
canonical API/RSS/crawler adapters.  No HTTP client is constructed here; the
worker runtime owns that service and can inject a fully offline transport.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from apps.api.app.domains.content import (
        APIAdapter,
        ArticleCandidate,
        CrawlerAdapter,
        CrawlerPolicyError,
        CrawlerPolicyGuard,
        RSSAdapter,
    )
except ImportError:  # pragma: no cover - supports PYTHONPATH=apps/worker.
    from api.app.domains.content import (  # type: ignore
        APIAdapter,
        ArticleCandidate,
        CrawlerAdapter,
        CrawlerPolicyError,
        CrawlerPolicyGuard,
        RSSAdapter,
    )

from ..source_fetcher import SourceFetchError, SourceFetchResponse
from .base import (
    HandlerContext,
    HandlerResult,
    NonRetryableHandlerError,
    RetryableHandlerError,
    lookup_service,
    require_mapping,
    stable_digest,
)

JOB_TYPE = "crawl"

_APPROVED_POLICY_STATUS = "APPROVED"
_FIXTURE_KEYS = ("fixture_payload", "fixture", "response_payload")
_FETCHER_NAMES = ("source_fetcher", "fetch_source", "source_fetch_service")
_MISSING = object()


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NonRetryableHandlerError(
            "crawl URL must be an absolute HTTP(S) URL",
            code="INVALID_CRAWL_URL",
        )
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


async def handle(payload: Mapping[str, Any], context: HandlerContext | None = None) -> HandlerResult:
    require_mapping(payload)
    source = dict(payload)
    if source.get("url") in (None, "") and source.get("source_id"):
        loaded = await lookup_service(
            context,
            ("source_lookup", "load_source", "sources"),
            identifier=source.get("source_id"),
            payload=source,
        )
        if isinstance(loaded, Mapping):
            source = {**dict(loaded), **source}
    if source.get("url") in (None, ""):
        raise NonRetryableHandlerError(
            "crawl URL is required directly or through source lookup",
            code="INVALID_CRAWL_URL",
            details={"required_any": ["url", "source_id"]},
        )
    source_type = str(source.get("source_type", source.get("adapter_type", "API"))).upper()
    if source_type not in {"API", "RSS", "CRAWLER"}:
        raise NonRetryableHandlerError(
            "source_type must be API, RSS or CRAWLER",
            code="INVALID_SOURCE_TYPE",
            details={"source_type": source_type},
        )
    _check_crawler_policy(source_type, source)
    url = canonical_url(str(source["url"]))
    source["url"] = url
    source_id = source.get("source_id")
    # Validate adapter retention settings before a live request starts.  This
    # avoids fetching data that cannot be durably represented by the worker.
    _retention_days(source)
    adapter_config = _source_config(source)

    # Fixture mode is intentionally side-effect free.  It may still parse a
    # supplied fixture, which is useful for deterministic integration tests.
    fixture = _fixture_from(source)
    if fixture is not _MISSING:
        try:
            candidates = _parse_payload(
                source_type,
                fixture,
                source_id=source_id,
                url=url,
                policy=_crawler_guard(source_type, source),
                config=adapter_config,
            )
        except CrawlerPolicyError as exc:
            raise NonRetryableHandlerError(
                "crawler policy, robots and terms approval are required",
                code="CRAWLER_POLICY_NOT_APPROVED",
            ) from exc
        except Exception as exc:
            raise NonRetryableHandlerError(
                "source fixture could not be parsed",
                code="SOURCE_PARSE_FAILED",
                details={"source_type": source_type},
            ) from exc
        return _ingestion_result(
            source,
            url=url,
            source_id=source_id,
            candidates=candidates,
            response=None,
            fetched=False,
        )

    fetcher = _source_fetcher(context, source_id)
    mode = _resolved_crawl_mode(source, fetcher_present=fetcher is not None)
    source["mode"] = mode
    # No injected service means the old deterministic fetch plan remains the
    # result.  In particular, a direct URL without a fetcher never causes a
    # public-network request.  A present fetcher with no explicit fixture
    # mode is live, including identifier-only jobs whose source lookup omits
    # ``mode``.
    if fetcher is None or mode == "fixture":
        return HandlerResult(
            value={
                "source_id": source_id,
                "url": url,
                "fetch_key": stable_digest({"source_id": source_id, "url": url}),
                "robots_checked": source_type != "CRAWLER"
                or str(source.get("robots_status")).upper() == _APPROVED_POLICY_STATUS,
                "terms_accepted": source_type != "CRAWLER"
                or str(source.get("terms_status")).upper() == _APPROVED_POLICY_STATUS,
                "mode": mode,
            },
            side_effect_key=(context.idempotency_key if context else None),
        )

    try:
        fetched = await _invoke_source_fetcher(fetcher, source, url)
        response = _coerce_response(fetched, url=url, source_type=source_type)
        payload_value = _payload_for_adapter(source_type, response)
        candidates = _parse_payload(
            source_type,
            payload_value,
            source_id=source_id,
            url=url,
            policy=_crawler_guard(source_type, source),
            config=adapter_config,
        )
    except SourceFetchError as exc:
        error_type = RetryableHandlerError if exc.retryable else NonRetryableHandlerError
        raise error_type(str(exc), code=exc.code, details=exc.details) from exc
    except CrawlerPolicyError as exc:
        raise NonRetryableHandlerError(
            "crawler policy, robots and terms approval are required",
            code="CRAWLER_POLICY_NOT_APPROVED",
        ) from exc
    except NonRetryableHandlerError:
        raise
    except Exception as exc:
        # Parsing failures are source-data errors, not transient worker
        # failures.  Do not persist arbitrary parser text or response bodies.
        raise NonRetryableHandlerError(
            "source response could not be parsed",
            code="SOURCE_PARSE_FAILED",
            details={"source_type": source_type},
        ) from exc
    return _ingestion_result(
        source,
        url=url,
        source_id=source_id,
        candidates=candidates,
        response=response,
        fetched=True,
    )


def _check_crawler_policy(source_type: str, source: Mapping[str, Any]) -> None:
    if source_type != "CRAWLER":
        return
    # Check the aggregate source lifecycle status before touching the injected
    # fetcher.  The guard then checks both independent permissions.
    if str(source.get("policy_status", "UNKNOWN")).upper() != _APPROVED_POLICY_STATUS:
        raise NonRetryableHandlerError(
            "crawler policy, robots and terms approval are required",
            code="CRAWLER_POLICY_NOT_APPROVED",
        )
    try:
        CrawlerPolicyGuard.from_source(source).check()
    except PermissionError as exc:
        raise NonRetryableHandlerError(
            "crawler policy, robots and terms approval are required",
            code="CRAWLER_POLICY_NOT_APPROVED",
        ) from exc


def _crawler_guard(source_type: str, source: Mapping[str, Any]) -> CrawlerPolicyGuard | None:
    if source_type != "CRAWLER":
        return None
    return CrawlerPolicyGuard.from_source(source)


def _resolved_crawl_mode(source: Mapping[str, Any], *, fetcher_present: bool) -> str:
    """Return fixture only when explicitly requested or no fetcher exists.

    Identifier-only producers look up a source row that has no ``mode``.
    Treating that omission as fixture would succeed an empty crawl even
    when a live ``source_fetcher`` is injected.
    """

    raw = source.get("mode", _MISSING)
    if raw is not _MISSING and raw not in (None, ""):
        return str(raw).lower()
    return "live" if fetcher_present else "fixture"


def _fixture_from(source: Mapping[str, Any]) -> Any:
    for key in _FIXTURE_KEYS:
        if key in source and source[key] is not None:
            return source[key]
    if "articles" in source and source["articles"] is not None:
        return source["articles"]
    return _MISSING


def _source_fetcher(context: HandlerContext | None, source_id: Any) -> Any:
    if context is None:
        return None
    for name in _FETCHER_NAMES:
        candidate = context.services.get(name)
        if candidate is None:
            continue
        # A mapping is useful for tests with one fetcher per source.  A
        # callable service or object with ``fetch`` is returned unchanged.
        if isinstance(candidate, Mapping) and not callable(candidate):
            if source_id in candidate:
                return candidate[source_id]
            if str(source_id) in candidate:
                return candidate[str(source_id)]
            continue
        return candidate
    return None


async def _invoke_source_fetcher(fetcher: Any, source: Mapping[str, Any], url: str) -> Any:
    target = getattr(fetcher, "fetch", None)
    if not callable(target):
        target = fetcher
    if not callable(target):
        raise NonRetryableHandlerError(
            "source_fetcher must be callable or expose fetch()",
            code="INVALID_SOURCE_FETCHER",
        )
    argument: Any = source
    try:
        signature = inspect.signature(target)
        parameters = list(signature.parameters.values())
        first = next(
            (
                parameter
                for parameter in parameters
                if parameter.kind
                in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
            ),
            None,
        )
        if first is not None and first.name.lower() in {"url", "uri", "endpoint"}:
            argument = url
    except (TypeError, ValueError):
        pass
    result = target(argument)
    if inspect.isawaitable(result):
        return await result
    return result


def _coerce_response(
    value: Any,
    *,
    url: str,
    source_type: str = "API",
) -> SourceFetchResponse:
    if isinstance(value, SourceFetchResponse):
        return value
    # Allow simple fake clients to return an httpx.Response directly.
    try:
        import httpx

        if isinstance(value, httpx.Response):
            return SourceFetchResponse(
                url=str(value.url or url),
                status_code=value.status_code,
                headers=dict(value.headers),
                body=value.content,
                fetched_at=datetime.now(UTC),
                attempts=1,
            )
    except ImportError:  # pragma: no cover - httpx is an application dependency.
        pass
    if isinstance(value, Mapping) and source_type == "CRAWLER" and "html" in value:
        html = value.get("html")
        if isinstance(html, str):
            body = html.encode("utf-8")
        elif isinstance(html, (bytes, bytearray)):
            body = bytes(html)
        else:
            body = str(html or "").encode("utf-8")
        return SourceFetchResponse(
            url=str(value.get("url") or url),
            status_code=int(value.get("status_code", 200)),
            headers={"content-type": "text/html; charset=utf-8"},
            body=body,
            fetched_at=datetime.now(UTC),
            attempts=max(1, int(value.get("attempts", 1))),
        )
    if isinstance(value, Mapping) and _looks_like_response(value):
        response_body = value.get("body", value.get("content", value.get("payload", b"")))
        if isinstance(response_body, str):
            encoded_body = response_body.encode("utf-8")
        elif isinstance(response_body, (bytes, bytearray)):
            encoded_body = bytes(response_body)
        else:
            encoded_body = json.dumps(
                response_body, ensure_ascii=False, default=str
            ).encode("utf-8")
        fetched_at = value.get("fetched_at")
        if not isinstance(fetched_at, datetime):
            fetched_at = datetime.now(UTC)
        elif fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        return SourceFetchResponse(
            url=str(value.get("url") or url),
            status_code=int(value.get("status_code", 200)),
            headers={str(k).lower(): str(v) for k, v in dict(value.get("headers") or {}).items()},
            body=encoded_body,
            fetched_at=fetched_at,
            attempts=max(1, int(value.get("attempts", 1))),
        )
    if isinstance(value, (bytes, bytearray)):
        return SourceFetchResponse(url=url, status_code=200, body=bytes(value))
    if isinstance(value, str):
        return SourceFetchResponse(url=url, status_code=200, body=value.encode("utf-8"))
    # A direct mapping/list is accepted as an already-decoded API payload.
    # JSON encoding keeps the response envelope uniform for the adapter.
    return SourceFetchResponse(
        url=url,
        status_code=200,
        headers={"content-type": "application/json"},
        body=json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"),
    )


def _looks_like_response(value: Mapping[str, Any]) -> bool:
    return any(key in value for key in ("body", "content", "payload", "status_code", "headers", "fetched_at"))


def _payload_for_adapter(source_type: str, response: SourceFetchResponse) -> Any:
    if response.status_code < 200 or response.status_code >= 300:
        retryable = response.status_code in {408, 425, 429} or response.status_code >= 500
        raise SourceFetchError(
            "source returned an unsuccessful HTTP status",
            code="SOURCE_HTTP_ERROR",
            retryable=retryable,
            details={"status_code": response.status_code, "attempts": response.attempts},
        )
    if source_type == "API":
        try:
            return response.json()
        except Exception as exc:
            raise ValueError("invalid API response") from exc
    if source_type == "RSS":
        return response.text
    if source_type == "CRAWLER":
        return {"url": response.url, "html": response.text}
    raise ValueError(f"unsupported source type: {source_type}")


def _parse_payload(
    source_type: str,
    payload: Any,
    *,
    source_id: Any,
    url: str,
    policy: CrawlerPolicyGuard | None,
    config: Mapping[str, Any] | None = None,
) -> list[ArticleCandidate]:
    if source_type == "API":
        return APIAdapter(None if source_id is None else str(source_id), config).parse(payload)
    if source_type == "RSS":
        return RSSAdapter(None if source_id is None else str(source_id), config).parse(payload)
    if source_type == "CRAWLER":
        if isinstance(payload, Mapping):
            if _looks_like_response(payload):
                payload = payload.get("body", payload.get("content", payload.get("payload")))
            if isinstance(payload, Mapping):
                crawler_payload = dict(payload)
                crawler_payload.setdefault("url", url)
            else:
                crawler_payload = {"url": url, "html": payload}
        else:
            crawler_payload = {"url": url, "html": payload}
        return CrawlerAdapter(
            None if source_id is None else str(source_id),
            policy,
            config,
        ).parse(crawler_payload)
    raise ValueError(f"unsupported source type: {source_type}")


def _retention_days(source: Mapping[str, Any]) -> int | None:
    value = source.get("raw_payload_retention_days")
    if value is None:
        config = _source_config(source)
        if isinstance(config, Mapping):
            value = config.get("raw_payload_retention_days", config.get("retention_days"))
    if value in (None, ""):
        return None
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise NonRetryableHandlerError(
            "raw payload retention days must be a non-negative integer",
            code="INVALID_RETENTION_POLICY",
        ) from exc
    if days < 0:
        raise NonRetryableHandlerError(
            "raw payload retention days must be a non-negative integer",
            code="INVALID_RETENTION_POLICY",
        )
    return days


def _source_config(source: Mapping[str, Any]) -> dict[str, Any]:
    """Merge adapter config aliases without letting it override source state.

    Worker lookups expose the joined adapter JSON as ``config`` while direct
    jobs and older callers use ``adapter_config``/``config_json``.  All three
    spellings remain accepted; nested ``adapter`` config is also flattened for
    source records produced by integrations.
    """

    merged: dict[str, Any] = {}
    for key in ("config_json", "adapter_config", "config"):
        value = source.get(key)
        if isinstance(value, Mapping):
            merged.update(dict(value))
    nested = merged.get("adapter")
    if isinstance(nested, Mapping):
        merged = {**dict(nested), **{key: value for key, value in merged.items() if key != "adapter"}}
    if source.get("rate_limit") is not None:
        merged.setdefault("rate_limit", source.get("rate_limit"))
    if source.get("raw_payload_retention_days") is not None:
        merged.setdefault("raw_payload_retention_days", source.get("raw_payload_retention_days"))
    return merged


def _ingestion_result(
    source: Mapping[str, Any],
    *,
    url: str,
    source_id: Any,
    candidates: list[ArticleCandidate],
    response: SourceFetchResponse | None,
    fetched: bool,
) -> HandlerResult:
    fetched_at = response.fetched_at if response is not None else datetime.now(UTC)
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    retention_days = _retention_days(source)
    expires_at = (
        fetched_at + timedelta(days=retention_days) if retention_days is not None else None
    )
    articles: list[dict[str, Any]] = []
    for candidate in candidates:
        article = candidate.as_dict()
        # DurableResultApplier consumes ``content`` while the canonical
        # adapter intentionally calls the field ``body``.
        article["content"] = candidate.body
        article["fetched_at"] = fetched_at
        article["raw_payload_retention_days"] = retention_days
        article["raw_payload_expires_at"] = expires_at
        articles.append(article)
    stats: dict[str, Any] = {
        "fetched": fetched,
        "article_count": len(articles),
    }
    if response is not None:
        stats.update(
            {
                "status_code": response.status_code,
                "attempts": response.attempts,
                "byte_size": len(response.body),
            }
        )
    value = {
        "source_id": source_id,
        "url": url,
        "fetch_key": stable_digest({"source_id": source_id, "url": url}),
        "mode": str(source.get("mode") or "fixture").lower(),
        "articles": articles,
        "stats": stats,
        "fetched_at": fetched_at,
        "raw_payload_retention_days": retention_days,
        "raw_payload_expires_at": expires_at,
    }
    return HandlerResult(
        value=value,
        side_effect_key=None,
    )


run = handle
