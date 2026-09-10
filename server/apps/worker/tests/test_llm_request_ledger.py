from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from apps.worker.worker.llm_budget import (
    DailyLLMBudgetExceeded,
    LLMBudgetReservation,
    LLMRequestSuppressed,
    MariaDBLLMBudget,
)


class _Rows:
    def __init__(self, row: dict[str, Any] | None = None,
                 rows: list[dict[str, Any]] | None = None) -> None:
        self.row = row
        self.rows = rows or []

    def mappings(self) -> _Rows:
        return self

    def first(self) -> dict[str, Any] | None:
        return copy.deepcopy(self.row)

    def all(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.rows)


class _Database:
    def __init__(self) -> None:
        self.days: dict[Any, dict[str, Any]] = {}
        self.requests: dict[str, dict[str, Any]] = {}
        self.articles: dict[Any, set[str]] = {}
        self.lock = asyncio.Lock()
        self.fail_update = False
        self.collide_request = False

    def session(self) -> _Session:
        return _Session(self)


class _Session:
    def __init__(self, db: _Database) -> None:
        self.db = db

    def begin(self) -> _Session:
        return self

    async def __aenter__(self) -> _Session:
        await self.db.lock.acquire()
        self.snapshot = copy.deepcopy((self.db.days, self.db.requests, self.db.articles))
        return self

    async def __aexit__(self, error: Any, *_args: Any) -> None:
        if error is not None:
            self.db.days, self.db.requests, self.db.articles = self.snapshot
        self.db.lock.release()

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Rows:
        query = " ".join(str(statement).split())
        if query.startswith("INSERT INTO llm_daily_usage"):
            self.db.days.setdefault(params["usage_date"], dict(
                request_count=0, article_request_count=0,
                comparison_request_count=0, reserved_microusd=0, observed_tokens=0,
            ))
        elif query.startswith("SELECT request_count"):
            return _Rows(self.db.days[params["usage_date"]])
        elif query.startswith("SELECT usage_date"):
            return _Rows(self.db.requests.get(params["request_key"]))
        elif query.startswith("SELECT article_key"):
            return _Rows(rows=[{"article_key": key}
                               for key in self.db.articles.get(params["usage_date"], set())])
        elif query.startswith("INSERT INTO llm_daily_articles"):
            self.db.articles.setdefault(params["usage_date"], set()).add(params["article_key"])
        elif query.startswith("SELECT request_key"):
            return _Rows(next((row for row in self.db.requests.values() if (
                row["category"] == "article"
                and row["usage_date"] == params["usage_date"]
                and row["subject_key"] == params["subject_key"]
            )), None))
        elif query.startswith("INSERT INTO llm_requests"):
            if self.db.collide_request:
                raise IntegrityError(query, {}, Exception("duplicate request"))
            self.db.requests[params["request_key"]] = {
                **params, "state": "SUBMITTED", "response_json": None,
            }
        elif "SET request_count = request_count + 1" in query:
            if self.db.fail_update:
                raise RuntimeError("injected transaction failure")
            row = self.db.days[params["usage_date"]]
            row["request_count"] += 1
            row["article_request_count"] += params["article_delta"]
            row["comparison_request_count"] += params["comparison_delta"]
            row["reserved_microusd"] += params["reserved_microusd"]
        elif "SET state = 'SUCCEEDED'" in query:
            row = self.db.requests[params["request_key"]]
            if row["state"] == "SUBMITTED":
                row.update(state="SUCCEEDED", response_json=params["response_json"])
        elif "SET observed_tokens = observed_tokens" in query:
            self.db.days[params["usage_date"]]["observed_tokens"] += params["tokens"]
        else:
            raise AssertionError(f"unhandled ledger query: {query}")
        return _Rows()


class _SessionFactory:
    """Expose session lifetime separately from its transaction context."""

    def __init__(self, db: _Database) -> None:
        self.db = db

    def __call__(self) -> Any:
        session = _Session(self.db)

        class SessionLifetime:
            def begin(self) -> _Session:
                return session

            async def execute(self, *args: Any) -> _Rows:
                return await session.execute(*args)

            async def close(self) -> None:
                return None

        return SessionLifetime()


def test_discovery_cannot_spend_article_analysis_capacity_even_when_essential():
    async def scenario():
        db = _Database()
        budget = MariaDBLLMBudget(_SessionFactory(db))
        await budget.reserve(category="discovery", estimated_max_cost_microusd=1_900_000, essential=True)
        with pytest.raises(DailyLLMBudgetExceeded):
            await budget.reserve(category="discovery", estimated_max_cost_microusd=200_000, essential=True)
        await budget.reserve(category="article", estimated_max_cost_microusd=2_000_000, essential=True)
        await budget.reserve(category="comparison", estimated_max_cost_microusd=1_000_000)
        with pytest.raises(DailyLLMBudgetExceeded):
            await budget.reserve(category="article", estimated_max_cost_microusd=200_000, essential=True)
        assert next(iter(db.days.values()))["reserved_microusd"] == 4_900_000
    asyncio.run(scenario())


def test_discovery_respects_larger_pending_analysis_estimates_and_request_slots():
    async def scenario():
        db = _Database()
        budget = MariaDBLLMBudget(_SessionFactory(db))
        with pytest.raises(DailyLLMBudgetExceeded):
            await budget.reserve(category="discovery", estimated_max_cost_microusd=1_100_000,
                                 protected_cost_microusd=4_000_000)
        with pytest.raises(DailyLLMBudgetExceeded):
            await budget.reserve(category="discovery", estimated_max_cost_microusd=1,
                                 protected_requests=110)
        assert not db.requests
    asyncio.run(scenario())


def test_durable_request_replay_concurrency_and_restart() -> None:
    async def scenario() -> None:
        db = _Database()
        clock_value = datetime(2026, 9, 6, 12, tzinfo=UTC)

        def budget() -> MariaDBLLMBudget:
            return MariaDBLLMBudget(_SessionFactory(db), clock=lambda: clock_value)

        async def reserve() -> LLMBudgetReservation:
            return await budget().reserve(
                category="article", estimated_max_cost_microusd=20,
                request_key="same-prompt-body-model", subject_key="article-1",
            )

        results = await asyncio.gather(*(reserve() for _ in range(20)), return_exceptions=True)
        authorized = [r for r in results if isinstance(r, LLMBudgetReservation)]
        assert len(authorized) == 1
        assert sum(isinstance(r, LLMRequestSuppressed) for r in results) == 19
        reservation = authorized[0]
        day = reservation.usage_date
        assert db.days[day]["request_count"] == 1

        # A crash after a potentially billed submission cannot re-bill tomorrow.
        clock_value += timedelta(days=1)
        with pytest.raises(LLMRequestSuppressed):
            await reserve()
        assert len(db.days) == 1  # Suppressed transaction rolls back empty day.

        response = {"assessment": {"summary": "정부 정책"}, "tokens": 42}
        await budget().record_response(reservation, response)
        await budget().record_observed_tokens(reservation, 42)
        replay = await reserve()
        assert replay.cached_response == response
        assert replay.reserved_microusd == 0
        await budget().record_observed_tokens(replay, 42)
        assert db.days[day]["observed_tokens"] == 42
        assert sum(row["request_count"] for row in db.days.values()) == 1
        assert json.loads(db.requests[reservation.request_key]["response_json"]) == response

    asyncio.run(scenario())


def test_same_article_one_submission_per_kst_day_but_changed_input_next_day() -> None:
    async def scenario() -> None:
        db = _Database()
        now = datetime(2026, 9, 6, 14, 59, tzinfo=UTC)
        budget = MariaDBLLMBudget(_SessionFactory(db), clock=lambda: now)
        await budget.reserve(category="article", estimated_max_cost_microusd=10,
                             request_key="body-v1", subject_key="article-1")
        with pytest.raises(LLMRequestSuppressed, match="ARTICLE_ALREADY_ANALYZED_TODAY"):
            await budget.reserve(category="article", estimated_max_cost_microusd=10,
                                 request_key="body-v2", subject_key="article-1")
        assert len(db.requests) == 1
        now += timedelta(minutes=1)
        second = await budget.reserve(category="article", estimated_max_cost_microusd=10,
                                      request_key="body-v2", subject_key="article-1")
        assert second.usage_date.isoformat() == "2026-09-07"
        assert len(db.requests) == 2

    asyncio.run(scenario())


def test_exhaustion_does_not_poison_input_and_cached_response_bypasses_budget() -> None:
    async def scenario() -> None:
        db = _Database()
        budget = MariaDBLLMBudget(_SessionFactory(db), daily_request_limit=1,
                                 daily_comparison_limit=0)
        first = await budget.reserve(category="article", estimated_max_cost_microusd=10,
                                     request_key="body-1", subject_key="article-1")
        await budget.record_response(first, {"ok": True})
        with pytest.raises(DailyLLMBudgetExceeded):
            await budget.reserve(category="article", estimated_max_cost_microusd=10,
                                 request_key="body-2", subject_key="article-2")
        assert len(db.requests) == 1
        cached = await budget.reserve(category="article", estimated_max_cost_microusd=9_000_000,
                                      request_key="body-1", subject_key="article-1")
        assert cached.cached_response == {"ok": True}
        assert db.days[first.usage_date]["request_count"] == 1

    asyncio.run(scenario())


def test_failed_reservation_transaction_rolls_back_request_and_cost() -> None:
    async def scenario() -> None:
        db = _Database()
        budget = MariaDBLLMBudget(_SessionFactory(db))
        db.fail_update = True
        with pytest.raises(RuntimeError, match="injected"):
            await budget.reserve(category="article", estimated_max_cost_microusd=10,
                                 request_key="body", subject_key="article")
        assert not db.requests
        assert not db.days
        assert not db.articles
        db.fail_update = False
        reserved = await budget.reserve(category="article", estimated_max_cost_microusd=10,
                                        request_key="body", subject_key="article")
        assert reserved.cached_response is None

    asyncio.run(scenario())


def test_absolute_caps_cannot_be_relaxed_by_configuration() -> None:
    budget = MariaDBLLMBudget(lambda: None, daily_budget_usd=500,
                             daily_request_limit=1000, daily_article_limit=1000,
                             daily_comparison_limit=1000)
    assert budget.daily_budget_microusd == 5_000_000
    assert budget.daily_request_limit == 110
    assert budget.daily_article_limit == 100
    assert budget.daily_comparison_limit == 10


def test_unique_collision_across_daily_locks_fails_closed_without_reservation() -> None:
    async def scenario() -> None:
        db = _Database()
        db.collide_request = True
        budget = MariaDBLLMBudget(_SessionFactory(db))
        with pytest.raises(LLMRequestSuppressed, match="LLM_INPUT_ALREADY_SUBMITTED"):
            await budget.reserve(category="article", estimated_max_cost_microusd=10,
                                 request_key="raced-at-midnight", subject_key="article")
        assert not db.days
        assert not db.requests

    asyncio.run(scenario())


def test_article_cap_does_not_consume_comparison_capacity() -> None:
    async def scenario() -> None:
        db = _Database()
        budget = MariaDBLLMBudget(_SessionFactory(db), daily_article_limit=1)
        await budget.reserve(category="article", estimated_max_cost_microusd=10,
                             request_key="article1", subject_key="1")
        with pytest.raises(DailyLLMBudgetExceeded):
            await budget.reserve(category="article", estimated_max_cost_microusd=10,
                                 request_key="article2", subject_key="2")
        await budget.reserve(category="comparison", estimated_max_cost_microusd=10,
                             request_key="comparison1", subject_key="issue1", article_keys=["1"])
        assert len(db.requests) == 2

    asyncio.run(scenario())


def test_comparisons_and_analysis_share_distinct_article_cohort() -> None:
    async def scenario() -> None:
        db = _Database()
        now = datetime(2026, 9, 6, 14, 59, tzinfo=UTC)
        budget = MariaDBLLMBudget(_SessionFactory(db), daily_article_limit=3, clock=lambda: now)
        first = await budget.reserve(
            category="comparison", estimated_max_cost_microusd=10,
            request_key="compare12", article_keys=["1", "2", "2"],
        )
        await budget.record_response(first, {"cached": True})
        await budget.reserve(category="article", estimated_max_cost_microusd=10,
                             request_key="analyze3", subject_key="3", article_keys=["3"])
        await budget.reserve(category="article", estimated_max_cost_microusd=10,
                             request_key="analyze1", subject_key="1", article_keys=["1"])
        with pytest.raises(DailyLLMBudgetExceeded, match="distinct article"):
            await budget.reserve(category="comparison", estimated_max_cost_microusd=10,
                                 request_key="compare34", article_keys=["3", "4"])
        with pytest.raises(DailyLLMBudgetExceeded, match="distinct article"):
            await budget.reserve(category="article", estimated_max_cost_microusd=10,
                                 request_key="analyze4", subject_key="4", article_keys=["4"])
        assert db.articles[first.usage_date] == {"1", "2", "3"}
        assert len(db.requests) == 3
        assert db.days[first.usage_date]["reserved_microusd"] == 30
        now += timedelta(minutes=1)
        cached = await budget.reserve(category="comparison", estimated_max_cost_microusd=10,
                                      request_key="compare12", article_keys=["1", "2"])
        assert cached.cached_response == {"cached": True}
        assert first.usage_date + timedelta(days=1) not in db.articles
        assert len(db.articles) == 1
        fresh = await budget.reserve(category="comparison", estimated_max_cost_microusd=10,
                                     request_key="compare34", article_keys=["3", "4"])
        assert fresh.usage_date != first.usage_date
        assert db.articles[fresh.usage_date] == {"3", "4"}

    asyncio.run(scenario())


def test_concurrent_mixed_requests_cannot_exceed_article_cohort() -> None:
    async def scenario() -> None:
        db = _Database()
        budget = MariaDBLLMBudget(_SessionFactory(db), daily_article_limit=3)

        async def reserve(index: int) -> LLMBudgetReservation:
            return await budget.reserve(
                category="comparison" if index % 2 else "article",
                estimated_max_cost_microusd=10, request_key=f"request-{index}",
                subject_key=f"article-{index}", article_keys=[f"article-{index}"],
            )

        results = await asyncio.gather(*(reserve(i) for i in range(20)), return_exceptions=True)
        assert sum(isinstance(value, LLMBudgetReservation) for value in results) == 3
        assert sum(isinstance(value, DailyLLMBudgetExceeded) for value in results) == 17
        assert len(next(iter(db.articles.values()))) == 3
        assert next(iter(db.days.values()))["request_count"] == 3

    asyncio.run(scenario())
