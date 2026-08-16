from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Cookie, Depends, Header, Request
from fastapi.security import APIKeyCookie

from apps.api.app.api.v1.schemas import Role
from apps.api.app.core.config import Settings, get_settings
from apps.api.app.core.errors import ApiError
from apps.api.app.repositories.platform import MariaDBPlatformRepository
from apps.api.app.state import STATE, PlatformState

SESSION_COOKIE = APIKeyCookie(name="session", auto_error=False, description="Opaque session token")
ROLE_ACCESS = {
    Role.MEMBER: {Role.MEMBER, Role.ANALYST, Role.REVIEWER, Role.ADMIN},
    Role.ANALYST: {Role.ANALYST, Role.ADMIN},
    Role.REVIEWER: {Role.REVIEWER, Role.ADMIN},
    Role.ADMIN: {Role.ADMIN},
}


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: str
    role: Role


def get_state() -> PlatformState:
    return STATE


async def get_repository(
    settings: Settings = Depends(get_settings),
) -> AsyncIterator[MariaDBPlatformRepository | None]:
    if settings.app_backend == "memory":
        yield None
        return
    from apps.api.app.db.session import session_factory

    factory = session_factory()
    async with factory() as session:
        try:
            yield MariaDBPlatformRepository(
                session,
                encryption_secret=settings.session_secret,
            )
        except BaseException:
            await session.rollback()
            raise


async def optional_principal(
    settings: Settings = Depends(get_settings),
    state: PlatformState = Depends(get_state),
    session: str | None = Depends(SESSION_COOKIE),
    debug_role: Role | None = Header(default=None, alias="X-Debug-Role"),
    debug_user: str | None = Header(default=None, alias="X-Debug-User"),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> Principal | None:
    if settings.app_env != "production" and debug_role:
        user_id = debug_user or state.default_users[debug_role.value]
        user = state.users.get(user_id)
        if not user or user["status"] != "ACTIVE":
            raise ApiError(401, "SESSION_INVALID", "The local principal is not active.")
        return Principal(user_id=user_id, role=debug_role)
    if not session:
        return None
    if repository is not None:
        record = await repository.find_session(session)
        if not record:
            return None
        return Principal(user_id=record["user_id"], role=Role(record["role"]))
    record = state.sessions.get(hashlib.sha256(session.encode()).hexdigest())
    if not record or record.get("revoked_at") or record["expires_at"] <= datetime.now(UTC):
        return None
    user = state.users.get(record["user_id"])
    if not user or user["status"] != "ACTIVE":
        return None
    return Principal(user_id=user["id"], role=Role(user["role"]))


def require_role(minimum: Role):
    def dependency(principal: Principal | None = Depends(optional_principal)) -> Principal:
        if principal is None:
            raise ApiError(401, "AUTH_REQUIRED", "Authentication is required.")
        if principal.role not in ROLE_ACCESS[minimum]:
            raise ApiError(403, "ROLE_REQUIRED", f"The {minimum.value} role is required.")
        return principal

    return dependency


require_member = require_role(Role.MEMBER)
require_analyst = require_role(Role.ANALYST)
require_reviewer = require_role(Role.REVIEWER)
require_admin = require_role(Role.ADMIN)


async def require_csrf(
    request: Request,
    settings: Settings = Depends(get_settings),
    state: PlatformState = Depends(get_state),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
    csrf_cookie: str | None = Cookie(default=None, alias="csrf"),
    session_cookie: str | None = Cookie(default=None, alias="session"),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if settings.app_env != "production" and csrf_header == "local-csrf":
        return
    if not csrf_header or not csrf_cookie or not hmac.compare_digest(csrf_header, csrf_cookie):
        raise ApiError(403, "CSRF_INVALID", "A matching CSRF token is required.")
    if repository is not None:
        session = await repository.find_session(session_cookie or "")
        if not session or not hmac.compare_digest(
            session["csrf_hash"], hashlib.sha256(csrf_header.encode()).digest()
        ):
            raise ApiError(403, "CSRF_INVALID", "The CSRF token is not bound to this session.")
        return
    session = state.sessions.get(hashlib.sha256((session_cookie or "").encode()).hexdigest())
    if not session or not hmac.compare_digest(session["csrf_hash"], hashlib.sha256(csrf_header.encode()).hexdigest()):
        raise ApiError(403, "CSRF_INVALID", "The CSRF token is not bound to this session.")


def require_idempotency_key(
    value: str | None = Header(default=None, alias="Idempotency-Key", min_length=8, max_length=200),
) -> str:
    if not value:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
    return value


def require_if_match(
    value: str | None = Header(default=None, alias="If-Match", min_length=1, max_length=100),
) -> str:
    if not value:
        raise ApiError(428, "IF_MATCH_REQUIRED", "If-Match is required.")
    return value.strip('"')
