from __future__ import annotations

import asyncio
from typing import NoReturn

import pytest

from apps.api.app.domains.analysis import (
    AssessmentInput,
    LLMProvider,
    ProviderConfig,
    ProviderError,
    ProviderHTTPError,
    ProviderSchemaError,
    make_stub_providers,
)
from apps.api.app.domains.scoring import canonical_score_json
from apps.worker.worker.handlers import build_default_registry
from apps.worker.worker.handlers.base import HandlerContext, HandlerError
from apps.worker.worker.main import _reasoning_effort_for_attempt


class _FailingProvider(LLMProvider):
    def __init__(self, error: Exception) -> None:
        self.config = ProviderConfig("failing", "gpt-test")
        self.error = error

    def analyze_article(
        self, input: AssessmentInput, prompt_version: str
    ) -> NoReturn:
        del input, prompt_version
        raise self.error


def test_analysis_retry_attempt_uses_bounded_reasoning_fallback() -> None:
    async def scenario() -> None:
        captured_attempts: list[int] = []

        async def provider_factory(*, attempt: int) -> LLMProvider:
            captured_attempts.append(attempt)
            return make_stub_providers(1)[0]

        analyze = build_default_registry().require_async("analyze")
        await analyze(
            {"text": "재시도에서도 평가되어야 하는 충분한 기사 본문"},
            HandlerContext(
                attempt=4,
                services={"analysis_provider_factory": provider_factory},
            ),
        )

        assert captured_attempts == [4]
        assert _reasoning_effort_for_attempt("xhigh", 3) == "xhigh"
        assert _reasoning_effort_for_attempt("xhigh", 4) == "high"
        assert _reasoning_effort_for_attempt("max", 5) == "high"
        assert _reasoning_effort_for_attempt("medium", 5) == "medium"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("provider_error", "expected_retryable"),
    [
        (ProviderSchemaError(), True),
        (ProviderHTTPError(400, retryable=False), False),
        (ProviderHTTPError(503, retryable=True), True),
    ],
)
def test_analysis_preserves_provider_retry_semantics(
    provider_error: ProviderError, expected_retryable: bool
) -> None:
    async def scenario() -> None:
        analyze = build_default_registry().require_async("analyze")
        with pytest.raises(HandlerError) as raised:
            await analyze(
                {"text": "article body"},
                HandlerContext(
                    services={"analysis_providers": [_FailingProvider(provider_error)]}
                ),
            )

        assert raised.value.code == "MINIMUM_ANALYSIS_PROVIDERS_NOT_REACHED"
        assert raised.value.retryable is expected_retryable
        assert raised.value.details["errors"] == [
            {
                "model_alias": "failing",
                "code": provider_error.code,
                "retryable": expected_retryable,
            }
        ]

    asyncio.run(scenario())


def test_analysis_rejects_invalid_prompt_and_provider_configuration_before_call() -> None:
    async def scenario() -> None:
        analyze = build_default_registry().require_async("analyze")
        with pytest.raises(HandlerError) as prompt_error:
            await analyze({"text": "article body", "prompt_version": " "})
        assert prompt_error.value.code == "INVALID_ANALYSIS_PAYLOAD"
        assert prompt_error.value.retryable is False

        with pytest.raises(HandlerError) as provider_error:
            await analyze(
                {"text": "article body"},
                HandlerContext(services={"analysis_providers": [object()]}),
            )
        assert provider_error.value.code == "INVALID_ANALYSIS_PROVIDER"
        assert provider_error.value.retryable is False

        def invalid_factory() -> LLMProvider:
            raise ValueError("bad model config")

        with pytest.raises(HandlerError) as factory_error:
            await analyze(
                {"text": "article body"},
                HandlerContext(services={"analysis_provider_factory": invalid_factory}),
            )
        assert factory_error.value.code == "INVALID_ANALYSIS_PROVIDER"
        assert factory_error.value.retryable is False

    asyncio.run(scenario())


def test_score_waits_for_trusted_assessment_instead_of_persisting_zero_snapshot() -> None:
    async def scenario() -> None:
        calculate = build_default_registry().require_async("calculate_score")
        with pytest.raises(HandlerError) as missing:
            await calculate(
                {"article_version_id": "version-missing"},
                HandlerContext(services={"score_components_lookup": {}}),
            )
        assert missing.value.code == "SCORE_ANALYSIS_NOT_READY"
        assert missing.value.retryable is True

        with pytest.raises(HandlerError) as raised:
            await calculate(
                {"article_version_id": "version-1"},
                HandlerContext(
                    services={
                        "score_components_lookup": {
                            "version-1": {
                                "components": {
                                    "model": [0, 0, 0],
                                    "relative": [0, 0, 0],
                                    "crowd": [0, 0, 0],
                                    "source": [0, 0, 0],
                                    "model_confidence": 0.0,
                                    "evidence_quality": 0.0,
                                },
                                "provenance": {
                                    "analysis_provider": "openai",
                                    "assessment_ids": [],
                                    "actual_model_ids": [],
                                },
                            }
                        }
                    }
                ),
            )

        assert raised.value.code == "SCORE_ANALYSIS_NOT_READY"
        assert raised.value.retryable is True

    asyncio.run(scenario())


def test_score_normalizes_legacy_single_model_confidence_and_is_reproducible() -> None:
    async def scenario() -> None:
        calculate = build_default_registry().require_async("calculate_score")
        result = await calculate(
            {"article_version_id": "version-1", "weights": {"model": 1.0}},
            HandlerContext(
                services={
                    "score_components_lookup": {
                        "version-1": {
                            "components": {
                                "model": [30, 0, 0],
                                "relative": [30, 0, 0],
                                "crowd": [0, 0, 0],
                                "source": [0, 0, 0],
                                "model_confidence": 0.8,
                                "model_spread": 14.14,
                                "sensationalism": 42,
                                "evidence_quality": 1 / 3,
                            },
                            "provenance": {
                                "analysis_provider": "openai",
                                "assessment_ids": ["assessment-1"],
                                "actual_model_ids": ["gpt-test"],
                            },
                        }
                    }
                }
            ),
        )

        assert result.value["x"] == 30
        assert result.value["sensationalism"] == 42
        assert result.value["confidence"] == 0.66
        assert result.value["components"]["model_spread"] == 0.0
        assert result.value["components"]["evidence_quality"] == 1.0
        score_projection = {
            key: result.value[key]
            for key in (
                "x",
                "y",
                "z",
                "sensationalism",
                "confidence",
                "weight_version",
                "components",
            )
        }
        assert canonical_score_json(score_projection)

    asyncio.run(scenario())
