"""Analysis provider interfaces, controls, and deterministic model stubs.

The analysis domain intentionally keeps the provider boundary small and
synchronous.  ``DeterministicStubProvider`` is used by the offline vertical
slice, while ``HttpLLMProvider`` is a transport-injected adapter for a
configured model endpoint.  The HTTP adapter never persists or logs a raw
request/response: only validated public fields and aggregate metrics leave the
provider boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

import httpx

from .schema import AssessmentInput, AssessmentStatus, Evidence, ModelAssessment


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ProviderError(RuntimeError):
    """Base class for errors crossing the provider boundary.

    Error messages are deliberately generic.  In particular, they never
    include endpoint response bodies, prompts, source content, or credentials.
    ``code`` is safe to persist as a structured error field.
    """

    code = "PROVIDER_ERROR"
    retryable = True

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        self.code = code or type(self).code
        super().__init__(message or self.code)


class ProviderConfigurationError(ProviderError, ValueError):
    code = "PROVIDER_CONFIGURATION_ERROR"
    retryable = False


class ProviderTransportError(ProviderError):
    code = "PROVIDER_TRANSPORT_ERROR"


class ProviderTimeoutError(ProviderTransportError):
    code = "PROVIDER_TIMEOUT"


class ProviderHTTPError(ProviderTransportError):
    code = "PROVIDER_HTTP_ERROR"

    def __init__(self, status_code: int, *, retryable: bool = False) -> None:
        self.status_code = int(status_code)
        self.retryable = bool(retryable)
        super().__init__(code=self.code)


class ProviderRateLimitError(ProviderError):
    code = "PROVIDER_RATE_LIMITED"

    def __init__(self, retry_after_seconds: float = 0.0) -> None:
        self.retry_after_seconds = max(0.0, float(retry_after_seconds))
        super().__init__(code=self.code)


class ProviderCircuitOpenError(ProviderError):
    code = "PROVIDER_CIRCUIT_OPEN"


class ProviderSchemaError(ProviderError, ValueError):
    """A structurally invalid upstream response.

    The handler has already validated its own input before invoking a
    provider.  A schema rejection at this boundary is therefore an upstream
    generation failure and a fresh job attempt may produce a valid structured
    response.
    """

    code = "PROVIDER_SCHEMA_REJECTED"
    retryable = True


# Short aliases are useful to callers that use the control name rather than
# the provider-prefixed exception name.  The long names remain canonical.
RateLimitError = ProviderRateLimitError
CircuitOpenError = ProviderCircuitOpenError
SchemaValidationError = ProviderSchemaError


_MAX_RETRIES = 8
_MAX_BACKOFF_SECONDS = 60.0
_MAX_TIMEOUT_SECONDS = 300.0
_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_MAX_ARTICLE_PROMPT_CHARS = 60_000


@dataclass(frozen=True)
class ProviderConfig:
    """Server-side settings for one model alias.

    ``alias`` is the stable local identifier used by the ensemble, while
    ``actual_model_id`` is the model identifier sent to the configured
    provider.  ``endpoint`` and ``api_key`` are only needed by the HTTP
    adapter; the deterministic stub can continue using a keyless config.

    Retry and circuit values are intentionally bounded at configuration time
    so a transient outage cannot create unbounded work or sleep.
    """

    alias: str
    actual_model_id: str
    timeout_seconds: float = 20.0
    max_retries: int = 2
    rate_limit_per_minute: int = 60
    endpoint: str = ""
    reasoning_effort: str = "xhigh"
    model_alias_id: str | None = None
    api_key: str | None = field(default=None, repr=False)
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer"
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    retry_backoff_seconds: float = 0.1
    max_backoff_seconds: float = 2.0
    circuit_failure_threshold: int = 3
    circuit_reset_timeout_seconds: float = 30.0
    rate_limit_window_seconds: float = 60.0
    # ``endpoint_url``/``base_url`` and ``circuit_open_seconds`` are accepted
    # as configuration aliases for deployments that use those names.
    endpoint_url: str | None = field(default=None, repr=False)
    base_url: str | None = field(default=None, repr=False)
    circuit_open_seconds: float | None = field(default=None, repr=False)
    # Compatibility spelling used by a few service configurations.
    circuit_recovery_seconds: float | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.alias.strip() or not self.actual_model_id.strip():
            raise ValueError("provider alias and actual model id are required")
        if not math.isfinite(self.timeout_seconds) or not (
            0 < self.timeout_seconds <= _MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("provider timeout must be positive and bounded")
        if not isinstance(self.max_retries, int) or not 0 <= self.max_retries <= _MAX_RETRIES:
            raise ValueError(f"provider max_retries must be between 0 and {_MAX_RETRIES}")
        if not isinstance(self.rate_limit_per_minute, int) or self.rate_limit_per_minute <= 0:
            raise ValueError("provider rate_limit_per_minute must be positive")
        if not math.isfinite(self.retry_backoff_seconds) or self.retry_backoff_seconds < 0:
            raise ValueError("provider retry backoff cannot be negative")
        if not math.isfinite(self.max_backoff_seconds) or not (
            0 <= self.max_backoff_seconds <= _MAX_BACKOFF_SECONDS
        ):
            raise ValueError("provider max backoff is invalid")
        if self.retry_backoff_seconds > self.max_backoff_seconds:
            raise ValueError("provider retry backoff cannot exceed max backoff")
        if not isinstance(self.circuit_failure_threshold, int) or (
            self.circuit_failure_threshold < 1
        ):
            raise ValueError("provider circuit failure threshold must be positive")
        endpoint_aliases = [value for value in (self.endpoint_url, self.base_url) if value]
        if endpoint_aliases:
            if self.endpoint and any(value != self.endpoint for value in endpoint_aliases):
                raise ValueError("provider endpoint aliases disagree")
            object.__setattr__(self, "endpoint", endpoint_aliases[0])
        recovery_seconds = next(
            (
                value
                for value in (
                    self.circuit_recovery_seconds,
                    self.circuit_open_seconds,
                    self.circuit_reset_timeout_seconds,
                )
                if value is not None
            ),
        )
        if not math.isfinite(recovery_seconds) or recovery_seconds <= 0:
            raise ValueError("provider circuit reset timeout must be positive")
        object.__setattr__(self, "circuit_reset_timeout_seconds", float(recovery_seconds))
        if not math.isfinite(self.rate_limit_window_seconds) or self.rate_limit_window_seconds <= 0:
            raise ValueError("provider rate limit window must be positive")
        if self.endpoint:
            parsed = urlsplit(self.endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("provider endpoint must be an absolute HTTP(S) URL")
        if not self.api_key_header.strip():
            raise ValueError("provider api key header is required")
        if self.reasoning_effort not in {"none", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("provider reasoning effort is invalid")
        normalised_headers: dict[str, str] = {}
        for key, value in self.headers.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(value, str):
                raise ValueError("provider headers must be string pairs")
            normalised_headers[key.strip()] = value
        object.__setattr__(self, "headers", MappingProxyType(normalised_headers))


class LLMProvider(ABC):
    """Provider contract used by analysis workers."""

    config: ProviderConfig

    @abstractmethod
    def analyze_article(self, input: AssessmentInput, prompt_version: str) -> ModelAssessment:
        raise NotImplementedError

    def analyze(self, input: AssessmentInput, prompt_version: str) -> ModelAssessment:
        return self.analyze_article(input, prompt_version)


def mask_source_identity(
    text: str, source_name: str | None = None, source_url: str | None = None
) -> str:
    """Remove source identity tokens for content-first evaluation.

    The HTTP adapter does not send the source fields at all.  This helper is
    also used on title/body values because source names frequently occur in
    bylines, headlines, or copied article text.
    """

    result = str(text or "")
    values = [source_name or ""]
    if source_url:
        parsed = urlsplit(source_url)
        values.extend([source_url, parsed.netloc, parsed.hostname or ""])
    # Longest first prevents replacing a domain before its full URL.
    for value in sorted({item for item in values if item.strip()}, key=len, reverse=True):
        result = re.sub(re.escape(value), "[SOURCE]", result, flags=re.IGNORECASE)
    return result


_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(?:bearer|authorization|token|secret|password|passwd|api[_ -]?key|client[_ -]?secret)"
    r"\s*[:=]\s*[\"']?[^\s,;\"']+"
)
_BEARER_VALUE_RE = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_JWT_RE = re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b")
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)


def _redact_source_excerpts(text: str, source_text: str) -> str:
    """Remove long exact source fragments without retaining source content.

    We only inspect a bounded number of windows.  This keeps sanitisation
    predictable for very large articles while still catching copied passages
    of the lengths that are unsafe in a public rationale/evidence field.
    """

    compact = re.sub(r"\s+", " ", source_text).strip()
    if not compact:
        return text
    # The public value is bounded by the caller shortly afterwards.  Scan its
    # windows (rather than a fixed prefix of the source) so copied passages
    # near the end of a long article are still found.
    bounded_text = text[:4096]
    for size in (120, 80, 40):
        if len(compact) < size or len(bounded_text) < size:
            continue
        step = max(1, size // 2)
        starts = range(0, len(bounded_text) - size + 1, step)
        changed = False
        for index, start in enumerate(starts):
            if index >= 64:
                break
            fragment = bounded_text[start : start + size]
            if fragment in compact:
                text = text.replace(fragment, "[SOURCE_EXCERPT]")
                changed = True
        if changed:
            # Replacing several overlapping windows creates artifacts such as
            # ``[S[SOURCE_EXCERPT]`` and does not improve redaction coverage.
            break
    return text


def sanitize_rationale(
    value: str | None,
    *,
    max_chars: int = 280,
    source_text: str | None = None,
    source_name: str | None = None,
    source_url: str | None = None,
) -> str:
    """Return a bounded public rationale with sensitive material redacted."""

    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    text = mask_source_identity(str(value or ""), source_name, source_url)
    text = re.sub(r"\s+", " ", text).strip()
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _SECRET_ASSIGN_RE.sub("[REDACTED_SECRET]", text)
    text = _BEARER_VALUE_RE.sub("[REDACTED_SECRET]", text)
    text = _JWT_RE.sub("[REDACTED_TOKEN]", text)
    text = _URL_RE.sub("[REDACTED_URL]", text)
    if source_text:
        text = _redact_source_excerpts(text, source_text)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return text


def _provider_schema_error(message: str, exc: BaseException | None = None) -> ProviderSchemaError:
    error = ProviderSchemaError(message, code=ProviderSchemaError.code)
    if exc is not None:
        error.__cause__ = exc
    return error


def validate_public_evidence(
    evidence: Iterable[Evidence | Mapping[str, Any]],
    *,
    article_version_id: str,
    source_text: str | None = None,
    source_name: str | None = None,
    source_url: str | None = None,
) -> list[Evidence]:
    """Validate and redact evidence before it can leave the provider.

    Evidence remains tied to one article version and its location must be
    inside the masked text supplied to the model.  Quotes/rationales are
    treated as public text and therefore receive the same bounded redaction as
    ``rationale_summary``.
    """

    items = list(evidence)
    if len(items) > 20:
        raise _provider_schema_error("provider returned too many evidence items")
    text_length = len(source_text or "")
    result: list[Evidence] = []
    for item in items:
        try:
            parsed = item if isinstance(item, Evidence) else Evidence.model_validate(item)
        except Exception as exc:
            raise _provider_schema_error("provider evidence failed schema validation", exc) from exc
        if parsed.article_version_id != article_version_id:
            raise _provider_schema_error("provider evidence references another article version")
        evidence_start = parsed.start
        evidence_end = parsed.end
        if source_text is not None:
            # Offsets are Python/Unicode character offsets, with an exclusive
            # end. Validate the model's quote before any masking or redaction
            # so a fabricated quote cannot be persisted as source evidence. A
            # unique exact quote may safely repair a model's Unicode offset
            # counting error; ambiguous or absent quotes still fail closed.
            if (
                evidence_end > text_length
                or source_text[evidence_start:evidence_end] != parsed.quote
            ):
                resolved_start = source_text.find(parsed.quote)
                if resolved_start < 0 or source_text.find(
                    parsed.quote, resolved_start + 1
                ) >= 0:
                    raise _provider_schema_error(
                        "provider evidence quote does not match a unique article location"
                    )
                evidence_start = resolved_start
                evidence_end = resolved_start + len(parsed.quote)
        try:
            result.append(
                Evidence(
                    article_version_id=article_version_id,
                    start=evidence_start,
                    end=evidence_end,
                    quote=sanitize_rationale(
                        parsed.quote,
                        max_chars=500,
                        source_text=source_text,
                        source_name=source_name,
                        source_url=source_url,
                    ),
                    rationale=sanitize_rationale(
                        parsed.rationale,
                        max_chars=500,
                        source_text=source_text,
                        source_name=source_name,
                        source_url=source_url,
                    ),
                )
            )
        except Exception as exc:
            raise _provider_schema_error("provider evidence failed public validation", exc) from exc
    return result


def sanitize_public_assessment(
    assessment: ModelAssessment | Mapping[str, Any],
    *,
    input: AssessmentInput,
) -> ModelAssessment:
    """Strictly validate one assessment and return a safe public copy."""

    try:
        parsed = (
            assessment
            if isinstance(assessment, ModelAssessment)
            else ModelAssessment.model_validate(_normalise_status(assessment))
        )
    except Exception as exc:
        raise _provider_schema_error("provider output failed schema validation", exc) from exc
    if parsed.article_version_id != input.article_version_id:
        raise _provider_schema_error("provider output references another article version")
    if parsed.status.value != "SUCCEEDED":
        raise _provider_schema_error("provider returned a non-successful assessment")
    source_text = mask_source_identity(input.content, input.source_name, input.source_url)
    evidence = validate_public_evidence(
        parsed.evidence,
        article_version_id=input.article_version_id,
        source_text=source_text,
        source_name=input.source_name,
        source_url=input.source_url,
    )
    rationale = sanitize_rationale(
        parsed.rationale_summary,
        max_chars=500,
        source_text=f"{mask_source_identity(input.title, input.source_name, input.source_url)}\n{source_text}",
        source_name=input.source_name,
        source_url=input.source_url,
    )
    try:
        return ModelAssessment.model_validate(
            {
                **parsed.model_dump(mode="python"),
                "evidence": evidence,
                "rationale_summary": rationale,
                "status": parsed.status,
            }
        )
    except Exception as exc:
        raise _provider_schema_error("provider output failed public validation", exc) from exc


# Friendly aliases for callers that describe this operation as validation.
validate_public_output = sanitize_public_assessment
validate_evidence = validate_public_evidence


@dataclass(frozen=True)
class ProviderMetricsSnapshot(Mapping[str, object]):
    """Redacted, aggregate provider metrics.

    This object deliberately contains counts and numeric timings only.  It
    has no prompt, source text, response body, API key, or exception message.
    """

    provider_alias: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    retry_count: int
    rate_limited_requests: int
    circuit_open_requests: int
    schema_rejections: int
    total_latency_ms: int
    total_tokens: int
    average_latency_ms: float
    error_counts: Mapping[str, int]
    last_error_code: str | None = None
    last_latency_ms: int = 0
    last_token_usage: int = 0

    @property
    def latency_ms(self) -> int:
        return self.last_latency_ms

    @property
    def token_usage(self) -> int:
        return self.last_token_usage

    @property
    def error(self) -> str | None:
        return self.last_error_code

    @property
    def errors(self) -> Mapping[str, int]:
        return self.error_counts

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "provider_alias": self.provider_alias,
            "total_requests": self.total_requests,
            "requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "successes": self.successful_requests,
            "failed_requests": self.failed_requests,
            "failures": self.failed_requests,
            "retry_count": self.retry_count,
            "retries": self.retry_count,
            "rate_limited_requests": self.rate_limited_requests,
            "rate_limited": self.rate_limited_requests,
            "circuit_open_requests": self.circuit_open_requests,
            "circuit_open": self.circuit_open_requests,
            "schema_rejections": self.schema_rejections,
            "total_latency_ms": self.total_latency_ms,
            "latency_ms": self.total_latency_ms,
            "total_tokens": self.total_tokens,
            "token_usage": self.total_tokens,
            "tokens": self.total_tokens,
            "average_latency_ms": self.average_latency_ms,
            "error_counts": dict(self.error_counts),
            "errors": dict(self.error_counts),
            "last_error_code": self.last_error_code,
            "last_error": self.last_error_code,
            "last_latency_ms": self.last_latency_ms,
            "last_token_usage": self.last_token_usage,
        }
        return data

    def __getitem__(self, key: str) -> object:
        return self.as_dict()[key]

    def __iter__(self):
        return iter(self.as_dict())

    def __len__(self) -> int:
        return len(self.as_dict())


class _Metrics:
    def __init__(self, provider_alias: str) -> None:
        self.provider_alias = provider_alias
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.retry_count = 0
        self.rate_limited_requests = 0
        self.circuit_open_requests = 0
        self.schema_rejections = 0
        self.total_latency_ms = 0
        self.total_tokens = 0
        self.error_counts: dict[str, int] = {}
        self.last_error_code: str | None = None
        self.last_latency_ms = 0
        self.last_token_usage = 0
        self._lock = threading.Lock()

    def request_started(self) -> None:
        with self._lock:
            self.total_requests += 1

    def retry(self) -> None:
        with self._lock:
            self.retry_count += 1

    def success(self, latency_ms: int, token_usage: int) -> None:
        with self._lock:
            self.successful_requests += 1
            self.total_latency_ms += max(0, int(latency_ms))
            self.total_tokens += max(0, int(token_usage))
            self.last_latency_ms = max(0, int(latency_ms))
            self.last_token_usage = max(0, int(token_usage))

    def failure(self, code: str, latency_ms: int, *, rate_limited: bool = False) -> None:
        with self._lock:
            self.failed_requests += 1
            self.total_latency_ms += max(0, int(latency_ms))
            self.last_latency_ms = max(0, int(latency_ms))
            self.last_token_usage = 0
            self.last_error_code = code
            self.error_counts[code] = self.error_counts.get(code, 0) + 1
            if rate_limited:
                self.rate_limited_requests += 1
            if code == ProviderCircuitOpenError.code:
                self.circuit_open_requests += 1
            if code == ProviderSchemaError.code:
                self.schema_rejections += 1

    def snapshot(self) -> ProviderMetricsSnapshot:
        with self._lock:
            average = (
                self.total_latency_ms / self.total_requests if self.total_requests else 0.0
            )
            return ProviderMetricsSnapshot(
                provider_alias=self.provider_alias,
                total_requests=self.total_requests,
                successful_requests=self.successful_requests,
                failed_requests=self.failed_requests,
                retry_count=self.retry_count,
                rate_limited_requests=self.rate_limited_requests,
                circuit_open_requests=self.circuit_open_requests,
                schema_rejections=self.schema_rejections,
                total_latency_ms=self.total_latency_ms,
                total_tokens=self.total_tokens,
                average_latency_ms=round(average, 3),
                error_counts=MappingProxyType(dict(self.error_counts)),
                last_error_code=self.last_error_code,
                last_latency_ms=self.last_latency_ms,
                last_token_usage=self.last_token_usage,
            )


class SlidingWindowRateLimiter:
    """Small in-process per-provider sliding-window limiter."""

    def __init__(
        self,
        limit: int,
        *,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("rate limiter values must be positive")
        self.limit = int(limit)
        self.window_seconds = float(window_seconds)
        self._clock = clock
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        now = float(self._clock())
        with self._lock:
            cutoff = now - self.window_seconds
            while self._timestamps and self._timestamps[0] <= cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.limit:
                retry_after = max(0.0, self._timestamps[0] + self.window_seconds - now)
                raise ProviderRateLimitError(retry_after)
            self._timestamps.append(now)

    @property
    def size(self) -> int:
        now = float(self._clock())
        with self._lock:
            cutoff = now - self.window_seconds
            while self._timestamps and self._timestamps[0] <= cutoff:
                self._timestamps.popleft()
            return len(self._timestamps)


class CircuitBreaker:
    """Thread-safe closed/open/half-open circuit state machine."""

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout_seconds: float = 30.0,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1 or reset_timeout_seconds <= 0:
            raise ValueError("circuit breaker values are invalid")
        self.failure_threshold = int(failure_threshold)
        self.reset_timeout_seconds = float(reset_timeout_seconds)
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_probe = False
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._refresh_locked(float(self._clock()))
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    @property
    def opened_at(self) -> float | None:
        with self._lock:
            return self._opened_at

    def before_call(self) -> None:
        now = float(self._clock())
        with self._lock:
            self._refresh_locked(now)
            if self._state == CircuitState.OPEN:
                raise ProviderCircuitOpenError()
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_probe:
                    raise ProviderCircuitOpenError()
                self._half_open_probe = True

    def record_success(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._half_open_probe = False

    def record_failure(self) -> None:
        now = float(self._clock())
        with self._lock:
            self._refresh_locked(now)
            if self._state == CircuitState.HALF_OPEN:
                self._open_locked(now)
                return
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._open_locked(now)

    def release_probe(self) -> None:
        """Return an unused half-open probe slot to the circuit."""

        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._half_open_probe = False

    def record_probe_failure(self) -> None:
        """Open a half-open circuit after a probe that cannot be retried."""

        now = float(self._clock())
        with self._lock:
            self._refresh_locked(now)
            if self._state == CircuitState.HALF_OPEN:
                self._open_locked(now)

    def _refresh_locked(self, now: float) -> None:
        if (
            self._state == CircuitState.OPEN
            and self._opened_at is not None
            and now - self._opened_at >= self.reset_timeout_seconds
        ):
            self._state = CircuitState.HALF_OPEN
            self._half_open_probe = False

    def _open_locked(self, now: float) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = now
        self._half_open_probe = False


class HTTPTransport(Protocol):
    """Structural marker for injected httpx transports."""

    def handle_request(self, request: httpx.Request) -> httpx.Response: ...


class HttpLLMProvider(LLMProvider):
    """OpenAI Responses API provider with bounded runtime controls.

    ``transport`` is passed to ``httpx.Client`` and can be an
    ``httpx.MockTransport`` in tests.  A caller may inject an already-created
    ``httpx.Client`` instead; in that case the provider does not close it.
    """

    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: httpx.BaseTransport | Callable[[httpx.Request], httpx.Response] | None = None,
        client: httpx.Client | None = None,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(config, ProviderConfig):
            raise ProviderConfigurationError("provider config is required")
        if not config.endpoint:
            raise ProviderConfigurationError("HTTP provider endpoint is required")
        if client is not None and http_client is not None and client is not http_client:
            raise ProviderConfigurationError("client and http_client cannot both be supplied")
        injected_runtime = transport is not None or client is not None or http_client is not None
        if not injected_runtime:
            if config.endpoint != "https://api.openai.com/v1/responses":
                raise ProviderConfigurationError(
                    "live analysis must use the official OpenAI Responses API"
                )
            if not config.actual_model_id.startswith("gpt-"):
                raise ProviderConfigurationError("live analysis requires an OpenAI GPT model")
            if not config.api_key:
                raise ProviderConfigurationError("live analysis requires OPENAI_API_KEY")
        self.config = config
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._metrics = _Metrics(config.alias)
        self._rate_limiter = SlidingWindowRateLimiter(
            config.rate_limit_per_minute,
            window_seconds=config.rate_limit_window_seconds,
            clock=self._clock,
        )
        self._circuit = CircuitBreaker(
            config.circuit_failure_threshold,
            config.circuit_reset_timeout_seconds,
            clock=self._clock,
        )
        injected_client = client or http_client
        self._owns_client = injected_client is None
        resolved_transport: httpx.BaseTransport | None = transport  # type: ignore[assignment]
        if transport is not None and not isinstance(transport, httpx.BaseTransport):
            if not callable(transport):
                raise ProviderConfigurationError("HTTP transport is invalid")
            resolved_transport = httpx.MockTransport(transport)
        self._client = injected_client or httpx.Client(
            timeout=config.timeout_seconds,
            transport=resolved_transport,
        )

    @property
    def metrics(self) -> ProviderMetricsSnapshot:
        return self._metrics.snapshot()

    def metrics_snapshot(self) -> dict[str, object]:
        return self._metrics.snapshot().as_dict()

    @property
    def circuit_state(self) -> CircuitState:
        return self._circuit.state

    @property
    def circuit(self) -> CircuitBreaker:
        return self._circuit

    @property
    def rate_limiter(self) -> SlidingWindowRateLimiter:
        return self._rate_limiter

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HttpLLMProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def analyze_article(self, input: AssessmentInput, prompt_version: str) -> ModelAssessment:
        if not isinstance(input, AssessmentInput):
            try:
                input = AssessmentInput.model_validate(input)
            except Exception as exc:
                raise ProviderSchemaError("analysis input failed schema validation") from exc
        if not isinstance(prompt_version, str) or not prompt_version.strip():
            raise ProviderSchemaError("prompt version is required")
        started = time.perf_counter()
        self._metrics.request_started()
        try:
            self._circuit.before_call()
        except ProviderCircuitOpenError as exc:
            self._metrics.failure(exc.code, self._elapsed_ms(started))
            raise
        try:
            self._rate_limiter.acquire()
        except ProviderRateLimitError as exc:
            self._circuit.release_probe()
            self._metrics.failure(exc.code, self._elapsed_ms(started), rate_limited=True)
            raise

        payload = self._request_with_retries(input, prompt_version, started)
        try:
            assessment = self._parse_assessment(payload, input, prompt_version, started)
            assessment = sanitize_public_assessment(assessment, input=input)
        except ProviderSchemaError as exc:
            self._metrics.failure(exc.code, self._elapsed_ms(started))
            self._circuit.record_failure()
            raise
        except Exception as exc:
            error = _provider_schema_error("provider output failed public validation", exc)
            self._metrics.failure(error.code, self._elapsed_ms(started))
            self._circuit.record_failure()
            raise error from exc

        latency_ms = self._elapsed_ms(started)
        token_usage = assessment.token_usage
        # Re-validate after replacing runtime-owned telemetry fields.  This
        # prevents a provider response from spoofing latency/token values.
        assessment = ModelAssessment.model_validate(
            {
                **assessment.model_dump(mode="python"),
                "model_alias": self.config.alias,
                "actual_model_id": self.config.actual_model_id,
                "prompt_version": prompt_version,
                "latency_ms": latency_ms,
                "token_usage": token_usage,
            }
        )
        self._metrics.success(latency_ms, token_usage)
        self._circuit.record_success()
        return assessment

    def analyze_issue_comparison(
        self,
        articles: Iterable[Mapping[str, Any]],
        prompt_version: str,
    ) -> dict[str, Any]:
        """Compare two to four source-masked articles using strict structured output."""

        article_rows = [dict(article) for article in articles]
        if not 2 <= len(article_rows) <= 4:
            raise ProviderSchemaError("issue comparison requires two to four articles")
        article_ids = [str(article.get("article_id") or "") for article in article_rows]
        if any(not article_id for article_id in article_ids) or len(set(article_ids)) != len(
            article_ids
        ):
            raise ProviderSchemaError("issue comparison article identifiers are invalid")
        if not isinstance(prompt_version, str) or not prompt_version.strip():
            raise ProviderSchemaError("prompt version is required")

        started = time.perf_counter()
        self._metrics.request_started()
        try:
            self._circuit.before_call()
        except ProviderCircuitOpenError as exc:
            self._metrics.failure(exc.code, self._elapsed_ms(started))
            raise
        try:
            self._rate_limiter.acquire()
        except ProviderRateLimitError as exc:
            self._circuit.release_probe()
            self._metrics.failure(exc.code, self._elapsed_ms(started), rate_limited=True)
            raise

        payload = self._request_json_with_retries(
            self._issue_comparison_request_body(article_rows, prompt_version),
            started,
        )
        try:
            candidate = dict(_extract_assessment_mapping(payload))
            result = _validate_issue_comparison_output(candidate, set(article_ids))
        except ProviderSchemaError as exc:
            self._metrics.failure(exc.code, self._elapsed_ms(started))
            self._circuit.record_failure()
            raise
        except Exception as exc:
            error = _provider_schema_error("provider comparison output failed validation", exc)
            self._metrics.failure(error.code, self._elapsed_ms(started))
            self._circuit.record_failure()
            raise error from exc

        token_usage = _extract_token_usage(payload, candidate)
        self._metrics.success(self._elapsed_ms(started), token_usage)
        self._circuit.record_success()
        return result

    def _request_with_retries(
        self,
        input: AssessmentInput,
        prompt_version: str,
        started: float,
    ) -> Mapping[str, Any]:
        return self._request_json_with_retries(
            self._request_body(input, prompt_version),
            started,
        )

    def _request_json_with_retries(
        self,
        request_json: Mapping[str, Any],
        started: float,
    ) -> Mapping[str, Any]:
        attempts = self.config.max_retries + 1
        last_error: ProviderError | None = None
        for attempt in range(attempts):
            try:
                response = self._client.post(
                    self.config.endpoint,
                    json=request_json,
                    headers=self._request_headers(),
                    timeout=self.config.timeout_seconds,
                )
                status_code = int(response.status_code)
                if status_code >= 400:
                    retryable = status_code in _RETRYABLE_STATUS_CODES
                    error: ProviderError = ProviderHTTPError(status_code, retryable=retryable)
                    if not retryable:
                        self._metrics.failure(error.code, self._elapsed_ms(started))
                        self._circuit.record_probe_failure()
                        raise error
                    last_error = error
                    if attempt + 1 < attempts:
                        self._retry(attempt)
                        continue
                    self._metrics.failure(error.code, self._elapsed_ms(started))
                    self._circuit.record_failure()
                    raise error
                try:
                    payload = response.json()
                except (ValueError, json.JSONDecodeError) as exc:
                    error = _provider_schema_error("provider returned invalid JSON", exc)
                    self._metrics.failure(error.code, self._elapsed_ms(started))
                    self._circuit.record_failure()
                    raise error from exc
                if not isinstance(payload, Mapping):
                    error = _provider_schema_error("provider returned a non-object response")
                    self._metrics.failure(error.code, self._elapsed_ms(started))
                    self._circuit.record_failure()
                    raise error
                return cast(Mapping[str, Any], payload)
            except ProviderHTTPError:
                raise
            except httpx.TimeoutException as exc:
                error = ProviderTimeoutError()
                last_error = error
                if attempt + 1 < attempts:
                    self._retry(attempt)
                    continue
                self._metrics.failure(error.code, self._elapsed_ms(started))
                self._circuit.record_failure()
                raise error from exc
            except (httpx.RequestError, TimeoutError) as exc:
                error = ProviderTransportError()
                last_error = error
                if attempt + 1 < attempts:
                    self._retry(attempt)
                    continue
                self._metrics.failure(error.code, self._elapsed_ms(started))
                self._circuit.record_failure()
                raise error from exc
            except ProviderSchemaError:
                raise
            except Exception as exc:
                # A custom MockTransport or injected client may use a
                # transport-specific exception that is not an httpx subclass.
                error = ProviderTransportError()
                last_error = error
                if attempt + 1 < attempts:
                    self._retry(attempt)
                    continue
                self._metrics.failure(error.code, self._elapsed_ms(started))
                self._circuit.record_failure()
                raise error from exc
        # The loop always returns or raises, but retaining a safe fallback
        # keeps static analyzers aware of the no-raw-error contract.
        error = last_error or ProviderTransportError()
        self._metrics.failure(error.code, self._elapsed_ms(started))
        self._circuit.record_failure()
        raise error

    def _issue_comparison_request_body(
        self,
        articles: list[dict[str, Any]],
        prompt_version: str,
    ) -> dict[str, object]:
        blocks: list[str] = []
        for article in articles:
            source_name = str(article.get("source_name") or "") or None
            source_url = str(article.get("source_url") or "") or None
            title = mask_source_identity(
                str(article.get("title") or ""), source_name, source_url
            )
            content = mask_source_identity(
                str(article.get("content") or article.get("body") or "")[:30_000],
                source_name,
                source_url,
            )
            blocks.append(
                "\n".join(
                    (
                        f"ARTICLE_ID: {article['article_id']}",
                        f"ARTICLE_VERSION_ID: {article.get('article_version_id', '')}",
                        f"TITLE: {title}",
                        f"CONTENT:\n{content}",
                    )
                )
            )
        prompt = (
            "Compare only the supplied article contents without inferring from publisher identity. "
            "A common fact must list at least two distinct supplied ARTICLE_ID values that directly "
            "support it; omit a fact instead of listing only one article. Keep evidence_refs short "
            "and use article IDs plus concise location labels; never reproduce long excerpts. "
            "Return exactly one article_frames item for every supplied ARTICLE_ID, with no missing "
            "or duplicate IDs. For every article, describe the headline frame, emphasized actors/values/effects, and "
            "only a cautious omission note when the supplied content supports that comparison. "
            "Do not judge truthfulness, overall quality, or the reader.\n\n"
            f"PROMPT_VERSION: {prompt_version}\n\n" + "\n\n---\n\n".join(blocks)
        )
        return {
            "model": self.config.actual_model_id,
            "reasoning": {"effort": self.config.reasoning_effort},
            "instructions": (
                "You are a content-first issue framing analyst. Return only the requested "
                "structured comparison. Do not include personal data, secrets, URLs, publisher "
                "identity, or long source excerpts."
            ),
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "issue_comparison",
                    "strict": True,
                    "schema": _issue_comparison_schema(),
                }
            },
        }

    def _retry(self, attempt: int) -> None:
        self._metrics.retry()
        delay = min(
            self.config.max_backoff_seconds,
            self.config.retry_backoff_seconds * (2**attempt),
        )
        if delay > 0:
            self._sleep(delay)

    def _request_body(self, input: AssessmentInput, prompt_version: str) -> dict[str, object]:
        # Deliberately omit source_name/source_url/author.  The title/body are
        # masked again here so custom callers cannot accidentally bypass the
        # content-first boundary.
        title = mask_source_identity(input.title, input.source_name, input.source_url)[:2_000]
        full_content = mask_source_identity(input.content, input.source_name, input.source_url)
        content = full_content[:_MAX_ARTICLE_PROMPT_CHARS]
        content_truncated = len(content) < len(full_content)
        prompt = (
            "Assess only the supplied article content. Do not infer from publisher identity. "
            "Return exactly two evaluation scores. X is political bias: -100 means strongly "
            "left-biased, 0 means neutral/balanced, and +100 means strongly right-biased. "
            "Judge framing, selection and omission of facts, loaded wording, attribution, and "
            "which political actors or positions receive favorable or unfavorable treatment. "
            "Sensationalism is independent: 0 means restrained/factual and 100 means highly "
            "exaggerated, alarmist, emotionally manipulative, or click-driven. Do not treat a "
            "political position itself as proof of bias, and do not infer missing context. "
            "Evidence offsets are zero-based character offsets into CONTENT, with end exclusive. "
            "Return evidence only when its quote is an exact CONTENT substring at those offsets.\n\n"
            f"PROMPT_VERSION: {prompt_version}\n"
            f"ARTICLE_VERSION_ID: {input.article_version_id}\n"
            f"TITLE: {title}\n"
            f"CONTENT_TRUNCATED: {'true' if content_truncated else 'false'}\n"
            f"CONTENT:\n{content}"
        )
        return {
            "model": self.config.actual_model_id,
            "reasoning": {"effort": self.config.reasoning_effort},
            "instructions": (
                "You are a content-first political framing analyst. Return only the "
                "requested structured assessment. Do not include personal data, secrets, "
                "URLs, publisher identity, or long source excerpts in rationale fields."
            ),
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "article_assessment",
                    "strict": True,
                    "schema": _chat_completion_assessment_schema(),
                },
            },
        }

    def _request_headers(self) -> dict[str, str]:
        headers = dict(self.config.headers)
        headers.setdefault("Accept", "application/json")
        headers.setdefault("Content-Type", "application/json")
        if self.config.api_key:
            prefix = self.config.api_key_prefix.strip()
            value = f"{prefix} {self.config.api_key}" if prefix else self.config.api_key
            headers[self.config.api_key_header] = value
        return headers

    def _parse_assessment(
        self,
        payload: Mapping[str, Any],
        input: AssessmentInput,
        prompt_version: str,
        started: float,
    ) -> ModelAssessment:
        candidate = _extract_assessment_mapping(payload)
        data = dict(candidate)
        _check_identity(data, "article_version_id", input.article_version_id)
        _check_identity(data, "model_alias", self.config.alias)
        _check_identity(data, "actual_model_id", self.config.actual_model_id)
        _check_identity(data, "prompt_version", prompt_version)
        data.setdefault("article_version_id", input.article_version_id)
        data.setdefault("model_alias", self.config.alias)
        data.setdefault("actual_model_id", self.config.actual_model_id)
        data.setdefault("prompt_version", prompt_version)
        # y/z remain in the public and persistence models during the schema
        # migration, but every newly analyzed assessment is canonicalized to
        # the two-axis model regardless of legacy fields returned upstream.
        data["y"] = 0
        data["z"] = 0
        usage = _extract_token_usage(payload, data)
        # Usage is transport metadata, not part of the strict public
        # assessment schema.  Remove all accepted usage spellings before
        # Pydantic's ``extra=forbid`` validation runs.
        for key in _USAGE_KEYS:
            data.pop(key, None)
        if usage is not None:
            data["token_usage"] = usage
        # Runtime latency is measured below and must not be trusted from a
        # response.  If a response includes a malformed value, strict Pydantic
        # validation still rejects it rather than silently coercing it.
        if "latency_ms" in data:
            supplied_latency = data["latency_ms"]
            if not isinstance(supplied_latency, int) or isinstance(supplied_latency, bool):
                raise _provider_schema_error("provider latency field is invalid")
        _normalise_status_in_place(data)
        data["latency_ms"] = self._elapsed_ms(started)
        try:
            assessment = ModelAssessment.model_validate(data)
        except Exception as exc:
            raise _provider_schema_error("provider output failed schema validation", exc) from exc
        return assessment

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(0, int(round((time.perf_counter() - started) * 1000)))


def _check_identity(data: Mapping[str, Any], key: str, expected: str) -> None:
    if key in data and data[key] != expected:
        raise _provider_schema_error(f"provider output has invalid {key}")


def _normalise_status(value: ModelAssessment | Mapping[str, Any]) -> ModelAssessment | Mapping[str, Any]:
    if isinstance(value, ModelAssessment):
        return value
    data = dict(value)
    _normalise_status_in_place(data)
    return data


def _normalise_status_in_place(data: dict[str, Any]) -> None:
    status = data.get("status")
    if isinstance(status, str):
        try:
            data["status"] = AssessmentStatus(status)
        except ValueError as exc:
            raise _provider_schema_error("provider status is invalid", exc) from exc


_WRAPPER_KEYS = ("assessment", "result", "data", "response")
_USAGE_KEYS = frozenset({"usage", "token_usage", "prompt_tokens", "completion_tokens", "total_tokens"})
_OUTER_METADATA_KEYS = _USAGE_KEYS | frozenset({"choices", "id", "model", "object", "created"})


def _chat_completion_assessment_schema() -> dict[str, object]:
    """Return the strict assessment schema sent to the Responses API."""

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "x": {"type": "integer", "minimum": -100, "maximum": 100},
            "sensationalism": {"type": "integer", "minimum": 0, "maximum": 100},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "article_version_id": {"type": "string"},
                        "start": {"type": "integer", "minimum": 0},
                        "end": {"type": "integer", "minimum": 1},
                        "quote": {"type": "string", "minLength": 1, "maxLength": 500},
                        "rationale": {"type": "string", "maxLength": 500},
                    },
                    "required": [
                        "article_version_id",
                        "start",
                        "end",
                        "quote",
                        "rationale",
                    ],
                },
            },
            "rationale_summary": {"type": "string", "maxLength": 500},
        },
        "required": [
            "x",
            "sensationalism",
            "confidence",
            "evidence",
            "rationale_summary",
        ],
    }


def _issue_comparison_schema() -> dict[str, object]:
    string_list = {
        "type": "array",
        "maxItems": 12,
        "items": {"type": "string", "minLength": 1, "maxLength": 240},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "common_facts": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 80},
                        "text": {"type": "string", "minLength": 1, "maxLength": 600},
                        "article_ids": string_list,
                        "evidence_refs": string_list,
                    },
                    "required": ["id", "text", "article_ids", "evidence_refs"],
                },
            },
            "dimensions": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "key": {"type": "string", "minLength": 1, "maxLength": 80},
                        "label": {"type": "string", "minLength": 1, "maxLength": 120},
                    },
                    "required": ["key", "label"],
                },
            },
            "article_frames": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "article_id": {"type": "string", "minLength": 1},
                        "headline_frame": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 600,
                        },
                        "emphasis": string_list,
                        "omissions_note": {
                            "type": ["string", "null"],
                            "maxLength": 600,
                        },
                        "evidence_refs": string_list,
                    },
                    "required": [
                        "article_id",
                        "headline_frame",
                        "emphasis",
                        "omissions_note",
                        "evidence_refs",
                    ],
                },
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["common_facts", "dimensions", "article_frames", "confidence"],
    }


def _validate_issue_comparison_output(
    candidate: Mapping[str, Any], article_ids: set[str]
) -> dict[str, Any]:
    if set(candidate) != {"common_facts", "dimensions", "article_frames", "confidence"}:
        raise ProviderSchemaError("provider comparison output has unexpected fields")
    common_facts = candidate.get("common_facts")
    dimensions = candidate.get("dimensions")
    frames = candidate.get("article_frames")
    if not isinstance(common_facts, list) or not isinstance(dimensions, list):
        raise ProviderSchemaError("provider comparison lists are invalid")
    if not isinstance(frames, list) or len(frames) != len(article_ids):
        raise ProviderSchemaError("provider comparison frames are invalid")
    for fact in common_facts:
        if not isinstance(fact, Mapping):
            raise ProviderSchemaError("provider common fact is invalid")
        supporting = fact.get("article_ids")
        if (
            not isinstance(supporting, list)
            or len(set(map(str, supporting))) < 2
            or not set(map(str, supporting)).issubset(article_ids)
        ):
            raise ProviderSchemaError("provider common fact support is invalid")
    frame_map: dict[str, dict[str, Any]] = {}
    for frame in frames:
        if not isinstance(frame, Mapping):
            raise ProviderSchemaError("provider article frame is invalid")
        article_id = str(frame.get("article_id") or "")
        if article_id not in article_ids or article_id in frame_map:
            raise ProviderSchemaError("provider article frame identity is invalid")
        value = dict(frame)
        value.pop("article_id", None)
        frame_map[article_id] = value
    if set(frame_map) != article_ids:
        raise ProviderSchemaError("provider article frames are incomplete")
    try:
        confidence = float(candidate.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise ProviderSchemaError("provider comparison confidence is invalid") from exc
    if not 0 <= confidence <= 1:
        raise ProviderSchemaError("provider comparison confidence is invalid")
    return {
        "common_facts": [dict(item) for item in common_facts],
        "dimensions": [dict(item) for item in dimensions],
        "article_frames": frame_map,
        "confidence": confidence,
    }


def _extract_assessment_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    output_text = payload.get("output_text")
    if output_text is None and isinstance(payload.get("output"), list):
        for item in payload["output"]:
            if not isinstance(item, Mapping) or item.get("type") != "message":
                continue
            contents = item.get("content")
            if not isinstance(contents, list):
                continue
            for content in contents:
                if isinstance(content, Mapping) and content.get("type") == "output_text":
                    output_text = content.get("text")
                    break
            if output_text is not None:
                break
    if output_text is not None:
        if not isinstance(output_text, str):
            raise _provider_schema_error("provider structured content is invalid")
        try:
            parsed_output = json.loads(output_text)
        except (TypeError, ValueError) as exc:
            raise _provider_schema_error("provider structured content is invalid", exc) from exc
        if not isinstance(parsed_output, Mapping):
            raise _provider_schema_error("provider structured content is invalid")
        return cast(Mapping[str, Any], parsed_output)

    candidate: Any = payload
    for key in _WRAPPER_KEYS:
        value = candidate.get(key) if isinstance(candidate, Mapping) else None
        if value is not None:
            if candidate is payload:
                unexpected = set(payload) - {key} - _OUTER_METADATA_KEYS
                if unexpected:
                    raise _provider_schema_error("provider response has unexpected fields")
            if not isinstance(value, Mapping):
                raise _provider_schema_error("provider assessment wrapper is not an object")
            candidate = value
            break
    if isinstance(candidate, Mapping) and "choices" in candidate:
        if candidate is payload:
            unexpected = set(payload) - {"choices"} - _OUTER_METADATA_KEYS
            if unexpected:
                raise _provider_schema_error("provider response has unexpected fields")
        choices = candidate.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
            raise _provider_schema_error("provider choices response is invalid")
        choice = choices[0]
        message = choice.get("message", choice)
        if isinstance(message, Mapping):
            content = message.get("content", message)
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except (TypeError, ValueError) as exc:
                    raise _provider_schema_error("provider structured content is invalid", exc) from exc
            if isinstance(content, Mapping):
                candidate = content
            else:
                raise _provider_schema_error("provider structured content is invalid")
    if not isinstance(candidate, Mapping):
        raise _provider_schema_error("provider assessment is not an object")
    return cast(Mapping[str, Any], candidate)


def _extract_token_usage(payload: Mapping[str, Any], data: Mapping[str, Any]) -> int | None:
    usage_value: Any = data.get("token_usage")
    if usage_value is None:
        usage_value = payload.get("token_usage")
    if usage_value is None:
        usage_value = payload.get("total_tokens")
    usage = payload.get("usage")
    if usage_value is None and isinstance(usage, Mapping):
        usage_value = usage.get("total_tokens")
        if usage_value is None:
            prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
            completion = usage.get("completion_tokens", usage.get("output_tokens"))
            if isinstance(prompt, int) and not isinstance(prompt, bool) and isinstance(completion, int) and not isinstance(completion, bool):
                usage_value = prompt + completion
    if usage_value is None:
        return None
    if not isinstance(usage_value, int) or isinstance(usage_value, bool) or usage_value < 0:
        raise _provider_schema_error("provider token usage is invalid")
    return usage_value


class DeterministicStubProvider(LLMProvider):
    """A repeatable content-derived provider used without network/API keys."""

    def __init__(
        self,
        config: ProviderConfig | None = None,
        *,
        model_alias: str | None = None,
        actual_model_id: str | None = None,
    ) -> None:
        if config is None:
            alias = model_alias or "stub-1"
            config = ProviderConfig(alias, actual_model_id or alias)
        self.config = config

    def analyze_article(self, input: AssessmentInput, prompt_version: str) -> ModelAssessment:
        masked_title = mask_source_identity(input.title, input.source_name, input.source_url)
        masked_content = mask_source_identity(input.content, input.source_name, input.source_url)
        basis = (
            f"{self.config.alias}|{prompt_version}|{input.article_version_id}|"
            f"{masked_title}|{masked_content}"
        )
        digest = hashlib.sha256(basis.encode("utf-8")).digest()
        # Distinct byte windows give deterministic but meaningfully different
        # outputs while keeping both canonical scores in range. y/z are only
        # retained as zero-valued persistence compatibility fields.
        x = int.from_bytes(digest[0:2], "big") % 201 - 100
        sensationalism = int.from_bytes(digest[6:8], "big") % 101
        confidence = round(0.55 + digest[8] / 255 * 0.4, 6)
        # Evidence offsets are exact Unicode character offsets into the masked
        # content. Do not collapse whitespace here: doing so would make the
        # quote differ from the slice that the provider validator checks.
        quote = masked_content[:160] or masked_title[:160]
        rationale = sanitize_rationale(
            f"Content-first stub assessment for {masked_title}; evidence: {quote}",
            source_text=masked_content,
        )
        evidence = [
            Evidence(
                article_version_id=input.article_version_id,
                start=0,
                end=max(1, len(quote)),
                quote=quote,
            )
        ]
        return ModelAssessment(
            article_version_id=input.article_version_id,
            model_alias=self.config.alias,
            actual_model_id=self.config.actual_model_id,
            prompt_version=prompt_version,
            x=x,
            y=0,
            z=0,
            sensationalism=sensationalism,
            confidence=confidence,
            evidence=evidence,
            rationale_summary=rationale,
            token_usage=len((masked_title + masked_content).split()),
            latency_ms=1,
        )


# Common spellings retained as aliases; all use the same controls and schema.
HTTPProvider = HttpLLMProvider
HttpProvider = HttpLLMProvider
LLMHttpProvider = HttpLLMProvider
HTTPProviderAdapter = HttpLLMProvider
LLMProviderAdapter = HttpLLMProvider
ConfiguredHTTPProvider = HttpLLMProvider
ConfiguredLLMProvider = HttpLLMProvider


def provider_from_config(
    config: ProviderConfig,
    *,
    transport: httpx.BaseTransport | Callable[[httpx.Request], httpx.Response] | None = None,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> LLMProvider:
    """Build an HTTP provider when an endpoint is configured, otherwise stub."""

    if config.endpoint:
        return HttpLLMProvider(
            config,
            transport=transport,
            client=client,
            sleep=sleep,
            clock=clock,
        )
    return DeterministicStubProvider(config)


StubProvider = DeterministicStubProvider


def make_stub_providers(count: int = 1) -> list[DeterministicStubProvider]:
    if count < 1:
        raise ValueError("count must be positive")
    return [
        DeterministicStubProvider(
            model_alias=f"stub-{index + 1}", actual_model_id=f"deterministic-{index + 1}"
        )
        for index in range(count)
    ]


make_deterministic_stub_providers = make_stub_providers

# Factory spelling used by service bootstrap code.
build_provider = provider_from_config
