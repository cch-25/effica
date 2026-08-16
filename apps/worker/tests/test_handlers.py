from __future__ import annotations

import asyncio

from apps.api.app.domains.analysis import DeterministicStubProvider, ProviderConfig
from apps.worker.worker.handlers import build_default_registry
from apps.worker.worker.handlers.base import HandlerContext


def test_all_builtin_handlers_are_registered():
    registry = build_default_registry()
    assert set(registry.names()) == {
        "crawl",
        "cluster",
        "analyze",
        "aggregate_votes",
        "calculate_score",
        "recommend_weights",
        "simulate_weights",
        "render_share_card",
        "export_user",
        "delete_user",
        "merge_issue",
        "split_issue",
    }


def test_builtin_handlers_return_deterministic_values():
    async def scenario():
        registry = build_default_registry()
        analyze = registry.require("analyze")
        first = await analyze({"text": "official evidence and data"})
        second = await analyze({"text": "official evidence and data"})
        assert first.value == second.value

        crawl = registry.require("crawl")
        result = await crawl({"url": "HTTPS://Example.COM/article?b=2&a=1#fragment"})
        assert result.value["url"] == "https://example.com/article?a=1&b=2"

        simulate = registry.require("simulate_weights")
        simulation = await simulate({"weights": {"model": 1.0}, "windows": [7, 30]})
        assert simulation.value["windows"] == [7, 30]
        assert simulation.value["guardrail_result"]["passed"] is True

    asyncio.run(scenario())


def test_analysis_uses_one_dynamically_configured_openai_model():
    async def scenario():
        provider = DeterministicStubProvider(
            ProviderConfig(
                alias="openai-default",
                actual_model_id="gpt-5.6-luna",
                reasoning_effort="xhigh",
                model_alias_id="01K00000000000000000000401",
                endpoint="https://api.openai.com/v1/responses",
            )
        )

        async def factory():
            return provider

        analyze = build_default_registry().require("analyze")
        result = await analyze(
            {"text": "official evidence and data", "min_success_models": 3},
            HandlerContext(services={"analysis_provider_factory": factory}),
        )
        assert result.value["ensemble"]["required_model_count"] == 1
        assert result.value["ensemble"]["successful_model_count"] == 1
        assert len(result.value["assessments"]) == 1
        assessment = result.value["assessments"][0]
        assert assessment["actual_model_id"] == "gpt-5.6-luna"
        assert assessment["model_alias_id"] == "01K00000000000000000000401"
        assert assessment["provider"] == "openai"

    asyncio.run(scenario())
