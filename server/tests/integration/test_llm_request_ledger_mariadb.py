"""Real MariaDB locking tests using only isolated, test-owned tables.

Run explicitly with RUN_MARIADB_INTEGRATION=1 .ops/run.sh integration
tests/integration/test_llm_request_ledger_mariadb.py. No provider is constructed.
Existing application tables and their data are never read or modified.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.models import LLMDailyArticle, LLMDailyUsage, LLMRequest
from apps.worker.worker.llm_budget import (
    DailyLLMBudgetExceeded,
    LLMBudgetReservation,
    LLMRequestSuppressed,
    MariaDBLLMBudget,
)

DATABASE_URL = os.environ.get("CI_MARIADB_URL")
pytestmark = [
    pytest.mark.mariadb,
    pytest.mark.skipif(not DATABASE_URL, reason="CI_MARIADB_URL is not configured"),
]


@pytest.mark.asyncio
async def test_mariadb_paid_input_at_most_once_and_cached_replay() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    names = {
        "llm_daily_usage": f"ci_llm_daily_{suffix}",
        "llm_requests": f"ci_llm_requests_{suffix}",
        "llm_daily_articles": f"ci_llm_articles_{suffix}",
    }
    metadata = MetaData()
    LLMDailyUsage.__table__.to_metadata(metadata, name=names["llm_daily_usage"])
    LLMRequest.__table__.to_metadata(metadata, name=names["llm_requests"])
    LLMDailyArticle.__table__.to_metadata(metadata, name=names["llm_daily_articles"])

    class IsolatedSession:
        def __init__(self) -> None:
            self.session = factory()

        def begin(self) -> Any:
            return self.session.begin()

        async def execute(self, statement: Any, params: dict[str, Any]) -> Any:
            query = str(statement)
            for original, isolated in names.items():
                query = query.replace(original, isolated)
            return await self.session.execute(text(query), params)

        async def close(self) -> None:
            await self.session.close()

    now = datetime(2026, 9, 6, 14, 59, tzinfo=UTC)

    def new_budget(**kwargs: Any) -> MariaDBLLMBudget:
        return MariaDBLLMBudget(IsolatedSession, clock=lambda: now, **kwargs)

    async def reserve(key: str = "same-input", subject: str = "article-1") -> Any:
        return await new_budget().reserve(
            category="article", estimated_max_cost_microusd=100,
            request_key=key, subject_key=subject,
        )

    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)

        # Independent connections and budget objects model parallel workers.
        concurrent = await asyncio.gather(*(reserve() for _ in range(20)),
                                          return_exceptions=True)
        authorized = [r for r in concurrent if isinstance(r, LLMBudgetReservation)]
        assert len(authorized) == 1, concurrent
        assert sum(isinstance(r, LLMRequestSuppressed) for r in concurrent) == 19, concurrent
        original = authorized[0]
        with pytest.raises(LLMRequestSuppressed, match="ARTICLE_ALREADY_ANALYZED_TODAY"):
            await reserve("changed-body")

        # A different service instance tomorrow must not retry uncertain billing.
        now += timedelta(minutes=1)
        with pytest.raises(LLMRequestSuppressed, match="LLM_INPUT_ALREADY_SUBMITTED"):
            await reserve()
        await new_budget().record_response(original, {"summary": "국회 정책", "ok": True})
        await new_budget().record_observed_tokens(original, 234)
        cached = await reserve()
        assert cached.cached_response == {"summary": "국회 정책", "ok": True}
        assert cached.reserved_microusd == 0
        await new_budget().record_observed_tokens(cached, 234)
        changed = await reserve("changed-body")
        assert changed.usage_date != original.usage_date

        # Exhaustion must not persist a request identity and poison later work.
        with pytest.raises(DailyLLMBudgetExceeded):
            await new_budget(daily_request_limit=1, daily_comparison_limit=0).reserve(
                category="article", estimated_max_cost_microusd=100,
                request_key="not-poisoned", subject_key="article-2",
            )
        await reserve("not-poisoned", "article-2")

        async with engine.connect() as connection:
            totals = (await connection.execute(text(
                f"SELECT SUM(request_count), SUM(article_request_count), "
                f"SUM(reserved_microusd), SUM(observed_tokens) "
                f"FROM `{names['llm_daily_usage']}`"
            ))).one()
            count = await connection.scalar(text(
                f"SELECT COUNT(*) FROM `{names['llm_requests']}`"
            ))
        assert tuple(int(value) for value in totals) == (3, 3, 300, 234)
        assert count == 3

        # Workers straddling KST midnight lock different daily rows. The global
        # request PK still permits at most one committed authorization. InnoDB
        # may choose a deadlock victim; that transaction cannot reach a provider.
        async def reserve_at(day: int) -> Any:
            budget = MariaDBLLMBudget(
                IsolatedSession,
                clock=lambda: datetime(2026, 9, day, tzinfo=UTC),
            )
            return await budget.reserve(
                category="article", estimated_max_cost_microusd=100,
                request_key="midnight-input", subject_key="midnight-article",
            )

        midnight = await asyncio.gather(reserve_at(8), reserve_at(9), return_exceptions=True)
        assert sum(isinstance(r, LLMBudgetReservation) for r in midnight) == 1, midnight
        errors = [r for r in midnight if isinstance(r, BaseException)]
        assert len(errors) == 1
        assert isinstance(errors[0], (LLMRequestSuppressed, OperationalError))
        if isinstance(errors[0], OperationalError):
            assert errors[0].orig.args[0] == 1213  # InnoDB deadlock victim only.
        with pytest.raises(LLMRequestSuppressed):
            await reserve_at(10)
        async with engine.connect() as connection:
            counts = await connection.scalar(text(
                f"SELECT SUM(request_count) FROM `{names['llm_daily_usage']}`"
            ))
        assert counts == 4

        # A single locked daily cohort covers both article and comparison text.
        now = datetime(2026, 9, 11, tzinfo=UTC)
        async def reserve_cohort(index: int) -> Any:
            return await new_budget(daily_article_limit=3).reserve(
                category="comparison" if index % 2 else "article",
                estimated_max_cost_microusd=100,
                request_key=f"cohort-{index}", subject_key=f"cohort-article-{index}",
                article_keys=[f"cohort-article-{index}"],
            )

        cohort = await asyncio.gather(*(reserve_cohort(i) for i in range(12)),
                                      return_exceptions=True)
        assert sum(isinstance(r, LLMBudgetReservation) for r in cohort) == 3, cohort
        assert sum(isinstance(r, DailyLLMBudgetExceeded) for r in cohort) == 9, cohort
        async with engine.connect() as connection:
            cohort_count = await connection.scalar(text(
                f"SELECT COUNT(*) FROM `{names['llm_daily_articles']}` "
                "WHERE usage_date = :day"
            ), {"day": now.date()})
            daily = (await connection.execute(text(
                f"SELECT request_count, reserved_microusd FROM `{names['llm_daily_usage']}` "
                "WHERE usage_date = :day"
            ), {"day": now.date()})).one()
        assert cohort_count == 3
        assert tuple(int(value) for value in daily) == (3, 300)
    finally:
        # Names are generated internally for exactly these three test tables.
        async with engine.begin() as connection:
            await connection.run_sync(metadata.drop_all)
        await engine.dispose()
