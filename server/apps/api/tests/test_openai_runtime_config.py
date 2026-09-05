from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.app.core.config import Settings


def test_openai_runtime_defaults_to_luna_high_and_one_key() -> None:
    settings = Settings(_env_file=None, openai_api_key="test-key")

    assert settings.llm_provider_mode == "auto"
    assert settings.live_llm_enabled is True
    assert settings.llm_model == "gpt-5.6-luna"
    assert settings.llm_reasoning_effort == "high"
    assert settings.llm_timeout_seconds == 180.0
    assert settings.llm_max_retries == 0
    assert settings.openai_endpoint == "https://api.openai.com/v1/responses"
    assert settings.worker_max_concurrency == 4
    assert settings.worker_shutdown_grace_seconds == 195.0
    assert settings.worker_crawl_scheduler_enabled is True
    assert settings.worker_crawl_interval_seconds == 900.0
    settings.assert_safe_runtime()


def test_live_runtime_rejects_missing_key_and_non_openai_configuration() -> None:
    offline = Settings(_env_file=None, llm_provider_mode="auto", openai_api_key=None)
    assert offline.live_llm_enabled is False
    offline.assert_safe_runtime()

    settings = Settings(_env_file=None, llm_provider_mode="live", openai_api_key=None)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        settings.assert_safe_runtime()

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            openai_api_key="test-key",
            openai_endpoint="https://api.upstage.ai/v1/chat/completions",
        )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, openai_api_key="test-key", llm_model="solar-pro")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_timeout_seconds=301)
    with pytest.raises(RuntimeError, match="WORKER_SHUTDOWN_GRACE_SECONDS"):
        Settings(
            _env_file=None,
            openai_api_key="test-key",
            llm_timeout_seconds=200,
            worker_shutdown_grace_seconds=100,
        ).assert_safe_runtime()
    with pytest.raises(RuntimeError, match="WORKER_HEARTBEAT_SECONDS"):
        Settings(
            _env_file=None,
            worker_lease_seconds=60,
            worker_heartbeat_seconds=30,
        ).assert_safe_runtime()


def test_production_requires_canonical_google_oauth_configuration() -> None:
    base = {
        "_env_file": None,
        "app_env": "production",
        "app_backend": "mariadb",
        "database_url": "mysql+asyncmy://effica:secret@127.0.0.1:3306/effica",
        "session_secret": "production-session-secret-that-is-long-enough",
        "public_base_url": "https://effica.vercel.app",
        "web_base_url": "https://effica.vercel.app",
        "oauth_redirect_allowlist": "https://effica.vercel.app/api/v1/auth/google/callback",
    }
    with pytest.raises(RuntimeError, match="Google OAuth"):
        Settings(**base).assert_safe_runtime()

    configured = Settings(
        **base,
        google_client_id="client.apps.googleusercontent.com",
        google_client_secret="client-secret",
    )
    configured.assert_safe_runtime()

    with pytest.raises(RuntimeError, match="canonical Google callback"):
        Settings(
            **{
                **base,
                "oauth_redirect_allowlist": (
                    "https://effica.vercel.app/api/v1/auth/google/callback,"
                    "https://effica.vercel.app/api/v1/auth/mock/callback"
                ),
            },
            google_client_id="client.apps.googleusercontent.com",
            google_client_secret="client-secret",
        ).assert_safe_runtime()
