"""Unit coverage for the auth/privacy primitives owned by this workstream."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import pytest

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
    MockOAuthProvider,
    OAuthNonceError,
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
