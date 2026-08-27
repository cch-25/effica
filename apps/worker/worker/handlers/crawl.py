"""Source crawl handler.

The handler keeps the historical deterministic fetch-plan behaviour when a
job is in fixture mode without a fixture payload.  A live-mode job uses the
injected ``source_fetcher`` service, then hands its bounded response to the
canonical API/RSS/crawler adapters.  No HTTP client is constructed here; the
worker runtime owns that service and can inject a fully offline transport.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

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
    # Admin-created crawl jobs include a URL, but adapter fields, pagination,
    # rate limits and retention live only on source_adapters.  Looking up the
    # source only when URL was absent silently discarded all of that production
    # configuration and is a direct cause of empty/misparsed crawls.
    if source.get("source_id"):
        loaded = await lookup_service(
            context,
            ("source_lookup", "load_source", "sources"),
            identifier=source.get("source_id"),
            payload=source,
        )
        if isinstance(loaded, Mapping):
            # Explicit job fields (mode/request metadata and policy snapshots)
            # remain authoritative over the current source row.
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
        candidates, parse_stats = _parse_payload_resilient(
            source_type,
            payload_value,
            source_id=source_id,
            url=url,
            policy=_crawler_guard(source_type, source),
            config=adapter_config,
        )
        candidates, pagination_stats = await _fetch_additional_pages(
            fetcher,
            source,
            source_type=source_type,
            source_id=source_id,
            initial_url=url,
            initial_payload=payload_value,
            initial_response=response,
            initial_candidates=candidates,
            policy=_crawler_guard(source_type, source),
            config=adapter_config,
        )
        for key in ("parse_item_count", "parse_rejected_count"):
            parse_stats[key] = parse_stats.get(key, 0) + int(pagination_stats.pop(key, 0) or 0)
        discovery_stats: dict[str, Any] = {}
        hydration_stats: dict[str, Any] = {}
        candidates = _limit_candidates(
            _deduplicate_candidates(candidates), adapter_config.get("max_items")
        )
        if source_type == "RSS" and _config_bool(
            adapter_config.get("hydrate_article_links"), default=False
        ):
            candidates, hydration_stats = await _hydrate_rss_articles(
                fetcher,
                source,
                source_id=source_id,
                seed_url=url,
                initial_candidates=candidates,
                config=adapter_config,
            )
        if source_type == "CRAWLER":
            candidates, discovery_stats = await _fetch_discovered_articles(
                fetcher,
                source,
                source_id=source_id,
                seed_url=url,
                seed_payload=payload_value,
                initial_candidates=candidates,
                policy=_crawler_guard(source_type, source),
                config=adapter_config,
            )
        candidates = _limit_candidates(
            _deduplicate_candidates(candidates), adapter_config.get("max_items")
        )
        if not candidates and not _config_bool(
            adapter_config.get("allow_empty_result"), default=False
        ):
            raise NonRetryableHandlerError(
                "source returned no usable article metadata",
                code="SOURCE_NO_ARTICLES",
                details={
                    "source_type": source_type,
                    "parse_item_count": parse_stats.get("parse_item_count", 0),
                    "parse_rejected_count": parse_stats.get("parse_rejected_count", 0),
                },
            )
    except SourceFetchError as exc:
        error_type = RetryableHandlerError if exc.retryable else NonRetryableHandlerError
        raise error_type(str(exc), code=exc.code, details=exc.details) from exc
    except CrawlerPolicyError as exc:
        raise NonRetryableHandlerError(
            "crawler policy, robots and terms approval are required",
            code="CRAWLER_POLICY_NOT_APPROVED",
        ) from exc
    except (NonRetryableHandlerError, RetryableHandlerError):
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
        extra_stats={
            **parse_stats,
            **pagination_stats,
            **hydration_stats,
            **discovery_stats,
        },
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
        # ElementTree can honour the XML encoding declaration only when it
        # receives bytes, but Python's bundled Expat still rejects some common
        # multibyte encodings (notably EUC-KR).  Preserve supported raw XML and
        # transcode only that unsupported case to an honest UTF-8 declaration.
        try:
            ElementTree.fromstring(response.body)
            return response.body
        except (ElementTree.ParseError, ValueError):
            decoded = response.text
            decoded = re.sub(
                r"(<\?xml\b[^>]*\bencoding\s*=\s*)[\"'][^\"']+[\"']",
                r'\1"utf-8"',
                decoded,
                count=1,
                flags=re.I,
            )
            return decoded.encode("utf-8")
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


def _parse_payload_resilient(
    source_type: str,
    payload: Any,
    *,
    source_id: Any,
    url: str,
    policy: CrawlerPolicyGuard | None,
    config: Mapping[str, Any] | None = None,
) -> tuple[list[ArticleCandidate], dict[str, int]]:
    """Keep valid API articles when one malformed item shares the response.

    APIAdapter deliberately fails fast for a malformed candidate.  At the
    ingestion boundary that used to discard every valid sibling in the same
    response.  Parse the already-discovered API item list independently,
    surface a rejected count, and still fail when *all* supplied items are
    invalid so a broken field mapping cannot masquerade as an empty feed.
    """

    if source_type != "API":
        return (
            _parse_payload(
                source_type,
                payload,
                source_id=source_id,
                url=url,
                policy=policy,
                config=config,
            ),
            {"parse_item_count": 0, "parse_rejected_count": 0},
        )
    adapter = APIAdapter(None if source_id is None else str(source_id), config)
    items = adapter._items(payload)  # type: ignore[attr-defined]
    if not isinstance(items, Iterable) or isinstance(
        items, (str, bytes, bytearray, Mapping)
    ):
        # Preserve the adapter's canonical error for a structurally invalid
        # response rather than silently treating it as no news.
        return adapter.parse(payload), {"parse_item_count": 0, "parse_rejected_count": 0}
    accepted: list[ArticleCandidate] = []
    scanned = 0
    rejected = 0
    for item in items:
        scanned += 1
        if not isinstance(item, Mapping):
            rejected += 1
            continue
        try:
            parsed = adapter.parse([item])
        except (TypeError, ValueError):
            rejected += 1
            continue
        if not parsed:
            rejected += 1
            continue
        accepted.extend(parsed)
    if scanned and rejected == scanned:
        raise ValueError("all API article items were invalid")
    return accepted, {"parse_item_count": scanned, "parse_rejected_count": rejected}


async def _fetch_additional_pages(
    fetcher: Any,
    source: Mapping[str, Any],
    *,
    source_type: str,
    source_id: Any,
    initial_url: str,
    initial_payload: Any,
    initial_response: SourceFetchResponse,
    initial_candidates: list[ArticleCandidate],
    policy: CrawlerPolicyGuard | None,
    config: Mapping[str, Any],
) -> tuple[list[ArticleCandidate], dict[str, Any]]:
    """Follow explicit API/RSS next links with hard bounds and partial success."""

    stats: dict[str, Any] = {
        "pages_fetched": 1,
        "page_failures": 0,
        "pagination_cycle_detected": False,
    }
    if source_type not in {"API", "RSS"} or not _pagination_enabled(config):
        return list(initial_candidates), stats
    pagination = config.get("pagination")
    page_config = dict(pagination) if isinstance(pagination, Mapping) else {}
    max_pages = _bounded_positive_int(
        page_config.get("max_pages", config.get("max_pages")), default=10, maximum=25
    )
    if max_pages <= 1:
        return list(initial_candidates), stats

    candidates = list(initial_candidates)
    current_payload = initial_payload
    current_response = initial_response
    seen = {_normalised_navigation_url(initial_url), _normalised_navigation_url(initial_response.url)}
    failure_counts: Counter[str] = Counter()
    last_failure_retryable = False
    while stats["pages_fetched"] < max_pages:
        if _candidate_limit_reached(candidates, config.get("max_items")):
            stats["pagination_stopped_at_item_limit"] = True
            break
        raw_next = _next_page_reference(
            source_type,
            current_payload,
            current_response,
            page_config=page_config,
        )
        if not raw_next:
            break
        next_url = _resolve_navigation_url(current_response.url, raw_next)
        if next_url is None:
            failure_counts["SOURCE_PAGINATION_URL_INVALID"] += 1
            stats["page_failures"] += 1
            break
        normalised = _normalised_navigation_url(next_url)
        if normalised in seen:
            stats["pagination_cycle_detected"] = True
            break
        if not _navigation_allowed(
            initial_url,
            next_url,
            config,
            purpose="pagination",
        ):
            failure_counts["SOURCE_PAGINATION_ORIGIN_BLOCKED"] += 1
            stats["page_failures"] += 1
            break
        seen.add(normalised)
        child_source = _navigation_source(
            source,
            next_url,
            config,
            purpose="page",
            seed_url=initial_url,
        )
        try:
            fetched = await _invoke_source_fetcher(fetcher, child_source, next_url)
            response = _coerce_response(fetched, url=next_url, source_type=source_type)
            page_payload = _payload_for_adapter(source_type, response)
            page_candidates, page_parse_stats = _parse_payload_resilient(
                source_type,
                page_payload,
                source_id=source_id,
                url=next_url,
                policy=policy,
                config=config,
            )
        except SourceFetchError as exc:
            failure_counts[exc.code] += 1
            stats["page_failures"] += 1
            last_failure_retryable = exc.retryable
            break
        except (TypeError, ValueError, ElementTree.ParseError):
            failure_counts["SOURCE_PAGE_PARSE_FAILED"] += 1
            stats["page_failures"] += 1
            break
        candidates.extend(page_candidates)
        stats["pages_fetched"] += 1
        stats["parse_item_count"] = stats.get("parse_item_count", 0) + page_parse_stats.get(
            "parse_item_count", 0
        )
        stats["parse_rejected_count"] = stats.get(
            "parse_rejected_count", 0
        ) + page_parse_stats.get("parse_rejected_count", 0)
        current_payload = page_payload
        current_response = response
    if failure_counts:
        stats["page_failure_counts"] = dict(sorted(failure_counts.items()))
    if not candidates and failure_counts:
        error_type = RetryableHandlerError if last_failure_retryable else NonRetryableHandlerError
        raise error_type(
            "source pagination failed before yielding an article",
            code="SOURCE_PAGINATION_FAILED",
            details={"failure_counts": dict(sorted(failure_counts.items()))},
        )
    return candidates, stats


async def _fetch_discovered_articles(
    fetcher: Any,
    source: Mapping[str, Any],
    *,
    source_id: Any,
    seed_url: str,
    seed_payload: Any,
    initial_candidates: list[ArticleCandidate],
    policy: CrawlerPolicyGuard,
    config: Mapping[str, Any],
) -> tuple[list[ArticleCandidate], dict[str, Any]]:
    """Turn crawler index links into real, body-bearing article candidates."""

    candidates = list(initial_candidates)
    discover_enabled = _config_bool(config.get("discover_links"), default=True)
    if discover_enabled and isinstance(seed_payload, Mapping):
        body_threshold = _bounded_nonnegative_int(
            config.get("discovery_body_threshold"), default=80, maximum=10_000
        )
        discover_always = _config_bool(
            config.get("discover_links_always"), default=False
        ) or str(config.get("page_type", "")).strip().lower() in {
            "index",
            "listing",
            "section",
        }
        if discover_always or max((len(item.body.strip()) for item in candidates), default=0) < body_threshold:
            adapter = CrawlerAdapter(
                None if source_id is None else str(source_id),
                policy,
                config,
            )
            candidates.extend(adapter.discover_links(seed_payload))

    candidates = _deduplicate_candidates(candidates)
    rich_initial = [candidate for candidate in candidates if candidate.body.strip()]
    discovered = [
        candidate
        for candidate in candidates
        if not candidate.body.strip()
        and _normalised_navigation_url(candidate.url) != _normalised_navigation_url(seed_url)
        and _navigation_allowed(seed_url, candidate.url, config, purpose="discovery")
    ]
    max_fetches = _bounded_positive_int(
        config.get("max_article_fetches", config.get("max_links")),
        default=40,
        maximum=100,
    )
    scheduled = discovered[:max_fetches]
    concurrency = _bounded_positive_int(
        config.get("fetch_concurrency"), default=4, maximum=12
    )
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(candidate: ArticleCandidate) -> tuple[list[ArticleCandidate], str | None, bool]:
        async with semaphore:
            child_source = _navigation_source(
                source,
                candidate.url,
                {**dict(config), "discover_links": False},
                purpose="article",
                seed_url=seed_url,
            )
            try:
                fetched = await _invoke_source_fetcher(fetcher, child_source, candidate.url)
                response = _coerce_response(
                    fetched, url=candidate.url, source_type="CRAWLER"
                )
                child_payload = _payload_for_adapter("CRAWLER", response)
                parsed, _parse_stats = _parse_payload_resilient(
                    "CRAWLER",
                    child_payload,
                    source_id=source_id,
                    url=candidate.url,
                    policy=policy,
                    config={**dict(config), "discover_links": False},
                )
                rich = [item for item in parsed if item.body.strip()]
                if not rich:
                    return [], "SOURCE_DISCOVERED_ARTICLE_EMPTY", False
                return rich, None, False
            except SourceFetchError as exc:
                return [], exc.code, exc.retryable
            except (CrawlerPolicyError, PermissionError):
                return [], "CRAWLER_POLICY_NOT_APPROVED", False
            except Exception:
                return [], "SOURCE_DISCOVERED_ARTICLE_PARSE_FAILED", False

    results = await asyncio.gather(*(fetch_one(candidate) for candidate in scheduled))
    fetched_articles: list[ArticleCandidate] = []
    failure_counts: Counter[str] = Counter()
    retryable_failure = False
    for parsed, error_code, retryable in results:
        fetched_articles.extend(parsed)
        if error_code:
            failure_counts[error_code] += 1
            retryable_failure = retryable_failure or retryable
    stats: dict[str, Any] = {
        "discovered_count": len(discovered),
        "article_fetch_attempted": len(scheduled),
        "article_fetch_succeeded": len(results) - sum(failure_counts.values()),
        "article_fetch_failed": sum(failure_counts.values()),
        "article_fetch_skipped": max(0, len(discovered) - len(scheduled)),
    }
    if failure_counts:
        stats["article_fetch_failure_counts"] = dict(sorted(failure_counts.items()))

    articles = _deduplicate_candidates([*rich_initial, *fetched_articles])
    if _config_bool(config.get("persist_unfetched_links"), default=False):
        articles = _deduplicate_candidates([*articles, *discovered])
    if not articles and failure_counts:
        error_type = RetryableHandlerError if retryable_failure else NonRetryableHandlerError
        raise error_type(
            "discovered article pages failed before yielding usable content",
            code="SOURCE_DISCOVERY_FETCH_FAILED",
            details={"failure_counts": dict(sorted(failure_counts.items()))},
        )
    if not articles and not _config_bool(config.get("allow_empty_result"), default=False):
        raise NonRetryableHandlerError(
            "crawler page yielded no body-bearing articles",
            code="SOURCE_NO_ARTICLES",
            details={"discovered_count": len(discovered)},
        )
    return articles, stats


async def _hydrate_rss_articles(
    fetcher: Any,
    source: Mapping[str, Any],
    *,
    source_id: Any,
    seed_url: str,
    initial_candidates: list[ArticleCandidate],
    config: Mapping[str, Any],
) -> tuple[list[ArticleCandidate], dict[str, Any]]:
    """Replace short RSS summaries with approved article-page bodies.

    This path is deliberately opt-in.  A feed fetch does not automatically
    grant permission to crawl every linked page, so all three crawler policy
    statuses must be approved before the option can perform network I/O.
    """

    if any(
        str(source.get(key, "")).upper() != _APPROVED_POLICY_STATUS
        for key in ("policy_status", "robots_status", "terms_status")
    ):
        raise NonRetryableHandlerError(
            "RSS article hydration requires approved policy, robots and terms status",
            code="RSS_HYDRATION_POLICY_NOT_APPROVED",
        )
    try:
        policy = CrawlerPolicyGuard.from_source(source)
        policy.check()
    except PermissionError as exc:
        raise NonRetryableHandlerError(
            "RSS article hydration requires approved policy, robots and terms status",
            code="RSS_HYDRATION_POLICY_NOT_APPROVED",
        ) from exc

    minimum_chars = _bounded_nonnegative_int(
        config.get("hydrate_min_body_chars"), default=300, maximum=100_000
    )
    eligible: list[tuple[int, ArticleCandidate]] = []
    origin_skipped = 0
    for index, candidate in enumerate(initial_candidates):
        if len(candidate.body.strip()) >= minimum_chars:
            continue
        if not _navigation_allowed(seed_url, candidate.url, config, purpose="hydration"):
            origin_skipped += 1
            continue
        eligible.append((index, candidate))
    max_fetches = _bounded_positive_int(
        config.get("max_hydration_fetches", config.get("max_article_fetches")),
        default=40,
        maximum=100,
    )
    scheduled = eligible[:max_fetches]
    concurrency = _bounded_positive_int(
        config.get("hydration_concurrency", config.get("fetch_concurrency")),
        default=4,
        maximum=12,
    )
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(
        index: int, candidate: ArticleCandidate
    ) -> tuple[int, ArticleCandidate | None, str | None]:
        async with semaphore:
            child_source = _navigation_source(
                source,
                candidate.url,
                {**dict(config), "discover_links": False},
                purpose="hydration",
                seed_url=seed_url,
            )
            # The fetch service must enforce crawler policy and advertise HTML
            # for an article page, rather than reusing the RSS Accept header.
            child_source["source_type"] = "CRAWLER"
            child_source["adapter_type"] = "CRAWLER"
            try:
                fetched = await _invoke_source_fetcher(fetcher, child_source, candidate.url)
                response = _coerce_response(
                    fetched, url=candidate.url, source_type="CRAWLER"
                )
                child_payload = _payload_for_adapter("CRAWLER", response)
                parsed, _parse_stats = _parse_payload_resilient(
                    "CRAWLER",
                    child_payload,
                    source_id=source_id,
                    url=candidate.url,
                    policy=policy,
                    config={**dict(config), "discover_links": False},
                )
                rich = max(
                    (item for item in parsed if item.body.strip()),
                    key=lambda item: len(item.body),
                    default=None,
                )
                if rich is None:
                    return index, None, "RSS_HYDRATED_ARTICLE_EMPTY"
                hydrated = ArticleCandidate(
                    url=rich.url,
                    title=rich.title or candidate.title,
                    body=rich.body,
                    author=rich.author or candidate.author,
                    published_at=candidate.published_at or rich.published_at,
                    source_id=candidate.source_id,
                    raw_payload=rich.raw_payload,
                    external_id=candidate.external_id,
                    adapter_type=candidate.adapter_type,
                )
                return index, hydrated, None
            except SourceFetchError as exc:
                return index, None, exc.code
            except Exception:
                return index, None, "RSS_HYDRATED_ARTICLE_PARSE_FAILED"

    results = await asyncio.gather(
        *(fetch_one(index, candidate) for index, candidate in scheduled)
    )
    articles = list(initial_candidates)
    failure_counts: Counter[str] = Counter()
    succeeded = 0
    for index, hydrated, error_code in results:
        if hydrated is not None:
            articles[index] = hydrated
            succeeded += 1
        elif error_code:
            failure_counts[error_code] += 1
    stats: dict[str, Any] = {
        "hydration_eligible_count": len(eligible),
        "hydration_attempted": len(scheduled),
        "hydration_succeeded": succeeded,
        "hydration_failed": sum(failure_counts.values()),
        "hydration_skipped": max(0, len(eligible) - len(scheduled)) + origin_skipped,
        "hydration_origin_skipped": origin_skipped,
    }
    if failure_counts:
        stats["hydration_failure_counts"] = dict(sorted(failure_counts.items()))
    return _deduplicate_candidates(articles), stats


def _pagination_enabled(config: Mapping[str, Any]) -> bool:
    pagination = config.get("pagination")
    if isinstance(pagination, Mapping) and "enabled" in pagination:
        return _config_bool(pagination.get("enabled"), default=True)
    return _config_bool(config.get("paginate"), default=True)


def _next_page_reference(
    source_type: str,
    payload: Any,
    response: SourceFetchResponse,
    *,
    page_config: Mapping[str, Any],
) -> str | None:
    header_next = _link_header_next(response.headers.get("link"))
    if header_next:
        return header_next
    if source_type == "API" and isinstance(payload, Mapping):
        configured = page_config.get("next_path") or page_config.get("next_url_path")
        paths = [configured] if configured else [
            "next",
            "next_url",
            "nextUrl",
            "links.next",
            "pagination.next",
            "paging.next",
            "meta.next",
            "response.next",
        ]
        for path in paths:
            value = _mapping_path(payload, path)
            if isinstance(value, Mapping):
                value = value.get("href") or value.get("url")
            if isinstance(value, str) and value.strip():
                return value.strip()
    if source_type == "RSS" and isinstance(payload, (str, bytes, bytearray)):
        try:
            root = ElementTree.fromstring(payload)
        except (ElementTree.ParseError, ValueError):
            return None
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1].lower() != "link":
                continue
            if str(node.attrib.get("rel", "")).lower() == "next" and node.attrib.get("href"):
                return str(node.attrib["href"]).strip()
    return None


def _link_header_next(value: str | None) -> str | None:
    if not value:
        return None
    for part in value.split(","):
        sections = [section.strip() for section in part.split(";")]
        if not sections or not sections[0].startswith("<") or not sections[0].endswith(">"):
            continue
        relations = " ".join(sections[1:]).lower()
        if "rel=next" in relations or 'rel="next"' in relations or "rel='next'" in relations:
            return sections[0][1:-1].strip()
    return None


def _mapping_path(mapping: Mapping[str, Any], path: Any) -> Any:
    if not isinstance(path, str) or not path:
        return None
    current: Any = mapping
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        if part in current:
            current = current[part]
            continue
        lowered = {str(key).lower(): value for key, value in current.items()}
        current = lowered.get(part.lower())
    return current


def _resolve_navigation_url(base_url: str, reference: str) -> str | None:
    value = str(reference).strip()
    if not value or value.lower().startswith(("javascript:", "data:", "file:")):
        return None
    # A bare cursor/token is not a URL.  Following it as a relative path would
    # send a surprising request (for example cursor "abc" -> /abc).  APIs that
    # use opaque cursors should expose a URL in next_path or a Link header.
    if "://" not in value and not value.startswith(("/", "?", "./", "../")):
        return None
    try:
        resolved = urljoin(base_url, value)
        parsed = urlsplit(resolved)
    except (TypeError, ValueError):
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    try:
        return canonical_url(resolved)
    except NonRetryableHandlerError:
        return None


def _normalised_navigation_url(value: str) -> str:
    try:
        return canonical_url(value)
    except (NonRetryableHandlerError, TypeError, ValueError):
        return str(value).strip()


def _navigation_allowed(
    seed_url: str,
    target_url: str,
    config: Mapping[str, Any],
    *,
    purpose: str,
) -> bool:
    try:
        seed_host = (urlsplit(seed_url).hostname or "").lower().removeprefix("www.")
        target_host = (urlsplit(target_url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return False
    if not seed_host or not target_host:
        return False
    if target_host == seed_host:
        return True
    domain_key = "pagination_domains" if purpose == "pagination" else "allowed_domains"
    allowed = config.get(domain_key)
    if isinstance(allowed, (list, tuple, set)):
        for item in allowed:
            domain = str(item).strip().lower()
            if "://" in domain:
                domain = (urlsplit(domain).hostname or "").lower()
            domain = domain.removeprefix("www.").lstrip(".")
            if domain and (target_host == domain or target_host.endswith(f".{domain}")):
                return True
    allow_key = "allow_external_pagination" if purpose == "pagination" else "allow_external_links"
    return _config_bool(config.get(allow_key), default=False)


def _navigation_source(
    source: Mapping[str, Any],
    url: str,
    config: Mapping[str, Any],
    *,
    purpose: str,
    seed_url: str,
) -> dict[str, Any]:
    """Build a GET child request without replaying index POST/query payloads."""

    child = dict(source)
    for key in ("config_json", "adapter_config", "config"):
        child.pop(key, None)
    child_config = dict(config)
    for key in ("params", "query_params", "body", "json", "http_method"):
        child_config.pop(key, None)
    child_config["method"] = "GET"
    override = config.get(f"{purpose}_request")
    if isinstance(override, Mapping):
        child_config.update(dict(override))
    if urlsplit(seed_url).hostname != urlsplit(url).hostname:
        # An explicitly allowed external link is still not authority to forward
        # API keys, cookies or a source-specific Authorization header.
        if not _config_bool(config.get("forward_cross_origin_credentials"), default=False):
            for holder in (child, child_config):
                headers = holder.get("headers")
                if isinstance(headers, Mapping):
                    holder["headers"] = {
                        key: value
                        for key, value in headers.items()
                        if str(key).lower()
                        not in {"authorization", "cookie", "proxy-authorization"}
                    }
    child["config"] = child_config
    child["url"] = url
    return child


def _deduplicate_candidates(candidates: Iterable[ArticleCandidate]) -> list[ArticleCandidate]:
    result: list[ArticleCandidate] = []
    positions: dict[str, int] = {}
    for candidate in candidates:
        key = candidate.canonical_url
        position = positions.get(key)
        if position is None:
            positions[key] = len(result)
            result.append(candidate)
            continue
        existing = result[position]
        existing_quality = (bool(existing.body.strip()), len(existing.body), bool(existing.title.strip()))
        candidate_quality = (
            bool(candidate.body.strip()),
            len(candidate.body),
            bool(candidate.title.strip()),
        )
        if candidate_quality > existing_quality:
            result[position] = candidate
    return result


def _candidate_limit_reached(candidates: Iterable[ArticleCandidate], raw_limit: Any) -> bool:
    limit = _optional_positive_int(raw_limit)
    return limit is not None and len(_deduplicate_candidates(candidates)) >= limit


def _limit_candidates(candidates: list[ArticleCandidate], raw_limit: Any) -> list[ArticleCandidate]:
    limit = _optional_positive_int(raw_limit)
    return candidates if limit is None else candidates[:limit]


def _optional_positive_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _bounded_positive_int(value: Any, *, default: int, maximum: int) -> int:
    parsed = _optional_positive_int(value)
    return min(maximum, parsed if parsed is not None else default)


def _bounded_nonnegative_int(value: Any, *, default: int, maximum: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(0, parsed))


def _config_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


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
    extra_stats: Mapping[str, Any] | None = None,
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
    if extra_stats:
        stats.update(dict(extra_stats))
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
