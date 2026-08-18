from __future__ import annotations

import json
import secrets
from collections.abc import Awaitable
from copy import deepcopy
from datetime import datetime, timedelta
from statistics import fmean
from typing import Any, Literal
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Cookie, Depends, Header, Query, Request, Response
from fastapi.responses import RedirectResponse

from apps.api.app.api.v1.dependencies import (
    Principal,
    get_repository,
    get_state,
    optional_principal,
    require_admin,
    require_analyst,
    require_csrf,
    require_idempotency_key,
    require_if_match,
    require_member,
    require_reviewer,
)
from apps.api.app.api.v1.schemas import (
    ArticlePage,
    ArticleView,
    AutopilotSettingsPut,
    AutopilotSettingsView,
    ConsentSubmission,
    ConsentView,
    DeleteAccountRequest,
    DemographicsPatch,
    EfficacySubmission,
    EfficacyView,
    FeedItem,
    FeedPage,
    IssueDetailView,
    IssuePage,
    JobAccepted,
    MergeIssueRequest,
    ModelCreate,
    Page,
    PatchDocument,
    ProfileView,
    QuestionnaireSubmission,
    QuestionnaireVersionView,
    ReadResult,
    ReadReturn,
    ReadSessionCreate,
    ReadSessionView,
    ReasonRequest,
    RecommendationGenerate,
    RetryCancelResponse,
    RollbackRequest,
    ScoreView,
    ShareCardCreate,
    ShareCardJobAccepted,
    ShareCardView,
    SimulationRequest,
    SourceCreate,
    SplitIssueRequest,
    UserView,
    VisualizationPointPage,
    VoteInput,
    VoteView,
    WeightCreate,
)
from apps.api.app.core.config import Settings, get_settings
from apps.api.app.core.errors import COMMON_ERROR_RESPONSES, ApiError
from apps.api.app.domains.auth.providers import (
    MockOAuthProvider,
    OAuthError,
    OAuthProviderConfig,
    provider_from_config,
)
from apps.api.app.domains.engagement.read import (
    create_redirect_token,
    evaluate_read_eligibility,
    verify_redirect_token,
)
from apps.api.app.repositories.admin import AdminRepositoryError
from apps.api.app.repositories.platform import MariaDBPlatformRepository
from apps.api.app.repositories.product import ProductConflictError, ProductValidationError
from apps.api.app.state import (
    PlatformState,
    decode_cursor,
    encode_cursor,
    new_id,
    stable_hash,
    utcnow,
)

router = APIRouter(prefix="/api/v1", responses=COMMON_ERROR_RESPONSES)


async def _admin_repo[T](awaitable: Awaitable[T]) -> T:
    try:
        return await awaitable
    except AdminRepositoryError as exc:
        code = str(exc.details.get("code", exc.code))
        raise ApiError(
            exc.status_code,
            code,
            exc.message,
            retryable=exc.retryable,
            details=exc.details,
        ) from exc


def _oauth_provider(provider: str, settings: Settings):
    if provider == "mock":
        return MockOAuthProvider()
    return provider_from_config(
        OAuthProviderConfig(
            provider=provider,
            client_id=getattr(settings, f"{provider}_client_id") or "",
            client_secret=getattr(settings, f"{provider}_client_secret") or "",
            timeout_seconds=5.0,
            max_retries=2,
            retry_backoff_seconds=0.2,
            enabled=True,
        )
    )


def _safe_return_to(value: str | None) -> str | None:
    """Validate an OAuth post-login path as a same-origin relative URL.

    OAuth state is the trust boundary for the value, so neither an absolute
    URL nor a protocol-relative/path-backslash variant may be persisted in a
    challenge.  Keeping the query string is intentional for the original
    page's filters and cursor.
    """

    if value is None or value == "":
        return None
    if any(ord(char) < 0x20 for char in value):
        raise ApiError(400, "RETURN_TO_INVALID", "The OAuth return path is invalid.")
    decoded = unquote(value)
    if not value.startswith("/") or value.startswith("//") or value.startswith("\\"):
        raise ApiError(400, "RETURN_TO_INVALID", "The OAuth return path is invalid.")
    if decoded.startswith(("//", "/\\", "\\")):
        raise ApiError(400, "RETURN_TO_INVALID", "The OAuth return path is invalid.")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        raise ApiError(400, "RETURN_TO_INVALID", "The OAuth return path is invalid.")
    return value


def _web_return_target(settings: Settings, return_to: str | None, fallback: str) -> str:
    path = return_to or fallback
    # ``_safe_return_to`` is called before persistence; keep this defensive
    # guard close to the final redirect as well.
    validated = _safe_return_to(path) or fallback
    return settings.web_base_url.rstrip("/") + validated


def _not_found(kind: str) -> ApiError:
    return ApiError(
        404, f"{kind.upper()}_NOT_FOUND", f"{kind.replace('_', ' ').title()} was not found."
    )


def _page(rows: list[dict[str, Any]], cursor: str | None, limit: int = 20) -> dict[str, Any]:
    try:
        start = decode_cursor(cursor)
    except ValueError as exc:
        raise ApiError(
            400, "CURSOR_INVALID", "The cursor is malformed or from another resource."
        ) from exc
    items = rows[start : start + limit]
    next_cursor = encode_cursor(start + limit) if start + limit < len(rows) else None
    return {"items": items, "next_cursor": next_cursor}


def _idempotent(
    state: PlatformState,
    scope: str,
    key: str,
    payload: Any,
    producer: Any,
) -> dict[str, Any]:
    digest = stable_hash(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")))
    prior = state.idempotency.get((scope, key))
    if prior:
        if prior["digest"] != digest:
            raise ApiError(
                409, "IDEMPOTENCY_KEY_REUSED", "This key was already used with another request."
            )
        return deepcopy(prior["response"])
    response = producer()
    state.idempotency[(scope, key)] = {"digest": digest, "response": deepcopy(response)}
    return response


@router.get("/auth/{provider}/start", operation_id="auth_provider_start")
async def auth_start(
    provider: Literal["kakao", "naver", "google", "mock"],
    redirect_uri: str,
    return_to: str | None = Query(default=None, alias="returnTo"),
    settings: Settings = Depends(get_settings),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> RedirectResponse:
    if redirect_uri not in settings.redirect_allowlist:
        raise ApiError(400, "REDIRECT_URI_INVALID", "The redirect URI is not allowlisted.")
    validated_return_to = _safe_return_to(return_to)
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    if (provider == "mock" and settings.app_env == "production") or (
        provider != "mock"
        and not (
            getattr(settings, f"{provider}_client_id")
            and getattr(settings, f"{provider}_client_secret")
        )
    ):
        raise ApiError(400, "AUTH_PROVIDER_DISABLED", "The requested OAuth provider is disabled.")
    try:
        target = _oauth_provider(provider, settings).authorization_url(state, nonce, redirect_uri)
    except (OAuthError, ValueError) as exc:
        raise ApiError(
            400, "AUTH_PROVIDER_DISABLED", "The requested OAuth provider is disabled."
        ) from exc
    challenge = {
        "provider": provider,
        "nonce": nonce,
        "redirect_uri": redirect_uri,
        "return_to": validated_return_to,
        "expires_at": utcnow() + timedelta(minutes=10),
    }
    if repository is not None:
        await repository.create_oauth_challenge(state=state, challenge=challenge)
    else:
        # The memory backend is intentionally deterministic but still needs a
        # one-use atomic transition when two callbacks race in one process.
        with platform.lock:
            now = utcnow()
            expired = [
                key
                for key, value in platform.oauth_challenges.items()
                if value.get("expires_at") and value["expires_at"] <= now
            ]
            for key in expired:
                platform.oauth_challenges.pop(key, None)
            platform.oauth_challenges[state] = challenge
    response = RedirectResponse(target, status_code=302)
    response.set_cookie(
        "oauth_state",
        state,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=600,
    )
    response.set_cookie(
        "oauth_nonce",
        nonce,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=600,
    )
    return response


@router.get(
    "/auth/providers",
    response_model=list[Literal["kakao", "naver", "google", "mock"]],
    operation_id="list_auth_providers",
)
def auth_providers(settings: Settings = Depends(get_settings)) -> list[str]:
    """Return only providers that can complete a server-side OAuth flow."""

    providers: list[str] = []
    if settings.app_env != "production":
        providers.append("mock")
    for provider in ("kakao", "naver", "google"):
        if getattr(settings, f"{provider}_client_id") and getattr(
            settings, f"{provider}_client_secret"
        ):
            providers.append(provider)
    return providers


@router.get("/auth/{provider}/callback", operation_id="auth_provider_callback")
async def auth_callback(
    provider: Literal["kakao", "naver", "google", "mock"],
    state_param: str = Query(alias="state"),
    code: str = "mock-local",
    redirect_uri: str | None = None,
    oauth_state_header: str | None = Header(default=None, alias="X-OAuth-State"),
    oauth_state_cookie: str | None = Cookie(default=None, alias="oauth_state"),
    oauth_nonce_cookie: str | None = Cookie(default=None, alias="oauth_nonce"),
    settings: Settings = Depends(get_settings),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> RedirectResponse:
    # The header exists for deterministic clients; browser adapters normally compare the HttpOnly cookie.
    expected_state = oauth_state_header or oauth_state_cookie
    if not expected_state or not secrets.compare_digest(state_param, expected_state):
        raise ApiError(400, "OAUTH_STATE_INVALID", "OAuth state verification failed.")
    if repository is not None:
        challenge = await repository.consume_oauth_challenge(state_param)
    else:
        with platform.lock:
            challenge = platform.oauth_challenges.pop(state_param, None)
    if (
        not challenge
        or challenge["provider"] != provider
        or challenge["expires_at"] <= utcnow()
        or not oauth_nonce_cookie
        or not secrets.compare_digest(challenge["nonce"], oauth_nonce_cookie)
    ):
        raise ApiError(400, "OAUTH_STATE_INVALID", "OAuth state or nonce verification failed.")
    if redirect_uri and redirect_uri not in settings.redirect_allowlist:
        raise ApiError(400, "REDIRECT_URI_INVALID", "The redirect URI is not allowlisted.")
    if (provider == "mock" and settings.app_env == "production") or (
        provider != "mock"
        and not (
            getattr(settings, f"{provider}_client_id")
            and getattr(settings, f"{provider}_client_secret")
        )
    ):
        raise ApiError(400, "AUTH_PROVIDER_DISABLED", "The requested OAuth provider is disabled.")
    # The challenge is authoritative.  Picking an arbitrary allowlist item
    # makes callbacks depend on set/hash iteration order and breaks providers
    # whose registered URI is not the first item.
    callback_uri = challenge["redirect_uri"]
    if redirect_uri is not None and redirect_uri != callback_uri:
        raise ApiError(400, "REDIRECT_URI_INVALID", "OAuth callback redirect URI changed.")
    try:
        identity = await _oauth_provider(provider, settings).exchange_code(
            code,
            callback_uri,
            # The callback cookie is mandatory for every provider.  The mock
            # adapter (and OIDC adapters that expose an ID-token nonce) can
            # additionally validate the provider claim; Kakao/Naver currently
            # use the documented state+browser-nonce binding instead.
            expected_nonce=challenge["nonce"] if provider in {"mock", "google"} else None,
        )
    except OAuthError as exc:
        raise ApiError(
            400, "OAUTH_CALLBACK_INVALID", "OAuth code or nonce verification failed."
        ) from exc
    if repository is not None:
        user = await repository.create_or_get_oauth_user(
            provider=identity.provider,
            subject=identity.subject,
            display_name=identity.display_name,
        )
        token, csrf = await repository.rotate_session(user["id"])
        complete_user = await repository.get_user(user["id"])
        onboarding_complete = bool(complete_user and complete_user["onboarding_complete"])
    else:
        account_key = (identity.provider, identity.subject)
        user_id = platform.oauth_accounts.get(account_key)
        if not user_id:
            user_id = platform.default_users["MEMBER"] if provider == "mock" else new_id()
            if user_id not in platform.users:
                platform.users[user_id] = {
                    "id": user_id,
                    "display_name": identity.display_name or "Member",
                    "role": "MEMBER",
                    "status": "ACTIVE",
                    "consent_complete": False,
                    "onboarding_complete": False,
                    "behavioral_profile_active": False,
                    "created_at": utcnow(),
                }
            platform.oauth_accounts[account_key] = user_id
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        platform.sessions[stable_hash(token)] = {
            "user_id": user_id,
            "csrf_hash": stable_hash(csrf),
            "expires_at": utcnow() + timedelta(hours=12),
            "revoked_at": None,
            "provider": provider,
            "nonce_verified": oauth_nonce_cookie is not None,
        }
        onboarding_complete = bool(platform.users[user_id]["onboarding_complete"])
    target = _web_return_target(
        settings,
        challenge.get("return_to"),
        "/" if onboarding_complete else "/onboarding/consent",
    )
    response = RedirectResponse(target, status_code=302)
    response.set_cookie(
        "session",
        token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=43_200,
    )
    response.set_cookie(
        "csrf",
        csrf,
        httponly=False,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=43_200,
    )
    response.delete_cookie("oauth_state")
    response.delete_cookie("oauth_nonce")
    return response


@router.post(
    "/auth/logout",
    status_code=204,
    dependencies=[Depends(require_csrf)],
    operation_id="auth_logout",
)
async def logout(
    response: Response,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    session_header: str | None = Header(default=None, alias="X-Session-Token"),
    session_cookie: str | None = Cookie(default=None, alias="session"),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> None:
    session = session_header or session_cookie
    if repository is not None and session:
        await repository.revoke_session(session)
    elif session and (record := platform.sessions.get(stable_hash(session))):
        if record["user_id"] == principal.user_id:
            record["revoked_at"] = utcnow()
    response.delete_cookie("session")
    response.delete_cookie("csrf")


@router.get("/me", response_model=UserView, operation_id="get_me")
async def get_me(
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        user = await repository.get_user(principal.user_id)
        if user is None:
            raise _not_found("user")
        return user
    user = platform.users[principal.user_id]
    return {
        key: user[key]
        for key in (
            "id",
            "display_name",
            "role",
            "consent_complete",
            "onboarding_complete",
            "behavioral_profile_active",
        )
    }


@router.get("/consents", response_model=list[ConsentView], operation_id="list_consents")
async def list_consents(
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> list[dict[str, Any]]:
    if repository is not None:
        return await repository.list_consents(principal.user_id)
    return [
        {**consent, "granted": platform.consent_grants.get((principal.user_id, consent_id), False)}
        for consent_id, consent in platform.consents.items()
    ]


@router.post(
    "/me/consents",
    response_model=ConsentView,
    dependencies=[Depends(require_csrf)],
    operation_id="submit_consent",
)
async def submit_consent(
    body: ConsentSubmission,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        consent = await repository.set_consent(
            principal.user_id, body.consent_version_id, body.granted
        )
        if consent is None:
            raise ApiError(
                409, "CONSENT_VERSION_STALE", "The consent version is no longer available."
            )
        return consent
    consent = platform.consents.get(body.consent_version_id)
    if not consent:
        raise ApiError(409, "CONSENT_VERSION_STALE", "The consent version is no longer available.")
    platform.consent_grants[(principal.user_id, body.consent_version_id)] = body.granted
    user = platform.users[principal.user_id]
    user["consent_complete"] = all(
        platform.consent_grants.get((principal.user_id, cid), False) for cid in platform.consents
    )
    if consent["sensitive"] and not body.granted:
        user["behavioral_profile_active"] = False
        for profile in platform.profiles.values():
            if profile["user_id"] == principal.user_id and profile["kind"] == "BEHAVIORAL":
                profile["active"] = False
    return {**consent, "granted": body.granted}


@router.get(
    "/questionnaires",
    response_model=list[QuestionnaireVersionView],
    operation_id="list_questionnaire_versions",
)
async def list_questionnaire_versions(
    kind: Literal["onboarding", "political", "efficacy"] | None = None,
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> list[dict[str, Any]]:
    """Expose the active questionnaire contract before a response is posted."""

    normalized_kind = "onboarding" if kind == "political" else kind
    if repository is not None:
        return await repository.list_questionnaire_versions(normalized_kind)
    rows: list[dict[str, Any]] = []
    for item in platform.questionnaires.values():
        item_kind = str(item.get("kind", "onboarding")).lower()
        if item_kind in {"political_onboarding", "political"}:
            item_kind = "onboarding"
        if normalized_kind and item_kind != normalized_kind:
            continue
        rows.append(
            {
                "id": item["id"],
                "kind": item_kind,
                "version": item.get("version", "1.0"),
                "schema_json": item.get(
                    "schema_json",
                    {"questions": [{"id": key, "required": True} for key in item.get("keys", [])]},
                ),
                "scoring_json": item.get("scoring_json", {}),
                "active_from": item.get("active_from", utcnow()),
                "keys": list(item.get("keys", [])),
            }
        )
    return rows


@router.post(
    "/me/questionnaire-responses",
    response_model=ProfileView,
    dependencies=[Depends(require_csrf)],
    operation_id="submit_questionnaire_response",
)
async def submit_questionnaire(
    body: QuestionnaireSubmission,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        try:
            profile = await repository.submit_questionnaire(
                principal.user_id, body.questionnaire_version_id, body.answers
            )
        except PermissionError as exc:
            raise ApiError(
                403, "CONSENT_REQUIRED", "Separate political-data consent is required."
            ) from exc
        except ValueError as exc:
            raise ApiError(
                400,
                "QUESTIONNAIRE_ANSWER_INVALID",
                "Required numeric answers are missing or invalid.",
            ) from exc
        if profile is None:
            raise ApiError(
                409, "QUESTIONNAIRE_VERSION_STALE", "The questionnaire version is stale."
            )
        return profile
    version = platform.questionnaires.get(body.questionnaire_version_id)
    if not version:
        raise ApiError(409, "QUESTIONNAIRE_VERSION_STALE", "The questionnaire version is stale.")
    if not platform.users[principal.user_id]["consent_complete"]:
        raise ApiError(403, "CONSENT_REQUIRED", "Separate political-data consent is required.")
    values = []
    for key in version["keys"]:
        try:
            values.append(max(-100, min(100, int(body.answers[key]))))
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError(
                400, "QUESTIONNAIRE_ANSWER_INVALID", f"A numeric {key} answer is required."
            ) from exc
    for profile in platform.profiles.values():
        if profile["user_id"] == principal.user_id and profile["kind"] == "SELF_REPORTED":
            profile["active"] = False
    profile_id = new_id()
    profile = {
        "profile_id": profile_id,
        "id": profile_id,
        "user_id": principal.user_id,
        "kind": "SELF_REPORTED",
        "x": values[0],
        "y": values[1],
        "z": values[2],
        "sensationalism": None,
        "confidence": min(1.0, 0.5 + len(body.answers) * 0.05),
        "source_version": version["version"],
        "active": True,
        "created_at": utcnow(),
    }
    platform.profiles[profile_id] = profile
    platform.users[principal.user_id]["onboarding_complete"] = True
    return {
        key: profile[key]
        for key in (
            "profile_id",
            "kind",
            "x",
            "y",
            "z",
            "sensationalism",
            "confidence",
            "source_version",
            "active",
        )
    }


@router.patch(
    "/me/demographics", dependencies=[Depends(require_csrf)], operation_id="patch_demographics"
)
async def patch_demographics(
    body: DemographicsPatch,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await repository.patch_demographics(
            principal.user_id,
            age_band=body.age_band,
            gender_response=body.gender_response,
        )
    platform.demographics[principal.user_id] = {**body.model_dump(), "updated_at": utcnow()}
    return platform.demographics[principal.user_id]


@router.post(
    "/me/export",
    response_model=JobAccepted,
    status_code=202,
    dependencies=[Depends(require_csrf)],
    operation_id="export_me",
)
async def export_me(
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        job = await repository.request_export(principal.user_id)
        return {"job_id": job["id"], "status": job["status"]}
    job = platform.enqueue("export_user", principal.user_id, {"user_id": principal.user_id})
    return {"job_id": job["id"], "status": "PENDING"}


@router.delete(
    "/me",
    response_model=JobAccepted,
    status_code=202,
    dependencies=[Depends(require_csrf)],
    operation_id="delete_me",
)
async def delete_me(
    body: DeleteAccountRequest,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        job = await repository.request_deletion(principal.user_id)
        return {"job_id": job["id"], "status": job["status"]}
    platform.users[principal.user_id]["status"] = "PENDING_DELETION"
    for record in platform.sessions.values():
        if record["user_id"] == principal.user_id:
            record["revoked_at"] = utcnow()
    for card in platform.share_cards.values():
        if card["user_id"] == principal.user_id:
            card["status"], card["revoked_at"] = "revoked", utcnow()
    job = platform.enqueue(
        "delete_user",
        principal.user_id,
        {"user_id": principal.user_id, "confirmed": True, "legal_hold_checked": True},
    )
    return {"job_id": job["id"], "status": "PENDING"}


@router.get("/feed", response_model=FeedPage, operation_id="get_feed")
async def feed(
    mode: Literal["balanced", "personalized"] = "balanced",
    cursor: str | None = None,
    principal: Principal | None = Depends(optional_principal),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        repository_rows, personalized = await repository.feed_items(
            user_id=None if principal is None else principal.user_id,
            personalized_requested=mode == "personalized",
        )
        page = _page(repository_rows, cursor)
        page["personalized"] = personalized
        return page
    profile = None
    if principal:
        profile = next(
            (
                p
                for p in platform.profiles.values()
                if p["user_id"] == principal.user_id and p["active"]
            ),
            None,
        )
    personalized = bool(mode == "personalized" and profile)
    rows: list[dict[str, Any]] = []
    last_source = None
    seen_article_ids: set[str] = set()
    issue_counts: dict[str | None, int] = {}
    articles = sorted(platform.articles.values(), key=lambda row: row["published_at"], reverse=True)
    if personalized and profile:
        profile_sensationalism = float(profile.get("sensationalism") or 0)

        def profile_distance(article: dict[str, Any]) -> float:
            score = (platform.scores.get(article["id"]) or [{"x": 0}])[-1]
            score_sensationalism = float(score.get("sensationalism") or 0)
            return (
                ((float(score["x"]) - float(profile["x"])) / 200.0) ** 2
                + ((score_sensationalism - profile_sensationalism) / 100.0) ** 2
            ) ** 0.5

        articles.sort(key=profile_distance)
    for article in articles:
        issue = platform.issues.get(article.get("issue_id"))
        if issue and str(issue.get("status", "")).upper() in {"MERGED", "CLOSED", "ARCHIVED"}:
            continue
        if article["id"] in seen_article_ids:
            continue
        seen_article_ids.add(article["id"])
        issue_id = article.get("issue_id") or "unclustered"
        if issue_counts.get(issue_id, 0) >= 1:
            continue
        if article["source_id"] == last_source:
            continue
        history = platform.scores.get(article["id"])
        if not history:
            continue
        score = history[-1]
        rows.append(
            FeedItem(
                article_id=article["id"],
                issue_id=issue_id,
                title=article["title"],
                source=article["source"],
                coordinate={
                    **{key: score[key] for key in ("x", "y", "z", "sensationalism", "confidence")}
                },
                reason_code="ADJACENT_PERSPECTIVE" if personalized else "BALANCED_FALLBACK",
                rank=len(rows) + 1,
            ).model_dump()
        )
        last_source = article["source_id"]
        issue_counts[issue_id] = issue_counts.get(issue_id, 0) + 1
    page = _page(rows, cursor)
    page["personalized"] = personalized
    return page


@router.get("/issues", response_model=IssuePage, operation_id="list_issues")
async def list_issues(
    topic: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    sort: Literal["recent", "oldest"] = "recent",
    cursor: str | None = None,
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        rows = await repository.list_issue_rows(
            topic=topic,
            from_time=from_,
            to_time=to,
            recent_first=sort == "recent",
        )
        return _page(rows, cursor)
    rows = list(platform.issues.values())
    if topic:
        rows = [
            row for row in rows if topic.casefold() in (row["title"] + row["summary"]).casefold()
        ]
    if from_:
        rows = [row for row in rows if row["last_activity_at"] >= from_]
    if to:
        rows = [row for row in rows if row["last_activity_at"] <= to]
    rows.sort(key=lambda row: row["last_activity_at"], reverse=sort == "recent")
    return _page(rows, cursor)


@router.get("/issues/{issue_id}", response_model=IssueDetailView, operation_id="get_issue")
async def get_issue(
    issue_id: str,
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        issue = await repository.issue_view(issue_id)
        if issue is None:
            raise _not_found("issue")
        return issue
    issue = platform.issues.get(issue_id)
    if not issue:
        raise _not_found("issue")
    axes = [platform.scores[aid][-1]["x"] for aid in issue["article_ids"] if aid in platform.scores]
    return {
        **issue,
        "distribution": {
            "minimum_x": min(axes) if axes else None,
            "maximum_x": max(axes) if axes else None,
            "count": len(axes),
        },
    }


@router.get(
    "/issues/{issue_id}/articles",
    response_model=ArticlePage,
    operation_id="list_issue_articles",
)
async def list_issue_articles(
    issue_id: str,
    perspective: Literal["all", "negative_x", "center", "positive_x"] = "all",
    cursor: str | None = None,
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        rows = await repository.issue_article_rows(issue_id, perspective=perspective)
        if rows is None:
            raise _not_found("issue")
        return _page(rows, cursor)
    issue = platform.issues.get(issue_id)
    if not issue:
        raise _not_found("issue")
    rows = []
    for article_id in issue["article_ids"]:
        article, score = platform.articles[article_id], platform.scores[article_id][-1]
        if perspective == "negative_x" and score["x"] >= -10:
            continue
        if perspective == "center" and abs(score["x"]) > 10:
            continue
        if perspective == "positive_x" and score["x"] <= 10:
            continue
        rows.append(
            {
                **article,
                "coordinate": {
                    key: score[key] for key in ("x", "y", "z", "sensationalism", "confidence")
                },
            }
        )
    return _page(rows, cursor)


@router.get("/articles/{article_id}", response_model=ArticleView, operation_id="get_article")
async def get_article(
    article_id: str,
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        article = await repository.article_view(article_id)
        if article is None:
            raise _not_found("article")
        return article
    article = platform.articles.get(article_id)
    if not article:
        raise _not_found("article")
    return article


@router.get("/articles/{article_id}/assessments", operation_id="list_article_assessments")
async def article_assessments(
    article_id: str,
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        assessments = await repository.assessment_view(article_id)
        if assessments is None:
            raise _not_found("article")
        return assessments
    if article_id not in platform.articles:
        raise _not_found("article")
    return {
        "article_version_id": platform.articles[article_id]["current_version_id"],
        "assessments": platform.assessments.get(article_id, []),
    }


@router.get(
    "/articles/{article_id}/score",
    response_model=ScoreView,
    operation_id="get_article_score",
)
async def article_score(
    article_id: str,
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        score = await repository.current_score(article_id)
        if score is None:
            raise _not_found("score")
        return score
    if article_id not in platform.scores:
        raise _not_found("score")
    return platform.scores[article_id][-1]


@router.get(
    "/articles/{article_id}/score-history",
    response_model=Page,
    operation_id="article_score_history",
)
async def article_score_history(
    article_id: str,
    cursor: str | None = None,
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        rows = await repository.score_history(article_id)
        if rows is None:
            raise _not_found("article")
        return _page(rows, cursor)
    if article_id not in platform.articles:
        raise _not_found("article")
    return _page(list(reversed(platform.scores.get(article_id, []))), cursor)


@router.get("/compare", operation_id="compare_articles")
async def compare_articles(
    article_ids: list[str] = Query(min_length=2, max_length=4),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if len(set(article_ids)) != len(article_ids):
        raise ApiError(400, "COMPARE_DUPLICATE_ARTICLE", "Comparison articles must be unique.")
    rows = []
    if repository is not None:
        for article_id in article_ids:
            article = await repository.article_view(article_id)
            score = await repository.current_score(article_id)
            if article is None or score is None:
                raise _not_found("article")
            rows.append({"article": article, "score": score})
        return {"rows": rows, "normalized_columns": ["x", "y", "z", "sensationalism", "confidence"]}
    for article_id in article_ids:
        if article_id not in platform.articles:
            raise _not_found("article")
        rows.append(
            {"article": platform.articles[article_id], "score": platform.scores[article_id][-1]}
        )
    return {"rows": rows, "normalized_columns": ["x", "y", "z", "sensationalism", "confidence"]}


@router.get("/sources/{source_id}", operation_id="get_source")
async def get_source(
    source_id: str,
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        source = await repository.source_summary(source_id)
        if source is None:
            raise _not_found("source")
        return source
    source = platform.sources.get(source_id)
    if not source:
        raise _not_found("source")
    values = [
        platform.scores[a["id"]][-1]["x"]
        for a in platform.articles.values()
        if a["source_id"] == source_id
    ]
    return {
        **source,
        "period_days": 90,
        "article_count": len(values),
        "distribution": values,
        "confidence": min(1.0, len(values) / 20),
    }


@router.post(
    "/articles/{article_id}/read-sessions",
    response_model=ReadSessionView,
    dependencies=[Depends(require_csrf)],
    operation_id="create_read_session",
)
async def create_read_session(
    article_id: str,
    body: ReadSessionCreate,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    settings: Settings = Depends(get_settings),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        session_id = new_id()
        expires_at = utcnow() + timedelta(minutes=30)
        signed_token = create_redirect_token(
            session_id=session_id,
            user_id=principal.user_id,
            article_id=article_id,
            secret=settings.session_secret,
            expires_at=expires_at,
        )
        try:
            created = await repository.create_read_session_row(
                session_id=session_id,
                user_id=principal.user_id,
                article_id=article_id,
                token=signed_token,
                expires_at=expires_at,
            )
        except ProductConflictError as exc:
            raise ApiError(409, "READ_SESSION_OVERLAP", "Another read session is active.") from exc
        if not created:
            raise _not_found("article")
        return {
            "read_session_id": session_id,
            "redirect_url": f"{settings.public_base_url}/api/v1/r/{signed_token}",
            "expires_at": expires_at,
        }
    article = platform.articles.get(article_id)
    if not article:
        raise _not_found("article")
    active = next(
        (
            session
            for session in platform.read_sessions.values()
            if session["user_id"] == principal.user_id
            and session["status"] in {"CREATED", "OUTBOUND"}
        ),
        None,
    )
    if active:
        raise ApiError(409, "READ_SESSION_OVERLAP", "Another read session is active.")
    session_id = new_id()
    expires_at = utcnow() + timedelta(minutes=30)
    signed_token = create_redirect_token(
        session_id=session_id,
        user_id=principal.user_id,
        article_id=article_id,
        secret=settings.session_secret,
        expires_at=expires_at,
    )
    platform.read_sessions[session_id] = {
        "id": session_id,
        "user_id": principal.user_id,
        "article_id": article_id,
        "token_hash": stable_hash(signed_token),
        "status": "CREATED",
        "outbound_at": None,
        "returned_at": None,
        "expires_at": expires_at,
        "return_path": body.return_path,
        "policy_version": "read-v1",
    }
    return {
        "read_session_id": session_id,
        "redirect_url": f"{settings.public_base_url}/api/v1/r/{signed_token}",
        "expires_at": expires_at,
    }


@router.get("/r/{token}", operation_id="redirect_to_article")
async def redirect_to_article(
    token: str,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    settings: Settings = Depends(get_settings),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> RedirectResponse:
    try:
        claims = verify_redirect_token(token, secret=settings.session_secret)
    except ValueError as exc:
        raise ApiError(404, "READ_TOKEN_INVALID", "The read redirect token is invalid.") from exc
    if repository is not None:
        try:
            target = await repository.use_read_redirect(
                session_id=claims["sid"],
                user_id=principal.user_id,
                article_id=claims["aid"],
                token=token,
            )
        except KeyError as exc:
            raise ApiError(
                404, "READ_TOKEN_INVALID", "The read redirect token is invalid."
            ) from exc
        except ProductConflictError as exc:
            if str(exc) == "READ_SESSION_EXPIRED":
                raise ApiError(410, "READ_SESSION_EXPIRED", "The read session expired.") from exc
            raise ApiError(
                409, "READ_REDIRECT_REPLAY", "The read redirect was already used."
            ) from exc
        return RedirectResponse(target, status_code=302)
    session = platform.read_sessions.get(claims["sid"])
    if (
        not session
        or session["token_hash"] != stable_hash(token)
        or session["user_id"] != principal.user_id
        or claims["uid"] != principal.user_id
        or claims["aid"] != session["article_id"]
    ):
        raise ApiError(404, "READ_TOKEN_INVALID", "The read redirect token is invalid.")
    if session["expires_at"] <= utcnow():
        session["status"] = "EXPIRED"
        raise ApiError(410, "READ_SESSION_EXPIRED", "The read session expired.")
    if session["status"] != "CREATED":
        raise ApiError(409, "READ_REDIRECT_REPLAY", "The read redirect was already used.")
    session["status"], session["outbound_at"] = "OUTBOUND", utcnow()
    return RedirectResponse(
        platform.articles[session["article_id"]]["canonical_url"], status_code=302
    )


@router.post(
    "/read-sessions/{read_session_id}/return",
    response_model=ReadResult,
    dependencies=[Depends(require_csrf)],
    operation_id="return_read_session",
)
async def return_read_session(
    read_session_id: str,
    body: ReadReturn,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        repository_result = await repository.return_read_session_row(
            session_id=read_session_id,
            user_id=principal.user_id,
            client_elapsed_ms=body.client_elapsed_ms,
        )
        if repository_result is None:
            raise _not_found("read_session")
        return repository_result
    session = platform.read_sessions.get(read_session_id)
    if not session or session["user_id"] != principal.user_id:
        raise _not_found("read_session")
    now = utcnow()
    if session["status"] == "RETURNED":
        return {
            "status": "rejected",
            "reason_code": "REPEAT_RETURN",
            "server_elapsed_ms": 0,
            "credit_delta": 0,
        }
    if session["expires_at"] <= now:
        session["status"] = "EXPIRED"
        return {
            "status": "expired",
            "reason_code": "SESSION_EXPIRED",
            "server_elapsed_ms": 0,
            "credit_delta": 0,
        }
    if session["status"] != "OUTBOUND" or session["outbound_at"] is None:
        return {
            "status": "rejected",
            "reason_code": "OUTBOUND_NOT_RECORDED",
            "server_elapsed_ms": 0,
            "credit_delta": 0,
        }
    result = evaluate_read_eligibility(
        outbound_at=session["outbound_at"],
        returned_at=now,
        client_elapsed_ms=body.client_elapsed_ms,
        expires_at=session["expires_at"],
        min_elapsed_ms=15_000,
        max_elapsed_ms=30 * 60_000,
    )
    elapsed = result.server_elapsed_ms
    session["status"], session["returned_at"] = "RETURNED", now
    eligible = result.eligible
    reason = result.reason_code
    delta = 10 if eligible else 0
    event_key = f"read:{read_session_id}"
    ledger = platform.credits.setdefault(principal.user_id, [])
    if delta and not any(entry["event_key"] == event_key for entry in ledger):
        ledger.append(
            {
                "id": new_id(),
                "event_type": "QUALIFIED_READ",
                "event_key": event_key,
                "delta": delta,
                "policy_version": "credit-v1",
                "status": "POSTED",
                "created_at": now,
            }
        )
    return {
        "status": "eligible" if eligible else "rejected",
        "reason_code": reason,
        "server_elapsed_ms": elapsed,
        "credit_delta": delta,
    }


@router.get("/articles/{article_id}/votes/aggregate", operation_id="get_vote_aggregate")
async def vote_aggregate(
    article_id: str,
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        result = await repository.vote_aggregate(article_id)
        if result is None:
            raise _not_found("article")
        return result
    if article_id not in platform.articles:
        raise _not_found("article")
    active = [
        history[-1]
        for (uid, aid), history in platform.votes.items()
        if aid == article_id and history[-1]["active"]
    ]
    qualified = [vote for vote in active if vote["quality_status"] == "QUALIFIED"]

    def aggregate(rows: list[dict[str, Any]], key: str) -> float | None:
        return round(fmean(row[key] for row in rows), 4) if rows else None

    return {
        "raw": {key: aggregate(active, key) for key in ("x", "y", "z", "sensationalism")},
        "qualified": {key: aggregate(qualified, key) for key in ("x", "y", "z", "sensationalism")},
        "raw_count": len(active),
        "qualified_count": len(qualified),
        "segments": {} if len(qualified) < 5 else {"all": {"count": len(qualified)}},
        "small_segments_suppressed": len(qualified) < 5,
    }


@router.get(
    "/articles/{article_id}/vote",
    response_model=VoteView,
    operation_id="get_vote",
)
async def get_vote(
    article_id: str,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        try:
            result = await repository.get_vote_row(
                user_id=principal.user_id, article_id=article_id
            )
        except KeyError:
            raise _not_found("article") from None
        if result is None:
            raise _not_found("vote")
        return result
    if article_id not in platform.articles:
        raise _not_found("article")
    history = platform.votes.get((principal.user_id, article_id))
    if not history or not history[-1]["active"]:
        raise _not_found("vote")
    vote = history[-1]
    return {
        key: vote[key]
        for key in ("x", "y", "z", "sensationalism", "revision", "quality_status", "active")
    }


@router.put(
    "/articles/{article_id}/vote",
    response_model=VoteView,
    dependencies=[Depends(require_csrf)],
    operation_id="put_vote",
)
async def put_vote(
    article_id: str,
    body: VoteInput,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    user = (
        await repository.get_user(principal.user_id)
        if repository is not None
        else platform.users.get(principal.user_id)
    )
    if not user or not user["consent_complete"]:
        raise ApiError(403, "CONSENT_REQUIRED", "Separate political-data consent is required.")
    if repository is not None:
        result = await repository.put_vote_row(
            user_id=principal.user_id,
            article_id=article_id,
            values=body.model_dump(),
        )
        if result is None:
            raise _not_found("article")
        return result
    if article_id not in platform.articles:
        raise _not_found("article")
    with platform.lock:
        history = platform.votes.setdefault((principal.user_id, article_id), [])
        if history:
            history[-1]["active"] = False
        latest_revision = max(
            (
                vote["revision"]
                for (vote_user_id, vote_article_id), user_history in platform.votes.items()
                if vote_article_id == article_id
                for vote in user_history
            ),
            default=0,
        )
        revision = latest_revision + 1
        vote = {
            **body.model_dump(),
            "id": new_id(),
            "revision": revision,
            "quality_status": "QUALIFIED",
            "active": True,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        history.append(vote)
        platform.enqueue(
            "aggregate_votes",
            f"{article_id}:{revision}",
            {"article_id": article_id, "version": revision},
        )
    return {
        key: vote[key]
        for key in ("x", "y", "z", "sensationalism", "revision", "quality_status", "active")
    }


@router.delete(
    "/articles/{article_id}/vote",
    status_code=204,
    dependencies=[Depends(require_csrf)],
    operation_id="delete_vote",
)
async def delete_vote(
    article_id: str,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> None:
    if repository is not None:
        if not await repository.delete_vote_row(user_id=principal.user_id, article_id=article_id):
            raise _not_found("vote")
        return
    with platform.lock:
        history = platform.votes.get((principal.user_id, article_id))
        if not history or not history[-1]["active"]:
            raise _not_found("vote")
        latest_revision = max(
            (
                vote["revision"]
                for (vote_user_id, vote_article_id), user_history in platform.votes.items()
                if vote_article_id == article_id
                for vote in user_history
            ),
            default=0,
        )
        revision = latest_revision + 1
        history[-1]["revision"] = revision
        history[-1]["active"] = False
        platform.enqueue(
            "aggregate_votes",
            f"{article_id}:{revision}",
            {"article_id": article_id, "version": revision},
        )


@router.get("/me/credits", response_model=Page, operation_id="get_credits")
async def credits(
    cursor: str | None = None,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return _page(await repository.credit_rows(principal.user_id), cursor)
    return _page(list(reversed(platform.credits.get(principal.user_id, []))), cursor)


@router.get("/me/progress", operation_id="get_progress")
async def progress(
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await repository.progress_view(principal.user_id)
    total = sum(entry["delta"] for entry in platform.credits.get(principal.user_id, []))
    level = max(1, total // 100 + 1)
    tier = "Explorer" if level < 3 else "Bridge Builder" if level < 6 else "Navigator"
    return {"credit_total": total, "level": level, "tier": tier, "policy_version": "tier-v1"}


@router.get("/me/efficacy", operation_id="get_efficacy")
async def get_efficacy(
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await repository.efficacy_view(principal.user_id)
    rows = platform.efficacy.get(principal.user_id, [])
    baseline = rows[0]["normalized_score"] if rows else None
    return {
        "baseline": baseline,
        "responses": rows,
        "due_survey": not rows or (utcnow() - rows[-1]["submitted_at"]).days >= 30,
    }


@router.post(
    "/me/efficacy-responses",
    response_model=EfficacyView,
    dependencies=[Depends(require_csrf)],
    operation_id="submit_efficacy_response",
)
async def submit_efficacy(
    body: EfficacySubmission,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        try:
            result = await repository.submit_efficacy_row(
                user_id=principal.user_id,
                questionnaire_version_id=body.questionnaire_version_id,
                answers=body.answers,
            )
        except ProductValidationError as exc:
            raise ApiError(
                400, "EFFICACY_ANSWERS_INVALID", "At least one numeric answer is required."
            ) from exc
        if result is None:
            raise ApiError(
                409, "QUESTIONNAIRE_VERSION_STALE", "The questionnaire version is stale."
            )
        return result
    numeric = [float(value) for value in body.answers.values() if isinstance(value, (int, float))]
    if not numeric:
        raise ApiError(400, "EFFICACY_ANSWERS_INVALID", "At least one numeric answer is required.")
    normalized = round(max(0.0, min(100.0, fmean(numeric))), 4)
    rows = platform.efficacy.setdefault(principal.user_id, [])
    delta = None if not rows else round(normalized - rows[0]["normalized_score"], 4)
    row = {
        "id": new_id(),
        "questionnaire_version_id": body.questionnaire_version_id,
        "normalized_score": normalized,
        "baseline_delta": delta,
        "submitted_at": utcnow(),
    }
    rows.append(row)
    return {"normalized_score": normalized, "baseline_delta": delta, "due_survey": False}


@router.get(
    "/visualization/points",
    response_model=VisualizationPointPage,
    operation_id="visualization_points",
)
async def visualization_points(
    type: Literal["article", "source", "user"] = "article",
    issue_id: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    cursor: str | None = None,
    principal: Principal | None = Depends(optional_principal),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        repository_rows = await repository.visualization_rows(
            entity_type=type,
            issue_id=issue_id,
            user_id=None if principal is None else principal.user_id,
        )
        if from_:
            repository_rows = [
                row for row in repository_rows if row.get("created_at", from_) >= from_
            ]
        if to:
            repository_rows = [row for row in repository_rows if row.get("created_at", to) <= to]
        return _page(repository_rows, cursor)
    rows: list[dict[str, Any]] = []
    if type == "article":
        for article in platform.articles.values():
            if issue_id and article["issue_id"] != issue_id:
                continue
            history = platform.scores.get(article["id"])
            if not history:
                continue
            score = history[-1]
            if from_ and score["created_at"] < from_ or to and score["created_at"] > to:
                continue
            rows.append(
                {
                    "entity_type": "article",
                    "entity_id": article["id"],
                    "label": article["title"],
                    **{key: score[key] for key in ("x", "y", "z", "sensationalism", "confidence")},
                }
            )
    elif type == "source":
        for source in platform.sources.values():
            scores = [
                platform.scores[a["id"]][-1]
                for a in platform.articles.values()
                if a["source_id"] == source["id"] and platform.scores.get(a["id"])
            ]
            if scores:
                rows.append(
                    {
                        "entity_type": "source",
                        "entity_id": source["id"],
                        "label": source["name"],
                        **{
                            axis: round(fmean(score.get(axis, 0) for score in scores), 2)
                            for axis in ("x", "y", "z", "sensationalism")
                        },
                        "confidence": min(1.0, len(scores) / 20),
                    }
                )
    elif principal:
        rows = [
            {
                "entity_type": "user",
                "entity_id": principal.user_id,
                "label": "Your response-based coordinate",
                **{
                    key: value
                    for key, value in profile.items()
                    if key in {"x", "y", "z", "sensationalism", "confidence"}
                },
            }
            for profile in platform.profiles.values()
            if profile["user_id"] == principal.user_id and profile["active"]
        ]
    return _page(rows, cursor)


@router.get("/visualization/timeline", operation_id="visualization_timeline")
async def visualization_timeline(
    entity_type: Literal["article", "source", "user"],
    entity_id: str,
    principal: Principal | None = Depends(optional_principal),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        if entity_type == "user" and (not principal or principal.user_id != entity_id):
            raise ApiError(403, "OWNER_REQUIRED", "User-coordinate history is private.")
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "snapshots": await repository.visualization_timeline_rows(
                entity_type=entity_type, entity_id=entity_id
            ),
        }
    if entity_type == "article":
        rows = platform.scores.get(entity_id, [])
    elif entity_type == "user":
        if not principal or principal.user_id != entity_id:
            raise ApiError(403, "OWNER_REQUIRED", "User-coordinate history is private.")
        rows = [
            profile for profile in platform.profiles.values() if profile["user_id"] == entity_id
        ]
    else:
        rows = [
            platform.scores[a["id"]][-1]
            for a in platform.articles.values()
            if a["source_id"] == entity_id
        ]
    return {"entity_type": entity_type, "entity_id": entity_id, "snapshots": rows}


@router.post(
    "/share-cards",
    response_model=ShareCardJobAccepted,
    status_code=202,
    dependencies=[Depends(require_csrf)],
    operation_id="create_share_card",
)
async def create_share_card(
    body: ShareCardCreate,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        try:
            job, _card = await repository.create_share_card_row(
                user_id=principal.user_id,
                template=body.template,
                display_name=body.display_name,
                publication_confirmed=body.political_data_publication_confirmed,
            )
        except ProductConflictError as exc:
            raise ApiError(
                409, "PROFILE_REQUIRED", "An active profile is required for sharing."
            ) from exc
        return {
            "job_id": job["id"],
            "status": job["status"],
            "share_card_id": _card["id"],
        }
    card = platform.create_share_card(
        principal.user_id,
        body.template,
        body.display_name,
        publication_confirmed=body.political_data_publication_confirmed,
    )
    job = next(
        job
        for job in platform.jobs.values()
        if job["job_type"] == "render_share_card" and job["dedupe_key"] == card["id"]
    )
    return {"job_id": job["id"], "status": "PENDING", "share_card_id": card["id"]}


@router.get(
    "/share-cards/{share_card_id}", response_model=ShareCardView, operation_id="get_share_card"
)
async def get_share_card(
    share_card_id: str,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        card = await repository.owner_share_card(card_id=share_card_id, user_id=principal.user_id)
        if card is None:
            raise _not_found("share_card")
        return card
    card = platform.share_cards.get(share_card_id)
    if not card or card["user_id"] != principal.user_id:
        raise _not_found("share_card")
    return {key: card[key] for key in ("id", "status", "public_token", "etag", "snapshot")}


def _public_card(public_token: str, platform: PlatformState) -> dict[str, Any]:
    card_id = platform.public_cards.get(stable_hash(public_token))
    card = platform.share_cards.get(card_id or "")
    if not card or card["status"] == "revoked" or card["expires_at"] <= utcnow():
        raise _not_found("public_share")
    return card


@router.get("/public/share/{public_token}", operation_id="get_public_share")
async def get_public_share(
    public_token: str,
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        repository_result = await repository.public_share_card(public_token)
        if repository_result is None:
            raise _not_found("public_share")
        repository_card, blob = repository_result
        return {
            "id": repository_card.id,
            "template": repository_card.template,
            "display_name": repository_card.display_name,
            "snapshot": repository_card.snapshot_json,
            "etag": None if blob is None else f'"{blob.sha256.hex()}"',
        }
    card = _public_card(public_token, platform)
    return {
        "id": card["id"],
        "template": card["template"],
        "display_name": card["display_name"],
        "snapshot": card["snapshot"],
        "etag": card["etag"],
    }


@router.get("/public/share/{public_token}/image", operation_id="get_public_share_image")
async def get_public_share_image(
    public_token: str,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> Response:
    if repository is not None:
        result = await repository.public_share_card(public_token)
        if result is None:
            raise _not_found("public_share")
        _card, blob = result
        if blob is None:
            raise ApiError(
                409, "SHARE_IMAGE_NOT_READY", "The share image is not ready.", retryable=True
            )
        etag = f'"{blob.sha256.hex()}"'
        headers = {"ETag": etag, "Cache-Control": "public, max-age=300"}
        if if_none_match == etag:
            return Response(status_code=304, headers=headers)
        return Response(content=blob.payload, media_type=blob.mime_type, headers=headers)
    card = _public_card(public_token, platform)
    headers = {"ETag": card["etag"], "Cache-Control": "public, max-age=300"}
    if if_none_match == card["etag"]:
        return Response(status_code=304, headers=headers)
    return Response(content=card["png"], media_type="image/png", headers=headers)


@router.delete(
    "/share-cards/{share_card_id}",
    status_code=204,
    dependencies=[Depends(require_csrf)],
    operation_id="delete_share_card",
)
async def delete_share_card(
    share_card_id: str,
    principal: Principal = Depends(require_member),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> None:
    if repository is not None:
        if not await repository.revoke_share_card(card_id=share_card_id, user_id=principal.user_id):
            raise _not_found("share_card")
        return
    card = platform.share_cards.get(share_card_id)
    if not card or card["user_id"] != principal.user_id:
        raise _not_found("share_card")
    card["status"], card["revoked_at"] = "revoked", utcnow()


@router.get("/admin/sources", response_model=Page, operation_id="admin_list_sources")
async def admin_list_sources(
    cursor: str | None = None,
    _: Principal = Depends(require_analyst),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return _page(await _admin_repo(repository.list_sources()), cursor)
    return _page(list(platform.sources.values()), cursor)


@router.get("/admin/sources/{source_id}", operation_id="admin_get_source")
async def admin_get_source(
    source_id: str,
    _: Principal = Depends(require_analyst),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(repository.get_source(source_id))
    source = platform.sources.get(source_id)
    if not source:
        raise _not_found("source")
    return source


@router.post(
    "/admin/sources",
    status_code=201,
    dependencies=[Depends(require_csrf)],
    operation_id="admin_create_source",
)
async def admin_create_source(
    body: SourceCreate,
    request: Request,
    principal: Principal = Depends(require_admin),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.create_source(
                body.model_dump(),
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )

    def create() -> dict[str, Any]:
        source_id = new_id()
        result = {"id": source_id, **body.model_dump(exclude={"reason"}), "version": 1}
        platform.sources[source_id] = result
        platform.audit_action(
            principal.user_id,
            "SOURCE_CREATED",
            "source",
            source_id,
            None,
            result,
            body.reason,
            request.state.request_id,
        )
        return result

    return _idempotent(platform, "admin:create-source", key, body.model_dump(), create)


@router.patch(
    "/admin/sources/{source_id}",
    dependencies=[Depends(require_csrf)],
    operation_id="admin_patch_source",
)
async def admin_patch_source(
    source_id: str,
    body: PatchDocument,
    request: Request,
    principal: Principal = Depends(require_admin),
    key: str = Depends(require_idempotency_key),
    if_match: str = Depends(require_if_match),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.update_source(
                source_id,
                body.values,
                if_match=if_match,
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    source = platform.sources.get(source_id)
    if not source:
        raise _not_found("source")
    if str(source["version"]) != if_match:
        raise ApiError(409, "VERSION_CONFLICT", "If-Match does not match the source version.")

    def patch() -> dict[str, Any]:
        before = deepcopy(source)
        allowed = {"name", "policy_status", "robots_status", "terms_status", "active"}
        source.update({key: value for key, value in body.values.items() if key in allowed})
        source["version"] += 1
        platform.audit_action(
            principal.user_id,
            "SOURCE_UPDATED",
            "source",
            source_id,
            before,
            source,
            body.reason,
            request.state.request_id,
        )
        return source

    return _idempotent(platform, f"admin:source:{source_id}", key, body.model_dump(), patch)


@router.post(
    "/admin/sources/{source_id}/crawl",
    response_model=JobAccepted,
    status_code=202,
    dependencies=[Depends(require_csrf)],
    operation_id="admin_crawl_source",
)
async def admin_crawl_source(
    source_id: str,
    body: ReasonRequest,
    request: Request,
    principal: Principal = Depends(require_analyst),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.enqueue_crawl(
                source_id,
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    source = platform.sources.get(source_id)
    if not source:
        raise _not_found("source")
    if source["source_type"] == "CRAWLER" and not all(
        source.get(name) == "APPROVED"
        for name in ("policy_status", "robots_status", "terms_status")
    ):
        raise ApiError(
            403,
            "CRAWLER_POLICY_NOT_APPROVED",
            "Crawler policy, robots and terms approval are required.",
        )
    job = platform.enqueue(
        "crawl",
        f"{source_id}:{key}",
        {
            "source_id": source_id,
            "url": source["canonical_url"],
            "source_type": source["source_type"],
            "policy_status": source["policy_status"],
            "robots_status": source.get("robots_status", "UNKNOWN"),
            "terms_status": source.get("terms_status", "UNKNOWN"),
            "actor_id": principal.user_id,
            "reason": body.reason,
            "mode": "fixture",
        },
    )
    platform.audit_action(
        principal.user_id,
        "CRAWL_ENQUEUED",
        "source",
        source_id,
        None,
        {"job_id": job["id"], "status": "PENDING"},
        body.reason,
        request.state.request_id,
    )
    return {"job_id": job["id"], "status": "PENDING"}


@router.get("/admin/crawls", response_model=Page, operation_id="admin_list_crawls")
async def admin_list_crawls(
    cursor: str | None = None,
    _: Principal = Depends(require_analyst),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return _page(await _admin_repo(repository.list_crawls()), cursor)
    return _page([job for job in platform.jobs.values() if job["job_type"] == "crawl"], cursor)


@router.post(
    "/admin/issues/{issue_id}/merge",
    response_model=JobAccepted,
    status_code=202,
    dependencies=[Depends(require_csrf)],
    operation_id="admin_merge_issue",
)
async def admin_merge_issue(
    issue_id: str,
    body: MergeIssueRequest,
    request: Request,
    principal: Principal = Depends(require_analyst),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.enqueue_merge_issue(
                issue_id,
                body.target_issue_id,
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    source = platform.issues.get(issue_id)
    if source is None:
        raise _not_found("issue")
    if issue_id == body.target_issue_id:
        raise ApiError(400, "INVALID_ISSUE_OPERATION_PAYLOAD", "An issue cannot be merged into itself.")
    # The merge worker treats the target as an output and can create it when
    # the caller supplies a new identifier.  Mirror that contract in the
    # deterministic backend so a missing target is not rejected only in local
    # mode.  Hold the state lock across target creation and enqueue so a
    # caller cannot observe a target without its merge job (or vice versa).
    with platform.lock:
        target_created = body.target_issue_id not in platform.issues
        if target_created:
            now = utcnow()
            platform.issues[body.target_issue_id] = {
                "id": body.target_issue_id,
                "title": source.get("title", "Untitled issue"),
                "summary": source.get("summary", ""),
                "status": "OPEN",
                "version": 1,
                "article_ids": [],
                "opened_at": now,
                "last_activity_at": now,
            }
        try:
            job = platform.enqueue(
                "merge_issue",
                f"{issue_id}:{body.target_issue_id}:{key}",
                {
                    "source_issue_id": issue_id,
                    "target_issue_id": body.target_issue_id,
                    "actor_id": principal.user_id,
                    "reason": body.reason,
                },
            )
        except BaseException:
            if target_created:
                platform.issues.pop(body.target_issue_id, None)
            raise
        platform.audit_action(
            principal.user_id,
            "ISSUE_MERGE_ENQUEUED",
            "issue",
            issue_id,
            None,
            {
                "job": job,
                "source_issue_id": issue_id,
                "target_issue_id": body.target_issue_id,
                "target_created": target_created,
            },
            body.reason,
            request.state.request_id,
        )
    return {"job_id": job["id"], "status": "PENDING"}


@router.post(
    "/admin/issues/{issue_id}/split",
    response_model=JobAccepted,
    status_code=202,
    dependencies=[Depends(require_csrf)],
    operation_id="admin_split_issue",
)
async def admin_split_issue(
    issue_id: str,
    body: SplitIssueRequest,
    request: Request,
    principal: Principal = Depends(require_analyst),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.enqueue_split_issue(
                issue_id,
                body.article_ids,
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    issue = platform.issues.get(issue_id)
    if not issue or not set(body.article_ids).issubset(issue["article_ids"]):
        raise ApiError(400, "ISSUE_SPLIT_INVALID", "All split articles must belong to the issue.")
    job = platform.enqueue(
        "split_issue",
        f"{issue_id}:{stable_hash('|'.join(sorted(body.article_ids)))}:{key}",
        {"issue_id": issue_id, "article_ids": body.article_ids, "actor_id": principal.user_id, "reason": body.reason},
    )
    platform.audit_action(
        principal.user_id,
        "ISSUE_SPLIT_ENQUEUED",
        "issue",
        issue_id,
        None,
        {"job": job, "issue_id": issue_id, "article_ids": body.article_ids},
        body.reason,
        request.state.request_id,
    )
    return {"job_id": job["id"], "status": "PENDING"}


@router.patch(
    "/admin/issues/{issue_id}",
    dependencies=[Depends(require_csrf)],
    operation_id="admin_patch_issue",
)
async def admin_patch_issue(
    issue_id: str,
    body: PatchDocument,
    request: Request,
    principal: Principal = Depends(require_analyst),
    key: str = Depends(require_idempotency_key),
    if_match: str = Depends(require_if_match),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.patch_issue(
                issue_id,
                body.values,
                if_match=if_match,
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    issue = platform.issues.get(issue_id)
    if not issue:
        raise _not_found("issue")
    if str(issue["version"]) != if_match:
        raise ApiError(409, "VERSION_CONFLICT", "If-Match does not match the issue version.")

    def patch() -> dict[str, Any]:
        before = deepcopy(issue)
        issue.update(
            {
                key: value
                for key, value in body.values.items()
                if key in {"title", "summary", "status"}
            }
        )
        issue["version"] += 1
        platform.audit_action(
            principal.user_id,
            "ISSUE_UPDATED",
            "issue",
            issue_id,
            before,
            issue,
            body.reason,
            request.state.request_id,
        )
        return issue

    return _idempotent(platform, f"admin:issue:{issue_id}", key, body.model_dump(), patch)


@router.get("/admin/models", response_model=Page, operation_id="admin_list_models")
async def admin_list_models(
    cursor: str | None = None,
    _: Principal = Depends(require_analyst),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return _page(await _admin_repo(repository.list_model_aliases()), cursor)
    return _page(list(platform.models.values()), cursor)


@router.get("/admin/models/{model_id}", operation_id="admin_get_model")
async def admin_get_model(
    model_id: str,
    _: Principal = Depends(require_analyst),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(repository.get_model_alias(model_id))
    model = platform.models.get(model_id)
    if not model:
        raise _not_found("model")
    return model


@router.post(
    "/admin/models",
    status_code=201,
    dependencies=[Depends(require_csrf)],
    operation_id="admin_create_model",
)
async def admin_create_model(
    body: ModelCreate,
    request: Request,
    principal: Principal = Depends(require_admin),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.create_model_alias(
                body.model_dump(),
                actor_id=principal.user_id,
                idempotency_key=key,
                request_id=request.state.request_id,
            )
        )

    def create() -> dict[str, Any]:
        model_id = new_id()
        result = {"id": model_id, **body.model_dump(), "version": 1}
        platform.models[model_id] = result
        platform.audit_action(
            principal.user_id,
            "MODEL_CREATED",
            "model",
            model_id,
            None,
            result,
            "create model alias",
            request.state.request_id,
        )
        return result

    return _idempotent(platform, "admin:create-model", key, body.model_dump(), create)


@router.patch(
    "/admin/models/{model_id}",
    dependencies=[Depends(require_csrf)],
    operation_id="admin_patch_model",
)
async def admin_patch_model(
    model_id: str,
    body: PatchDocument,
    request: Request,
    principal: Principal = Depends(require_admin),
    key: str = Depends(require_idempotency_key),
    if_match: str = Depends(require_if_match),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.update_model_alias(
                model_id,
                body.values,
                if_match=if_match,
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    model = platform.models.get(model_id)
    if not model:
        raise _not_found("model")
    if str(model["version"]) != if_match:
        raise ApiError(409, "VERSION_CONFLICT", "If-Match does not match the model version.")

    def patch() -> dict[str, Any]:
        before = deepcopy(model)
        candidate = {
            **model,
            **{
                field: value
                for field, value in body.values.items()
                if field
                in {
                    "alias",
                    "provider",
                    "actual_model_id",
                    "reasoning_effort",
                    "secret_env_name",
                    "status",
                }
            },
        }
        if candidate.get("provider") != "openai":
            raise ApiError(400, "ADMIN_VALIDATION_ERROR", "Only OpenAI is allowed.")
        if not str(candidate.get("actual_model_id", "")).startswith("gpt-"):
            raise ApiError(
                400,
                "ADMIN_VALIDATION_ERROR",
                "actual_model_id must be an OpenAI GPT model ID.",
            )
        if candidate.get("reasoning_effort", "xhigh") not in {
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ApiError(
                400,
                "ADMIN_VALIDATION_ERROR",
                "reasoning_effort is invalid.",
            )
        model.update(candidate)
        model["version"] += 1
        platform.audit_action(
            principal.user_id,
            "MODEL_UPDATED",
            "model",
            model_id,
            before,
            model,
            body.reason,
            request.state.request_id,
        )
        return model

    return _idempotent(platform, f"admin:model:{model_id}", key, body.model_dump(), patch)


@router.post(
    "/admin/articles/{article_id}/analyze",
    response_model=JobAccepted,
    status_code=202,
    dependencies=[Depends(require_csrf)],
    operation_id="admin_analyze_article",
)
async def admin_analyze_article(
    article_id: str,
    request: Request,
    principal: Principal = Depends(require_analyst),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.enqueue_analysis(
                article_id,
                actor_id=principal.user_id,
                idempotency_key=key,
                request_id=request.state.request_id,
            )
        )
    article = platform.articles.get(article_id)
    if not article:
        raise _not_found("article")
    job = platform.enqueue(
        "analyze",
        f"{article['current_version_id']}:{key}",
        {
            "article_id": article_id,
            "article_version_id": article["current_version_id"],
            "actor_id": principal.user_id,
        },
    )
    return {"job_id": job["id"], "status": "PENDING"}


@router.get("/admin/analysis-runs/{run_id}", operation_id="admin_get_analysis_run")
async def admin_get_analysis_run(
    run_id: str,
    _: Principal = Depends(require_analyst),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(repository.get_analysis_run(run_id))
    job = platform.jobs.get(run_id)
    if not job or job["job_type"] != "analyze":
        raise _not_found("analysis_run")
    return job


@router.get("/admin/weights", response_model=Page, operation_id="admin_list_weights")
async def admin_list_weights(
    cursor: str | None = None,
    _: Principal = Depends(require_analyst),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        rows = await _admin_repo(repository.list_weights())
        settings = await _admin_repo(repository.get_autopilot_settings())
        rows = [{**row, "profile_version": settings["version"]} for row in rows]
        return _page(rows, cursor)
    profile_version = int(platform.autopilot.get("version", 1))
    rows = [{**row, "profile_version": profile_version} for row in platform.weights.values()]
    return _page(
        sorted(rows, key=lambda row: row["revision"], reverse=True), cursor
    )


@router.post(
    "/admin/weights",
    status_code=201,
    dependencies=[Depends(require_csrf)],
    operation_id="admin_create_weight",
)
async def admin_create_weight(
    body: WeightCreate,
    request: Request,
    principal: Principal = Depends(require_admin),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.create_weight(
                body.model_dump(),
                actor_id=principal.user_id,
                idempotency_key=key,
                request_id=request.state.request_id,
            )
        )
    if abs(sum(body.weights.values()) - 1.0) > 1e-9 or any(
        value < 0 or value > 1 for value in body.weights.values()
    ):
        raise ApiError(400, "WEIGHT_PROFILE_INVALID", "Weights must each be in [0,1] and sum to 1.")

    def create() -> dict[str, Any]:
        weight_id = new_id()
        row = {
            "id": weight_id,
            "revision": max((r["revision"] for r in platform.weights.values()), default=0) + 1,
            "status": "draft",
            **body.model_dump(),
            "created_by": principal.user_id,
            "created_at": utcnow(),
            "published_at": None,
        }
        platform.weights[weight_id] = row
        platform.audit_action(
            principal.user_id,
            "WEIGHT_DRAFT_CREATED",
            "weight",
            weight_id,
            None,
            row,
            "create immutable weight draft",
            request.state.request_id,
        )
        return row

    return _idempotent(platform, "admin:create-weight", key, body.model_dump(), create)


@router.post(
    "/admin/weights/{weight_id}/simulate",
    response_model=JobAccepted,
    status_code=202,
    dependencies=[Depends(require_csrf)],
    operation_id="admin_simulate_weight",
)
async def admin_simulate_weight(
    weight_id: str,
    body: SimulationRequest,
    request: Request,
    principal: Principal = Depends(require_analyst),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.simulate_weight(
                weight_id,
                body.windows,
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    weight = platform.weights.get(weight_id)
    if not weight:
        raise _not_found("weight")
    if sorted(set(body.windows)) != [7, 30]:
        raise ApiError(
            400, "SIMULATION_WINDOWS_REQUIRED", "Both 7-day and 30-day simulations are required."
        )
    weight["status"] = "simulation"
    platform.simulations[weight_id] = [
        {
            "window_days": days,
            "metrics": {"accuracy_delta": 0.0, "diversity_delta": 0.01, "maximum_axis_shift": 2.0},
            "guardrail_result": "PASS",
        }
        for days in body.windows
    ]
    # Keep the deterministic memory backend faithful to the durable flow:
    # every simulated revision has a reviewable recommendation with the same
    # identifier, just as ``MariaDBPlatformRepository.simulate_weight`` does.
    # Publishing must therefore pass both simulation and human-review gates.
    platform.recommendations.setdefault(
        weight_id,
        {
            "id": weight_id,
            "base_revision_id": weight.get("based_on_revision_id") or weight_id,
            "proposed_weights": deepcopy(weight["weights"]),
            "evidence_snapshot": {
                "kind": "manual_weight_simulation",
                "windows": sorted(set(body.windows)),
                "captured_at": utcnow(),
            },
            "provider_assessment_ref": "manual-weight",
            "status": "PENDING_REVIEW",
            "created_at": utcnow(),
        },
    )
    job = platform.enqueue(
        "simulate_weights",
        f"{weight_id}:{key}",
        {
            "weight_id": weight_id,
            "windows": body.windows,
            "actor_id": principal.user_id,
            "reason": body.reason,
        },
    )
    platform.audit_action(
        principal.user_id,
        "WEIGHT_SIMULATION_ENQUEUED",
        "weight",
        weight_id,
        None,
        {"job_id": job["id"], "status": "PENDING", "windows": body.windows},
        body.reason,
        request.state.request_id,
    )
    return {"job_id": job["id"], "status": "PENDING"}


@router.post(
    "/admin/weights/{weight_id}/publish",
    dependencies=[Depends(require_csrf)],
    operation_id="admin_publish_weight",
)
async def admin_publish_weight(
    weight_id: str,
    body: ReasonRequest,
    request: Request,
    principal: Principal = Depends(require_admin),
    key: str = Depends(require_idempotency_key),
    if_match: str = Depends(require_if_match),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.publish_weight(
                weight_id,
                if_match=if_match,
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    weight = platform.weights.get(weight_id)
    if not weight:
        raise _not_found("weight")
    if weight.get("status") not in {"draft", "simulation"}:
        raise ApiError(
            409,
            "WEIGHT_STATE_INVALID",
            "Only a draft or simulated weight revision can be published.",
        )
    if str(platform.autopilot["version"]) != if_match:
        raise ApiError(
            409, "VERSION_CONFLICT", "If-Match does not match the active-profile version."
        )
    sims = platform.simulations.get(weight_id, [])
    if {sim["window_days"] for sim in sims if sim["guardrail_result"] == "PASS"} != {7, 30}:
        raise ApiError(
            409, "GUARDRAIL_NOT_SATISFIED", "Passing 7-day and 30-day simulations are required."
        )
    recommendation = platform.recommendations.get(weight_id)
    if not recommendation or recommendation.get("status") != "APPROVED":
        raise ApiError(
            409,
            "REVIEWER_APPROVAL_REQUIRED",
            "Reviewer approval is required before publishing a weight revision.",
        )

    def publish() -> dict[str, Any]:
        before = next(
            (deepcopy(row) for row in platform.weights.values() if row["status"] == "active"), None
        )
        for row in platform.weights.values():
            if row["status"] == "active":
                row["status"] = "archived"
        weight["status"], weight["published_at"] = "active", utcnow()
        recommendation["status"] = "PUBLISHED"
        platform.autopilot["version"] += 1
        platform.audit_action(
            principal.user_id,
            "WEIGHT_PUBLISHED",
            "weight",
            weight_id,
            before,
            weight,
            body.reason,
            request.state.request_id,
        )
        return weight

    return _idempotent(platform, f"admin:publish:{weight_id}", key, body.model_dump(), publish)


@router.post(
    "/admin/weights/{weight_id}/rollback",
    dependencies=[Depends(require_csrf)],
    operation_id="admin_rollback_weight",
)
async def admin_rollback_weight(
    weight_id: str,
    body: RollbackRequest,
    request: Request,
    principal: Principal = Depends(require_admin),
    key: str = Depends(require_idempotency_key),
    if_match: str = Depends(require_if_match),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.rollback_weight(
                weight_id,
                body.target_revision_id,
                if_match=if_match,
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    active = platform.weights.get(weight_id)
    target = platform.weights.get(body.target_revision_id)
    if not active or active["status"] != "active" or not target:
        raise ApiError(409, "ROLLBACK_TARGET_INVALID", "Active and target revisions are required.")
    if target.get("status") != "archived":
        raise ApiError(
            409,
            "ROLLBACK_TARGET_INVALID",
            "Only an archived revision can be used as a rollback target.",
        )
    if (
        target.get("id") == active.get("id")
        or int(target.get("revision", 0)) >= int(active.get("revision", 0))
    ):
        raise ApiError(
            409,
            "ROLLBACK_TARGET_INVALID",
            "Only an older archived revision can be used as a rollback target.",
        )
    if str(platform.autopilot["version"]) != if_match:
        raise ApiError(
            409, "VERSION_CONFLICT", "If-Match does not match the active-profile version."
        )
    target_recommendation = platform.recommendations.get(body.target_revision_id)
    if target_recommendation and target_recommendation.get("status") not in {
        "APPROVED",
        "PUBLISHED",
    }:
        raise ApiError(
            409,
            "REVIEWER_APPROVAL_REQUIRED",
            "The archived revision does not have reviewer approval.",
        )
    target_simulations = platform.simulations.get(body.target_revision_id, [])
    if target_simulations and {
        sim.get("window_days")
        for sim in target_simulations
        if sim.get("guardrail_result") in {"PASS", "PASSED"}
    } != {7, 30}:
        raise ApiError(
            409,
            "GUARDRAIL_NOT_SATISFIED",
            "Passing 7-day and 30-day simulations are required.",
        )

    def rollback() -> dict[str, Any]:
        new_weight_id = new_id()
        row = {
            **deepcopy(target),
            "id": new_weight_id,
            "revision": max(item["revision"] for item in platform.weights.values()) + 1,
            "status": "active",
            "based_on_revision_id": target["id"],
            "created_by": principal.user_id,
            "created_at": utcnow(),
            "published_at": utcnow(),
        }
        active["status"] = "archived"
        platform.weights[new_weight_id] = row
        platform.autopilot["version"] += 1
        platform.audit_action(
            principal.user_id,
            "WEIGHT_ROLLED_BACK",
            "weight",
            new_weight_id,
            active,
            row,
            body.reason,
            request.state.request_id,
        )
        return row

    return _idempotent(platform, f"admin:rollback:{weight_id}", key, body.model_dump(), rollback)


@router.get(
    "/admin/autopilot/recommendations",
    response_model=Page,
    operation_id="admin_list_recommendations",
)
async def admin_list_recommendations(
    cursor: str | None = None,
    _: Principal = Depends(require_analyst),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return _page(await _admin_repo(repository.list_recommendations()), cursor)
    return _page(list(platform.recommendations.values()), cursor)


@router.post(
    "/admin/autopilot/recommendations/generate",
    response_model=JobAccepted,
    status_code=202,
    dependencies=[Depends(require_csrf)],
    operation_id="admin_generate_recommendation",
)
async def admin_generate_recommendation(
    body: RecommendationGenerate,
    request: Request,
    principal: Principal = Depends(require_reviewer),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.generate_recommendation(
                body.evidence_window_days,
                actor_id=principal.user_id,
                idempotency_key=key,
                request_id=request.state.request_id,
            )
        )
    active = next(row for row in platform.weights.values() if row["status"] == "active")
    recommendation_id = new_id()
    platform.recommendations[recommendation_id] = {
        "id": recommendation_id,
        "base_revision_id": active["id"],
        "proposed_weights": active["weights"],
        "evidence_snapshot": {"window_days": body.evidence_window_days, "captured_at": utcnow()},
        "provider_assessment_ref": "deterministic-stub",
        "status": "PENDING_REVIEW",
        "created_at": utcnow(),
    }
    job = platform.enqueue(
        "recommend_weights",
        f"{body.evidence_window_days}:{key}",
        {"recommendation_id": recommendation_id, "actor_id": principal.user_id},
    )
    return {"job_id": job["id"], "status": "PENDING"}


def _review_recommendation(
    recommendation_id: str,
    body: ReasonRequest,
    decision: Literal["APPROVED", "REJECTED"],
    request: Request,
    principal: Principal,
    key: str,
    platform: PlatformState,
) -> dict[str, Any]:
    recommendation = platform.recommendations.get(recommendation_id)
    if not recommendation:
        raise _not_found("recommendation")

    def review() -> dict[str, Any]:
        if recommendation["status"] != "PENDING_REVIEW":
            raise ApiError(
                409, "RECOMMENDATION_ALREADY_REVIEWED", "Recommendation review is immutable."
            )
        before = deepcopy(recommendation)
        recommendation.update(
            {
                "status": decision,
                "review_reason": body.reason,
                "reviewed_by": principal.user_id,
                "reviewed_at": utcnow(),
            }
        )
        platform.audit_action(
            principal.user_id,
            f"RECOMMENDATION_{decision}",
            "recommendation",
            recommendation_id,
            before,
            recommendation,
            body.reason,
            request.state.request_id,
        )
        return recommendation

    return _idempotent(
        platform,
        f"admin:recommendation:{recommendation_id}:{decision}",
        key,
        body.model_dump(),
        review,
    )


@router.post(
    "/admin/autopilot/recommendations/{recommendation_id}/approve",
    dependencies=[Depends(require_csrf)],
    operation_id="admin_approve_recommendation",
)
async def admin_approve_recommendation(
    recommendation_id: str,
    body: ReasonRequest,
    request: Request,
    principal: Principal = Depends(require_reviewer),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.review_recommendation(
                recommendation_id,
                "APPROVED",
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    return _review_recommendation(
        recommendation_id, body, "APPROVED", request, principal, key, platform
    )


@router.post(
    "/admin/autopilot/recommendations/{recommendation_id}/reject",
    dependencies=[Depends(require_csrf)],
    operation_id="admin_reject_recommendation",
)
async def admin_reject_recommendation(
    recommendation_id: str,
    body: ReasonRequest,
    request: Request,
    principal: Principal = Depends(require_reviewer),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.review_recommendation(
                recommendation_id,
                "REJECTED",
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    return _review_recommendation(
        recommendation_id, body, "REJECTED", request, principal, key, platform
    )


@router.get(
    "/admin/autopilot/settings",
    response_model=AutopilotSettingsView,
    operation_id="admin_get_autopilot_settings",
)
async def admin_get_autopilot_settings(
    _: Principal = Depends(require_admin),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(repository.get_autopilot_settings())
    with platform.lock:
        settings = deepcopy(platform.autopilot)
    settings.setdefault("updated_by", None)
    settings.setdefault("updated_at", None)
    return settings


@router.put(
    "/admin/autopilot/settings",
    dependencies=[Depends(require_csrf)],
    operation_id="admin_put_autopilot_settings",
)
async def admin_put_autopilot_settings(
    body: AutopilotSettingsPut,
    request: Request,
    principal: Principal = Depends(require_admin),
    key: str = Depends(require_idempotency_key),
    if_match: str = Depends(require_if_match),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.update_autopilot_settings(
                body.model_dump(exclude={"reason"}),
                if_match=if_match,
                actor_id=principal.user_id,
                idempotency_key=key,
                reason=body.reason,
                request_id=request.state.request_id,
            )
        )
    if str(platform.autopilot["version"]) != if_match:
        raise ApiError(409, "VERSION_CONFLICT", "If-Match does not match Auto Pilot settings.")

    def update() -> dict[str, Any]:
        before = deepcopy(platform.autopilot)
        if body.mode == "LIMITED_AUTO" and not body.guardrails:
            raise ApiError(
                400,
                "LIMITED_AUTO_GUARDRAILS_REQUIRED",
                "LIMITED_AUTO requires explicit guardrails.",
            )
        platform.autopilot.update(body.model_dump(exclude={"reason"}))
        platform.autopilot["version"] += 1
        platform.audit_action(
            principal.user_id,
            "AUTOPILOT_SETTINGS_UPDATED",
            "autopilot",
            "singleton",
            before,
            platform.autopilot,
            body.reason,
            request.state.request_id,
        )
        return platform.autopilot

    return _idempotent(platform, "admin:autopilot-settings", key, body.model_dump(), update)


@router.get("/admin/jobs", response_model=Page, operation_id="admin_list_jobs")
async def admin_list_jobs(
    status: str | None = None,
    job_type: str | None = None,
    cursor: str | None = None,
    _: Principal = Depends(require_analyst),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return _page(
            await _admin_repo(repository.list_jobs(status=status, job_type=job_type)), cursor
        )
    rows = list(platform.jobs.values())
    if status:
        rows = [row for row in rows if row["status"] == status]
    if job_type:
        rows = [row for row in rows if row["job_type"] == job_type]
    return _page(rows, cursor)


@router.post(
    "/admin/jobs/{job_id}/retry",
    response_model=RetryCancelResponse,
    dependencies=[Depends(require_csrf)],
    operation_id="admin_retry_job",
)
async def admin_retry_job(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_reviewer),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.retry_job(
                job_id,
                actor_id=principal.user_id,
                idempotency_key=key,
                request_id=request.state.request_id,
            )
        )
    job = platform.jobs.get(job_id)
    if not job:
        raise _not_found("job")

    def retry() -> dict[str, Any]:
        before = deepcopy(job)
        if job["status"] not in {"FAILED", "DEAD", "CANCELLED"}:
            raise ApiError(
                409, "JOB_NOT_RETRYABLE", "Only failed, dead, or cancelled jobs can be retried."
            )
        retry_at = utcnow()
        job.update(
            {
                "status": "PENDING",
                "attempts": 0,
                "available_at": retry_at,
                "lease_owner": None,
                "lease_expires_at": None,
                "last_error": None,
                "updated_at": retry_at,
            }
        )
        platform.audit_action(
            principal.user_id,
            "JOB_RETRIED",
            "job",
            job_id,
            before,
            job,
            "manual retry",
            request.state.request_id,
        )
        return {"job_id": job_id, "status": "PENDING"}

    return _idempotent(platform, f"admin:retry-job:{job_id}", key, {}, retry)


@router.post(
    "/admin/jobs/{job_id}/cancel",
    response_model=RetryCancelResponse,
    dependencies=[Depends(require_csrf)],
    operation_id="admin_cancel_job",
)
async def admin_cancel_job(
    job_id: str,
    request: Request,
    principal: Principal = Depends(require_reviewer),
    key: str = Depends(require_idempotency_key),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.cancel_job(
                job_id,
                actor_id=principal.user_id,
                idempotency_key=key,
                request_id=request.state.request_id,
            )
        )
    job = platform.jobs.get(job_id)
    if not job:
        raise _not_found("job")

    def cancel() -> dict[str, Any]:
        before = deepcopy(job)
        if job["status"] != "PENDING":
            raise ApiError(409, "JOB_NOT_CANCELLABLE", "Only pending jobs can be cancelled.")
        job["status"] = "CANCELLED"
        platform.audit_action(
            principal.user_id,
            "JOB_CANCELLED",
            "job",
            job_id,
            before,
            job,
            "manual cancel",
            request.state.request_id,
        )
        return {"job_id": job_id, "status": "CANCELLED"}

    return _idempotent(platform, f"admin:cancel-job:{job_id}", key, {}, cancel)


@router.get("/admin/audit", response_model=Page, operation_id="admin_list_audit")
async def admin_list_audit(
    actor: str | None = None,
    action: str | None = None,
    target: str | None = None,
    cursor: str | None = None,
    _: Principal = Depends(require_reviewer),
    platform: PlatformState = Depends(get_state),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return _page(
            await _admin_repo(repository.list_audit(actor=actor, action=action, target=target)),
            cursor,
        )
    rows = list(reversed(platform.audit))
    if actor:
        rows = [row for row in rows if row["actor_id"] == actor]
    if action:
        rows = [row for row in rows if row["action"] == action]
    if target:
        rows = [row for row in rows if row["target_id"] == target or row["target_type"] == target]
    return _page(rows, cursor)


@router.get("/admin/metrics/efficacy", operation_id="admin_efficacy_metrics")
async def admin_efficacy_metrics(
    _: Principal = Depends(require_analyst),
    platform: PlatformState = Depends(get_state),
    settings: Settings = Depends(get_settings),
    repository: MariaDBPlatformRepository | None = Depends(get_repository),
) -> dict[str, Any]:
    if repository is not None:
        return await _admin_repo(
            repository.get_efficacy_metrics(minimum_cohort_size=settings.cohort_minimum)
        )
    latest_by_user = {
        user_id: max(
            responses,
            key=lambda row: (row.get("submitted_at", utcnow()), row.get("id", "")),
        )
        for user_id, responses in platform.efficacy.items()
        if responses
    }
    scores = [row["normalized_score"] for row in latest_by_user.values()]
    if len(scores) < settings.cohort_minimum:
        return {"suppressed": True, "minimum_cohort_size": settings.cohort_minimum, "cohorts": []}
    return {
        "suppressed": False,
        "minimum_cohort_size": settings.cohort_minimum,
        "cohorts": [{"cohort_key": "all", "count": len(scores), "mean": round(fmean(scores), 4)}],
    }
