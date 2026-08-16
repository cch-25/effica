from __future__ import annotations

import asyncio

from apps.worker.worker.handlers import build_default_registry


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
