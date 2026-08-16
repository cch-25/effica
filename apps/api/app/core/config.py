from __future__ import annotations

import os
import stat
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
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
    oauth_redirect_allowlist: str = "http://localhost:3000/auth/callback"
    llm_provider_mode: str = "auto"
    openai_api_key: str | None = None
    openai_endpoint: str = "https://api.openai.com/v1/responses"
    llm_model: str = "gpt-5.6-luna"
    llm_model_alias: str = "openai-default"
    llm_reasoning_effort: str = "xhigh"
    log_level: str = "INFO"
    kakao_client_id: str | None = None
    kakao_client_secret: str | None = None
    naver_client_id: str | None = None
    naver_client_secret: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
