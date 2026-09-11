from __future__ import annotations

import copy
import json

import httpx
import pytest

from apps.api.app.core.config import Settings
from apps.worker.tests.test_issue_discovery import URLS, _Harness, _html
from apps.worker.worker.llm_budget import EssentialLLMBudgetReserved


def _sparse_fixture(*, status: int = 200, results=None):
    fixture = _Harness()
    fixture.urls = URLS[:2]
    fixture.topics[0]["seed_urls"] = URLS[:2]
    requests = []

    def search(request):
        requests.append(json.loads(request.content))
        return httpx.Response(status, json={"results": results if results is not None else [
            {"url": URLS[0]}, {"url": URLS[2], "content": "Untrusted search snippet"},
            {"url": "https://unapproved.test/news/pension"},
        ]})

    fixture.service.tavily_api_key = "test-tavily-key"
    fixture.service.tavily_transport = httpx.MockTransport(search)
    return fixture, requests


async def test_sparse_success_uses_tavily_and_real_publisher_bodies_then_replays_without_spend():
    fixture, requests = _sparse_fixture()
    reservations = []
    reserve = fixture.budget.reserve

    async def capture(**kwargs):
        reservations.append(kwargs)
        return await reserve(**kwargs)

    fixture.budget.reserve = capture
    first = await fixture.discover()
    assert len(first["issues"]) == 1
    assert len({a["publisher_key"] for a in first["issues"][0]["articles"]}) == 3
    assert fixture.page_requests == URLS
    assert all("Untrusted search snippet" not in a["content"] for a in first["issues"][0]["articles"])
    assert requests[0]["topic"] == "news"
    assert requests[0]["search_depth"] == "advanced"
    assert requests[0]["auto_parameters"] is False
    assert requests[0]["include_domains_mode"] == "filter"
    assert requests[0]["include_domains"] == [f"publisher-{i}.test" for i in range(3)]
    assert requests[0]["start_date"] == "2026-09-03"
    assert requests[0]["end_date"] == "2026-09-11"
    assert requests[0]["max_results"] == 15
    assert len(fixture.paid_requests) == 3
    tavily = [r for r in fixture.db.requests.values() if r["subject_key"].startswith("tavily-sources:")]
    assert len(tavily) == 1
    assert next(r for r in reservations if r["subject_key"].startswith("tavily-sources:"))["estimated_max_cost_microusd"] == 16_000
    ledger = copy.deepcopy(fixture.db.days)
    assert await fixture.discover() == first
    assert len(requests) == 1
    assert len(fixture.paid_requests) == 3
    assert fixture.db.days == ledger


async def test_existing_three_publisher_coverage_does_not_call_tavily():
    fixture, requests = _sparse_fixture()
    fixture.urls = URLS.copy()
    assert len((await fixture.discover())["issues"]) == 1
    assert requests == []


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_failed_tavily_submission_is_not_retried_or_replaced_by_another_paid_search(status):
    fixture, requests = _sparse_fixture(status=status)
    first = await fixture.discover()
    assert not first["issues"]
    assert first["rejected_issues"][0]["reason"] == "IssueDiscoveryError"
    second = await fixture.discover()
    assert not second["issues"]
    assert second["rejected_issues"][0]["reason"] == "LLMRequestSuppressed"
    assert len(requests) == 1
    assert len(fixture.paid_requests) == 2


async def test_uncertain_primary_search_does_not_trigger_tavily():
    fixture, requests = _sparse_fixture()
    fixture.status = 500
    with pytest.raises(RuntimeError):
        await fixture.discover()
    assert not requests


async def test_tavily_respects_shared_budget_before_network_call():
    fixture, requests = _sparse_fixture()
    original = fixture.budget.reserve

    async def exhausted(**kwargs):
        if kwargs["subject_key"].startswith("tavily-sources:"):
            raise EssentialLLMBudgetReserved()
        return await original(**kwargs)

    fixture.budget.reserve = exhausted
    result = await fixture.discover()
    assert not result["issues"]
    assert result["stopped_reason"] == "ESSENTIAL_LLM_BUDGET_RESERVED"
    assert not requests


async def test_tavily_snippet_does_not_replace_missing_publisher_body():
    fixture, requests = _sparse_fixture(results=[{"url": URLS[2], "content": "연금 개편 쟁점 " * 200}])
    fixture.pages[URLS[2]] = _html(body="")
    result = await fixture.discover()
    assert not result["issues"]
    assert len(requests) == 1
    assert len(fixture.paid_requests) == 2
    assert result["rejected_issues"][0]["reason"] == "FEWER_THAN_THREE_PUBLISHERS"


async def test_supplement_does_not_bypass_same_event_selection():
    fixture, requests = _sparse_fixture()
    fixture.selected = URLS[:2]
    result = await fixture.discover()
    assert len(requests) == 1
    assert not result["issues"]


def test_tavily_setting_reads_root_style_env_without_repr_exposure(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TAVILY_API_KEY=test-tavily-configuration\n")
    settings = Settings(_env_file=env)
    assert settings.tavily_api_key == "test-tavily-configuration"
    assert "test-tavily-configuration" not in repr(settings)


def test_worker_connects_tavily_to_the_shared_budget(monkeypatch):
    from apps.api.app.core import config
    from apps.worker.worker.main import _default_services

    settings = Settings(_env_file=None, app_env="test", app_backend="memory",
                        openai_api_key="test-openai", tavily_api_key="test-tavily")
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    services = _default_services(lambda: None)
    discovery = services["issue_discovery"]
    assert discovery.tavily_api_key == "test-tavily"
    assert discovery.budget is services["llm_budget"]
    assert discovery.source_fetcher is services["source_fetcher"]
    assert discovery.budget.daily_budget_microusd == 5_000_000
