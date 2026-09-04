"""Async SQLAlchemy engine and session helpers.

Only the root ``.env`` is considered when deriving a database URL.  Callers
can always pass a URL explicitly (which is useful for tests); no service-local
environment file is read here.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _read_root_env_value(key: str) -> str | None:
    """Read one non-secret setting from the repository root's ``.env``.

    This intentionally parses only the requested key and never logs values.
    Environment variables take precedence, as expected by deployment tooling.
    """

    value = os.getenv(key)
    if value:
        return value
    server_root = Path(__file__).resolve().parents[4]
    repository_root = server_root.parent if server_root.name == "server" else server_root
    root_env = repository_root / ".env"
    try:
        lines = root_env.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    prefix = f"{key}="
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or not stripped.startswith(prefix):
            continue
        candidate = stripped[len(prefix) :].strip()
        if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"'", '"'}:
            candidate = candidate[1:-1]
        return candidate or None
    return None


def database_url_from_env() -> str:
    """Return the configured async database URL.

    ``DATABASE_URL``/``DB_URL`` may be a full SQLAlchemy URL.  For ergonomic
    local setup, the conventional ``DB_*`` pieces are also accepted.  A
    missing URL is an explicit error rather than silently connecting to an
    unexpected database.
    """

    for key in ("DATABASE_URL", "DB_URL", "MARIADB_URL"):
        value = _read_root_env_value(key)
        if value:
            return value

    host = _read_root_env_value("DB_HOST") or _read_root_env_value("MARIADB_HOST")
    name = _read_root_env_value("DB_NAME") or _read_root_env_value("MARIADB_DATABASE")
    user = _read_root_env_value("DB_USER") or _read_root_env_value("MARIADB_USER")
    password = _read_root_env_value("DB_PASSWORD") or _read_root_env_value("MARIADB_PASSWORD")
    port = _read_root_env_value("DB_PORT") or _read_root_env_value("MARIADB_PORT") or "3306"
    if host and name and user is not None and password is not None:
        return (
            f"mariadb+asyncmy://{quote_plus(user)}:{quote_plus(password)}"
            f"@{host}:{port}/{quote_plus(name)}"
        )
    raise RuntimeError(
        "database URL is not configured; set DATABASE_URL in the root .env "
        "or pass one explicitly to create_engine()"
    )


def _normalize_url(database_url: str) -> str:
    # Accept the common sync MariaDB/MySQL spelling while ensuring the async
    # driver is selected for runtime sessions.
    if database_url.startswith("mariadb://"):
        return "mariadb+asyncmy://" + database_url[len("mariadb://") :]
    if database_url.startswith("mysql://"):
        return "mysql+asyncmy://" + database_url[len("mysql://") :]
    return database_url


def create_engine(database_url: str | None = None, **kwargs: Any) -> AsyncEngine:
    """Create and register the process-wide async engine.

    A caller may pass an engine URL for tests (for example SQLite with an
    async driver).  ``pool_pre_ping`` is enabled for MariaDB by default to
    recover cleanly from idle connection timeouts.
    """

    global _engine, _session_factory
    url = _normalize_url(database_url or database_url_from_env())
    kwargs.setdefault("pool_pre_ping", True)
    # Request handlers perform several reads before their write-side locks are
    # acquired (authentication, consent checks, and resource lookup).  MariaDB
    # REPEATABLE READ can therefore retain a stale snapshot after waiting for
    # a lock and raise error 1020 on the current row.  READ COMMITTED keeps
    # those serialized transactions on the latest committed state.
    if url.startswith(("mariadb+", "mysql+")):
        kwargs.setdefault("isolation_level", "READ COMMITTED")
    _engine = create_async_engine(url, **kwargs)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine() -> AsyncEngine:
    """Return the configured engine, raising if startup has not configured it."""

    if _engine is None:
        raise RuntimeError("database engine is not configured; call create_engine()")
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the configured async session factory."""

    if _session_factory is None:
        create_engine()
    assert _session_factory is not None
    return _session_factory


# Explicitly named alias for dependency-injection code that prefers the
# SQLAlchemy terminology.


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session and roll back unhandled failures."""

    factory = session_factory()
    async with factory() as session:
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the registered engine during graceful application shutdown."""

    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
