"""Security primitives shared by the API domains.

The application deliberately keeps authentication state opaque.  This module
contains the small, dependency-free pieces that are safe to use from routes,
repositories, and tests: random token generation, one-way token hashing,
session lifecycle helpers, CSRF checks, redirect validation, and role guards.

No function in this module logs a credential or returns a credential from a
persistent record.  ``SessionCredentials`` is the one exception to the latter
rule: it is a short-lived value returned only at session creation/rotation so a
caller can set the cookie and then discard the plaintext values.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from urllib.parse import urlsplit, urlunsplit

UTC = timezone.utc  # noqa: UP017 - Python 3.9-compatible fallback for local tooling
DEFAULT_SESSION_TTL = timedelta(days=30)
DEFAULT_OAUTH_TTL = timedelta(minutes=10)
MIN_TOKEN_BYTES = 32


class SecurityError(Exception):
    """Base class for security validation failures."""


class InvalidTokenError(SecurityError):
    """Raised when an opaque token is empty, malformed, or does not match."""


class SessionExpiredError(InvalidTokenError):
    """Raised when a session is past its expiry time."""


class SessionRevokedError(InvalidTokenError):
    """Raised when a session has been explicitly revoked."""


class CSRFError(SecurityError):
    """Raised when a state-changing request has no valid CSRF token."""


class RedirectNotAllowedError(SecurityError):
    """Raised when a callback/return URL is not in the configured allowlist."""


class OAuthStateError(SecurityError):
    """Raised for missing, expired, or replayed OAuth state."""


class AuthorizationError(SecurityError):
    """Raised when an actor does not have the required application role."""


class Role(str, Enum):
    """Application roles in increasing privilege order."""

    GUEST = "guest"
    MEMBER = "member"
    ANALYST = "analyst"
    REVIEWER = "reviewer"
    ADMIN = "admin"


UserRole = Role

# The ordering is intentional.  Analyst and reviewer are separate capabilities
# rather than a strict inheritance chain; an admin is allowed to perform both.
ROLE_RANK: Mapping[Role, int] = {
    Role.GUEST: 0,
    Role.MEMBER: 10,
    Role.ANALYST: 20,
    Role.REVIEWER: 30,
    Role.ADMIN: 40,
}


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def new_identifier() -> str:
    """Return a 26-character ULID without introducing a secret.

    ``ulid-py`` is the normal implementation dependency.  The small fallback
    keeps unit tests runnable in a bare Python environment while preserving the
    same sortable Crockford Base32 shape required by the API/DB contract.
    """

    try:
        import ulid  # type: ignore

        return str(ulid.new())
    except ImportError:
        alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
        timestamp = int(time.time() * 1000) & ((1 << 48) - 1)
        random_bits = secrets.randbits(80)
        value = (timestamp << 80) | random_bits
        encoded = []
        for _ in range(26):
            encoded.append(alphabet[value & 0x1F])
            value >>= 5
        return "".join(reversed(encoded))


def generate_token(nbytes: int = MIN_TOKEN_BYTES) -> str:
    """Generate a cryptographically random URL-safe opaque token."""

    if nbytes < MIN_TOKEN_BYTES:
        raise ValueError("opaque tokens must contain at least 32 random bytes")
    return secrets.token_urlsafe(nbytes)


generate_opaque_token = generate_token


def hash_token(token: str) -> str:
    """Return the SHA-256 digest persisted for an opaque token.

    The plaintext token must never be persisted.  SHA-256 is used exactly as
    specified by the service contract (and compared with ``compare_digest``).
    """

    if not isinstance(token, str) or not token:
        raise InvalidTokenError("token is required")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


sha256_token = hash_token
token_hash = hash_token


def token_matches(token: str, expected_hash: str) -> bool:
    """Constant-time comparison of a presented token and a stored hash."""

    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        return False
    try:
        # ``hexdigest`` is ASCII and has a fixed length; compare_digest avoids
        # timing differences for valid hashes.
        return hmac.compare_digest(hash_token(token), expected_hash.lower())
    except (InvalidTokenError, UnicodeError):
        return False


verify_token = token_matches


def generate_csrf_token() -> str:
    """Generate a CSRF token that is kept only in the session cookie boundary."""

    return generate_token()


def verify_csrf_token(expected_hash: str, presented_token: str) -> bool:
    """Verify a CSRF token against the session's SHA-256 hash."""

    return token_matches(presented_token, expected_hash)


csrf_matches = verify_csrf_token
verify_csrf = verify_csrf_token


def require_csrf(expected_hash: str, presented_token: str | None) -> None:
    """Raise ``CSRFError`` unless a valid token is supplied."""

    if not presented_token or not verify_csrf_token(expected_hash, presented_token):
        raise CSRFError("invalid CSRF token")


@dataclass(frozen=True)
class SessionCredentials:
    """Plaintext values returned once when a session is created or rotated."""

    session_token: str
    csrf_token: str

    @property
    def token(self) -> str:
        """Compatibility alias for callers that call the cookie ``token``."""

        return self.session_token

    def __repr__(self) -> str:
        # Credentials are intentionally not printable; accidental repr() in a
        # structured log must not defeat the redaction filter.
        return "SessionCredentials(session_token=<redacted>, csrf_token=<redacted>)"


@dataclass
class SessionRecord:
    """Persistable session state; only hashes, never plaintext tokens, live here."""

    id: str
    user_id: str
    token_hash: str
    csrf_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    rotated_at: datetime | None = None
    replaced_by: str | None = None

    @property
    def active(self) -> bool:
        now = utc_now()
        return self.revoked_at is None and _aware(self.expires_at) > now

    def is_active(self, now: datetime | None = None) -> bool:
        current = _aware(now)
        return self.revoked_at is None and _aware(self.expires_at) > current


class SessionStore:
    """Thread-safe in-memory session repository for local flows and unit tests.

    Production code can use the same lifecycle methods against a SQLAlchemy
    repository.  Keeping this implementation here makes the security contract
    executable without a database or external services.
    """

    def __init__(self, *, session_ttl: timedelta = DEFAULT_SESSION_TTL):
        self.session_ttl = session_ttl
        self._sessions: dict[str, SessionRecord] = {}
        self._by_token_hash: dict[str, str] = {}
        self._lock = threading.RLock()

    def create(
        self,
        user_id: str,
        *,
        now: datetime | None = None,
        ttl: timedelta | None = None,
    ) -> tuple[SessionRecord, SessionCredentials]:
        if not user_id:
            raise ValueError("user_id is required")
        current = _aware(now)
        lifetime = ttl if ttl is not None else self.session_ttl
        if lifetime <= timedelta(0):
            raise ValueError("session TTL must be positive")
        session_token = generate_token()
        csrf_token = generate_csrf_token()
        record = SessionRecord(
            id=new_identifier(),
            user_id=str(user_id),
            token_hash=hash_token(session_token),
            csrf_hash=hash_token(csrf_token),
            created_at=current,
            expires_at=current + lifetime,
        )
        with self._lock:
            self._sessions[record.id] = record
            self._by_token_hash[record.token_hash] = record.id
        return record, SessionCredentials(session_token, csrf_token)

    def _get_by_token(self, session_token: str) -> SessionRecord:
        token_digest = hash_token(session_token)
        with self._lock:
            session_id = self._by_token_hash.get(token_digest)
            record = self._sessions.get(session_id) if session_id else None
        if record is None:
            raise InvalidTokenError("unknown session")
        if record.revoked_at is not None:
            raise SessionRevokedError("session revoked")
        if not record.is_active():
            raise SessionExpiredError("session expired")
        # Check the digest again so a repository implementation cannot use a
        # hash index as an authorization bypass.
        if not token_matches(session_token, record.token_hash):
            raise InvalidTokenError("invalid session")
        return record

    def authenticate(self, session_token: str) -> SessionRecord:
        """Validate and return an active session record."""

        if not session_token:
            raise InvalidTokenError("session token is required")
        return self._get_by_token(session_token)

    get_active = authenticate

    def rotate(
        self,
        session_token: str,
        *,
        now: datetime | None = None,
        ttl: timedelta | None = None,
    ) -> tuple[SessionRecord, SessionCredentials]:
        """Atomically revoke a valid session and issue a replacement."""

        old = self._get_by_token(session_token)
        current = _aware(now)
        with self._lock:
            # Re-check under the write lock to prevent two concurrent callback
            # requests from both successfully rotating one session.
            if old.revoked_at is not None:
                raise SessionRevokedError("session already rotated or revoked")
            old.revoked_at = current
            old.rotated_at = current
            replacement, credentials = self.create(old.user_id, now=current, ttl=ttl)
            old.replaced_by = replacement.id
        return replacement, credentials

    rotate_session = rotate

    def revoke(self, session_token: str, *, now: datetime | None = None) -> SessionRecord:
        """Revoke an active session; unknown tokens remain an error."""

        record = self._get_by_token(session_token)
        with self._lock:
            record.revoked_at = _aware(now)
        return record

    revoke_session = revoke

    def revoke_user(self, user_id: str, *, now: datetime | None = None) -> int:
        """Revoke every active session for a user (e.g. account deletion)."""

        current = _aware(now)
        count = 0
        with self._lock:
            for record in self._sessions.values():
                if record.user_id == str(user_id) and record.revoked_at is None:
                    record.revoked_at = current
                    count += 1
        return count

    def verify_csrf(self, session_token: str, presented_token: str | None) -> SessionRecord:
        """Authenticate a session and enforce its CSRF token."""

        record = self._get_by_token(session_token)
        require_csrf(record.csrf_hash, presented_token)
        return record


SessionManager = SessionStore


def normalize_role(role: Role | str) -> Role:
    if isinstance(role, Role):
        return role
    if not isinstance(role, str):
        raise AuthorizationError("unknown role")
    value = role.strip().lower()
    try:
        return Role(value)
    except ValueError as exc:
        raise AuthorizationError("unknown role") from exc


def role_rank(role: Role | str) -> int:
    return ROLE_RANK[normalize_role(role)]


def role_allows(actor_role: Role | str, required_role: Role | str) -> bool:
    """Return whether an actor role satisfies a minimum role requirement."""

    actor = normalize_role(actor_role)
    required = normalize_role(required_role)
    if actor is Role.ADMIN:
        return True
    # Reviewer actions are distinct from analyst actions.  A reviewer does not
    # automatically gain analyst access merely due to numeric ordering.
    if required is Role.ANALYST:
        return actor in {Role.ANALYST, Role.ADMIN}
    if required is Role.REVIEWER:
        return actor in {Role.REVIEWER, Role.ADMIN}
    return role_rank(actor) >= role_rank(required)


has_role = role_allows
check_role = role_allows


def require_role(actor_role: Role | str, required_role: Role | str) -> Role:
    actor = normalize_role(actor_role)
    if not role_allows(actor, required_role):
        required = normalize_role(required_role)
        raise AuthorizationError(
            f"role {actor.value} is not allowed to perform a {required.value} action"
        )
    return actor


def require_any_role(actor_role: Role | str, required_roles: Iterable[Role | str]) -> Role:
    actor = normalize_role(actor_role)
    requirements = tuple(required_roles)
    if not any(role_allows(actor, required) for required in requirements):
        labels = ", ".join(normalize_role(required).value for required in requirements)
        raise AuthorizationError(f"role {actor.value} requires one of: {labels}")
    return actor


def _canonical_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RedirectNotAllowedError("redirect URI must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise RedirectNotAllowedError("redirect URI cannot contain credentials")
    if parsed.fragment:
        raise RedirectNotAllowedError("redirect URI cannot contain a fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RedirectNotAllowedError("redirect URI has an invalid port") from exc
    hostname = parsed.hostname.lower().rstrip(".")
    # Drop default ports so equivalent configured URLs compare consistently.
    netloc = hostname
    is_default_port = (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    )
    if port is not None and not is_default_port:
        netloc = f"{hostname}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


class RedirectAllowlist:
    """Exact redirect URL/origin allowlist with open-redirect protections.

    Entries with a path other than ``/`` match exactly.  An entry consisting of
    an origin (for example ``https://app.example``) intentionally allows paths
    under that configured origin; this is useful when multiple fixed callback
    routes share one trusted frontend origin.
    """

    def __init__(self, allowed: Iterable[str] = ()):
        self._entries = tuple(_canonical_url(item) for item in allowed)
        if not self._entries:
            raise ValueError("redirect allowlist cannot be empty")

    @property
    def entries(self) -> tuple[str, ...]:
        return self._entries

    def is_allowed(self, redirect_uri: str) -> bool:
        try:
            candidate = _canonical_url(redirect_uri)
            parsed = urlsplit(candidate)
        except RedirectNotAllowedError:
            return False
        for entry in self._entries:
            if candidate == entry:
                return True
            configured = urlsplit(entry)
            if configured.path == "/" and not configured.query:
                # Origin-only entries intentionally ignore the candidate path,
                # but still require the same scheme and host/port.
                if (parsed.scheme, parsed.netloc) == (configured.scheme, configured.netloc):
                    return True
        return False

    def validate(self, redirect_uri: str) -> str:
        candidate = _canonical_url(redirect_uri)
        if not self.is_allowed(candidate):
            raise RedirectNotAllowedError("redirect URI is not allowlisted")
        return candidate

    check = validate


def validate_redirect_uri(redirect_uri: str, allowed: Iterable[str]) -> str:
    """Validate and return a canonical redirect URI."""

    return RedirectAllowlist(allowed).validate(redirect_uri)


def is_allowed_redirect(redirect_uri: str, allowed: Iterable[str]) -> bool:
    """Boolean convenience wrapper for redirect validation."""

    try:
        validate_redirect_uri(redirect_uri, allowed)
    except (RedirectNotAllowedError, ValueError):
        return False
    return True


redirect_allowed = is_allowed_redirect


@dataclass(frozen=True)
class OAuthChallenge:
    """Server-side OAuth callback challenge (state and nonce are one-use)."""

    state: str
    nonce: str
    redirect_uri: str
    expires_at: datetime

    def is_expired(self, now: datetime | None = None) -> bool:
        return _aware(self.expires_at) <= _aware(now)


def new_oauth_challenge(
    redirect_uri: str,
    allowlist: RedirectAllowlist,
    *,
    now: datetime | None = None,
    ttl: timedelta = DEFAULT_OAUTH_TTL,
) -> OAuthChallenge:
    """Create a state/nonce pair only for an allowlisted callback target."""

    canonical = allowlist.validate(redirect_uri)
    if ttl <= timedelta(0):
        raise ValueError("OAuth challenge TTL must be positive")
    current = _aware(now)
    return OAuthChallenge(
        state=generate_token(),
        nonce=generate_token(),
        redirect_uri=canonical,
        expires_at=current + ttl,
    )


__all__ = [
    "AuthorizationError",
    "CSRFError",
    "DEFAULT_OAUTH_TTL",
    "DEFAULT_SESSION_TTL",
    "InvalidTokenError",
    "OAuthChallenge",
    "OAuthStateError",
    "RedirectAllowlist",
    "RedirectNotAllowedError",
    "Role",
    "ROLE_RANK",
    "SecurityError",
    "SessionCredentials",
    "SessionExpiredError",
    "SessionRecord",
    "SessionRevokedError",
    "SessionStore",
    "SessionManager",
    "UserRole",
    "csrf_matches",
    "generate_csrf_token",
    "generate_opaque_token",
    "generate_token",
    "hash_token",
    "has_role",
    "is_allowed_redirect",
    "new_identifier",
    "new_oauth_challenge",
    "normalize_role",
    "require_any_role",
    "require_csrf",
    "require_role",
    "role_allows",
    "role_rank",
    "redirect_allowed",
    "sha256_token",
    "token_hash",
    "token_matches",
    "utc_now",
    "validate_redirect_uri",
    "verify_csrf_token",
    "verify_csrf",
    "verify_token",
    "check_role",
]
