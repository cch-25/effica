from __future__ import annotations

import asyncio

import pytest

import apps.worker.worker.handlers.render_share_card as render_share_card_module
from apps.api.app.domains.analysis import DeterministicStubProvider, ProviderConfig
from apps.worker.worker.handlers import build_default_registry
from apps.worker.worker.handlers.base import HandlerContext, NonRetryableHandlerError


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
        analyze = registry.require_async("analyze")
        first = await analyze({"text": "official evidence and data"})
        second = await analyze({"text": "official evidence and data"})
        assert first.value == second.value
        assert first.value["prompt_version"] == "bias-sensationalism-v1"
        assert first.value["ensemble"]["y"] == 0
        assert first.value["ensemble"]["z"] == 0

        crawl = registry.require_async("crawl")
        result = await crawl({"url": "HTTPS://Example.COM/article?b=2&a=1#fragment"})
        assert result.value["url"] == "https://example.com/article?a=1&b=2"

        simulate = registry.require_async("simulate_weights")
        simulation = await simulate(
            {
                "base_weights": {"model": 1.0},
                "weights": {"model": 1.0},
                "windows": [7, 30],
            }
        )
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

        analyze = build_default_registry().require_async("analyze")
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


def test_render_share_card_marks_unmeasured_sensationalism_without_a_point(monkeypatch):
    draws = []
    original_draw = render_share_card_module.ImageDraw.Draw

    class DrawProxy:
        def __init__(self, delegate):
            self.delegate = delegate
            self.ellipses = 0

        def ellipse(self, *args, **kwargs):
            self.ellipses += 1
            return self.delegate.ellipse(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.delegate, name)

    def draw_factory(image, *args, **kwargs):
        proxy = DrawProxy(original_draw(image, *args, **kwargs))
        draws.append(proxy)
        return proxy

    monkeypatch.setattr(render_share_card_module.ImageDraw, "Draw", draw_factory)
    png = render_share_card_module._render_png(
        {
            "display_name": "Member",
            "snapshot": {
                "coordinate": {"x": 12, "sensationalism": None},
                "tier": "Explorer",
                "activity": 0,
            },
        }
    )

    assert png.startswith(b"\x89PNG")
    assert draws and draws[0].ellipses == 0


def test_aggregate_handler_preserves_vote_revision_contract() -> None:
    async def scenario():
        aggregate = build_default_registry().require_async("aggregate_votes")
        result = await aggregate(
            {"article_id": "article-1", "vote_revision": 7, "votes": []}
        )
        assert result.value["version"] == 7
        assert result.value["vote_revision"] == 7
        assert result.value["source_revision"] == 7

    asyncio.run(scenario())


def test_recommend_weights_uses_domain_base_and_ignores_snapshot_metadata() -> None:
    async def scenario() -> None:
        recommend = build_default_registry().require_async("recommend_weights")
        context = HandlerContext(
            services={
                "weights_lookup": {
                    "base-1": {"weights": {"model": 0.6, "crowd": 0.4, "version": "3"}},
                    "active": {"weights": {"model": 0.6, "crowd": 0.4}},
                },
                "recommendation_lookup": {
                    "rec-1": {
                        "recommendation_id": "rec-1",
                        "base_revision_id": "base-1",
                        "evidence_snapshot_id": "snap-1",
                        "evidence_snapshot": {
                            "window_days": 30,
                            "captured_at": "2026-01-01T00:00:00Z",
                            "deltas": {"model": 0.05, "crowd": -0.05},
                        },
                    }
                },
            }
        )
        result = await recommend({"recommendation_id": "rec-1"}, context)
        weights = result.value["weights"]
        assert set(weights) == {"model", "crowd"}
        assert "window_days" not in weights
        assert "captured_at" not in weights
        assert "version" not in weights
        assert result.value["recommendation_id"] == "rec-1"
        assert result.value["base_revision_id"] == "base-1"
        assert weights["model"] > 0.6

        with pytest.raises(NonRetryableHandlerError) as raised:
            await recommend(
                {
                    "metrics": {"window_days": 30, "captured_at": "2026-01-01T00:00:00Z"},
                }
            )
        assert raised.value.code == "INVALID_WEIGHT_PAYLOAD"

    asyncio.run(scenario())


def test_simulate_weights_compares_base_revision_to_proposed() -> None:
    async def scenario() -> None:
        simulate = build_default_registry().require_async("simulate_weights")
        same = await simulate(
            {
                "base_weights": {"model": 0.5, "crowd": 0.5},
                "weights": {"model": 0.5, "crowd": 0.5},
                "windows": [7, 30],
            }
        )
        shifted = await simulate(
            {
                "base_weights": {"model": 0.5, "crowd": 0.5},
                "weights": {"model": 0.55, "crowd": 0.45},
                "windows": [7, 30],
                "evidence": {"metrics": {"distribution_shift": 0.01}},
            }
        )
        assert shifted.value["base_weights"] == {"model": 0.5, "crowd": 0.5}
        assert shifted.value["weights"] == {"model": 0.55, "crowd": 0.45}
        assert (
            shifted.value["simulations"][0]["distribution_shift"]
            > same.value["simulations"][0]["distribution_shift"]
        )

        with pytest.raises(NonRetryableHandlerError) as raised:
            await simulate({"weights": {"model": 1.0}, "windows": [7, 30]})
        assert raised.value.code == "INVALID_SIMULATION_PAYLOAD"

    asyncio.run(scenario())


def test_cluster_empty_lookup_is_non_retryable() -> None:
    async def scenario() -> None:
        cluster = build_default_registry().require_async("cluster")
        with pytest.raises(NonRetryableHandlerError) as raised:
            await cluster(
                {
                    "article_ids": ["missing-1"],
                    "topic": "Should not become a synthetic article",
                }
            )
        assert raised.value.code == "INVALID_CLUSTER_PAYLOAD"

        context = HandlerContext(services={"articles_lookup": {}})
        with pytest.raises(NonRetryableHandlerError) as empty_lookup:
            await cluster({"article_ids": ["missing-1"], "topic": "Ignored"}, context)
        assert empty_lookup.value.code == "INVALID_CLUSTER_PAYLOAD"

    asyncio.run(scenario())


def test_aggregate_votes_uses_max_lookup_revision_when_payload_omits_version() -> None:
    async def scenario() -> None:
        aggregate = build_default_registry().require_async("aggregate_votes")
        votes = [
            {
                "vote_id": "v1",
                "user_id": "u1",
                "article_id": "article-1",
                "revision": 4,
                "x": 1,
                "y": 0,
                "z": 0,
                "sensationalism": 0,
                "quality_status": "QUALIFIED",
                "active": True,
            },
            {
                "vote_id": "v2",
                "user_id": "u2",
                "article_id": "article-1",
                "revision": 9,
                "x": 2,
                "y": 0,
                "z": 0,
                "sensationalism": 0,
                "quality_status": "QUALIFIED",
                "active": True,
            },
        ]
        result = await aggregate({"article_id": "article-1", "votes": votes})
        assert result.value["version"] == 9
        assert result.value["vote_revision"] == 9

        snapshot = await aggregate(
            {"article_id": "article-1", "votes": []},
            HandlerContext(services={"vote_snapshot_lookup": {"article-1": {"version": 3}}}),
        )
        assert snapshot.value["version"] == 4

        with pytest.raises(NonRetryableHandlerError) as raised:
            await aggregate({"article_id": "article-1", "votes": []})
        assert raised.value.code == "INVALID_VOTE_PAYLOAD"

    asyncio.run(scenario())


def test_crawl_identifier_only_is_live_when_fetcher_exists_and_lookup_omits_mode() -> None:
    async def scenario() -> None:
        crawl = build_default_registry().require_async("crawl")
        fetched: list[str] = []

        async def source_lookup(identifier):
            return {
                "source_id": str(identifier),
                "url": "https://example.test/feed",
                "source_type": "API",
            }

        async def source_fetcher(source):
            fetched.append(str(source.get("url")))
            return {
                "status_code": 200,
                "headers": {"content-type": "application/json"},
                "body": (
                    b'{"articles": [{"url": "https://example.test/a",'
                    b' "title": "Hello", "body": "text"}]}'
                ),
            }

        live = await crawl(
            {"source_id": "source-1"},
            HandlerContext(
                services={"source_lookup": source_lookup, "source_fetcher": source_fetcher}
            ),
        )
        assert fetched == ["https://example.test/feed"]
        assert live.value["mode"] == "live"
        assert live.value["stats"]["article_count"] == 1

        empty_fixture = await crawl(
            {"url": "https://example.test/x", "mode": "fixture"},
            HandlerContext(services={"source_fetcher": source_fetcher}),
        )
        assert empty_fixture.value["mode"] == "fixture"
        assert "articles" not in empty_fixture.value
        assert fetched == ["https://example.test/feed"]

    asyncio.run(scenario())
