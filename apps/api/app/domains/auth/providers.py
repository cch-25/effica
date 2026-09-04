"""OAuth provider interfaces and configured Kakao/Naver/Google adapters.

The adapters are deliberately transport-injected.  Production can provide a
small HTTP client with the configured timeout/retry policy, while tests use a
deterministic callable or ``MockOAuthProvider`` and never contact the public
network.  Access tokens are used for the user-info request and are never part
of the returned identity object or persisted by this module.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import inspect
import json
import math
import time
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class OAuthError(Exception):
    """Base OAuth adapter error safe to map to an API error envelope."""


class OAuthProviderDisabled(OAuthError):
    """Raised when a provider has no server-side client configuration."""


class OAuthTransportError(OAuthError):
    """Raised when an OAuth provider could not be reached after retries."""


class OAuthResponseError(OAuthError):
    """Raised when a provider returns an invalid or unusable response."""


class OAuthNonceError(OAuthResponseError):
    """Raised when a provider response does not match the callback nonce."""


class ProviderName(str, Enum):
    GOOGLE = "google"
    MOCK = "mock"


@dataclass(frozen=True)
class OAuthProviderConfig:
    """Server-only OAuth settings; never expose ``client_secret`` to a route."""

    provider: ProviderName | str
    client_id: str = ""
    client_secret: str = ""
    authorize_endpoint: str = ""
    token_endpoint: str = ""
    userinfo_endpoint: str = ""
    scopes: tuple[str, ...] = ()
    timeout_seconds: float = 5.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.1
    enabled: bool = True
    issuer: str = ""
    jwks_endpoint: str = ""

    def normalized_provider(self) -> str:
        value = (
            self.provider.value if isinstance(self.provider, ProviderName) else str(self.provider)
        )
        return value.strip().lower()

    def validate(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("OAuth timeout must be positive")
        if self.max_retries < 0:
            raise ValueError("OAuth max_retries cannot be negative")
        if self.retry_backoff_seconds < 0:
            raise ValueError("OAuth retry backoff cannot be negative")
        if self.enabled and not self.client_id:
            raise ValueError("enabled OAuth providers require a client_id")


@dataclass(frozen=True)
class OAuthUserInfo:
    """Minimal identity claims needed to create/link a local account."""

    provider: str
    subject: str
    email: str | None = None
    display_name: str | None = None
    nonce: str | None = None
    avatar_url: str | None = None

    @property
    def provider_subject(self) -> str:
        return self.subject


class OAuthTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float,
    ) -> Any:
        """Return a mapping or an object with ``status_code``/``json``."""


class UrllibOAuthTransport:
    """Minimal stdlib transport with an explicit request timeout."""

    def request(
        self,
        method: str,
        url: str,
        *,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float,
    ) -> Mapping[str, Any]:
        body: bytes | None = None
        target = url
        if method.upper() == "GET" and data:
            target = "{}{}{}".format(url, "&" if "?" in url else "?", urlencode(data))
        elif data is not None:
            body = urlencode(data).encode("utf-8")
        request = Request(target, data=body, method=method.upper())
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", "application/x-www-form-urlencoded")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        with urlopen(request, timeout=timeout) as response:  # nosec B310 - endpoint is configured server-side
            raw = response.read()
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OAuthResponseError("OAuth provider returned invalid JSON") from exc
        if not isinstance(value, Mapping):
            raise OAuthResponseError("OAuth provider returned a non-object response")
        return value


TransportLike = OAuthTransport | Callable[..., Any]


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _response_json(response: Any) -> Mapping[str, Any]:
    if isinstance(response, tuple) and len(response) == 2:
        status, payload = response
        if isinstance(status, int) and status >= 400:
            raise OAuthResponseError(f"OAuth provider returned HTTP {status}")
        response = payload
    if isinstance(response, Mapping):
        return response
    status = getattr(response, "status_code", 200)
    if status >= 400:
        raise OAuthResponseError(f"OAuth provider returned HTTP {status}")
    payload = (
        response.json()
        if callable(getattr(response, "json", None))
        else getattr(response, "json", None)
    )
    if inspect.isawaitable(payload):
        raise OAuthResponseError("asynchronous response.json must be handled by transport")
    if not isinstance(payload, Mapping):
        raise OAuthResponseError("OAuth provider returned a non-object response")
    return payload


class OAuthProvider(Protocol):
    name: str

    def authorization_url(self, state: str, nonce: str, redirect_uri: str) -> str: ...

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        *,
        expected_nonce: str | None = None,
    ) -> OAuthUserInfo: ...


class ConfiguredOAuthProvider:
    """Common implementation for providers with code/token/user-info endpoints."""

    name = "oauth"
    default_scopes: tuple[str, ...] = ()
    token_auth_style = "form"

    def __init__(
        self,
        config: OAuthProviderConfig,
        *,
        transport: TransportLike | None = None,
    ):
        self.config = config
        self.config.validate()
        self.name = config.normalized_provider()
        self._transport = transport or UrllibOAuthTransport()

    @property
    def enabled(self) -> bool:
        return bool(self.config.enabled and self.config.client_id and self.config.client_secret)

    def _ensure_enabled(self) -> None:
        if not self.enabled:
            raise OAuthProviderDisabled(f"OAuth provider {self.name} is disabled")
        if not (
            self.config.authorize_endpoint
            and self.config.token_endpoint
            and self.config.userinfo_endpoint
        ):
            raise OAuthProviderDisabled(f"OAuth provider {self.name} is incompletely configured")

    def authorization_url(self, state: str, nonce: str, redirect_uri: str) -> str:
        if not state or not nonce:
            raise OAuthResponseError("state and nonce are required")
        self._ensure_enabled()
        scopes = self.config.scopes or self.default_scopes
        query = {
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "nonce": nonce,
        }
        if scopes:
            query["scope"] = " ".join(scopes)
        return "{}{}{}".format(
            self.config.authorize_endpoint,
            "&" if "?" in self.config.authorize_endpoint else "?",
            urlencode(query),
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Mapping[str, Any]:
        attempts = self.config.max_retries + 1
        last_error: BaseException | None = None
        for attempt in range(attempts):
            try:
                if hasattr(self._transport, "request"):
                    response = self._transport.request(
                        method,
                        url,
                        data=data,
                        headers=headers,
                        timeout=self.config.timeout_seconds,
                    )
                else:
                    response = self._transport(
                        method,
                        url,
                        data=data,
                        headers=headers,
                        timeout=self.config.timeout_seconds,
                    )
                result = await _maybe_await(response)
                return _response_json(result)
            except (OAuthResponseError, ValueError) as exc:
                # A malformed/4xx response is not made better by retries.  A
                # custom transport can raise OAuthTransportError for retryable
                # network failures.
                raise OAuthResponseError("OAuth provider returned an invalid response") from exc
            except Exception as exc:  # transport libraries have varied errors
                last_error = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(self.config.retry_backoff_seconds * (2**attempt))
        raise OAuthTransportError("OAuth provider request failed after retries") from last_error

    @staticmethod
    def _require_string(payload: Mapping[str, Any], key: str, *, context: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise OAuthResponseError(f"OAuth {context} response is missing {key}")
        return value.strip()

    @staticmethod
    def _require_subject(payload: Mapping[str, Any], key: str, *, context: str) -> str:
        """Accept a string or integer subject; JSON numbers are common (Kakao)."""

        value = payload.get(key)
        if isinstance(value, bool) or value is None:
            raise OAuthResponseError(f"OAuth {context} response is missing {key}")
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise OAuthResponseError(f"OAuth {context} response is missing {key}")

    async def _validate_token_response(
        self, token_response: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        """Validate provider-specific token claims before requesting userinfo."""

        del token_response
        return None

    def _merge_token_claims(
        self,
        profile: OAuthUserInfo,
        token_claims: Mapping[str, Any] | None,
    ) -> OAuthUserInfo:
        """Merge claims already validated by a provider-specific adapter."""

        del token_claims
        return profile

    def _validate_nonce(self, profile: OAuthUserInfo, expected_nonce: str | None) -> None:
        if expected_nonce is None:
            return
        # Some providers return nonce only in an ID token.  The configured
        # adapter must expose it after validating that token.  Requiring it in
        # this common layer prevents a callback from silently skipping nonce
        # verification in tests or custom transports.
        if not profile.nonce or not hmac_compare(profile.nonce, expected_nonce):
            raise OAuthNonceError("OAuth nonce mismatch")

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        *,
        expected_nonce: str | None = None,
    ) -> OAuthUserInfo:
        self._ensure_enabled()
        if not code:
            raise OAuthResponseError("OAuth authorization code is required")
        token_response = await self._request(
            "POST",
            self.config.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
        )
        access_token = self._require_string(token_response, "access_token", context="token")
        token_claims = await self._validate_token_response(token_response)
        # ``access_token`` exists only in this local variable and is passed to
        # the user-info request.  It is never returned or persisted.
        profile_payload = await self._request(
            "GET",
            self.config.userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        profile = self._parse_profile(profile_payload)
        profile = self._merge_token_claims(profile, token_claims)
        self._validate_nonce(profile, expected_nonce)
        return profile

    def _parse_profile(self, payload: Mapping[str, Any]) -> OAuthUserInfo:
        subject = self._require_string(payload, "sub", context="profile")
        return OAuthUserInfo(provider=self.name, subject=subject)


def _decode_base64url(value: Any, *, context: str) -> bytes:
    """Decode an unpadded base64url value without accepting junk characters."""

    if not isinstance(value, str) or not value or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        for character in value
    ):
        raise OAuthResponseError(f"OAuth {context} contains invalid base64url data")
    try:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (UnicodeError, binascii.Error, ValueError) as exc:
        raise OAuthResponseError(f"OAuth {context} contains invalid base64url data") from exc


def _decode_json_object(value: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, str):
        raise OAuthResponseError(f"OAuth {context} is invalid")
    try:
        decoded = json.loads(_decode_base64url(value, context=context).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OAuthResponseError(f"OAuth {context} is invalid") from exc
    if not isinstance(decoded, Mapping):
        raise OAuthResponseError(f"OAuth {context} must be an object")
    return decoded


def hmac_compare(left: str, right: str) -> bool:
    # Local import avoids exposing another hash helper from the core security
    # module in this adapter's public surface.
    import hmac

    return hmac.compare_digest(left, right)


class GoogleOAuthProvider(ConfiguredOAuthProvider):
    name = ProviderName.GOOGLE.value
    default_scopes = ("openid", "email", "profile")
    issuer = "https://accounts.google.com"
    jwks_endpoint = "https://www.googleapis.com/oauth2/v3/certs"
    id_token_algorithm = "RS256"

    def __init__(
        self,
        config: OAuthProviderConfig,
        *,
        transport: TransportLike | None = None,
        clock: Callable[[], float] | None = None,
    ):
        super().__init__(config, transport=transport)
        self._clock = clock or time.time

    async def _validate_google_id_token(self, id_token: str) -> Mapping[str, Any]:
        parts = id_token.split(".")
        if len(parts) != 3 or any(not part for part in parts):
            raise OAuthResponseError("Google id_token is not a compact JWS")

        header = _decode_json_object(parts[0], context="Google id_token header")
        claims = _decode_json_object(parts[1], context="Google id_token claims")
        if header.get("alg") != self.id_token_algorithm:
            raise OAuthResponseError("Google id_token uses an unsupported signing algorithm")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise OAuthResponseError("Google id_token is missing a signing key id")
        signature = _decode_base64url(parts[2], context="Google id_token signature")
        try:
            signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        except UnicodeEncodeError as exc:
            raise OAuthResponseError("Google id_token contains non-ASCII segments") from exc
        signing_key = await self._get_jwks_key(kid)
        try:
            signing_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise OAuthResponseError("Google id_token signature verification failed") from exc

        expected_issuer = self.config.issuer
        valid_issuers = (
            (expected_issuer,)
            if expected_issuer
            else (self.issuer, "accounts.google.com")
        )
        if claims.get("iss") not in valid_issuers:
            raise OAuthResponseError("Google id_token issuer is invalid")
        audience = claims.get("aud")
        if isinstance(audience, str):
            audiences = (audience,)
        elif isinstance(audience, list) and audience and all(
            isinstance(item, str) and item for item in audience
        ):
            audiences = tuple(audience)
        else:
            raise OAuthResponseError("Google id_token audience is invalid")
        if self.config.client_id not in audiences:
            raise OAuthResponseError("Google id_token audience does not match client_id")
        if len(audiences) > 1 and claims.get("azp") != self.config.client_id:
            raise OAuthResponseError("Google id_token authorized party is invalid")

        expiry = claims.get("exp")
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
            raise OAuthResponseError("Google id_token expiry is invalid")
        if not math.isfinite(float(expiry)) or self._clock() >= float(expiry):
            raise OAuthResponseError("Google id_token is expired")

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise OAuthResponseError("Google id_token subject is invalid")
        nonce = claims.get("nonce")
        if nonce is not None and (not isinstance(nonce, str) or not nonce):
            raise OAuthResponseError("Google id_token nonce is invalid")
        return claims

    async def _get_jwks_key(self, kid: str) -> rsa.RSAPublicKey:
        endpoint = self.config.jwks_endpoint or self.jwks_endpoint
        jwks = await self._request("GET", endpoint)
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            raise OAuthResponseError("Google JWKS response is invalid")
        candidates = [
            key
            for key in keys
            if isinstance(key, Mapping)
            and key.get("kid") == kid
            and key.get("kty") == "RSA"
            and key.get("alg", self.id_token_algorithm) == self.id_token_algorithm
            and key.get("use", "sig") == "sig"
        ]
        if len(candidates) != 1:
            raise OAuthResponseError("Google JWKS does not contain a unique signing key")
        key = candidates[0]
        modulus = _decode_base64url(key.get("n"), context="Google JWKS modulus")
        exponent = _decode_base64url(key.get("e"), context="Google JWKS exponent")
        try:
            return rsa.RSAPublicNumbers(
                int.from_bytes(exponent, byteorder="big"),
                int.from_bytes(modulus, byteorder="big"),
            ).public_key()
        except (TypeError, ValueError) as exc:
            raise OAuthResponseError("Google JWKS signing key is invalid") from exc

    async def _validate_token_response(
        self, token_response: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        id_token = token_response.get("id_token")
        if not isinstance(id_token, str):
            raise OAuthResponseError("Google token response is missing id_token")
        return await self._validate_google_id_token(id_token)

    def _merge_token_claims(
        self,
        profile: OAuthUserInfo,
        token_claims: Mapping[str, Any] | None,
    ) -> OAuthUserInfo:
        if token_claims is None:
            raise OAuthResponseError("Google ID-token claims were not validated")
        token_subject = token_claims.get("sub")
        if token_subject != profile.subject:
            raise OAuthResponseError("Google ID-token subject does not match userinfo")
        nonce = token_claims.get("nonce")
        return replace(profile, nonce=nonce if isinstance(nonce, str) else None)

    def _parse_profile(self, payload: Mapping[str, Any]) -> OAuthUserInfo:
        subject = self._require_string(payload, "sub", context="profile")
        return OAuthUserInfo(
            provider=self.name,
            subject=subject,
            email=payload.get("email") if isinstance(payload.get("email"), str) else None,
            display_name=(payload.get("name") if isinstance(payload.get("name"), str) else None),
            nonce=(payload.get("nonce") if isinstance(payload.get("nonce"), str) else None),
            avatar_url=(
                payload.get("picture") if isinstance(payload.get("picture"), str) else None
            ),
        )


def _default_endpoints(provider: str) -> tuple[str, str, str]:
    if provider == ProviderName.GOOGLE.value:
        return (
            "https://accounts.google.com/o/oauth2/v2/auth",
            "https://oauth2.googleapis.com/token",
            "https://openidconnect.googleapis.com/v1/userinfo",
        )
    raise ValueError(f"unsupported OAuth provider: {provider}")


def provider_from_config(
    config: OAuthProviderConfig,
    *,
    transport: TransportLike | None = None,
) -> ConfiguredOAuthProvider:
    """Build one configured provider with defaults for official endpoints."""

    provider = config.normalized_provider()
    authorize, token, userinfo = _default_endpoints(provider)
    if not config.authorize_endpoint or not config.token_endpoint or not config.userinfo_endpoint:
        config = OAuthProviderConfig(
            provider=config.provider,
            client_id=config.client_id,
            client_secret=config.client_secret,
            authorize_endpoint=config.authorize_endpoint or authorize,
            token_endpoint=config.token_endpoint or token,
            userinfo_endpoint=config.userinfo_endpoint or userinfo,
            scopes=config.scopes,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            retry_backoff_seconds=config.retry_backoff_seconds,
            enabled=config.enabled,
            issuer=config.issuer,
            jwks_endpoint=config.jwks_endpoint,
        )
    if provider != ProviderName.GOOGLE.value:
        raise ValueError(f"unsupported configured OAuth provider: {provider}")
    return GoogleOAuthProvider(config, transport=transport)


class MockOAuthProvider:
    """Deterministic OAuth provider used for local/integration flows."""

    name = ProviderName.MOCK.value

    def __init__(
        self,
        *,
        issuer: str = "http://mock.oauth.local",
        users: Mapping[str, OAuthUserInfo] | None = None,
    ):
        self.issuer = issuer.rstrip("/")
        self._users: MutableMapping[str, OAuthUserInfo] = dict(users or {})
        self._used_codes: set[str] = set()

    def register_code(
        self,
        code: str,
        *,
        subject: str,
        email: str | None = None,
        display_name: str | None = None,
        nonce: str | None = None,
    ) -> OAuthUserInfo:
        if not code or not subject:
            raise ValueError("mock code and subject are required")
        profile = OAuthUserInfo(
            provider=self.name,
            subject=subject,
            email=email,
            display_name=display_name,
            nonce=nonce,
        )
        self._users[code] = profile
        return profile

    def authorization_url(self, state: str, nonce: str, redirect_uri: str) -> str:
        if not state or not nonce:
            raise OAuthResponseError("state and nonce are required")
        return "{}/authorize?{}".format(
            self.issuer,
            urlencode({"state": state, "nonce": nonce, "redirect_uri": redirect_uri}),
        )

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        *,
        expected_nonce: str | None = None,
    ) -> OAuthUserInfo:
        del redirect_uri  # The caller validates the URI before this adapter runs.
        if not code or code in self._used_codes:
            raise OAuthResponseError("invalid or replayed mock authorization code")
        profile = self._users.get(code)
        if profile is None:
            # A stable, explicit local fallback keeps tests simple while still
            # avoiding any accidental production identity.
            if code.startswith("mock-"):
                import hashlib

                subject = hashlib.sha256(code.encode("utf-8")).hexdigest()[:24]
                profile = OAuthUserInfo(provider=self.name, subject=subject, nonce=expected_nonce)
            else:
                raise OAuthResponseError("unknown mock authorization code")
        if expected_nonce is not None:
            if profile.nonce is None:
                # The local provider models a code exchange that validates the
                # nonce server-side; it need not manufacture an ID-token claim
                # in every fixture.  A supplied, mismatching nonce still fails.
                profile = OAuthUserInfo(
                    provider=profile.provider,
                    subject=profile.subject,
                    email=profile.email,
                    display_name=profile.display_name,
                    nonce=expected_nonce,
                    avatar_url=profile.avatar_url,
                )
            elif not hmac_compare(profile.nonce, expected_nonce):
                raise OAuthNonceError("OAuth nonce mismatch")
        self._used_codes.add(code)
        return profile


class ProviderRegistry:
    """Provider lookup with an explicit allowlist."""

    def __init__(self, providers: Mapping[ProviderName | str, OAuthProvider] | None = None):
        self._providers: dict[str, OAuthProvider] = {}
        for name, provider in (providers or {}).items():
            self.register(name, provider)

    def register(self, name: ProviderName | str, provider: OAuthProvider) -> None:
        key = name.value if isinstance(name, ProviderName) else str(name).strip().lower()
        if key not in {item.value for item in ProviderName}:
            raise ValueError(f"unsupported OAuth provider: {key}")
        self._providers[key] = provider

    def get(self, name: ProviderName | str) -> OAuthProvider:
        key = name.value if isinstance(name, ProviderName) else str(name).strip().lower()
        try:
            return self._providers[key]
        except KeyError as exc:
            raise OAuthProviderDisabled(f"OAuth provider {key} is disabled") from exc

    def __contains__(self, name: object) -> bool:
        key = name.value if isinstance(name, ProviderName) else str(name).strip().lower()
        return key in self._providers

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


__all__ = [
    "ConfiguredOAuthProvider",
    "GoogleOAuthProvider",
    "MockOAuthProvider",
    "OAuthError",
    "OAuthNonceError",
    "OAuthProvider",
    "OAuthProviderConfig",
    "OAuthProviderDisabled",
    "OAuthResponseError",
    "OAuthTransport",
    "OAuthTransportError",
    "OAuthUserInfo",
    "ProviderName",
    "ProviderRegistry",
    "UrllibOAuthTransport",
    "provider_from_config",
]
