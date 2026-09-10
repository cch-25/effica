from __future__ import annotations

import copy
import importlib
import io
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from apps.api.app.db.base import Base
from apps.worker.tests.test_llm_request_ledger import _Database, _SessionFactory
from apps.worker.worker.handlers.base import HandlerContext
from apps.worker.worker.handlers.registry import build_default_registry
from apps.worker.worker.issue_discovery import IssueDiscoveryError, IssueDiscoveryService
from apps.worker.worker.llm_budget import (
    DailyLLMBudgetExceeded,
    EssentialLLMBudgetReserved,
    LLMRequestSuppressed,
    MariaDBLLMBudget,
)
from apps.worker.worker.source_fetcher import SourceFetchService

NOW = datetime(2026, 9, 10, 3, tzinfo=UTC)
DAY = "2026-09-10"
URLS = [f"https://publisher-{number}.test/news/pension" for number in range(3)]
TOPIC = {
    "title": "연금 개편안 소득대체율 인상 논쟁",
    "summary": "연금 개편안을 두고 세대별 부담에 대한 논쟁이 이어졌다.",
    "topic": "정치", "issue_key": "pension-reform-2026",
    "controversy_reason": "노후 소득 보장과 미래 세대의 부담을 둘러싼 충돌",
    "is_controversial": True, "political_relevance": True, "priority": 95,
}


def _sources() -> list[dict[str, Any]]:
    return [{
        "source_id": f"publisher-{number}", "name": f"Publisher {number}",
        "home_url": f"https://publisher-{number}.test/",
        "policy_status": "APPROVED", "robots_status": "APPROVED",
        "terms_status": "APPROVED",
    } for number in range(3)]


def _html(*, published: datetime = NOW - timedelta(hours=2), body: str | None = None) -> str:
    content = body if body is not None else (
        "연금 개편안에 대해 여당은 노후 소득 보장 강화를 주장했다. "
        "야당은 미래 세대의 보험료 부담이 늘어난다며 재정 검증을 요구했다. " * 8
    )
    return (
        '<html><head><meta property="og:type" content="article">'
        f'<meta property="article:published_time" content="{published.isoformat()}">'
        f'<title>{TOPIC["title"]}</title></head><body><article><p>{content}</p>'
        '</article></body></html>'
    )


def _response(value: dict[str, Any], urls: list[str] | None = None) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    if urls is not None:
        output.append({
            "type": "web_search_call", "status": "completed",
            "action": {"type": "search", "sources": [{"url": url} for url in urls]},
        })
    output.append({"type": "message", "content": [{
        "type": "output_text", "text": json.dumps(value, ensure_ascii=False),
    }]})
    return {"status": "completed", "output": output, "usage": {"total_tokens": 150}}


class _Harness:
    def __init__(self) -> None:
        self.db = _Database()
        self.budget = MariaDBLLMBudget(_SessionFactory(self.db), clock=lambda: NOW)
        self.topics = [copy.deepcopy(TOPIC)]
        self.urls = URLS.copy()
        self.grounded = URLS.copy()
        self.selected = URLS.copy()
        self.additional = {}
        self.controversial = True
        self.status = 200
        self.search_evidence = True
        self.pages = dict.fromkeys(URLS, _html())
        self.paid_requests: list[dict[str, Any]] = []
        self.page_requests: list[str] = []
        self.service = IssueDiscoveryService(
            api_key="test-key", model="gpt-5.6-luna", budget=self.budget,
            transport=httpx.MockTransport(self.provider),
            source_fetcher=SourceFetchService(
                transport=httpx.MockTransport(self.publisher), max_retries=0,
                resolver=lambda _host, _port: ["93.184.216.34"],
            ),
        )

    def provider(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        self.paid_requests.append(payload)
        if self.status != 200:
            return httpx.Response(self.status)
        prompt = payload["input"]
        if '"topics"' in prompt:
            value = _response({"topics": self.topics}, URLS if self.search_evidence else None)
        elif '"urls"' in prompt:
            value = _response({"urls": self.urls}, self.grounded)
        else:
            value = _response({
                "is_controversial": self.controversial, "political_relevance": True,
                "summary": TOPIC["summary"], "controversy_reason": TOPIC["controversy_reason"],
                "article_ids": self.selected,
                "additional_context": self.additional,
            })
        return httpx.Response(200, json=value)

    def publisher(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.page_requests.append(url)
        return httpx.Response(200, text=self.pages.get(url, ""))

    async def discover(self, sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return await self.service.discover(DAY, _sources() if sources is None else sources, NOW)


async def test_two_search_stages_hydrate_three_publishers_and_replay_without_new_spend() -> None:
    fixture = _Harness()
    first = await fixture.discover()
    assert len(first["issues"]) == 1
    articles = first["issues"][0]["articles"]
    assert len({article["publisher_key"] for article in articles}) == 3
    assert all("여당은" in article["content"] for article in articles)
    assert fixture.page_requests == URLS
    assert len(fixture.paid_requests) == 3
    assert all(request["tool_choice"] == "required" for request in fixture.paid_requests[:2])
    assert all(request["max_tool_calls"] == 2 for request in fixture.paid_requests[:2])
    assert "tools" not in fixture.paid_requests[2]
    ledger = copy.deepcopy(fixture.db.days)
    assert await fixture.discover() == first
    assert fixture.db.days == ledger
    assert len(fixture.paid_requests) == 3
    assert {row["category"] for row in fixture.db.requests.values()} == {"discovery"}


async def test_changed_publisher_evidence_cannot_authorize_another_selection() -> None:
    fixture = _Harness()
    assert len((await fixture.discover())["issues"]) == 1
    fixture.pages[URLS[0]] = _html(body="변경된 연금 개편안 보도와 정책 논쟁. " * 30)
    result = await fixture.discover()
    assert result["issues"] == []
    assert result["rejected_issues"][0]["reason"] == "LLMRequestSuppressed"
    assert len(fixture.paid_requests) == 3


@pytest.mark.parametrize("status", [429, 500])
async def test_uncertain_provider_submission_is_never_retried(status: int) -> None:
    fixture = _Harness()
    fixture.status = status
    with pytest.raises(IssueDiscoveryError):
        await fixture.discover()
    with pytest.raises(LLMRequestSuppressed):
        await fixture.discover()
    assert len(fixture.paid_requests) == 1
    assert next(iter(fixture.db.requests.values()))["state"] == "SUBMITTED"


async def test_search_response_without_real_tool_evidence_fails_closed() -> None:
    fixture = _Harness()
    fixture.search_evidence = False
    with pytest.raises(IssueDiscoveryError, match="no completed web search"):
        await fixture.discover()
    assert fixture.page_requests == []


async def test_unapproved_and_ungrounded_urls_are_never_fetched() -> None:
    fixture = _Harness()
    unapproved = "https://unapproved.test/news/pension"
    invented = "https://publisher-0.test/news/invented"
    fixture.urls.extend([unapproved, invented])
    fixture.grounded.append(unapproved)
    result = await fixture.discover()
    assert len(result["issues"]) == 1
    assert fixture.page_requests == URLS
    assert result["rejected_sources"] == [{"url": unapproved, "reason": "PUBLISHER_NOT_APPROVED"}]


async def test_policy_denied_source_cannot_complete_three_publisher_quorum() -> None:
    fixture = _Harness()
    sources = _sources()
    sources[2]["terms_status"] = "DENIED"
    result = await fixture.discover(sources)
    assert result["issues"] == []
    assert result["blocked_reason"] == "INSUFFICIENT_APPROVED_PUBLISHERS"
    assert URLS[2] not in fixture.page_requests
    assert len(fixture.paid_requests) == 2


async def test_publisher_subdomains_cannot_inflate_independent_source_count() -> None:
    fixture = _Harness()
    duplicate = "https://mobile.publisher-0.test/news/pension"
    fixture.urls = URLS[:2] + [duplicate]
    fixture.grounded = fixture.urls.copy()
    fixture.pages[duplicate] = _html()
    result = await fixture.discover()
    assert result["issues"] == []
    assert result["rejected_issues"][0]["reason"] == "FEWER_THAN_THREE_PUBLISHERS"
    assert len(fixture.paid_requests) == 2


async def test_cross_publisher_canonical_page_cannot_borrow_source_approval() -> None:
    fixture = _Harness()
    fixture.pages[URLS[2]] = _html().replace(
        "</head>", '<link rel="canonical" href="https://unapproved.test/news/pension"></head>',
    )
    result = await fixture.discover()
    assert result["issues"] == []
    assert result["rejected_articles"] == [{"url": URLS[2], "reason": "IssueDiscoveryError"}]


@pytest.mark.parametrize("invalid", ["old", "future", "snippet"])
async def test_publication_window_and_fetched_body_are_mandatory(invalid: str) -> None:
    fixture = _Harness()
    if invalid == "old":
        fixture.pages[URLS[2]] = _html(published=NOW - timedelta(days=8))
    elif invalid == "future":
        fixture.pages[URLS[2]] = _html(published=NOW + timedelta(hours=1))
    else:
        fixture.pages[URLS[2]] = _html(body="").replace(
            "</head>", '<meta name="description" content="' + "기사 검색 요약. " * 50 + '"></head>',
        )
    result = await fixture.discover()
    assert result["issues"] == []
    assert len(result["rejected_articles"]) == 1
    assert len(fixture.paid_requests) == 2


@pytest.mark.parametrize("rejection", ["unrelated", "not_controversial"])
async def test_actual_article_relevance_check_cannot_be_bypassed(rejection: str) -> None:
    fixture = _Harness()
    if rejection == "unrelated":
        fixture.selected = URLS[:2]
    else:
        fixture.controversial = False
    result = await fixture.discover()
    assert result["issues"] == []
    assert len(fixture.paid_requests) == 3


async def test_nonpolitical_candidate_never_starts_article_search() -> None:
    fixture = _Harness()
    fixture.topics = [{**TOPIC, "topic": "스포츠"}, {**TOPIC, "political_relevance": False}]
    result = await fixture.discover()
    assert result["candidate_count"] == 0
    assert fixture.page_requests == []
    assert len(fixture.paid_requests) == 1


async def test_shared_cost_limit_stops_discovery_before_provider_submission() -> None:
    fixture = _Harness()
    fixture.budget.daily_budget_microusd = 1
    with pytest.raises(DailyLLMBudgetExceeded):
        await fixture.discover()
    assert fixture.paid_requests == []


@pytest.mark.parametrize("extra", [False, True])
async def test_three_to_five_articles_are_normal_and_extras_require_new_context(extra):
    fixture = _Harness()
    fixture.urls = [f"https://publisher-{i}.test/news/pension" for i in range(9)]
    fixture.grounded = fixture.urls.copy()
    fixture.selected = fixture.urls.copy()
    fixture.pages = dict.fromkeys(fixture.urls, _html())
    if extra:
        fixture.additional = {url: f"추가 쟁점 {i}: 해당 본문에서 앞선 기사에 없는 지역별 부담의 차이를 설명한다."
                              for i, url in enumerate(fixture.urls[5:])}
    sources = [{**_sources()[0], "source_id": f"publisher-{i}", "home_url": f"https://publisher-{i}.test/"}
               for i in range(9)]
    result = await fixture.discover(sources)
    assert len(result["issues"][0]["articles"]) == (8 if extra else 5)


async def test_discovery_stops_searching_after_filling_the_edition():
    fixture = _Harness()
    fixture.service.max_issues = 1
    fixture.topics.append({**TOPIC, "issue_key": "another-event"})
    result = await fixture.discover()
    assert result["stopped_reason"] == "EDITION_FULL"
    assert len(fixture.paid_requests) == 3


async def test_reserved_analysis_capacity_stops_more_search_without_losing_valid_issues():
    fixture = _Harness()
    fixture.topics.append({**TOPIC, "issue_key": "another-event"})
    original = fixture.budget.reserve
    source_searches = 0

    async def limited(**kwargs):
        nonlocal source_searches
        if kwargs["subject_key"].startswith("sources:"):
            source_searches += 1
            if source_searches > 1:
                assert kwargs["protected_cost_microusd"] > 0
                assert kwargs["protected_requests"] == 4
                raise EssentialLLMBudgetReserved()
        return await original(**kwargs)

    fixture.budget.reserve = limited
    result = await fixture.discover()
    assert len(result["issues"]) == 1
    assert result["stopped_reason"] == "ESSENTIAL_LLM_BUDGET_RESERVED"
    assert len(fixture.paid_requests) == 3


async def test_selection_reserves_estimated_article_analysis_before_paid_verification():
    fixture = _Harness()
    reservations = []
    original = fixture.budget.reserve

    async def capture(**kwargs):
        reservations.append(kwargs)
        return await original(**kwargs)

    fixture.budget.reserve = capture
    result = await fixture.discover()
    assert len(result["issues"]) == 1
    assert reservations[-1]["protected_cost_microusd"] > 0
    assert reservations[-1]["protected_requests"] == 4


async def test_discovery_handler_is_registered_and_receives_live_service_contract() -> None:
    fixture = _Harness()
    handler = build_default_registry().require_async("discover_issues")
    result = await handler({"run_date": DAY}, HandlerContext(now=NOW, services={
        "issue_discovery": fixture.service, "allowed_sources": _sources,
    }))
    assert len(result.value["issues"]) == 1
    assert result.metadata["pipeline"] == "daily_topic_first"


def test_budget_migration_uses_existing_constraint_name() -> None:
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="mariadb", opts={
        "as_sql": True, "output_buffer": output, "target_metadata": Base.metadata,
    })
    migration = importlib.import_module("db.alembic.versions.0022_issue_discovery_budget")
    with Operations.context(context):
        migration.upgrade()
    sql = output.getvalue()
    assert "DROP CONSTRAINT ck_llm_requests_valid_llm_category" in sql
    assert "ADD CONSTRAINT ck_llm_requests_valid_llm_category CHECK" in sql
    assert "ck_llm_requests_ck_" not in sql
    assert "'discovery'" in sql
