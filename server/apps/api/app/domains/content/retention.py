"""Seven-day article retention, including an ingestion fence for deleted URLs."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

RETENTION_DAYS = 7


def utc(value: Any) -> datetime | None:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError("invalid article timestamp")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def expired(published_at: Any, created_at: Any, now: datetime) -> bool:
    effective = utc(published_at) or utc(created_at)
    return effective is not None and effective < utc(now) - timedelta(days=RETENTION_DAYS)


async def skip_ingestion(session: Any, article: Mapping[str, Any], url: str, now: datetime) -> bool:
    from sqlalchemy import text

    if expired(article.get("published_at"), now, now):
        return True
    result = await session.execute(
        text("SELECT canonical_url_hash FROM article_retention_tombstones "
             "WHERE canonical_url_hash = :url_hash LIMIT 1"),
        {"url_hash": hashlib.sha256(url.encode("utf-8")).digest()},
    )
    # Small fake sessions used by worker contract tests return lists.
    return bool(result if isinstance(result, list) else result.mappings().all())
