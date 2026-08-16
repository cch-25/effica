"""Structured logging helpers with conservative secret redaction.

Authentication and questionnaire flows frequently carry values that must not
reach logs.  ``redact`` is intentionally recursive and defaults to redacting
unknown values under suspicious keys, while preserving ordinary operational
metadata such as IDs, statuses, and counts.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any

REDACTED = "[REDACTED]"

# Match normalized key names after punctuation/case is removed.  Keep this
# broad: accidentally logging a secret is worse than losing a debug field.
_SENSITIVE_KEY_PARTS = (
    "access_token",
    "authorization",
    "cookie",
    "csrf",
    "client_secret",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "session_token",
    "state",
    "nonce",
    "oauth_subject",
    "provider_subject",
    "token",
    "survey",
    "questionnaire",
    "answer",
    "raw_payload",
    "encrypted_payload",
)

_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:access[_-]?token|refresh[_-]?token|client[_-]?secret|session[_-]?token|csrf[_-]?token|password|secret|state|nonce)\s*[=:]\s*)([^\s,;]+)"
)


def _normalized_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def is_sensitive_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    """Redact common credential forms embedded in an otherwise safe message."""

    if not isinstance(value, str):
        return value
    value = _BEARER_RE.sub(r"\1" + REDACTED, value)
    return _SECRET_ASSIGNMENT_RE.sub(r"\1" + REDACTED, value)


def redact(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact secrets and sensitive user data.

    Dictionaries preserve their shape so structured logs remain searchable;
    sensitive fields are replaced before serialization.  Lists/tuples are
    traversed, while arbitrary objects are represented by a safe string rather
    than introspected for attributes that may contain credentials.
    """

    if key is not None and is_sensitive_key(key):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, set):
        return {redact(item) for item in value}
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (bool, int, float)):
        return value
    # Do not call ``vars`` or ``repr`` on arbitrary domain objects.  A custom
    # repr is a common accidental path for leaking provider credentials.
    return f"<{type(value).__name__}>"


redact_value = redact
redact_log_record = redact


class RedactingFilter(logging.Filter):
    """Sanitize log messages and extras before handlers serialize them."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib API
        record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = redact(record.args)
            else:
                record.args = tuple(redact(arg) for arg in record.args)
        # ``extra`` values are copied directly onto the record.  Sanitize all
        # non-standard fields while keeping formatter fields intact.
        standard = logging.LogRecord(None, 0, "", 0, "", (), None).__dict__
        for name, value in list(record.__dict__.items()):
            if name not in standard and name not in {"message", "asctime"}:
                record.__dict__[name] = redact(value, key=name)
        return True


class JsonFormatter(logging.Formatter):
    """Small JSON formatter suitable for API/worker stdout logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),  # noqa: UP017
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = str(request_id)
        event = getattr(record, "event", None)
        if event:
            payload["event"] = str(event)
        for name, value in record.__dict__.items():
            if name in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "asctime",
                "request_id",
                "event",
            }:
                continue
            payload[name] = redact(value, key=name)
        if record.exc_info:
            # Exception messages can contain provider error payloads.  Include
            # only the type and sanitized message, never traceback locals.
            payload["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": redact_text(str(record.exc_info[1])),
            }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def configure_logging(
    *,
    level: int | str = logging.INFO,
    logger_name: str | None = None,
    handler: logging.Handler | None = None,
) -> logging.Logger:
    """Configure one logger with redaction and deterministic JSON output."""

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False
    target = handler or logging.StreamHandler()
    target.setFormatter(JsonFormatter())
    # Avoid stacking duplicate filters when the API imports this helper more
    # than once during test collection/reload.
    if not any(isinstance(item, RedactingFilter) for item in target.filters):
        target.addFilter(RedactingFilter())
    if target not in logger.handlers:
        logger.addHandler(target)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger; callers can configure the root once during startup."""

    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit a structured event with all fields passed through redaction."""

    safe_fields = redact(fields)
    logger.info(event, extra={"event": event, **safe_fields})


__all__ = [
    "JsonFormatter",
    "REDACTED",
    "RedactingFilter",
    "configure_logging",
    "get_logger",
    "is_sensitive_key",
    "log_event",
    "redact",
    "redact_log_record",
    "redact_text",
    "redact_value",
]
