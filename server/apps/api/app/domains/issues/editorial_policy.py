"""Shared fail-closed eligibility for topic-first public news."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from apps.api.app.db.utc import ensure_utc, utc_now
from apps.api.app.domains.issues.topics import PUBLIC_ISSUE_TOPICS

PUBLIC_CONTENT_MAX_AGE = timedelta(days=7)
MIN_PUBLIC_ISSUE_SOURCES = 3
DAILY_ISSUE_KEY_PREFIX = "daily-issue:"


def _field(record: Any, name: str, default: Any = None) -> Any:
    return record.get(name, default) if isinstance(record, dict) else getattr(record, name, default)


def is_curated_issue(issue: Any) -> bool:
    """Only deliberate daily editorial events can enter public product surfaces."""
    return bool(
        issue is not None
        and str(_field(issue, "editorial_key", "") or "").startswith(DAILY_ISSUE_KEY_PREFIX)
        and str(_field(issue, "issue_kind", _field(issue, "kind", ""))).upper() == "EVENT"
        and str(_field(issue, "status", "")).casefold() == "active"
        and _field(issue, "topic") in PUBLIC_ISSUE_TOPICS
        and str(_field(issue, "summary", "") or "").strip()
    )


def is_current_article(published_at: datetime | str | None, now: datetime | None = None) -> bool:
    """Publication timestamps must be known, non-future and within seven days."""
    if isinstance(published_at, str):
        try:
            published_at = datetime.fromisoformat(published_at)
        except ValueError:
            return False
    if not isinstance(published_at, datetime):
        return False
    current = ensure_utc(now or utc_now())
    return current - PUBLIC_CONTENT_MAX_AGE <= ensure_utc(published_at) <= current


def publisher_identity(canonical_url: str) -> str | None:
    """Collapse publisher subdomains, including Korean second-level suffixes.

    Aggregator URLs deliberately share one identity and cannot manufacture
    independent source coverage by varying source rows, names or subdomains.
    """
    try:
        parsed = urlsplit(canonical_url)
        host = (parsed.hostname or "").rstrip(".").lower().encode("idna").decode("ascii")
    except (ValueError, UnicodeError):
        return None
    if parsed.scheme not in {"http", "https"} or not host or "." not in host:
        return None
    parts = host.split(".")
    suffix = ".".join(parts[-2:])
    common_second_levels = {"co", "com", "org", "net", "ac", "go", "gov", "or", "ne"}
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in common_second_levels:
        return ".".join(parts[-3:])
    return suffix
