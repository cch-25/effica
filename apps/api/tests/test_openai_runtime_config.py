from __future__ import annotations

import pytest
from pydantic import ValidationError

from apps.api.app.core.config import Settings


def test_openai_runtime_defaults_to_luna_xhigh_and_one_key() -> None:
    settings = Settings(_env_file=None, openai_api_key="test-key")

    assert settings.llm_provider_mode == "auto"
    assert settings.live_llm_enabled is True
    assert settings.llm_model == "gpt-5.6-luna"
    assert settings.llm_reasoning_effort == "xhigh"
    assert settings.openai_endpoint == "https://api.openai.com/v1/responses"
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
