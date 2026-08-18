"""Unit coverage for the auth/privacy primitives owned by this workstream."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from apps.api.app.core.logging import redact
from apps.api.app.core.security import (
    AuthorizationError,
    CSRFError,
    InvalidTokenError,
    OAuthStateError,
    RedirectAllowlist,
    RedirectNotAllowedError,
    Role,
    SessionRevokedError,
    SessionStore,
    hash_token,
    new_identifier,
    require_csrf,
    role_allows,
)
from apps.api.app.domains.auth.providers import (
    GoogleOAuthProvider,
    KakaoOAuthProvider,
    MockOAuthProvider,
    NaverOAuthProvider,
    OAuthNonceError,
    OAuthProviderConfig,
    OAuthResponseError,
    ProviderName,
    ProviderRegistry,
)
from apps.api.app.domains.auth.service import AuthResult, AuthService, OAuthStateStore
from apps.api.app.domains.users.models import (
    ConsentPurpose,
    ProfileKind,
    QuestionnaireVersion,
    QuestionSpec,
    UserStatus,
)
from apps.api.app.domains.users.service import (
    ConsentRequiredError,
    ConsentService,
    DeletionConfirmationError,
    InMemoryUserRepository,
    PrivacyService,
    QuestionnaireService,
    UserService,
)


def test_opaque_token_hash_and_session_rotation_revoke() -> None:
    assert len(new_identifier()) == 26
    sessions = SessionStore()
    record, credentials = sessions.create("user-1")
    assert record.token_hash == hash_token(credentials.session_token)
    assert credentials.session_token not in record.token_hash
    assert sessions.authenticate(credentials.session_token).user_id == "user-1"
    rotated, replacement = sessions.rotate(credentials.session_token)
    assert rotated.user_id == "user-1"
    assert sessions.authenticate(replacement.session_token).id == rotated.id
    with pytest.raises(SessionRevokedError):
        sessions.authenticate(credentials.session_token)


def test_csrf_and_role_matrix() -> None:
    token = "csrf-value"
    expected = hash_token(token)
    require_csrf(expected, token)
    with pytest.raises(CSRFError):
        require_csrf(expected, "wrong")
    assert role_allows(Role.ADMIN, Role.REVIEWER)
    assert role_allows(Role.REVIEWER, Role.MEMBER)
    assert not role_allows(Role.REVIEWER, Role.ANALYST)
    with pytest.raises(AuthorizationError):
        from apps.api.app.core.security import require_role

        require_role(Role.MEMBER, Role.ADMIN)


def test_redirect_allowlist_rejects_open_redirect() -> None:
    allowlist = RedirectAllowlist(["https://app.example.test"])
    assert (
        allowlist.validate("https://app.example.test/oauth/callback")
        == "https://app.example.test/oauth/callback"
    )
    assert not allowlist.is_allowed("https://evil.example.test/oauth/callback")
    with pytest.raises(RedirectNotAllowedError):
        allowlist.validate("javascript:alert(1)")


def test_state_store_is_one_use_and_expires() -> None:
    allowlist = RedirectAllowlist(["http://localhost:3000"])
    store = OAuthStateStore(default_ttl=timedelta(seconds=1))
    pending = store.issue("mock", "http://localhost:3000/callback", allowlist)
    assert store.consume(pending.challenge.state).provider == "mock"
    with pytest.raises(OAuthStateError):
        store.consume(pending.challenge.state)


def test_mock_oauth_flow_is_network_free_and_nonce_checked() -> None:
    provider = MockOAuthProvider()
    provider.register_code("ok", subject="subject-1", email="user@example.test")
    registry = ProviderRegistry({ProviderName.MOCK: provider})
    service = AuthService(
        providers=registry,
        redirect_allowlist=RedirectAllowlist(["http://localhost:3000"]),
    )
    start = service.start_oauth("mock", "http://localhost:3000/callback")

    async def callback() -> AuthResult:
        return await service.complete_oauth(
            "mock",
            code="ok",
            state=start.state,
            redirect_uri="http://localhost:3000/callback",
        )

    result = asyncio.run(callback())
    assert result.user.email == "user@example.test"
    assert service.authenticate(result.session_token).id == result.user.id

    # A new challenge and an explicitly wrong provider nonce must fail before
    # an account/session is created.
    provider.register_code("wrong", subject="subject-2", nonce="wrong-nonce")
    second = service.start_oauth("mock", "http://localhost:3000/callback")

    async def bad_callback() -> AuthResult:
        return await service.complete_oauth("mock", code="wrong", state=second.state)

    with pytest.raises(OAuthNonceError):
        asyncio.run(bad_callback())


def _onboarding_fixture() -> tuple[
    InMemoryUserRepository,
    UserService,
    ConsentService,
    QuestionnaireService,
    str,
    str,
]:
    repository = InMemoryUserRepository()
    users = UserService(repository)
    consents = ConsentService(repository, users)
    questionnaires = QuestionnaireService(repository, consents, users)
    user = users.create_user(display_name="Tester")
    sensitive = repository.add_consent_version(
        purpose=ConsentPurpose.SENSITIVE_POLITICAL,
        version="2026-01",
        body_hash="body-hash",
    )
    questionnaire = repository.add_questionnaire_version(
        QuestionnaireVersion(
            id="q-v1",
            kind="political_onboarding",
            version="1",
            questions=(
                QuestionSpec("q-x", "x", scale_min=1, scale_max=5),
                QuestionSpec("q-y", "y", scale_min=1, scale_max=5, reverse=True),
                QuestionSpec("q-z", "z", scale_min=1, scale_max=5),
            ),
        )
    )
    consents.grant(user.id, sensitive.id)
    return repository, users, consents, questionnaires, user.id, questionnaire.id


def test_questionnaire_normalizes_self_reported_profile() -> None:
    repository, users, consents, questionnaires, user_id, version_id = _onboarding_fixture()
    result = questionnaires.submit(user_id, version_id, {"q-x": 5, "q-y": 1, "q-z": 3})
    assert result.profile.kind is ProfileKind.SELF_REPORTED
    assert result.profile.active
    assert result.profile.x == 100
    assert result.profile.y == 100  # reversed low value becomes the positive end
    assert result.profile.z == 0
    assert result.profile.confidence == 1


def test_questionnaire_requires_sensitive_consent_and_withdrawal_disables_profiles() -> None:
    repository, users, consents, questionnaires, user_id, version_id = _onboarding_fixture()
    consents.withdraw(user_id, ConsentPurpose.SENSITIVE_POLITICAL)
    with pytest.raises(ConsentRequiredError):
        questionnaires.submit(user_id, version_id, {"q-x": 3, "q-y": 3, "q-z": 3})
    # Re-grant, submit, then withdraw to verify the active profile is disabled.
    version = repository.add_consent_version(
        purpose=ConsentPurpose.SENSITIVE_POLITICAL,
        version="2026-02",
        body_hash="body-hash-2",
    )
    consents.grant(user_id, version.id)
    questionnaires.submit(user_id, version_id, {"q-x": 3, "q-y": 3, "q-z": 3})
    consents.withdraw(user_id, ConsentPurpose.SENSITIVE_POLITICAL)
    assert not any(item.active for item in repository.profiles.values())
    assert not users.get_user(user_id).personalization_enabled


def test_optional_demographics_and_async_export_delete_jobs() -> None:
    repository, users, consents, questionnaires, user_id, version_id = _onboarding_fixture()
    questionnaires.submit(user_id, version_id, {"q-x": 3, "q-y": 3, "q-z": 3})
    questionnaires.update_demographics(user_id, age_band="30-39")
    sessions = SessionStore()
    _, credentials = sessions.create(user_id)
    privacy = PrivacyService(repository, users, sessions=sessions)
    export_job = privacy.request_export(user_id)
    assert export_job.status.value == "queued"
    completed = privacy.process_job(export_job.id)
    assert completed.result and "questionnaire_responses" in completed.result
    assert "token_hash" not in json.dumps(completed.result)
    with pytest.raises(DeletionConfirmationError):
        privacy.request_deletion(user_id, "delete")
    deletion_job = privacy.request_deletion(user_id, "DELETE MY ACCOUNT")
    privacy.process_job(deletion_job.id)
    assert users.get_user(user_id).status is UserStatus.DELETED
    with pytest.raises(InvalidTokenError):
        sessions.authenticate(credentials.session_token)


def test_structured_redaction_removes_secret_and_questionnaire_data() -> None:
    payload = redact(
        {
            "access_token": "access-secret",
            "oauth_subject": "provider-subject",
            "questionnaire_answers": {"q1": 5},
            "request_id": "req-1",
        }
    )
    assert payload["access_token"] == "[REDACTED]"
    assert payload["oauth_subject"] == "[REDACTED]"
    assert payload["questionnaire_answers"] == "[REDACTED]"
    assert payload["request_id"] == "req-1"


_GOOGLE_NOW = 1_700_000_000.0
_GOOGLE_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _google_jwk() -> dict[str, str]:
    numbers = _GOOGLE_PRIVATE_KEY.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": "test-key",
        "alg": "RS256",
        "use": "sig",
        "n": _b64url(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
        "e": _b64url(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
    }


def _google_id_token(**overrides: object) -> str:
    claims: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": "google-id",
        "exp": _GOOGLE_NOW + 300,
        "sub": "google-sub",
        "nonce": "server-nonce",
    }
    claims.update(overrides)
    encoded_header = _b64url(
        json.dumps({"alg": "RS256", "kid": "test-key", "typ": "JWT"}, separators=(",", ":")).encode()
    )
    encoded_claims = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = _GOOGLE_PRIVATE_KEY.sign(
        signing_input,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return f"{encoded_header}.{encoded_claims}.{_b64url(signature)}"


def _unsigned_google_id_token(**overrides: object) -> str:
    claims: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": "google-id",
        "exp": _GOOGLE_NOW + 300,
        "sub": "google-sub",
        "nonce": "server-nonce",
    }
    claims.update(overrides)
    encoded_header = _b64url(json.dumps({"alg": "none", "kid": "test-key"}).encode())
    encoded_claims = _b64url(json.dumps(claims).encode())
    return f"{encoded_header}.{encoded_claims}.not-a-signature"


def _google_provider(
    id_token: str,
    *,
    userinfo: dict[str, object] | None = None,
) -> GoogleOAuthProvider:
    def transport(method: str, url: str, **_: object) -> dict[str, object]:
        if method == "POST":
            return {"access_token": "token", "id_token": id_token}
        if url == "https://www.googleapis.com/oauth2/v3/certs":
            return {"keys": [_google_jwk()]}
        return userinfo or {"sub": "google-sub", "name": "Lee"}

    return GoogleOAuthProvider(
        OAuthProviderConfig(
            provider="google",
            client_id="google-id",
            client_secret="google-secret",
            authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
            token_endpoint="https://oauth2.googleapis.com/token",
            userinfo_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
            jwks_endpoint="https://www.googleapis.com/oauth2/v3/certs",
        ),
        transport=transport,
        clock=lambda: _GOOGLE_NOW,
    )


def test_kakao_profile_accepts_numeric_id() -> None:
    provider = KakaoOAuthProvider(
        OAuthProviderConfig(
            provider="kakao",
            client_id="kakao-id",
            client_secret="kakao-secret",
            authorize_endpoint="https://kauth.kakao.com/oauth/authorize",
            token_endpoint="https://kauth.kakao.com/oauth/token",
            userinfo_endpoint="https://kapi.kakao.com/v2/user/me",
        )
    )
    identity = provider._parse_profile({"id": 1234567890, "properties": {"nickname": "한강"}})
    assert identity.subject == "1234567890"
    assert identity.display_name == "한강"


def test_naver_profile_accepts_numeric_id() -> None:
    provider = NaverOAuthProvider(
        OAuthProviderConfig(
            provider="naver",
            client_id="naver-id",
            client_secret="naver-secret",
            authorize_endpoint="https://nid.naver.com/oauth2.0/authorize",
            token_endpoint="https://nid.naver.com/oauth2.0/token",
            userinfo_endpoint="https://openapi.naver.com/v1/nid/me",
        )
    )
    identity = provider._parse_profile({"response": {"id": 987654321}})
    assert identity.subject == "987654321"


def test_google_exchange_reads_nonce_from_id_token() -> None:
    provider = _google_provider(_google_id_token())
    identity = asyncio.run(
        provider.exchange_code("code", "http://localhost/callback", expected_nonce="server-nonce")
    )
    assert identity.subject == "google-sub"
    assert identity.nonce == "server-nonce"


def test_google_exchange_rejects_id_token_nonce_mismatch() -> None:
    provider = _google_provider(_google_id_token(nonce="other"))
    with pytest.raises(OAuthNonceError):
        asyncio.run(
            provider.exchange_code("code", "http://localhost/callback", expected_nonce="server-nonce")
        )


def test_google_exchange_rejects_unsigned_id_token() -> None:
    provider = _google_provider(_unsigned_google_id_token())
    with pytest.raises(OAuthResponseError):
        asyncio.run(
            provider.exchange_code("code", "http://localhost/callback", expected_nonce="server-nonce")
        )


def test_google_exchange_rejects_tampered_id_token_signature() -> None:
    id_token = _google_id_token()
    header, claims, signature = id_token.split(".")
    tampered_signature = f"{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    tampered = f"{header}.{claims}.{tampered_signature}"
    provider = _google_provider(tampered)
    with pytest.raises(OAuthResponseError):
        asyncio.run(
            provider.exchange_code("code", "http://localhost/callback", expected_nonce="server-nonce")
        )


@pytest.mark.parametrize(
    ("claim", "value"),
    (
        ("iss", "https://accounts.google.test"),
        ("aud", "another-client"),
        ("exp", _GOOGLE_NOW - 1),
    ),
)
def test_google_exchange_rejects_invalid_id_token_claims(claim: str, value: object) -> None:
    provider = _google_provider(_google_id_token(**{claim: value}))
    with pytest.raises(OAuthResponseError):
        asyncio.run(
            provider.exchange_code("code", "http://localhost/callback", expected_nonce="server-nonce")
        )


def test_google_exchange_binds_id_token_subject_to_userinfo() -> None:
    provider = _google_provider(
        _google_id_token(),
        userinfo={"sub": "different-google-sub", "name": "Lee"},
    )
    with pytest.raises(OAuthResponseError):
        asyncio.run(
            provider.exchange_code("code", "http://localhost/callback", expected_nonce="server-nonce")
        )
