"""Durable, concurrency-safe daily authorization for paid LLM requests."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

SEOUL = ZoneInfo("Asia/Seoul")


class DailyLLMBudgetExceeded(RuntimeError):
    """Raised before a paid request when its daily authorization is unavailable."""

    code = "DAILY_LLM_BUDGET_EXCEEDED"


class EssentialLLMBudgetReserved(DailyLLMBudgetExceeded):
    """Ordinary feed work cannot consume the capacity protected for events."""

    code = "ESSENTIAL_LLM_BUDGET_RESERVED"


class LLMRequestSuppressed(RuntimeError):
    """A previously authorized input must not cause another paid submission."""

    def __init__(self, reason: str = "LLM_INPUT_ALREADY_SUBMITTED") -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class LLMBudgetReservation:
    usage_date: date
    category: str
    reserved_microusd: int
    request_key: str | None = None
    cached_response: dict[str, Any] | None = None


def usd_to_microusd(value: Decimal | str | float | int) -> int:
    amount = Decimal(str(value))
    if amount < 0:
        raise ValueError("daily LLM budget cannot be negative")
    return int((amount * Decimal(1_000_000)).to_integral_value(rounding=ROUND_DOWN))


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@asynccontextmanager
async def _session_scope(factory: Callable[[], Any]) -> AsyncIterator[Any]:
    session = await _maybe_await(factory())
    if hasattr(session, "__aenter__"):
        async with session as entered:
            yield entered
        return
    try:
        yield session
    finally:
        close = getattr(session, "close", None)
        if close is not None:
            await _maybe_await(close())


@asynccontextmanager
async def _transaction(session: Any) -> AsyncIterator[Any]:
    context = session.begin()
    if not hasattr(context, "__aenter__"):
        context = await _maybe_await(context)
    if hasattr(context, "__aenter__"):
        async with context:
            yield session
        return
    try:
        yield session
    except BaseException:
        rollback = getattr(session, "rollback", None)
        if rollback is not None:
            await _maybe_await(rollback())
        raise
    else:
        commit = getattr(session, "commit", None)
        if commit is not None:
            await _maybe_await(commit())


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, default)


class MariaDBLLMBudget:
    """Reserve worst-case request cost under one locked KST daily ledger row.

    Reservations are never released. If a worker dies after authorization, the
    request may still have reached OpenAI, so retaining the reservation is the
    only fail-closed accounting behavior.
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        daily_budget_usd: Decimal | str | float | int = Decimal("5.00"),
        daily_request_limit: int = 110,
        daily_article_limit: int = 100,
        daily_comparison_limit: int = 10,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.daily_budget_microusd = min(5_000_000, usd_to_microusd(daily_budget_usd))
        self.daily_request_limit = min(110, int(daily_request_limit))
        self.daily_article_limit = min(100, int(daily_article_limit))
        self.daily_comparison_limit = min(10, int(daily_comparison_limit))
        # Keep room for three events with three sources and one comparison
        # each. Smaller operator limits scale this reserve down. These are
        # portions of the existing limits, never additional spending.
        self.essential_article_reserve = min(9, self.daily_article_limit // 5)
        self.essential_request_reserve = min(12, self.daily_request_limit // 5)
        self.essential_cost_reserve = self.daily_budget_microusd // 5
        self.clock = clock or (lambda: datetime.now(UTC))
        if self.daily_budget_microusd < 1:
            raise ValueError("daily LLM budget must be positive")
        if self.daily_request_limit < 1:
            raise ValueError("daily LLM request limit must be positive")
        if self.daily_article_limit < 1:
            raise ValueError("daily article limit must be positive")
        if not 0 <= self.daily_comparison_limit <= self.daily_request_limit:
            raise ValueError("daily comparison limit must fit inside the request limit")

    async def discovery_article_capacity(
        self, *, pending_articles: int = 0, pending_requests: int = 0,
    ) -> int:
        """Size a new cohort to unused analysis slots, without authorizing spend.

        Call after source search. Leave one request for verification and one
        for comparison. Actual paid reservations still enforce the locked ledger.
        """
        async with _session_scope(self.session_factory) as session:
            result = await _maybe_await(session.execute(text("""
                SELECT request_count, article_request_count, comparison_request_count
                FROM llm_daily_usage WHERE usage_date = :usage_date
            """), {"usage_date": self._usage_date()}))
            row = result.mappings().first()
        return max(0, min(
            self.daily_article_limit - int(_row_value(row, "article_request_count", 0) or 0) - pending_articles,
            self.daily_request_limit - int(_row_value(row, "request_count", 0) or 0) - pending_requests - 2,
        ))

    def _usage_date(self) -> date:
        current = self.clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return current.astimezone(SEOUL).date()

    async def reserve(
        self,
        *,
        category: str,
        estimated_max_cost_microusd: int,
        request_key: str | None = None,
        subject_key: str | None = None,
        article_keys: Sequence[str] | None = None,
        essential: bool = False,
        protected_cost_microusd: int = 0,
        protected_requests: int = 0,
    ) -> LLMBudgetReservation:
        if category not in {"article", "comparison", "discovery"}:
            raise ValueError("unsupported LLM budget category")
        if request_key is not None and not request_key:
            raise ValueError("request key cannot be empty")
        if subject_key is not None and (not subject_key or len(subject_key) > 255):
            raise ValueError("subject key must contain 1 to 255 characters")
        if isinstance(article_keys, (str, bytes)):
            raise ValueError("article keys must be a sequence of article identifiers")
        cohort_keys = tuple(dict.fromkeys(
            article_keys if article_keys is not None
            else ([subject_key] if category == "article" and subject_key else [])
        ))
        if any(not isinstance(value, str) or not value or len(value) > 255
               for value in cohort_keys):
            raise ValueError("article keys must contain 1 to 255 characters")
        key = hashlib.sha256(request_key.encode()).hexdigest() if request_key else None
        try:
            return await self._reserve(
                category=category,
                requested=int(estimated_max_cost_microusd),
                request_key=key,
                subject_key=subject_key,
                article_keys=cohort_keys,
                essential=essential or category == "comparison",
                protected_cost_microusd=max(0, int(protected_cost_microusd)),
                protected_requests=max(0, int(protected_requests)),
            )
        except IntegrityError as exc:
            # Concurrent reservations on different KST dates can both miss the
            # global request. The unique insert rolls back the losing budget
            # transaction. Never let that worker reach the provider.
            raise LLMRequestSuppressed() from exc

    async def _reserve(
        self, *, category: str, requested: int,
        request_key: str | None, subject_key: str | None,
        article_keys: Sequence[str],
        essential: bool,
        protected_cost_microusd: int = 0,
        protected_requests: int = 0,
    ) -> LLMBudgetReservation:
        usage_date = self._usage_date()
        now = datetime.now(UTC).replace(tzinfo=None)
        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                await _maybe_await(
                    session.execute(
                        text(
                            """
                            INSERT INTO llm_daily_usage
                              (usage_date, request_count, article_request_count,
                               comparison_request_count, reserved_microusd,
                               observed_tokens, updated_at)
                            VALUES
                              (:usage_date, 0, 0, 0, 0, 0, :updated_at)
                            ON DUPLICATE KEY UPDATE usage_date = VALUES(usage_date)
                            """
                        ),
                        {"usage_date": usage_date, "updated_at": now},
                    )
                )
                result = await _maybe_await(
                    session.execute(
                        text(
                            """
                            SELECT request_count, article_request_count, comparison_request_count,
                                   reserved_microusd
                            FROM llm_daily_usage
                            WHERE usage_date = :usage_date
                            FOR UPDATE
                            """
                        ),
                        {"usage_date": usage_date},
                    )
                )
                mappings = result.mappings()
                row = mappings.first()
                if row is None:
                    raise RuntimeError("daily LLM budget row was not created")
                if request_key is not None:
                    existing_result = await _maybe_await(session.execute(text("""
                        SELECT usage_date, category, state, response_json
                        FROM llm_requests WHERE request_key = :request_key FOR UPDATE
                    """), {"request_key": request_key}))
                    existing = existing_result.mappings().first()
                    if existing is not None:
                        response = _row_value(existing, "response_json")
                        if isinstance(response, str):
                            response = json.loads(response)
                        if (
                            _row_value(existing, "state") == "SUCCEEDED"
                            and _row_value(existing, "category") == category
                            and isinstance(response, dict)
                        ):
                            return LLMBudgetReservation(
                                _row_value(existing, "usage_date"), category, 0,
                                request_key, response,
                            )
                        raise LLMRequestSuppressed()
                    if category == "article" and subject_key is not None:
                        subject_result = await _maybe_await(session.execute(text("""
                            SELECT request_key FROM llm_requests
                            WHERE category = 'article' AND usage_date = :usage_date
                              AND subject_key = :subject_key
                            LIMIT 1 FOR UPDATE
                        """), {"usage_date": usage_date, "subject_key": subject_key}))
                        if subject_result.mappings().first() is not None:
                            raise LLMRequestSuppressed("ARTICLE_ALREADY_ANALYZED_TODAY")
                if requested < 1 or requested > self.daily_budget_microusd:
                    raise DailyLLMBudgetExceeded("request maximum exceeds the daily LLM budget")
                requests = int(_row_value(row, "request_count", 0) or 0)
                articles = int(_row_value(row, "article_request_count", 0) or 0)
                comparisons = int(_row_value(row, "comparison_request_count", 0) or 0)
                reserved = int(_row_value(row, "reserved_microusd", 0) or 0)
                if category == "discovery":
                    # Discovery cannot spend the capacity needed to analyze its
                    # selected articles, even though it is an essential job.
                    cost_floor = max(self.daily_budget_microusd // 5, protected_cost_microusd)
                    # The daily analysis allocation includes work already paid
                    # for today. Reserving another 30 after it was consumed
                    # strands otherwise usable discovery capacity.
                    request_floor = max(
                        0, min(30, self.daily_request_limit * 3 // 5) - articles - comparisons,
                        protected_requests,
                    )
                    if (reserved + requested + cost_floor > self.daily_budget_microusd
                            or requests + 1 + request_floor > self.daily_request_limit):
                        raise EssentialLLMBudgetReserved("remaining capacity is reserved for article and comparison analysis")
                exhausted = requests >= self.daily_request_limit
                exhausted = exhausted or reserved + requested > self.daily_budget_microusd
                if category == "comparison":
                    exhausted = exhausted or comparisons >= self.daily_comparison_limit
                if category == "article":
                    exhausted = exhausted or articles >= self.daily_article_limit
                if exhausted:
                    raise DailyLLMBudgetExceeded(
                        "daily LLM request or cost budget has been exhausted"
                    )
                if not essential and (
                    requests >= self.daily_request_limit - self.essential_request_reserve
                    or articles >= self.daily_article_limit - self.essential_article_reserve
                    or reserved + requested > self.daily_budget_microusd - self.essential_cost_reserve
                ):
                    raise EssentialLLMBudgetReserved("remaining daily capacity is reserved for events")
                new_article_keys: set[str] = set()
                if article_keys:
                    cohort_result = await _maybe_await(session.execute(text("""
                        SELECT article_key FROM llm_daily_articles
                        WHERE usage_date = :usage_date
                    """), {"usage_date": usage_date}))
                    existing_article_keys = {
                        str(_row_value(member, "article_key"))
                        for member in cohort_result.mappings().all()
                    }
                    new_article_keys = set(article_keys) - existing_article_keys
                    if len(existing_article_keys) + len(new_article_keys) > self.daily_article_limit:
                        raise DailyLLMBudgetExceeded(
                            "daily distinct article cohort has been exhausted"
                        )
                    if not essential and (
                        len(existing_article_keys) + len(new_article_keys)
                        > self.daily_article_limit - self.essential_article_reserve
                    ):
                        raise EssentialLLMBudgetReserved("remaining article cohort is reserved for events")
                if request_key is not None:
                    await _maybe_await(session.execute(text("""
                        INSERT INTO llm_requests
                          (request_key, category, subject_key, usage_date, state,
                           response_json, created_at, updated_at)
                        VALUES
                          (:request_key, :category, :subject_key, :usage_date,
                           'SUBMITTED', NULL, :now, :now)
                    """), {
                        "request_key": request_key, "category": category,
                        "subject_key": subject_key, "usage_date": usage_date, "now": now,
                    }))
                for article_key in sorted(new_article_keys):
                    await _maybe_await(session.execute(text("""
                        INSERT INTO llm_daily_articles (usage_date, article_key)
                        VALUES (:usage_date, :article_key)
                    """), {"usage_date": usage_date, "article_key": article_key}))
                await _maybe_await(
                    session.execute(
                        text(
                            """
                            UPDATE llm_daily_usage
                            SET request_count = request_count + 1,
                                article_request_count = article_request_count + :article_delta,
                                comparison_request_count = comparison_request_count + :comparison_delta,
                                reserved_microusd = reserved_microusd + :reserved_microusd,
                                updated_at = :updated_at
                            WHERE usage_date = :usage_date
                            """
                        ),
                        {
                            "usage_date": usage_date,
                            "article_delta": 1 if category == "article" else 0,
                            "comparison_delta": 1 if category == "comparison" else 0,
                            "reserved_microusd": requested,
                            "updated_at": now,
                        },
                    )
                )
        return LLMBudgetReservation(usage_date, category, requested, request_key)

    async def record_response(
        self, reservation: LLMBudgetReservation, response: dict[str, Any],
    ) -> None:
        """Persist parsed results before applying domain writes; never re-bill replay."""
        if reservation.request_key is None or reservation.cached_response is not None:
            return
        encoded = json.dumps(response, ensure_ascii=False, allow_nan=False)
        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                await _maybe_await(session.execute(text("""
                    UPDATE llm_requests
                    SET state = 'SUCCEEDED', response_json = :response_json,
                        updated_at = :updated_at
                    WHERE request_key = :request_key AND state = 'SUBMITTED'
                """), {
                    "request_key": reservation.request_key,
                    "response_json": encoded,
                    "updated_at": datetime.now(UTC).replace(tzinfo=None),
                }))

    async def record_observed_tokens(
        self,
        reservation: LLMBudgetReservation,
        token_usage: int | None,
    ) -> None:
        if reservation.cached_response is not None:
            return
        tokens = max(0, int(token_usage or 0))
        if tokens == 0:
            return
        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                await _maybe_await(
                    session.execute(
                        text(
                            """
                            UPDATE llm_daily_usage
                            SET observed_tokens = observed_tokens + :tokens,
                                updated_at = :updated_at
                            WHERE usage_date = :usage_date
                            """
                        ),
                        {
                            "usage_date": reservation.usage_date,
                            "tokens": tokens,
                            "updated_at": datetime.now(UTC).replace(tzinfo=None),
                        },
                    )
                )
