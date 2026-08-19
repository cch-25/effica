"""Shared handler contracts.

Handlers are pure-ish functions at this boundary: persistence, provider calls,
and domain side effects are injected through ``HandlerContext`` by the owning
service.  The built-ins use deterministic local transformations so a complete
queue vertical slice can run without external credentials.
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class HandlerContext:
    """Execution metadata and optional side-effect adapter for a handler."""

    job_id: str = ""
    job_type: str = ""
    worker_id: str = ""
    idempotency_key: str = ""
    now: datetime | None = None
    services: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HandlerResult:
    """Normalized handler output persisted/handed to a domain service."""

    value: Any = None
    side_effect_key: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        if isinstance(self.value, Mapping):
            result = dict(self.value)
        else:
            result = {"value": self.value}
        if self.side_effect_key is not None:
            result.setdefault("side_effect_key", self.side_effect_key)
        if self.metadata:
            result.setdefault("metadata", dict(self.metadata))
        return result


class HandlerError(RuntimeError):
    """Structured handler failure; retry policy is explicit."""

    retryable = True
    code = "HANDLER_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
        if retryable is not None:
            self.retryable = retryable
        self.details = dict(details or {})

    def as_error(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "retryable": bool(self.retryable),
            "details": dict(self.details),
        }


class RetryableHandlerError(HandlerError):
    retryable = True
    code = "HANDLER_RETRYABLE_ERROR"


class NonRetryableHandlerError(HandlerError):
    retryable = False
    code = "HANDLER_NON_RETRYABLE_ERROR"


HandlerCallable = Callable[[Mapping[str, Any], HandlerContext], HandlerResult | Mapping[str, Any] | Any | Awaitable[Any]]


class AsyncHandlerCallable(Protocol):
    """The concrete contract implemented by every built-in handler."""

    def __call__(
        self,
        payload: Mapping[str, Any],
        context: HandlerContext | None = None,
    ) -> Awaitable[HandlerResult]: ...


async def lookup_service(
    context: HandlerContext | None,
    names: tuple[str, ...],
    *,
    identifier: Any = None,
    payload: Mapping[str, Any] | None = None,
) -> Any:
    """Resolve a repository lookup without coupling handlers to SQL models.

    Production workers inject callables or mappings under one of the supplied
    names.  The small calling convention adapter keeps deterministic tests
    pleasant (``{"id": value}``, ``fn(identifier)``, and ``fn(payload)`` are
    all accepted) while making a missing lookup an explicit handler error at
    the caller.
    """

    if context is None:
        return None
    services = context.services
    for name in names:
        service = services.get(name)
        if service is None:
            continue
        if isinstance(service, Mapping):
            try:
                value = service[identifier] if identifier in service else service.get(str(identifier))
            except TypeError:
                value = None
                if isinstance(identifier, (list, tuple, set)):
                    value = [
                        service[item] if item in service else service.get(str(item))
                        for item in identifier
                        if item in service or str(item) in service
                    ]
            if value is not None:
                return value
            continue
        if not callable(service):
            for method_name in ("get", "lookup", "load", "resolve"):
                method = getattr(service, method_name, None)
                if callable(method):
                    service = method
                    break
            else:
                continue
        attempts: list[tuple[Any, ...]] = []
        if identifier is not None:
            attempts.extend(((identifier,), (identifier, context)))
        if payload is not None:
            attempts.extend(((payload,), (payload, context)))
        for args in attempts:
            try:
                value = service(*args)
            except TypeError:
                continue
            if inspect.isawaitable(value):
                value = await value
            if value is not None:
                return value
        if identifier is not None:
            keyword_attempts = (
                {"identifier": identifier},
                {"id": identifier},
                {"article_id": identifier},
                {"article_version_id": identifier},
                {"source_id": identifier},
                {"user_id": identifier},
            )
            for kwargs in keyword_attempts:
                try:
                    value = service(**kwargs)
                except TypeError:
                    continue
                if inspect.isawaitable(value):
                    value = await value
                if value is not None:
                    return value
    return None


async def invoke_handler(
    handler: HandlerCallable,
    payload: Mapping[str, Any],
    context: HandlerContext,
) -> HandlerResult:
    """Invoke old one-argument and current two-argument handler functions."""

    try:
        # Inspect before invocation so a TypeError raised *inside* a legacy
        # one-argument handler is not mistaken for a signature mismatch and
        # executed twice.
        try:
            signature = inspect.signature(handler)
            positional = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.kind
                in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
            ]
            accepts_varargs = any(
                parameter.kind == parameter.VAR_POSITIONAL
                for parameter in signature.parameters.values()
            )
        except (TypeError, ValueError):
            positional = []
            accepts_varargs = True
        if accepts_varargs or len(positional) != 1:
            value = handler(payload, context)
        else:
            value = handler(payload)  # type: ignore[call-arg]
        if inspect.isawaitable(value):
            value = await value
    except HandlerError:
        raise
    except Exception as exc:
        raise RetryableHandlerError(
            str(exc) or exc.__class__.__name__,
            code="HANDLER_EXCEPTION",
            details={"exception": exc.__class__.__name__},
        ) from exc

    if isinstance(value, HandlerResult):
        return value
    if isinstance(value, Mapping):
        return HandlerResult(value=dict(value))
    return HandlerResult(value=value)


def stable_digest(value: Any) -> str:
    """Produce a stable short digest for local deterministic artifacts."""

    import json

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def require_mapping(payload: Mapping[str, Any], *keys: str) -> None:
    missing = [key for key in keys if payload.get(key) in (None, "")]
    if missing:
        raise NonRetryableHandlerError(
            "required job payload is missing",
            code="INVALID_JOB_PAYLOAD",
            details={"missing": missing},
        )
