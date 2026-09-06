from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from apps.api.app.domains.analysis import AssessmentInput, HttpLLMProvider, ProviderConfig
from apps.worker.tests.test_llm_request_ledger import _Database, _SessionFactory
from apps.worker.worker.analysis_eligibility import assess_analysis_eligibility
from apps.worker.worker.handlers.analyze import handle
from apps.worker.worker.handlers.base import HandlerContext, HandlerError
from apps.worker.worker.llm_budget import DailyLLMBudgetExceeded, MariaDBLLMBudget
from apps.worker.worker.services import _article_input_hash


def test_analysis_eligibility_rejects_noise_before_paid_work() -> None:
    sports = assess_analysis_eligibility(
        "프로야구 시즌 개막",
        "야구 선수와 리그 경기 소식입니다. " * 100,
    )
    short_index = assess_analysis_eligibility(
        "금융위원회 보도자료",
        "금융 정책 목록",
    )
    public_affairs = assess_analysis_eligibility(
        "정부의 주거 정책 개편안 발표",
        "정부와 국회가 주거 정책과 예산을 논의했습니다. " * 100,
    )

    assert sports.eligible is True
    assert short_index.eligible is False
    assert public_affairs.eligible is True


def test_luna_request_has_hard_output_cap_and_conservative_price() -> None:
    provider = HttpLLMProvider(
        ProviderConfig(
            "openai-default",
            "gpt-5.6-luna",
            endpoint="https://api.openai.com/v1/responses",
            reasoning_effort="none",
            max_output_tokens=4_096,
        ),
        transport=lambda _request: None,  # type: ignore[arg-type,return-value]
    )
    article = AssessmentInput(
        article_version_id="version-1",
        title="정부 정책 분석",
        content="정부 정책과 국회 논의를 설명하는 기사입니다. " * 2_000,
    )

    body = provider._request_body(article, "budget-v1")
    estimate = provider.estimate_article_max_cost_microusd(article, "budget-v1")

    assert body["reasoning"] == {"effort": "none"}
    assert body["max_output_tokens"] == 4_096
    assert len(str(body["input"])) < len(article.content)
    assert 1 <= estimate < 50_000
    provider.close()


class _Rows:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def mappings(self) -> _Rows:
        return self

    def first(self) -> dict[str, Any]:
        return dict(self.row)


class _Transaction:
    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None


class _BudgetSession:
    def __init__(self) -> None:
        self.row = {
            "request_count": 0,
            "article_request_count": 0,
            "comparison_request_count": 0,
            "reserved_microusd": 0,
            "observed_tokens": 0,
        }

    def begin(self) -> _Transaction:
        return _Transaction()

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Rows:
        query = str(statement)
        if "SELECT request_count" in query:
            return _Rows(self.row)
        if "SET request_count = request_count + 1" in query:
            self.row["request_count"] += 1
            self.row["article_request_count"] += params["article_delta"]
            self.row["comparison_request_count"] += params["comparison_delta"]
            self.row["reserved_microusd"] += params["reserved_microusd"]
        if "SET observed_tokens = observed_tokens" in query:
            self.row["observed_tokens"] += params["tokens"]
        return _Rows(self.row)

    async def close(self) -> None:
        return None


def test_daily_budget_stops_before_the_third_paid_request() -> None:
    async def scenario() -> None:
        session = _BudgetSession()
        budget = MariaDBLLMBudget(
            lambda: session,
            daily_budget_usd="0.000020",
            daily_request_limit=2,
            daily_comparison_limit=1,
            clock=lambda: datetime(2026, 9, 6, tzinfo=UTC),
        )

        article = await budget.reserve(
            category="article", estimated_max_cost_microusd=10
        )
        comparison = await budget.reserve(
            category="comparison", estimated_max_cost_microusd=10
        )
        await budget.record_observed_tokens(article, 123)
        with pytest.raises(DailyLLMBudgetExceeded):
            await budget.reserve(category="article", estimated_max_cost_microusd=1)

        assert article.usage_date.isoformat() == "2026-09-06"
        assert comparison.category == "comparison"
        assert session.row["request_count"] == 2
        assert session.row["reserved_microusd"] == 20
        assert session.row["observed_tokens"] == 123

    asyncio.run(scenario())


def test_article_handler_reuses_paid_response_across_version_and_job_ids() -> None:
    async def scenario() -> None:
        calls = []
        content = "국회가 새로운 주거 법안을 심사했습니다. " * 30

        def respond(request: httpx.Request) -> httpx.Response:
            calls.append(json.loads(request.content))
            return httpx.Response(200, json={
                "x": 0, "y": 0, "z": 0, "sensationalism": 10,
                "confidence": 0.8, "rationale_summary": "국회 심사 내용을 설명합니다.",
                "evidence": [{"article_version_id": "version-1", "start": 0, "end": 3,
                              "quote": "국회가", "rationale": "행위 주체를 명시합니다."}],
                "token_usage": 15,
            })

        provider = HttpLLMProvider(ProviderConfig(
            "openai-default", "gpt-5.6-luna", endpoint="https://api.openai.com/v1/responses",
            max_retries=0,
        ), transport=httpx.MockTransport(respond))
        db = _Database()
        services = {"analysis_providers": [provider], "llm_budget": MariaDBLLMBudget(_SessionFactory(db))}
        try:
            results = []
            for version in ("version-1", "version-2"):
                results.append(await handle({
                    "article_id": "article-1", "article_version_id": version,
                    "title": "국회 주거 법안 심사 진행", "text": content,
                }, HandlerContext(job_id=version, services=services)))
            assert len(calls) == 1
            replay = results[1].value["assessments"][0]
            assert replay["article_version_id"] == "version-2"
            assert replay["evidence"][0]["article_version_id"] == "version-2"
            assert replay["token_usage"] == 0
            assert next(iter(db.days.values()))["request_count"] == 1
        finally:
            provider.close()

    asyncio.run(scenario())


def test_article_handler_does_not_retry_possibly_billed_timeout() -> None:
    async def scenario() -> None:
        calls = []

        def fail(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            raise httpx.ReadTimeout("timeout", request=request)

        provider = HttpLLMProvider(ProviderConfig(
            "openai-default", "gpt-5.6-luna", endpoint="https://api.openai.com/v1/responses",
            max_retries=0,
        ), transport=httpx.MockTransport(fail))
        db = _Database()
        context = HandlerContext(services={
            "analysis_providers": [provider], "llm_budget": MariaDBLLMBudget(_SessionFactory(db)),
        })
        payload = {"article_id": "a", "article_version_id": "v", "title": "국회 법안 심사 진행",
                   "text": "국회가 법안을 심사했습니다. " * 30}
        try:
            with pytest.raises(HandlerError) as error:
                await handle(payload, context)
            assert error.value.retryable is False
            result = await handle(payload, context)
            assert result.value["skip_reason"] == "LLM_INPUT_ALREADY_SUBMITTED"
            assert len(calls) == 1
        finally:
            provider.close()

    asyncio.run(scenario())


def test_cache_identity_tracks_input_policy_not_bookkeeping() -> None:
    provider = HttpLLMProvider(ProviderConfig(
        "default", "gpt-5.6-luna", endpoint="https://api.openai.com/v1/responses",
    ), transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    article = AssessmentInput(article_version_id="v1", title="headline", content="exact content")
    try:
        key = provider.article_request_key(article, "p1")
        assert key == provider.article_request_key(article.model_copy(update={"article_version_id": "v2"}), "p1")
        for change in ({"title": "changed headline"}, {"content": "changed content"}):
            assert key != provider.article_request_key(article.model_copy(update=change), "p1")
        assert key != provider.article_request_key(article, "p2")
        rows = [{"article_id": "a", "article_version_id": "v1", "title": "a", "content": "aaa"},
                {"article_id": "b", "article_version_id": "v2", "title": "b", "content": "bbb"}]
        first = provider.comparison_request_key(rows, "p1")
        assert first == provider.comparison_request_key(list(reversed(rows)), "p1")
        assert first == provider.comparison_request_key([dict(row, article_version_id="changed") for row in rows], "p1")
        rows[0]["content"] = "actual change"
        assert first != provider.comparison_request_key(rows, "p1")
    finally:
        provider.close()


def test_headline_changes_version_without_reanalyzing_unchanged_legacy_input() -> None:
    body = "기사의 실제 본문입니다.".encode()
    legacy_hash = hashlib.sha256(body).digest()
    prior = [{"title": "Original", "normalized_payload": body, "content_hash": legacy_hash}]
    assert _article_input_hash("Original", body, prior) == legacy_hash
    changed = _article_input_hash("Corrected", body, prior)
    assert changed != legacy_hash
    assert changed == _article_input_hash("Corrected", body, [])
    current = [{"title": "Corrected", "normalized_payload": body, "content_hash": changed}]
    assert _article_input_hash("Corrected", body, current) == changed
    assert _article_input_hash("Corrected", body + b"added", current) != changed
