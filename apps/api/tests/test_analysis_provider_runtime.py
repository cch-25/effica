import json

import httpx
import pytest
from app.domains.analysis import (
    AssessmentInput,
    CircuitState,
    HTTPProvider,
    ProviderCircuitOpenError,
    ProviderConfig,
    ProviderConfigurationError,
    ProviderRateLimitError,
    ProviderSchemaError,
    ProviderTimeoutError,
)


def _input(content: str = "A short article body.") -> AssessmentInput:
    return AssessmentInput(
        article_version_id="version-1",
        title="Example source headline",
        content=content,
        source_name="Example Source",
        source_url="https://example.test/story?id=42",
        author="Reporter Name",
    )


def _response_payload(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "x": 10,
        "y": -5,
        "z": 20,
        "sensationalism": 12,
        "confidence": 0.82,
        "evidence": [
            {
                "article_version_id": "version-1",
                "start": 0,
                "end": 8,
                "quote": "A short ",
                "rationale": "opening",
            }
        ],
        "rationale_summary": "The article frames the issue with an opening claim.",
        "token_usage": 17,
    }
    value.update(overrides)
    return value


def _provider(
    handler: httpx.MockTransport,
    *,
    config: ProviderConfig | None = None,
    clock=None,
    sleep=None,
) -> HTTPProvider:
    return HTTPProvider(
        config
        or ProviderConfig(
            "test-provider",
            "actual-model-v1",
            endpoint="https://provider.test/analyze",
            timeout_seconds=0.25,
            retry_backoff_seconds=0,
        ),
        transport=handler,
        clock=clock or (lambda: 0.0),
        sleep=sleep or (lambda _: None),
    )


def test_live_provider_rejects_non_openai_endpoints_without_test_injection():
    with pytest.raises(ProviderConfigurationError):
        HTTPProvider(
            ProviderConfig(
                "upstage",
                "solar-pro",
                endpoint="https://api.upstage.ai/v1/chat/completions",
                api_key="test-key",
            )
        )


def test_timeout_retries_with_bounded_backoff_and_records_metrics():
    calls = 0
    sleeps: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ReadTimeout("upstream timeout", request=request)
        return httpx.Response(200, json=_response_payload(), request=request)

    provider = _provider(
        httpx.MockTransport(handle),
        config=ProviderConfig(
            "test-provider",
            "actual-model-v1",
            endpoint="https://provider.test/analyze",
            timeout_seconds=0.25,
            max_retries=2,
            retry_backoff_seconds=0.2,
            max_backoff_seconds=0.25,
        ),
        sleep=sleeps.append,
    )

    result = provider.analyze_article(_input(), "prompt-v1")

    assert result.model_alias == "test-provider"
    assert result.actual_model_id == "actual-model-v1"
    assert calls == 3
    assert sleeps == [0.2, 0.25]
    assert provider.metrics["retry_count"] == 2
    assert provider.metrics["total_tokens"] == 17
    assert provider.metrics["last_error_code"] is None


def test_circuit_opens_and_allows_one_half_open_recovery_probe():
    now = [0.0]
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(200, json=_response_payload(), request=request)

    provider = _provider(
        httpx.MockTransport(handle),
        config=ProviderConfig(
            "breaker-provider",
            "model",
            endpoint="https://provider.test/analyze",
            max_retries=0,
            circuit_failure_threshold=1,
            circuit_reset_timeout_seconds=5,
        ),
        clock=lambda: now[0],
    )

    with pytest.raises(ProviderTimeoutError):
        provider.analyze_article(_input(), "prompt-v1")
    assert provider.circuit_state == CircuitState.OPEN
    with pytest.raises(ProviderCircuitOpenError):
        provider.analyze_article(_input(), "prompt-v1")
    assert calls == 1

    now[0] = 5.0
    assert provider.circuit_state == CircuitState.HALF_OPEN
    result = provider.analyze_article(_input(), "prompt-v1")
    assert result.x == 10
    assert provider.circuit_state == CircuitState.CLOSED
    assert provider.metrics["circuit_open_requests"] == 1


def test_per_provider_rate_limit_rejects_until_window_expires():
    now = [0.0]
    provider = _provider(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=_response_payload(), request=request)
        ),
        config=ProviderConfig(
            "limited-provider",
            "model",
            endpoint="https://provider.test/analyze",
            rate_limit_per_minute=1,
            rate_limit_window_seconds=10,
        ),
        clock=lambda: now[0],
    )

    provider.analyze_article(_input(), "prompt-v1")
    with pytest.raises(ProviderRateLimitError) as error:
        provider.analyze_article(_input(), "prompt-v1")
    assert error.value.retry_after_seconds == 10
    assert provider.metrics["rate_limited_requests"] == 1

    now[0] = 10.1
    provider.analyze_article(_input(), "prompt-v1")
    assert provider.metrics["successful_requests"] == 2


def test_schema_rejection_is_strict_and_does_not_expose_response_content():
    leaked = "private article text that must never become an exception message"

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response_payload(x=101, rationale_summary=leaked),
            request=request,
        )

    provider = _provider(httpx.MockTransport(handle))
    with pytest.raises(ProviderSchemaError) as error:
        provider.analyze_article(_input(), "prompt-v1")

    assert error.value.code == "PROVIDER_SCHEMA_REJECTED"
    assert leaked not in str(error.value)
    assert provider.metrics["schema_rejections"] == 1


def test_masking_and_public_redaction_cover_source_identity_secrets_and_long_quotes():
    body = "Example Source reported this long source passage. " + ("important context " * 8)
    seen: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=_response_payload(
                rationale_summary=(
                    "Contact test@example.com; Bearer super-secret; "
                    "https://private.example/a; " + body[:80]
                ),
                evidence=[
                    {
                        "article_version_id": "version-1",
                        "start": 0,
                        "end": 20,
                            "quote": "[SOURCE] reported this "[:20],
                        "rationale": "api_key=do-not-publish",
                    }
                ],
            ),
            request=request,
        )

    provider = _provider(httpx.MockTransport(handle))
    result = provider.analyze_article(_input(body), "prompt-v1")
    request_body = seen[0]

    encoded = json.dumps(request_body)
    assert "Example Source" not in encoded
    assert "example.test" not in encoded
    assert "Reporter Name" not in encoded
    assert "TITLE: [SOURCE]" in request_body["input"]
    assert "[REDACTED_EMAIL]" in result.rationale_summary
    assert "[REDACTED_SECRET]" in result.rationale_summary
    assert "[REDACTED_URL]" in result.rationale_summary
    assert body[:40] not in result.rationale_summary
    assert "[REDACTED_SECRET]" in result.evidence[0].rationale
    assert "private" not in json.dumps(provider.metrics.as_dict())


def test_openai_responses_style_sends_reasoning_and_strict_schema():
    seen: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assessment = _response_payload()
        assessment.pop("token_usage")
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps(assessment)}
                        ],
                    }
                ],
                "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
            },
            request=request,
        )

    provider = _provider(
        httpx.MockTransport(handle),
        config=ProviderConfig(
            "openai-default",
            "gpt-5.6-luna",
            endpoint="https://api.openai.com/v1/responses",
            reasoning_effort="xhigh",
        ),
    )

    result = provider.analyze_article(_input(), "content-first-v1")

    body = seen[0]
    assert body["model"] == "gpt-5.6-luna"
    assert body["reasoning"] == {"effort": "xhigh"}
    assert "input" in body
    text_config = body["text"]
    assert isinstance(text_config, dict)
    json_schema = text_config["format"]
    assert isinstance(json_schema, dict)
    assert json_schema["type"] == "json_schema"
    assert json_schema["strict"] is True
    schema = json_schema["schema"]
    assert set(schema["properties"]) == {
        "x",
        "sensationalism",
        "confidence",
        "evidence",
        "rationale_summary",
    }
    assert "left-biased" in body["input"]
    assert "right-biased" in body["input"]
    assert result.token_usage == 18
    assert result.x == 10
    assert result.y == 0 and result.z == 0


def test_openai_issue_comparison_uses_strict_schema_and_validates_support():
    seen: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        comparison = {
            "common_facts": [
                {
                    "id": "fact-1",
                    "text": "Both articles describe the same policy decision.",
                    "article_ids": ["article-1", "article-2"],
                    "evidence_refs": ["article-1:policy", "article-2:policy"],
                }
            ],
            "dimensions": [{"key": "responsibility", "label": "책임 귀속"}],
            "article_frames": [
                {
                    "article_id": "article-1",
                    "headline_frame": "Implementation benefits",
                    "emphasis": ["benefits"],
                    "omissions_note": None,
                    "evidence_refs": ["article-1:headline"],
                },
                {
                    "article_id": "article-2",
                    "headline_frame": "Implementation costs",
                    "emphasis": ["costs"],
                    "omissions_note": None,
                    "evidence_refs": ["article-2:headline"],
                },
            ],
            "confidence": 0.82,
        }
        return httpx.Response(
            200,
            json={"output_text": json.dumps(comparison), "usage": {"total_tokens": 41}},
            request=request,
        )

    provider = _provider(
        httpx.MockTransport(handle),
        config=ProviderConfig(
            "openai-default",
            "gpt-5.6-luna",
            endpoint="https://api.openai.com/v1/responses",
            reasoning_effort="xhigh",
        ),
    )
    result = provider.analyze_issue_comparison(
        [
            {
                "article_id": "article-1",
                "article_version_id": "version-1",
                "title": "Policy benefits",
                "content": "The policy was announced and benefits were described.",
            },
            {
                "article_id": "article-2",
                "article_version_id": "version-2",
                "title": "Policy costs",
                "content": "The policy was announced and costs were described.",
            },
        ],
        "issue-comparison-v1",
    )

    assert result["article_frames"]["article-2"]["headline_frame"] == "Implementation costs"
    assert result["common_facts"][0]["article_ids"] == ["article-1", "article-2"]
    text_format = seen[0]["text"]
    assert isinstance(text_format, dict)
    assert text_format["format"]["name"] == "issue_comparison"
    assert text_format["format"]["strict"] is True
    assert "publisher identity" in str(seen[0]["input"])
    assert "at least two distinct supplied ARTICLE_ID" in str(seen[0]["input"])
    assert "exactly one article_frames item" in str(seen[0]["input"])
