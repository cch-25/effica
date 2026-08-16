"""OAuth flow, session lifecycle, and role/authentication facade."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from ...core.security import (
    DEFAULT_OAUTH_TTL,
    AuthorizationError,
    OAuthChallenge,
    OAuthStateError,
    RedirectAllowlist,
    Role,
    SessionCredentials,
    SessionRecord,
    SessionStore,
    new_oauth_challenge,
    require_role,
    utc_now,
)
from ..users.models import OAuthAccount, OnboardingState, User
from ..users.service import InMemoryUserRepository, UserService
from .providers import (
    MockOAuthProvider,
    ProviderName,
    ProviderRegistry,
)


@dataclass(frozen=True)
class PendingOAuthChallenge:
    provider: str
    challenge: OAuthChallenge


class OAuthStateStore:
    """One-use server-side state/nonce store.

    State values are random opaque handles.  The redirect URI and provider are
    kept server-side so a callback cannot swap either value.
    """

    def __init__(self, *, default_ttl: timedelta = DEFAULT_OAUTH_TTL):
        self.default_ttl = default_ttl
        self._pending: dict[str, PendingOAuthChallenge] = {}
        self._lock = threading.RLock()

    def issue(
        self,
        provider: ProviderName | str,
        redirect_uri: str,
        allowlist: RedirectAllowlist,
        *,
        now: datetime | None = None,
        ttl: timedelta | None = None,
    ) -> PendingOAuthChallenge:
        name = (
            provider.value if isinstance(provider, ProviderName) else str(provider).strip().lower()
        )
        challenge = new_oauth_challenge(
            redirect_uri,
            allowlist,
            now=now,
            ttl=ttl or self.default_ttl,
        )
        pending = PendingOAuthChallenge(name, challenge)
        with self._lock:
            self._pending[challenge.state] = pending
        return pending

    create = issue

    def consume(
        self,
        state: str,
        *,
        now: datetime | None = None,
    ) -> PendingOAuthChallenge:
        if not state:
            raise OAuthStateError("OAuth state is required")
        with self._lock:
            pending = self._pending.pop(state, None)
        if pending is None:
            raise OAuthStateError("OAuth state is invalid or already used")
        if pending.challenge.is_expired(now):
            raise OAuthStateError("OAuth state expired")
        return pending

    validate_and_consume = consume

    def discard_expired(self, *, now: datetime | None = None) -> int:
        current = now or utc_now()
        with self._lock:
            expired = [
                state
                for state, pending in self._pending.items()
                if pending.challenge.is_expired(current)
            ]
            for state in expired:
                del self._pending[state]
        return len(expired)


@dataclass(frozen=True)
class OAuthStart:
    provider: str
    authorization_url: str
    state: str
    redirect_uri: str
    expires_at: datetime


@dataclass(frozen=True)
class AuthResult:
    user: User
    oauth_account: OAuthAccount
    session: SessionRecord
    credentials: SessionCredentials
    created: bool
    redirect_uri: str
    onboarding: OnboardingState

    @property
    def session_token(self) -> str:
        return self.credentials.session_token


OAuthCallbackResult = AuthResult


class AuthService:
    """Coordinates provider callback validation and local account sessions."""

    def __init__(
        self,
        *,
        providers: ProviderRegistry | None = None,
        redirect_allowlist: RedirectAllowlist | None = None,
        sessions: SessionStore | None = None,
        users: UserService | None = None,
        state_store: OAuthStateStore | None = None,
    ):
        self.providers = providers or ProviderRegistry({ProviderName.MOCK: MockOAuthProvider()})
        self.redirect_allowlist = redirect_allowlist
        self.sessions = sessions or SessionStore()
        self.users = users or UserService(InMemoryUserRepository())
        self.state_store = state_store or OAuthStateStore()

    def start_oauth(
        self,
        provider: ProviderName | str,
        redirect_uri: str,
        *,
        now: datetime | None = None,
        ttl: timedelta | None = None,
    ) -> OAuthStart:
        if self.redirect_allowlist is None:
            raise OAuthStateError("OAuth redirect allowlist is not configured")
        name = (
            provider.value if isinstance(provider, ProviderName) else str(provider).strip().lower()
        )
        adapter = self.providers.get(name)
        pending = self.state_store.issue(
            name,
            redirect_uri,
            self.redirect_allowlist,
            now=now,
            ttl=ttl,
        )
        url = adapter.authorization_url(
            pending.challenge.state,
            pending.challenge.nonce,
            pending.challenge.redirect_uri,
        )
        return OAuthStart(
            provider=name,
            authorization_url=url,
            state=pending.challenge.state,
            redirect_uri=pending.challenge.redirect_uri,
            expires_at=pending.challenge.expires_at,
        )

    begin_oauth = start_oauth
    oauth_start = start_oauth

    async def complete_oauth(
        self,
        provider: ProviderName | str,
        *,
        code: str,
        state: str,
        redirect_uri: str | None = None,
        current_session_token: str | None = None,
        now: datetime | None = None,
    ) -> AuthResult:
        """Consume state, exchange code, link identity, and rotate/create session."""

        name = (
            provider.value if isinstance(provider, ProviderName) else str(provider).strip().lower()
        )
        pending = self.state_store.consume(state, now=now)
        if pending.provider != name:
            raise OAuthStateError("OAuth provider does not match callback state")
        callback_uri = pending.challenge.redirect_uri
        if redirect_uri is not None:
            if self.redirect_allowlist is None:
                raise OAuthStateError("OAuth redirect allowlist is not configured")
            callback_uri = self.redirect_allowlist.validate(redirect_uri)
            if callback_uri != pending.challenge.redirect_uri:
                raise OAuthStateError("OAuth redirect URI does not match callback state")
        adapter = self.providers.get(name)
        identity = await adapter.exchange_code(
            code,
            callback_uri,
            expected_nonce=pending.challenge.nonce,
        )
        if identity.provider != name:
            # A custom adapter must not smuggle an identity from another
            # provider into a callback.
            raise OAuthStateError("OAuth identity provider mismatch")
        user, account, created = self.users.find_or_create_oauth_user(
            provider=identity.provider,
            subject=identity.subject,
            email=identity.email,
            display_name=identity.display_name,
        )
        if current_session_token:
            current = self.sessions.authenticate(current_session_token)
            if current.user_id != user.id:
                # Do not rotate or revoke the existing browser session when an
                # OAuth callback resolves to another account.
                raise AuthorizationError("OAuth account does not match current session")
            session, credentials = self.sessions.rotate(current_session_token, now=now)
        else:
            session, credentials = self.sessions.create(user.id, now=now)
        return AuthResult(
            user=user,
            oauth_account=account,
            session=session,
            credentials=credentials,
            created=created,
            redirect_uri=callback_uri,
            onboarding=self.users.onboarding_state(user.id),
        )

    callback = complete_oauth
    oauth_callback = complete_oauth

    def authenticate(self, session_token: str) -> User:
        session = self.sessions.authenticate(session_token)
        return self.users.require_active(session.user_id)

    current_user = authenticate

    def authenticate_with_csrf(self, session_token: str, csrf_token: str) -> User:
        session = self.sessions.verify_csrf(session_token, csrf_token)
        return self.users.require_active(session.user_id)

    def logout(self, session_token: str) -> None:
        self.sessions.revoke(session_token)

    revoke = logout

    def require_role(
        self,
        session_token: str,
        required_role: Role | str,
        *,
        csrf_token: str | None = None,
    ) -> User:
        if csrf_token is not None:
            user = self.authenticate_with_csrf(session_token, csrf_token)
        else:
            user = self.authenticate(session_token)
        require_role(user.role, required_role)
        return user


__all__ = [
    "AuthResult",
    "AuthService",
    "OAuthCallbackResult",
    "OAuthStart",
    "OAuthStateStore",
    "PendingOAuthChallenge",
]
