from __future__ import annotations

import os
import stat
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_ROOT = Path(__file__).resolve().parents[4]
REPOSITORY_ROOT = SERVER_ROOT.parent if SERVER_ROOT.name == "server" else SERVER_ROOT
ROOT_ENV_FILE = REPOSITORY_ROOT / ".env"


class Settings(BaseSettings):
    """Server-only settings loaded from the single repository-root environment file."""

    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "local"
    app_backend: str = "memory"
    database_url: str = "mysql+asyncmy://platform:platform@127.0.0.1:3306/platform"
    session_secret: str = "local-development-placeholder-change-me"
    public_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"
    oauth_redirect_allowlist: str = (
        "http://localhost:3000/api/v1/auth/google/callback"
    )
    llm_provider_mode: str = "auto"
    openai_api_key: str | None = None
    openai_endpoint: str = "https://api.openai.com/v1/responses"
    llm_model: str = "gpt-5.6-luna"
    llm_model_alias: str = "openai-default"
    llm_reasoning_effort: str = "xhigh"
    llm_timeout_seconds: float = Field(default=180.0, gt=0, le=300)
    # The durable queue is the retry authority. Keeping provider-local retries
    # at zero prevents one slow request from occupying a worker slot for
    # several timeout windows before queue backoff can restore fairness.
    llm_max_retries: int = Field(default=0, ge=0, le=4)
    log_level: str = "INFO"
    worker_lease_seconds: float = Field(default=180.0, gt=5, le=3600)
    worker_heartbeat_seconds: float = Field(default=45.0, gt=1, le=1200)
    worker_poll_interval_seconds: float = Field(default=0.5, ge=0.05, le=60)
    worker_shutdown_grace_seconds: float = Field(default=195.0, ge=0, le=600)
    worker_max_concurrency: int = Field(default=4, ge=1, le=32)
    worker_queue_error_backoff_base_seconds: float = Field(default=1.0, gt=0, le=60)
    worker_queue_error_backoff_max_seconds: float = Field(default=30.0, gt=0, le=300)
    worker_crawl_scheduler_enabled: bool = True
    worker_crawl_interval_seconds: float = Field(default=900.0, ge=60, le=86400)
    worker_crawl_batch_size: int = Field(default=50, ge=1, le=500)
    worker_crawl_max_attempts: int = Field(default=5, ge=1, le=20)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    admin_username: str = "dev"
    admin_password: str = "1234"
    cohort_minimum: int = Field(default=5, ge=3)

    @field_validator("app_env")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        if value not in {"local", "test", "production"}:
            raise ValueError("APP_ENV must be local, test, or production")
        return value

    @field_validator("app_backend")
    @classmethod
    def validate_backend(cls, value: str) -> str:
        if value not in {"memory", "mariadb"}:
            raise ValueError("APP_BACKEND must be memory or mariadb")
        return value

    @field_validator("llm_provider_mode")
    @classmethod
    def validate_llm_mode(cls, value: str) -> str:
        if value not in {"auto", "stub", "live"}:
            raise ValueError("LLM_PROVIDER_MODE must be auto, stub, or live")
        return value

    @field_validator("llm_model")
    @classmethod
    def validate_llm_model(cls, value: str) -> str:
        if not value.strip().startswith("gpt-"):
            raise ValueError("LLM_MODEL must be an OpenAI GPT model ID")
        return value

    @field_validator("llm_reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, value: str) -> str:
        if value not in {"none", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError(
                "LLM_REASONING_EFFORT must be none, low, medium, high, xhigh, or max"
            )
        return value

    @field_validator("openai_endpoint")
    @classmethod
    def validate_openai_endpoint(cls, value: str) -> str:
        if value != "https://api.openai.com/v1/responses":
            raise ValueError("OPENAI_ENDPOINT must use the official OpenAI Responses API")
        return value

    @property
    def redirect_allowlist(self) -> set[str]:
        return {item.strip() for item in self.oauth_redirect_allowlist.split(",") if item.strip()}

    @property
    def live_llm_enabled(self) -> bool:
        return self.llm_provider_mode == "live" or (
            self.llm_provider_mode == "auto" and bool(self.openai_api_key)
        )

    def assert_safe_runtime(self) -> None:
        if ROOT_ENV_FILE.exists() and os.name != "nt":
            mode = stat.S_IMODE(ROOT_ENV_FILE.stat().st_mode)
            if mode & 0o077:
                raise RuntimeError("repository-root .env must have mode 600")
        if self.app_env == "production" and self.app_backend != "mariadb":
            raise RuntimeError("production requires APP_BACKEND=mariadb")
        if self.app_env == "production":
            if not self.google_client_id or not self.google_client_secret:
                raise RuntimeError("production requires Google OAuth client credentials")
            if not self.web_base_url.startswith("https://"):
                raise RuntimeError("production WEB_BASE_URL must use HTTPS")
            if not self.public_base_url.startswith("https://"):
                raise RuntimeError("production PUBLIC_BASE_URL must use HTTPS")
            expected_callback = (
                self.web_base_url.rstrip("/") + "/api/v1/auth/google/callback"
            )
            if self.redirect_allowlist != {expected_callback}:
                raise RuntimeError(
                    "production OAUTH_REDIRECT_ALLOWLIST must contain only the canonical "
                    "Google callback URL"
                )
        if self.app_backend == "mariadb":
            if "platform:platform@" in self.database_url:
                raise RuntimeError("MariaDB DATABASE_URL must not use the local placeholder")
            if len(self.session_secret.encode()) < 32 or "placeholder" in self.session_secret:
                raise RuntimeError(
                    "MariaDB SESSION_SECRET must contain at least 32 random bytes"
                )
        if self.llm_provider_mode == "live":
            if not self.openai_api_key:
                raise RuntimeError("live LLM mode requires OPENAI_API_KEY")
        if (
            self.live_llm_enabled
            and self.worker_shutdown_grace_seconds < self.llm_timeout_seconds + 10
        ):
            raise RuntimeError(
                "WORKER_SHUTDOWN_GRACE_SECONDS must be at least "
                "LLM_TIMEOUT_SECONDS + 10 when live LLM is enabled"
            )
        if self.worker_heartbeat_seconds >= self.worker_lease_seconds / 2:
            raise RuntimeError(
                "WORKER_HEARTBEAT_SECONDS must be less than half WORKER_LEASE_SECONDS"
            )
        if (
            self.worker_queue_error_backoff_max_seconds
            < self.worker_queue_error_backoff_base_seconds
        ):
            raise RuntimeError(
                "WORKER_QUEUE_ERROR_BACKOFF_MAX_SECONDS must be at least the base delay"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
