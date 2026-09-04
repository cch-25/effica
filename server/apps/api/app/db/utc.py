"""UTC-only timestamp helpers and a MariaDB-compatible datetime type."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.dialects import mysql
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for application defaults."""

    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize an aware or naive datetime to an aware UTC datetime.

    Naive values are treated as UTC.  The database stores ``DATETIME(6)``
    without a timezone because MariaDB has no timezone-aware datetime type;
    this boundary is therefore the only place where that convention is made.
    """

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Store UTC datetimes as ``DATETIME(6)`` and return aware values."""

    cache_ok = True
    impl = DateTime

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name in {"mysql", "mariadb"}:
            return dialect.type_descriptor(mysql.DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime())

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        # MariaDB DATETIME is timezone-naive; always bind a naive UTC value.
        return ensure_utc(value).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return ensure_utc(value)
