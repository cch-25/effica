"""Stable data contracts for jobs crossing the API/worker boundary.

No SQLAlchemy model is defined here on purpose.  The API and worker can use
these contracts while deployments migrate the physical ``jobs`` table, and
tests can use them with an in-memory repository.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

DEFAULT_MAX_ATTEMPTS = 3


def normalize_job_type(value: Any) -> str:
    """Return the persisted string for a string-like enum or plain value."""

    candidate = getattr(value, "value", value)
    result = str(candidate).strip()
    if not result:
        raise ValueError("job_type must not be empty")
    return result


class JobStatus(str, Enum):
    """Persisted queue states.

    Values are intentionally upper-case because they are also used by the
    MariaDB enum/check constraint and exposed by the admin API.
    """

    PENDING = "PENDING"
    LEASED = "LEASED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD = "DEAD"
    CANCELLED = "CANCELLED"


class JobType(str, Enum):
    """Built-in handler names.

    Strings remain accepted by all public functions so applications may add a
    domain-specific handler without changing this enum.
    """

    CRAWL = "crawl"
    CLUSTER = "cluster"
    ANALYZE = "analyze"
    BUILD_ISSUE_COMPARISON = "build_issue_comparison"
    AGGREGATE_VOTES = "aggregate_votes"
    CALCULATE_SCORE = "calculate_score"
    RECOMMEND_WEIGHTS = "recommend_weights"
    SIMULATE_WEIGHTS = "simulate_weights"
    RENDER_SHARE_CARD = "render_share_card"
    EXPORT_USER = "export_user"
    DELETE_USER = "delete_user"
    MERGE_ISSUE = "merge_issue"
    SPLIT_ISSUE = "split_issue"


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for persistence."""

    return datetime.now(UTC)


def _base32(value: int, length: int) -> str:
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    chars = [alphabet[0]] * length
    for index in range(length - 1, -1, -1):
        chars[index] = alphabet[value & 31]
        value >>= 5
    return "".join(chars)


def generate_job_id(*, now_ms: int | None = None) -> str:
    """Generate an application-owned 26-character ULID.

    The implementation avoids an additional dependency while preserving the
    canonical ULID shape (48-bit milliseconds followed by 80 random bits).
    """

    timestamp = int(time.time() * 1000) if now_ms is None else int(now_ms)
    timestamp &= (1 << 48) - 1
    randomness = secrets.randbits(80)
    return _base32(timestamp, 10) + _base32(randomness, 16)


def canonical_payload_json(payload: Mapping[str, Any]) -> str:
    """Serialize a payload deterministically for queue storage and hashing."""

    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


@dataclass(frozen=True)
class JobEnvelope:
    """A producer-facing job description.

    ``id`` may be omitted by callers that construct the object manually; the
    producer fills it before insertion.  The worker's richer ``Job`` record is
    intentionally separate because it includes lease state.
    """

    job_type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    id: str | None = None
    dedupe_key: str | None = None
    priority: int = 0
    available_at: datetime | None = None
    max_attempts: int = DEFAULT_MAX_ATTEMPTS

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_type", normalize_job_type(self.job_type))
        # Validate known built-ins at the producer boundary while retaining
        # support for extension job types owned by an injected registry.
        from .payloads import validate_job_payload

        object.__setattr__(self, "payload", validate_job_payload(self.job_type, self.payload))
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


@dataclass(frozen=True)
class JobSubmission:
    """Result of enqueueing, including dedupe information."""

    job_id: str
    job_type: str
    dedupe_key: str | None
    created: bool
