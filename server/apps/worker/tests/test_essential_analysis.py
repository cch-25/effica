from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from apps.worker.tests.test_llm_request_ledger import _Database, _SessionFactory
from apps.worker.worker.comparison_cohort import select_comparison_cohort
from apps.worker.worker.llm_budget import (
    DailyLLMBudgetExceeded,
    EssentialLLMBudgetReserved,
    MariaDBLLMBudget,
)
from apps.worker.worker.queue import Job
from apps.worker.worker.services import MariaDBResultApplier


def test_comparison_keeps_distinct_real_sources_despite_extra_members_and_index_page():
    def article(identifier, source, title="정부의 새 정책 발표", content="기사 본문입니다. " * 100):
        return {"article_id": identifier, "article_version_id": f"v-{identifier}",
                "source_id": source, "source_url": f"https://{source}.co.kr/story/{identifier}",
                "title": title, "content": content}

    rows = [article("index", "government", "정보공개 홈"),
            article("a", "news-a"), article("b", "news-a"),
            article("c", "news-b"), article("d", "news-b")]
    cohort = select_comparison_cohort(rows)
    assert cohort == []
    assert select_comparison_cohort(list(reversed(rows))) == cohort
    assert select_comparison_cohort(rows[:3]) == []
    diverse = rows + [article("e", "news-c"), article("f", "news-d")]
    assert [row["article_id"] for row in select_comparison_cohort(diverse)] == ["a", "c", "e"]
    assert select_comparison_cohort(list(reversed(diverse))) == select_comparison_cohort(diverse)
    forged = [article("a", "one"), article("b", "two"), article("c", "three")]
    for row in forged:
        row["source_url"] = f"https://{row['source_id']}.same-publisher.co.kr/story"
    assert select_comparison_cohort(forged) == []


def test_general_feed_cannot_spend_event_cohort_and_comparison_capacity():
    async def scenario():
        db = _Database()
        budget = MariaDBLLMBudget(_SessionFactory(db))
        for index in range(91):
            await budget.reserve(
                category="article", request_key=f"feed-{index}",
                subject_key=f"feed-{index}", estimated_max_cost_microusd=10,
            )
        with pytest.raises(EssentialLLMBudgetReserved):
            await budget.reserve(
                category="article", request_key="overflow", subject_key="overflow",
                estimated_max_cost_microusd=10,
            )
        # Rejected work has no submission record and can be admitted later.
        assert len(db.requests) == 91
        for index in range(9):
            await budget.reserve(
                category="article", essential=True, request_key=f"event-{index}",
                subject_key=f"event-{index}", estimated_max_cost_microusd=10,
            )
        for issue in range(3):
            await budget.reserve(
                category="comparison", request_key=f"comparison-{issue}",
                article_keys=[f"event-{index}" for index in range(issue * 3, issue * 3 + 3)],
                estimated_max_cost_microusd=10,
            )
        row = next(iter(db.days.values()))
        assert row["article_request_count"] == 100
        assert row["comparison_request_count"] == 3
        assert len(next(iter(db.articles.values()))) == 100
        with pytest.raises(DailyLLMBudgetExceeded):
            await budget.reserve(
                category="article", essential=True, request_key="extra-event",
                subject_key="extra-event", estimated_max_cost_microusd=10,
            )

    asyncio.run(scenario())


def test_essential_cost_reserve_is_inside_hard_budget_and_cache_remains_free():
    async def scenario():
        db = _Database()
        budget = MariaDBLLMBudget(_SessionFactory(db), daily_budget_usd="0.000100")
        first = await budget.reserve(
            category="article", request_key="feed", estimated_max_cost_microusd=80,
        )
        await budget.record_response(first, {"saved": True})
        with pytest.raises(EssentialLLMBudgetReserved):
            await budget.reserve(category="article", estimated_max_cost_microusd=1)
        await budget.reserve(category="article", essential=True, estimated_max_cost_microusd=20)
        with pytest.raises(DailyLLMBudgetExceeded):
            await budget.reserve(category="comparison", estimated_max_cost_microusd=1)
        cached = await budget.reserve(
            category="article", request_key="feed", estimated_max_cost_microusd=80,
        )
        assert cached.cached_response == {"saved": True}
        assert next(iter(db.days.values()))["reserved_microusd"] == 100

    asyncio.run(scenario())


@pytest.mark.parametrize("job_type,payload", [
    ("analyze", {"article_version_id": "v1"}),
    ("build_issue_comparison", {"issue_id": "i1", "issue_version": 1,
                                "article_version_ids": ["v1", "v2"],
                                "prompt_version": "issue-comparison-v1"}),
])
def test_budget_deferral_resumes_at_kst_midnight_and_expires(job_type, payload):
    class Session:
        def __init__(self):
            self.jobs = {}

        async def execute(self, query, params):
            if "INSERT INTO jobs" in str(query):
                self.jobs.setdefault(params["dedupe_key"], params)
            return []

    async def scenario():
        now = datetime(2026, 9, 7, 14, 59, tzinfo=UTC)
        session = Session()
        applier = MariaDBResultApplier(lambda: None)
        job = Job(id="job", job_type=job_type, payload=payload, priority=7)
        skipped = {"status": "SKIPPED", "skip_reason": "DAILY_LLM_BUDGET_EXCEEDED"}
        await applier._apply_domain(session, job, skipped, now)
        await applier._apply_domain(session, job, skipped, now)
        assert len(session.jobs) == 1
        deferred = next(iter(session.jobs.values()))
        assert deferred["available_at"] == datetime(2026, 9, 7, 15, tzinfo=UTC)
        assert deferred["priority"] == 7
        assert json.loads(deferred["payload_json"])["budget_defer_reason"] == (
            "DAILY_LLM_BUDGET_EXCEEDED"
        )
        job.payload = json.loads(deferred["payload_json"])
        await applier._apply_domain(session, job, skipped, now + timedelta(days=1))
        assert len(session.jobs) == 2
        deadlines = {json.loads(row["payload_json"])["budget_defer_deadline"]
                     for row in session.jobs.values()}
        assert len(deadlines) == 1
        await applier._apply_domain(session, job, skipped, now + timedelta(days=4))
        assert len(session.jobs) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("reason", ["LLM_INPUT_ALREADY_SUBMITTED", "TITLE_TOO_SHORT"])
def test_paid_or_invalid_inputs_are_never_budget_requeued(reason):
    class NoWrites:
        async def execute(self, *_args):
            raise AssertionError("a skipped input must not create another job")

    asyncio.run(MariaDBResultApplier(lambda: None)._apply_domain(
        NoWrites(), Job(id="job", job_type="analyze", payload={"article_version_id": "v1"}),
        {"status": "SKIPPED", "skip_reason": reason}, datetime.now(UTC),
    ))


def test_event_membership_recovers_old_budget_skip_without_duplicating_pending_analysis():
    class Session:
        def __init__(self):
            self.pending = {"future-budget-retry"}
            self.created = []

        async def execute(self, query, params):
            if "SELECT ma.id" in str(query):
                if params["version_id"] == "stored-analysis":
                    return [{"id": "existing"}]
                return []
            if "FROM jobs" in str(query) and params["version_id"] in self.pending:
                return [{
                    "id": "existing",
                    "status": "PENDING",
                    "available_at": datetime(2026, 9, 7, 15, tzinfo=UTC),
                    "budget_defer_reason": None,
                }]
            if "INSERT INTO jobs" in str(query):
                self.created.append(params)
                self.pending.add(json.loads(params["payload_json"])["article_version_id"])
            return []

    async def scenario():
        session = Session()
        applier = MariaDBResultApplier(lambda: None)
        versions = [{"article_version_id": key} for key in (
            "previously-skipped", "stored-analysis", "future-budget-retry",
        )]
        now = datetime(2026, 9, 7, 15, tzinfo=UTC)
        await applier._ensure_event_article_analyses(session, versions, now)
        await applier._ensure_event_article_analyses(session, versions, now)
        assert len(session.created) == 1
        assert session.created[0]["dedupe_key"] == "article-version:previously-skipped:essential:2026-09-08"

    asyncio.run(scenario())


def test_event_membership_wakes_only_capacity_reserved_deferral():
    now = datetime(2026, 9, 10, 7, tzinfo=UTC)
    later = now + timedelta(hours=8)

    class Session:
        def __init__(self):
            self.updated = []
            self.jobs = {
                "reserved": {
                    "id": "reserved-job",
                    "status": "PENDING",
                    "available_at": later,
                    "budget_defer_reason": "ESSENTIAL_LLM_BUDGET_RESERVED",
                },
                "hard-cap": {
                    "id": "hard-cap-job",
                    "status": "PENDING",
                    "available_at": later,
                    "budget_defer_reason": "DAILY_LLM_BUDGET_EXCEEDED",
                },
                "leased": {
                    "id": "leased-job",
                    "status": "LEASED",
                    "available_at": later,
                    "budget_defer_reason": "ESSENTIAL_LLM_BUDGET_RESERVED",
                },
                "ready": {
                    "id": "ready-job",
                    "status": "PENDING",
                    "available_at": now,
                    "budget_defer_reason": "ESSENTIAL_LLM_BUDGET_RESERVED",
                },
            }

        async def execute(self, query, params):
            statement = str(query)
            if "SELECT ma.id" in statement:
                return []
            if "FROM jobs" in statement:
                return [self.jobs[params["version_id"]]]
            if "UPDATE jobs" in statement:
                self.updated.append(dict(params))
                return []
            if "INSERT INTO jobs" in statement:
                raise AssertionError("active analysis must not be duplicated")
            return []

    async def scenario():
        session = Session()
        applier = MariaDBResultApplier(lambda: None)
        rows = [{"article_version_id": version_id} for version_id in session.jobs]
        await applier._ensure_event_article_analyses(session, rows, now)
        assert session.updated == [{"job_id": "reserved-job", "now": now}]

    asyncio.run(scenario())
