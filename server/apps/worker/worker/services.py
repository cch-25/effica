"""Worker-side durable outcome application services.

Handlers intentionally return serialisable values.  This module is the
side-effect boundary that turns those values into MariaDB rows in one
transaction, records a compact completion receipt, and makes replay safe. It
uses SQL text rather than importing API ORM models so the worker can start
without constructing the FastAPI application and so SQL contract tests can
run with tiny fake sessions.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import math
import time
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .handlers.base import HandlerContext, HandlerResult
from .queue import Job

try:
    from apps.api.app.domains.issues.topics import (
        PUBLIC_ISSUE_TOPICS,
        canonical_topic_editorial_key,
        canonical_topic_issue_id,
        infer_issue_topic,
    )
    from apps.api.app.jobs.payloads import JobPayloadError, validate_job_payload
    from apps.api.app.jobs.types import generate_job_id, utc_now
except ImportError:  # pragma: no cover - supports PYTHONPATH=apps/worker.
    from api.app.domains.issues.topics import (  # type: ignore
        PUBLIC_ISSUE_TOPICS,
        canonical_topic_editorial_key,
        canonical_topic_issue_id,
        infer_issue_topic,
    )
    from api.app.jobs.payloads import JobPayloadError, validate_job_payload  # type: ignore
    from api.app.jobs.types import generate_job_id, utc_now  # type: ignore


class ResultApplicationError(RuntimeError):
    """Raised when a handler result cannot be durably applied.

    Explicit apply conflicts (stale revision, missing share row) are not
    retryable.  Unexpected infrastructure failures may set ``retryable=True``.
    """

    retryable = False

    def __init__(self, message: str, *, retryable: bool | None = None) -> None:
        super().__init__(message)
        if retryable is not None:
            self.retryable = bool(retryable)


class ResultApplier(Protocol):
    async def apply(
        self,
        job: Job,
        result: HandlerResult | Any,
        *,
        context: HandlerContext | None = None,
    ) -> Any:
        """Apply a result before the queue row may become SUCCEEDED."""


def _result_value(result: HandlerResult | Any) -> Any:
    return result.value if isinstance(result, HandlerResult) else result


def _result_mapping(result: HandlerResult | Any) -> dict[str, Any]:
    value = _result_value(result)
    if isinstance(value, Mapping):
        return dict(value)
    return {"value": value}


def _json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _sql(statement: str) -> Any:
    try:
        from sqlalchemy import text

        return text(statement)
    except ImportError:  # pragma: no cover - SQLAlchemy is an app dependency.
        return statement


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
    begin = getattr(session, "begin", None)
    if begin is None:
        yield session
        return
    # AsyncSessionTransaction is awaitable as well as an async context
    # manager; entering an already-awaited transaction begins it twice.
    context = begin()
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


def _rows(result: Any) -> list[Any]:
    mappings = getattr(result, "mappings", None)
    if mappings is not None:
        mapped = mappings()
        all_rows = getattr(mapped, "all", None)
        if all_rows is not None:
            return list(all_rows())
        first = getattr(mapped, "first", None)
        if first is not None:
            row = first()
            return [] if row is None else [row]
    all_rows = getattr(result, "all", None)
    if all_rows is not None:
        return list(all_rows())
    first = getattr(result, "first", None)
    if first is not None:
        row = first()
        return [] if row is None else [row]
    if isinstance(result, (list, tuple)):
        return list(result)
    return []


def _row(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, default)


def _rowcount(result: Any) -> int:
    try:
        return int(getattr(result, "rowcount", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _new_id() -> str:
    try:
        return str(generate_job_id())
    except Exception:  # pragma: no cover - defensive fallback for test doubles.
        return uuid.uuid4().hex[:26].upper()


def _stable_id(value: str) -> str:
    """Return a deterministic ULID-shaped identifier for replayable rows."""

    digest = hashlib.sha256(value.encode("utf-8")).digest()
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    number = int.from_bytes(digest[:16], "big")
    chars = [alphabet[0]] * 26
    for index in range(25, -1, -1):
        chars[index] = alphabet[number & 31]
        number >>= 5
    return "".join(chars)


def _utc(value: datetime | None = None) -> datetime:
    value = value or utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _database_timestamp(value: Any) -> datetime | None:
    """Normalize queue timestamps for MariaDB ``DATETIME`` bindings."""

    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ResultApplicationError("stored BLOB expiry is not a valid ISO timestamp") from exc
    else:
        raise ResultApplicationError("stored BLOB expiry must be a datetime or ISO timestamp")
    # SQLAlchemy ORM columns apply UTCDateTime automatically. This worker path
    # uses textual SQL, so perform the same conversion before asyncmy binds it.
    return _utc(parsed).replace(tzinfo=None)


class MariaDBRuntimeControl:
    """Read the fail-closed background-processing switch with a short cache."""

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        cache_seconds: float = 1.0,
    ) -> None:
        self.session_factory = session_factory
        self.cache_seconds = max(0.0, float(cache_seconds))
        self._cached_enabled = False
        self._cached_until = 0.0

    async def is_enabled(self) -> bool:
        now = time.monotonic()
        if now < self._cached_until:
            return self._cached_enabled
        async with _session_scope(self.session_factory) as session:
            result = await _maybe_await(
                session.execute(
                    _sql(
                        """
                        SELECT llm_enabled
                        FROM runtime_controls
                        WHERE singleton_key = 'global'
                        LIMIT 1
                        """.strip()
                    )
                )
            )
            rows = _rows(result)
        enabled = bool(rows and int(_row(rows[0], "llm_enabled", 0) or 0) == 1)
        self._cached_enabled = enabled
        self._cached_until = now + self.cache_seconds
        return enabled


def _database_confidence(value: Any) -> float:
    """Fit externally produced confidence into MariaDB ``NUMERIC(5, 4)``."""

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return round(max(0.0, min(1.0, parsed)), 4)


@dataclass
class MemoryResultApplier:
    """Deterministic result sink for memory workers and unit tests."""

    results: dict[str, Any] = field(default_factory=dict)
    contexts: dict[str, dict[str, Any]] = field(default_factory=dict)
    apply_count: dict[str, int] = field(default_factory=dict)

    async def apply(
        self,
        job: Job,
        result: HandlerResult | Any,
        *,
        context: HandlerContext | None = None,
    ) -> Any:
        if job.id in self.results:
            return self.results[job.id]
        value = _result_value(result)
        self.results[job.id] = value
        self.apply_count[job.id] = self.apply_count.get(job.id, 0) + 1
        self.contexts[job.id] = {
            "job_id": job.id,
            "job_type": job.job_type,
            "idempotency_key": context.idempotency_key if context else f"{job.job_type}:{job.id}",
            "request_id": job.payload.get("request_id"),
        }
        return value

    # Naming aliases make this sink convenient for injected service maps.
    apply_result = apply


class MariaDBCrawlScheduler:
    """Periodically enqueue every eligible source without an external cron.

    Leadership is connection-scoped and short lived.  The advisory lock keeps
    a fleet of workers from scanning the same source set simultaneously, while
    the durable ``(job_type, dedupe_key)`` constraint is the final authority if
    processes start sequentially or a lock connection disappears.  Dedupe keys
    include the configured interval bucket, so a completed crawl never blocks
    the next scheduled refresh.
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        interval_seconds: float = 900.0,
        batch_size: int = 50,
        max_attempts: int = 1,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if interval_seconds < 1:
            raise ValueError("crawl interval must be positive")
        if not 1 <= batch_size <= 500:
            raise ValueError("crawl scheduler batch size must be between 1 and 500")
        if not 1 <= max_attempts <= 20:
            raise ValueError("crawl scheduler max attempts must be between 1 and 20")
        self.session_factory = session_factory
        self.interval_seconds = float(interval_seconds)
        self.batch_size = int(batch_size)
        self.max_attempts = int(max_attempts)
        self.clock = clock
        self.lock_name = "effica:crawl-scheduler"

    def candidate_source_statement(self) -> Any:
        """Return the exact MariaDB query used to select the next source batch.

        Keeping this query available as one statement lets the integration
        suite run ``EXPLAIN`` against the production MariaDB dialect without
        enqueueing work or duplicating SQL in a test.
        """

        return _sql(
            f"""
            SELECT s.id, s.canonical_url,
                   a.adapter_type, a.config_json, a.rate_limit,
                   s.policy_status, s.robots_status, s.terms_status
            FROM sources s
            JOIN source_adapters a
              ON a.id = (
                   SELECT a2.id
                   FROM source_adapters a2
                   WHERE a2.source_id = s.id
                     AND a2.active = 1
                     AND LOWER(COALESCE(JSON_UNQUOTE(
                       JSON_EXTRACT(a2.config_json, '$.scheduled')
                     ), 'false')) = 'true'
                   ORDER BY a2.id
                   LIMIT 1
                 )
            LEFT JOIN jobs j
              ON j.job_type = 'crawl'
             AND j.dedupe_key = CONCAT(
                   :dedupe_prefix, s.id, ':', :bucket
                 )
            LEFT JOIN (
              SELECT JSON_UNQUOTE(JSON_EXTRACT(
                       payload_json, '$.source_id'
                     )) AS source_id,
                     MAX(created_at) AS last_scheduled_at,
                     SUM(status IN ('PENDING', 'LEASED')) AS active_jobs
              FROM jobs
              WHERE job_type = 'crawl'
              GROUP BY JSON_UNQUOTE(JSON_EXTRACT(
                payload_json, '$.source_id'
              ))
            ) history ON history.source_id = s.id
            WHERE s.active = 1
              AND s.policy_status = 'APPROVED'
              AND s.robots_status = 'APPROVED'
              AND s.terms_status = 'APPROVED'
              AND j.id IS NULL
              AND COALESCE(history.active_jobs, 0) = 0
            ORDER BY history.last_scheduled_at IS NOT NULL,
                     history.last_scheduled_at, s.id
            LIMIT {self.batch_size}
            """.strip()
        )

    async def tick(self, worker_id: str) -> int:
        """Enqueue one bounded interval batch, returning newly created jobs."""

        del worker_id  # The DB lock owns leadership; worker IDs remain ephemeral.
        now = _utc(self.clock())
        database_now = _database_timestamp(now)
        bucket = int(now.timestamp() // self.interval_seconds)
        dedupe_prefix = "scheduled:"

        # Keep the named lock on a dedicated checked-out connection.  The
        # mutation transaction uses another session and is fully committed
        # before leadership is released.
        async with _session_scope(self.session_factory) as lock_session:
            acquired_result = await _maybe_await(
                lock_session.execute(
                    _sql("SELECT GET_LOCK(:lock_name, 0) AS acquired"),
                    {"lock_name": self.lock_name},
                )
            )
            acquired_rows = _rows(acquired_result)
            acquired = bool(
                acquired_rows
                and int(_row(acquired_rows[0], "acquired", 0) or 0) == 1
            )
            if not acquired:
                return 0
            try:
                async with _session_scope(self.session_factory) as session:
                    async with _transaction(session):
                        result = await _maybe_await(
                            session.execute(
                                self.candidate_source_statement(),
                                {"dedupe_prefix": dedupe_prefix, "bucket": str(bucket)},
                            )
                        )
                        created = 0
                        for source in _rows(result):
                            source_id = str(_row(source, "id", "") or "")
                            config = _json_mapping(_row(source, "config_json", {}))
                            canonical_url = str(
                                config.get("feed_url")
                                or _row(source, "canonical_url", "")
                                or ""
                            )
                            source_type = str(
                                _row(source, "adapter_type", "") or ""
                            ).upper()
                            if not source_id or not canonical_url or source_type not in {
                                "API",
                                "RSS",
                                "CRAWLER",
                            }:
                                continue
                            dedupe_key = f"{dedupe_prefix}{source_id}:{bucket}"
                            job_id = _stable_id(f"job:crawl:{dedupe_key}")
                            payload_value: dict[str, Any] = {
                                "source_id": source_id,
                                "url": canonical_url,
                                "source_type": source_type,
                                "adapter_type": source_type,
                                # Freeze the explicitly scheduled adapter at
                                # enqueue time. A later lookup cannot silently
                                # replace it with an unscheduled direct adapter.
                                "config": config,
                                "policy_status": str(
                                    _row(source, "policy_status", "") or ""
                                ).upper(),
                                "robots_status": str(
                                    _row(source, "robots_status", "") or ""
                                ).upper(),
                                "terms_status": str(
                                    _row(source, "terms_status", "") or ""
                                ).upper(),
                                "reason": "scheduled source refresh",
                                "mode": "live",
                                "schedule_bucket": bucket,
                            }
                            rate_limit = _row(source, "rate_limit")
                            if rate_limit is not None:
                                payload_value["rate_limit"] = int(rate_limit)
                            payload = validate_job_payload(
                                "crawl",
                                payload_value,
                            )
                            inserted = await _maybe_await(
                                session.execute(
                                    _sql(
                                        """
                                        INSERT INTO jobs
                                          (id, job_type, dedupe_key, status, priority,
                                           available_at, lease_owner, lease_expires_at,
                                           attempts, max_attempts, payload_json,
                                           last_error_json, created_at, updated_at)
                                        VALUES
                                          (:id, 'crawl', :dedupe_key, 'PENDING', 0,
                                           :available_at, NULL, NULL, 0, :max_attempts,
                                           :payload_json, NULL, :created_at, :updated_at)
                                        ON DUPLICATE KEY UPDATE id = id
                                        """.strip()
                                    ),
                                    {
                                        "id": job_id,
                                        "dedupe_key": dedupe_key,
                                        "available_at": database_now,
                                        "max_attempts": self.max_attempts,
                                        "payload_json": _json(payload),
                                        "created_at": database_now,
                                        "updated_at": database_now,
                                    },
                                )
                            )
                            # MariaDB reports 1 for an insert and 0 for the
                            # deliberate duplicate no-op.  Affected-row modes
                            # may differ, so the unique key remains authoritative
                            # and crawl-run creation is idempotent as well.
                            if _rowcount(inserted) == 1:
                                created += 1
                            await _maybe_await(
                                session.execute(
                                    _sql(
                                        """
                                        INSERT INTO crawl_runs
                                          (id, source_id, status, started_at,
                                           finished_at, stats_json, error_json)
                                        VALUES
                                          (:id, :source_id, 'PENDING', NULL, NULL,
                                           NULL, NULL)
                                        ON DUPLICATE KEY UPDATE id = id
                                        """.strip()
                                    ),
                                    {"id": job_id, "source_id": source_id},
                                )
                            )
                        return created
            finally:
                try:
                    await _maybe_await(
                        lock_session.execute(
                            _sql("SELECT RELEASE_LOCK(:lock_name)"),
                            {"lock_name": self.lock_name},
                        )
                    )
                except Exception:
                    # Closing the dedicated connection releases named locks.
                    pass


class MariaDBIdempotencyStore:
    """Durable replay lookup backed by compact job receipts.

    The row lock taken by :class:`MariaDBResultApplier` serialises replay with
    the original application. Receipts expire alongside completed jobs.
    """

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def begin(self, key: str) -> tuple[str, Any]:
        # Keys are ``job_type:dedupe_key``; also accept a direct job identifier.
        token = uuid.uuid4().hex
        suffix = key.split(":", 1)[1] if ":" in key else key
        query = _sql(
            """
            SELECT r.result_json FROM job_receipts r JOIN jobs j ON j.id = r.job_id
            WHERE j.job_type = :job_type AND (j.id = :target_id OR j.dedupe_key = :target_id)
            ORDER BY r.applied_at DESC, r.job_id DESC
            LIMIT 1
            """.strip()
        )
        async with _session_scope(self.session_factory) as session:
            # An operational error here must reach the worker runtime.  A
            # missing/failed idempotency read is not evidence that no result
            # exists; treating it as a cache miss would permit a replayed
            # domain side effect during a DB outage.
            result = await _maybe_await(
                session.execute(query, {"target_id": suffix, "job_type": key.split(":", 1)[0]})
            )
            rows = _rows(result)
        if rows:
            value = _row(rows[0], "result_json")
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    pass
            if isinstance(value, Mapping) and "result" in value:
                value = value["result"]
            return "cached", value
        return token, None

    async def complete(self, key: str, owner_token: str, result: Any) -> None:
        del key, owner_token, result

    async def abandon(self, key: str, owner_token: str) -> None:
        del key, owner_token


class MariaDBResultApplier:
    """Apply every built-in handler result inside one MariaDB transaction."""

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock

    async def apply(
        self,
        job: Job,
        result: HandlerResult | Any,
        *,
        context: HandlerContext | None = None,
    ) -> Any:
        value = _result_mapping(result)
        now = _utc(self.clock())
        request_id = (
            value.get("request_id")
            or job.payload.get("request_id")
            or (context.services.get("request_id") if context else None)
        )
        async with _session_scope(self.session_factory) as session:
            async with _transaction(session):
                # Serialize replay with the current lease holder.  The query
                # is intentionally harmless for small fake sessions used by
                # SQL contract tests.
                await _maybe_await(
                    session.execute(
                        _sql("SELECT id FROM jobs WHERE id = :job_id FOR UPDATE"),
                        {"job_id": job.id},
                    )
                )

                existing = await self._existing_result(session, job.id)
                if existing is not None:
                    return existing

                await self._apply_domain(session, job, value, now)
                await self._persist_result_record(
                    session,
                    job,
                    value,
                    now=now,
                    request_id=str(request_id) if request_id is not None else None,
                )
        return _result_value(result)

    apply_result = apply

    async def _existing_result(self, session: Any, job_id: str) -> Any | None:
        query = _sql(
            """
            SELECT result_json FROM job_receipts
            WHERE job_id = :job_id
            LIMIT 1 FOR UPDATE
            """.strip()
        )
        result = await _maybe_await(session.execute(query, {"job_id": job_id}))
        rows = _rows(result)
        if not rows:
            return None
        value = _row(rows[0], "result_json")
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return value
        if isinstance(value, Mapping) and "result" in value:
            return value["result"]
        return value

    async def _persist_result_record(
        self,
        session: Any,
        job: Job,
        value: Mapping[str, Any],
        *,
        now: datetime,
        request_id: str | None,
    ) -> None:
        from apps.api.app.domains.content.storage import compact_job_payload, job_receipt

        record = job_receipt(job.job_type, value)
        # Store completion metadata without duplicating article or model data.
        await _maybe_await(
            session.execute(
                _sql(
                    """
                    INSERT INTO job_receipts (job_id, job_type, result_json, applied_at)
                    VALUES (:job_id, :job_type, :result_json, :applied_at)
                    """.strip()
                ),
                {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "result_json": _json(record),
                    "applied_at": now,
                },
            )
        )
        await self._execute(
            session,
            "UPDATE jobs SET payload_json = :payload_json WHERE id = :job_id",
            {"job_id": job.id, "payload_json": _json(compact_job_payload(job.payload))},
        )

    async def _apply_domain(
        self,
        session: Any,
        job: Job,
        result: Mapping[str, Any],
        now: datetime,
    ) -> None:
        handlers = {
            "crawl": self._apply_crawl,
            "cluster": self._apply_cluster,
            "merge_issue": self._apply_merge_issue,
            "split_issue": self._apply_split_issue,
            "analyze": self._apply_analyze,
            "build_issue_comparison": self._apply_issue_comparison,
            "aggregate_votes": self._apply_aggregate,
            "calculate_score": self._apply_score,
            "recommend_weights": self._apply_recommendation,
            "simulate_weights": self._apply_simulation,
            "render_share_card": self._apply_share_card,
            "export_user": self._apply_export,
            "delete_user": self._apply_delete,
        }
        handler = handlers.get(job.job_type)
        if handler is None:
            # Extension handlers still get durable result and audit records;
            # they do not silently lose their output.
            return
        await handler(session, job, result, now)

    async def _apply_issue_comparison(
        self, session: Any, job: Job, result: Mapping[str, Any], now: datetime
    ) -> None:
        issue_id = str(result.get("issue_id") or job.payload.get("issue_id") or "")
        issue_version = int(result.get("issue_version") or job.payload.get("issue_version") or 0)
        prompt_version = str(
            result.get("prompt_version") or job.payload.get("prompt_version") or ""
        )
        if not issue_id or issue_version < 1 or not prompt_version:
            raise ResultApplicationError("comparison result is missing version identity")
        if str(result.get("status") or "").strip().upper() == "SKIPPED":
            # Keep the durable job-result audit written by ``apply`` while
            # leaving the last successful comparison snapshot untouched.
            return
        await self._execute(
            session,
            """
            UPDATE issue_comparison_snapshots
            SET status = 'SUPERSEDED'
            WHERE issue_id = :issue_id AND status = 'SUCCEEDED'
              AND (issue_version <> :issue_version OR prompt_version <> :prompt_version)
            """,
            {
                "issue_id": issue_id,
                "issue_version": issue_version,
                "prompt_version": prompt_version,
            },
        )
        await self._execute(
            session,
            """
            INSERT INTO issue_comparison_snapshots
              (id, issue_id, issue_version, prompt_version, model_alias_id,
               common_facts_json, framing_dimensions_json, article_frames_json,
               confidence, status, reviewed_at, reviewed_by, created_at)
            VALUES
              (:id, :issue_id, :issue_version, :prompt_version, :model_alias_id,
               :common_facts, :dimensions, :article_frames,
               :confidence, 'SUCCEEDED', NULL, NULL, :created_at)
            ON DUPLICATE KEY UPDATE
              model_alias_id = VALUES(model_alias_id),
              common_facts_json = VALUES(common_facts_json),
              framing_dimensions_json = VALUES(framing_dimensions_json),
              article_frames_json = VALUES(article_frames_json),
              confidence = VALUES(confidence), status = 'SUCCEEDED',
              reviewed_at = NULL, reviewed_by = NULL, created_at = VALUES(created_at)
            """,
            {
                "id": _stable_id(
                    f"comparison:{issue_id}:{issue_version}:{prompt_version}"
                ),
                "issue_id": issue_id,
                "issue_version": issue_version,
                "prompt_version": prompt_version,
                "model_alias_id": result.get("model_alias_id"),
                "common_facts": _json({"common_facts": result.get("common_facts", [])}),
                "dimensions": _json({"dimensions": result.get("dimensions", [])}),
                "article_frames": _json(
                    {
                        "article_frames": result.get("article_frames", {}),
                        "article_version_ids": result.get("article_version_ids", {}),
                    }
                ),
                "confidence": _database_confidence(result.get("confidence", 0)),
                "created_at": now,
            },
        )

    async def _execute(self, session: Any, statement: str, params: Mapping[str, Any]) -> Any:
        return await _maybe_await(session.execute(_sql(statement.strip()), dict(params)))

    async def _enqueue_job(
        self,
        session: Any,
        job_type: str,
        payload: Mapping[str, Any],
        *,
        dedupe_key: str,
        now: datetime,
        priority: int = 0,
        max_attempts: int = 3,
    ) -> str:
        """Insert one validated downstream job in the result transaction.

        A result application and the jobs it unlocks must commit together.  In
        particular, opening a second session here would allow a downstream
        job to run against a parent projection that later rolls back.  The
        unique ``(job_type, dedupe_key)`` constraint makes this safe when a
        lease expires and the parent result is replayed.
        """

        if not dedupe_key:
            raise ResultApplicationError("downstream job dedupe key must not be empty")
        try:
            validated = validate_job_payload(job_type, payload)
        except JobPayloadError as exc:
            raise ResultApplicationError(
                f"invalid downstream {job_type} payload: {exc}"
            ) from exc
        job_id = _stable_id(f"job:{job_type}:{dedupe_key}")
        await self._execute(
            session,
            """
            INSERT INTO jobs
              (id, job_type, dedupe_key, status, priority, available_at,
               lease_owner, lease_expires_at, attempts, max_attempts,
               payload_json, last_error_json, created_at, updated_at)
            VALUES
              (:id, :job_type, :dedupe_key, 'PENDING', :priority, :available_at,
               NULL, NULL, 0, :max_attempts, :payload_json, NULL,
               :created_at, :updated_at)
            ON DUPLICATE KEY UPDATE id = id
            """,
            {
                "id": job_id,
                "job_type": str(job_type),
                "dedupe_key": dedupe_key,
                "priority": int(priority),
                "available_at": now,
                "max_attempts": int(max_attempts),
                "payload_json": _json(validated),
                "created_at": now,
                "updated_at": now,
            },
        )
        return job_id

    @staticmethod
    def _article_set_dedupe(article_ids: list[str], threshold: Any = None) -> str:
        canonical_ids = sorted({str(article_id) for article_id in article_ids if str(article_id)})
        digest = hashlib.sha256(
            _json({"article_ids": canonical_ids, "threshold": threshold}).encode("utf-8")
        ).hexdigest()
        return f"article-set:{digest}"

    @staticmethod
    def _request_id(job: Job, result: Mapping[str, Any]) -> Any:
        return result.get("request_id") or job.payload.get("request_id")

    async def _rolling_cluster_ids(
        self,
        session: Any,
        seed_article_ids: list[str],
        *,
        now: datetime,
        window_hours: int = 72,
        limit: int = 500,
    ) -> list[str]:
        """Return a bounded recent, approved, cross-source clustering pool."""

        result = await self._execute(
            session,
            """
            SELECT a.id
            FROM articles AS a
            JOIN sources AS s ON s.id = a.source_id
            WHERE a.current_version_id IS NOT NULL
              AND a.status NOT IN ('removed', 'blocked')
              AND s.active = 1
              AND s.policy_status = 'APPROVED'
              AND COALESCE(a.published_at, a.updated_at) >= :cutoff
            ORDER BY COALESCE(a.published_at, a.updated_at) DESC, a.id DESC
            LIMIT :limit
            """,
            {
                "cutoff": now - timedelta(hours=max(1, min(window_hours, 168))),
                "limit": max(2, min(limit, 1000)),
            },
        )
        recent = [str(_row(row, "id")) for row in _rows(result) if _row(row, "id")]
        return sorted({*recent, *(str(value) for value in seed_article_ids if value)})

    async def _store_blob(
        self,
        session: Any,
        payload: bytes,
        *,
        mime_type: str,
        expires_at: Any = None,
    ) -> str:
        if len(payload) > 10 * 1024 * 1024:
            raise ResultApplicationError("stored BLOB exceeds 10 MiB")
        digest = hashlib.sha256(payload).digest()
        blob_id = _new_id()
        await self._execute(
            session,
            """
            INSERT INTO stored_blobs
              (id, sha256, mime_type, byte_size, payload, expires_at, created_at)
            VALUES (:id, :sha256, :mime_type, :byte_size, :payload, :expires_at, :created_at)
            ON DUPLICATE KEY UPDATE id = id
            """,
            {
                "id": blob_id,
                "sha256": digest,
                "mime_type": mime_type,
                "byte_size": len(payload),
                "payload": payload,
                "expires_at": _database_timestamp(expires_at),
                "created_at": _utc(self.clock()),
            },
        )
        result = await self._execute(
            session,
            "SELECT id FROM stored_blobs WHERE sha256 = :sha256 LIMIT 1",
            {"sha256": digest},
        )
        rows = _rows(result)
        return str(_row(rows[0], "id", blob_id)) if rows else blob_id

    async def _apply_crawl(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        source_id = result.get("source_id") or job.payload.get("source_id")
        # The API intentionally creates CrawlRun with the queue job's ID so
        # operators can correlate both records without a join table.  Always
        # reuse that ID; generating a second one leaves the original run
        # permanently PENDING.
        run_id = result.get("crawl_run_id") or job.payload.get("crawl_run_id") or job.id
        if source_id:
            await self._execute(
                session,
                """
                INSERT INTO crawl_runs
                  (id, source_id, status, started_at, finished_at, stats_json, error_json)
                VALUES (:id, :source_id, 'SUCCEEDED', :started_at, :finished_at, :stats_json, NULL)
                ON DUPLICATE KEY UPDATE status = VALUES(status), finished_at = VALUES(finished_at), stats_json = VALUES(stats_json), error_json = NULL
                """,
                {
                    "id": run_id,
                    "source_id": source_id,
                    "started_at": now,
                    "finished_at": now,
                    "stats_json": _json(result.get("stats", {"url": result.get("url")})),
                },
            )
        articles = result.get("articles") or job.payload.get("articles") or []
        if not isinstance(articles, (list, tuple)):
            return
        persisted_article_ids: list[str] = []
        analyzable_version_ids: list[str] = []
        for article in articles:
            if not isinstance(article, Mapping):
                continue
            url = str(article.get("url") or article.get("canonical_url") or result.get("url") or "")
            title = str(article.get("title") or "Untitled article")[:500]
            if not url:
                continue
            from apps.api.app.domains.content.retention import skip_ingestion

            if await skip_ingestion(session, article, url, now):
                continue
            content: str | bytes | None = None
            for candidate in (article.get("content"), article.get("text")):
                if isinstance(candidate, str) and candidate.strip():
                    content = candidate
                    break
                if isinstance(candidate, (bytes, bytearray)) and bytes(candidate).strip():
                    content = bytes(candidate)
                    break
            article_status = "active" if content is not None else "blocked"
            canonical_hash = hashlib.sha256(url.encode("utf-8")).digest()
            article_id = str(article.get("article_id") or article.get("id") or _stable_id(f"article:{url}"))
            await self._execute(
                session,
                """
                INSERT INTO articles
                  (id, source_id, canonical_url, canonical_url_hash, title, author,
                   published_at, current_version_id, status, created_at, updated_at)
                VALUES
                  (:id, :source_id, :url, :url_hash, :title, :author, :published_at,
                   NULL, :status, :created_at, :updated_at)
                ON DUPLICATE KEY UPDATE title = VALUES(title), author = VALUES(author),
                  published_at = COALESCE(VALUES(published_at), published_at),
                  status = CASE
                    WHEN status = 'removed' THEN status
                    WHEN VALUES(status) = 'active' THEN 'active'
                    ELSE status
                  END,
                  updated_at = VALUES(updated_at)
                """,
                {
                    "id": article_id,
                    "source_id": source_id or article.get("source_id"),
                    "url": url,
                    "url_hash": canonical_hash,
                    "title": title,
                    "author": article.get("author"),
                    "published_at": _database_timestamp(article.get("published_at")),
                    "status": article_status,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            existing_article = await self._execute(
                session,
                "SELECT id FROM articles WHERE canonical_url_hash = :url_hash LIMIT 1",
                {"url_hash": canonical_hash},
            )
            article_rows = _rows(existing_article)
            if article_rows:
                article_id = str(_row(article_rows[0], "id", article_id))
            if content is None:
                continue
            version_id = str(article.get("article_version_id") or article.get("version_id") or _new_id())
            normalized_ref = None
            if content is not None:
                normalized_ref = await self._store_blob(
                    session, _bytes(content), mime_type="text/plain; charset=utf-8"
                )
            content_hash = hashlib.sha256(
                _bytes(content)
            ).digest()
            await self._execute(
                session,
                """
                INSERT INTO article_versions
                  (id, article_id, content_hash, normalized_text_ref, fetched_at, modified_at)
                VALUES (:id, :article_id, :content_hash, :normalized_ref, :fetched_at, :modified_at)
                ON DUPLICATE KEY UPDATE normalized_text_ref = VALUES(normalized_text_ref),
                  modified_at = VALUES(modified_at)
                """,
                {
                    "id": version_id,
                    "article_id": article_id,
                    "content_hash": content_hash,
                    "normalized_ref": normalized_ref,
                    "fetched_at": now,
                    "modified_at": now,
                },
            )
            existing_version = await self._execute(
                session,
                "SELECT id FROM article_versions WHERE article_id = :article_id AND content_hash = :content_hash LIMIT 1",
                {"article_id": article_id, "content_hash": content_hash},
            )
            version_rows = _rows(existing_version)
            if version_rows:
                version_id = str(_row(version_rows[0], "id", version_id))
            await self._execute(
                session,
                "UPDATE articles SET current_version_id = :version_id, updated_at = :now WHERE id = :article_id",
                {"version_id": version_id, "article_id": article_id, "now": now},
            )

            # An identifier-only analysis job is valid, but it can only be
            # useful when a normalized article body was persisted.  Raw-only
            # adapter payloads remain available for retention/export without
            # creating a guaranteed-to-fail analysis or clustering job, or a
            # public topic membership for a metadata-only article.
            if normalized_ref is None:
                continue
            persisted_article_ids.append(article_id)
            analyzable_version_ids.append(version_id)
            await self._upsert_topic_membership(
                session,
                article_id=article_id,
                title=title,
                summary=str(content)[:1000],
                now=now,
            )

        request_id = self._request_id(job, result)
        for version_id in sorted(set(analyzable_version_ids)):
            trusted_assessment = await self._execute(
                session,
                """
                SELECT assessments.id
                FROM model_assessments AS assessments
                JOIN model_aliases AS aliases
                  ON aliases.id = assessments.model_alias_id
                WHERE assessments.article_version_id = :version_id
                  AND assessments.status = 'SUCCEEDED'
                  AND LOWER(aliases.provider) = 'openai'
                  AND aliases.actual_model_id LIKE 'gpt-%'
                LIMIT 1
                """,
                {"version_id": version_id},
            )
            if _rows(trusted_assessment):
                continue
            active_analysis = await self._execute(
                session,
                """
                SELECT id
                FROM jobs
                WHERE job_type = 'analyze'
                  AND status IN ('PENDING', 'LEASED')
                  AND JSON_UNQUOTE(JSON_EXTRACT(payload_json, '$.article_version_id')) = :version_id
                LIMIT 1
                """,
                {"version_id": version_id},
            )
            if _rows(active_analysis):
                continue
            analyze_payload: dict[str, Any] = {
                "article_version_id": version_id,
                "crawl_job_id": job.id,
            }
            if request_id is not None:
                analyze_payload["request_id"] = request_id
            await self._enqueue_job(
                session,
                "analyze",
                analyze_payload,
                # Recrawling unchanged content must not spend another provider
                # call. Explicit admin/recovery reanalysis uses its own
                # generation key when a model or prompt intentionally changes.
                dedupe_key=f"article-version:{version_id}:crawl-analysis",
                now=now,
            )

        # Clustering consumes article identifiers and resolves their current
        # bodies through the worker lookup service. One rolling job spans
        # sources so one publisher can never manufacture an issue by itself.
        cluster_ids = await self._rolling_cluster_ids(
            session,
            persisted_article_ids,
            now=now,
            window_hours=int(job.payload.get("cluster_window_hours", 72)),
        )
        if len(cluster_ids) >= 2:
            cluster_payload: dict[str, Any] = {"article_ids": cluster_ids}
            threshold = job.payload.get("threshold", result.get("threshold"))
            if threshold is not None:
                cluster_payload["threshold"] = threshold
            if request_id is not None:
                cluster_payload["request_id"] = request_id
            await self._enqueue_job(
                session,
                "cluster",
                cluster_payload,
                dedupe_key=self._article_set_dedupe(cluster_ids, threshold),
                now=now,
            )

    async def _upsert_topic_membership(
        self,
        session: Any,
        *,
        article_id: str,
        title: str,
        summary: str,
        now: datetime,
    ) -> None:
        """Keep every new article in one durable, navigable broad-topic bucket."""

        topic = infer_issue_topic(title, summary)
        if topic not in PUBLIC_ISSUE_TOPICS:
            return
        issue_id = canonical_topic_issue_id(topic)
        await self._execute(
            session,
            """
            INSERT INTO issues
              (id, title, summary, topic, status, issue_kind, editorial_key,
               opened_at, last_activity_at, version)
            VALUES
              (:id, :title, :summary, :topic, 'active', 'TOPIC', :editorial_key,
               :opened_at, :last_activity_at, 1)
            ON DUPLICATE KEY UPDATE
              status = 'active', issue_kind = 'TOPIC',
              last_activity_at = GREATEST(last_activity_at, VALUES(last_activity_at))
            """,
            {
                "id": issue_id,
                "title": topic,
                "summary": f"{topic} 분야의 최신 기사",
                "topic": topic,
                "editorial_key": canonical_topic_editorial_key(topic),
                "opened_at": now,
                "last_activity_at": now,
            },
        )
        await self._execute(
            session,
            """
            INSERT INTO issue_memberships (issue_id, article_id, confidence, created_at)
            VALUES (:issue_id, :article_id, 1.0, :created_at)
            ON DUPLICATE KEY UPDATE confidence = GREATEST(confidence, VALUES(confidence))
            """,
            {"issue_id": issue_id, "article_id": article_id, "created_at": now},
        )

    async def _apply_cluster(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        candidates = result.get("candidates") or result.get("groups") or []
        if isinstance(candidates, Mapping):
            candidates = list(candidates.values())
        for candidate in candidates if isinstance(candidates, (list, tuple)) else ():
            if not isinstance(candidate, Mapping):
                continue
            articles = candidate.get("article_ids") or candidate.get("articles") or []
            candidate_article_ids = [
                str(item.get("article_id") if isinstance(item, Mapping) else item)
                for item in (articles if isinstance(articles, (list, tuple)) else ())
                if str(item.get("article_id") if isinstance(item, Mapping) else item)
            ]
            source_count = int(candidate.get("source_count", 0) or 0)
            if len(candidate_article_ids) < 2 or source_count < 2:
                continue
            issue_id = str(candidate.get("issue_id") or "")
            if not issue_id:
                # Article-set hashes change when a later crawl adds one more
                # report. Reuse an overlapping automatic EVENT candidate so
                # a developing story gains membership instead of duplicating.
                for article_id in candidate_article_ids:
                    existing = await self._execute(
                        session,
                        """
                        SELECT issues.id
                        FROM issue_memberships AS memberships
                        JOIN issues ON issues.id = memberships.issue_id
                        WHERE memberships.article_id = :article_id
                          AND issues.status = 'candidate'
                          AND issues.issue_kind = 'EVENT'
                        ORDER BY issues.last_activity_at DESC, issues.id
                        LIMIT 1
                        """,
                        {"article_id": article_id},
                    )
                    rows = _rows(existing)
                    if rows:
                        issue_id = str(_row(rows[0], "id"))
                        break
            if not issue_id:
                issue_id = _stable_id(
                    f"cluster:{candidate.get('candidate_id', _json(candidate))}"
                )
            title = str(candidate.get("title") or "Untitled issue")[:500]
            issue_status = (
                "active"
                if len(candidate_article_ids) >= 3 and source_count >= 3
                else "candidate"
            )
            await self._execute(
                session,
                """
                INSERT INTO issues
                  (id, title, summary, topic, status, issue_kind,
                   opened_at, last_activity_at, version)
                VALUES (:id, :title, :summary, :topic, :status, 'EVENT',
                        :opened_at, :last_activity_at, 1)
                ON DUPLICATE KEY UPDATE
                  title = VALUES(title), summary = VALUES(summary), topic = VALUES(topic),
                  status = IF(status = 'active', 'active', VALUES(status)),
                  issue_kind = 'EVENT', last_activity_at = VALUES(last_activity_at),
                  version = version + 1
                """,
                {
                    "id": issue_id,
                    "title": title,
                    "summary": candidate.get("summary"),
                    "topic": str(candidate.get("topic") or "일반")[:40],
                    "status": issue_status,
                    "opened_at": now,
                    "last_activity_at": now,
                },
            )
            for item in articles if isinstance(articles, (list, tuple)) else ():
                article_id = str(item.get("article_id") if isinstance(item, Mapping) else item)
                confidence = _database_confidence(
                    item.get("confidence", 0.0)
                    if isinstance(item, Mapping)
                    else candidate.get("confidence", 0.0)
                )
                await self._execute(
                    session,
                    """
                    INSERT INTO issue_memberships (issue_id, article_id, confidence, created_at)
                    VALUES (:issue_id, :article_id, :confidence, :created_at)
                    ON DUPLICATE KEY UPDATE confidence = VALUES(confidence)
                    """,
                    {"issue_id": issue_id, "article_id": article_id, "confidence": confidence, "created_at": now},
                )
            if candidate_article_ids:
                await self._enqueue_issue_comparisons_for_article(
                    session,
                    article_id=candidate_article_ids[0],
                    request_id=self._request_id(job, result),
                    now=now,
                )

    async def _apply_merge_issue(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        source = str(result.get("source_issue_id") or job.payload.get("source_issue_id"))
        target = str(result.get("target_issue_id") or job.payload.get("target_issue_id"))
        if not source or not target or source == target:
            raise ResultApplicationError("merge result requires distinct source and target issue IDs")
        # The target is the merge output and may legitimately not exist when
        # the queue item is claimed (for example, an API producer can enqueue
        # before a separate target projection is materialised).  Lock and
        # validate the source first, then create the target in this same
        # result-application transaction.  Membership copy, source cleanup,
        # and the job-linked audit written by ``apply`` therefore commit as a
        # single unit.
        source_result = await self._execute(
            session,
            """
            SELECT id, title, summary
            FROM issues
            WHERE id = :source_id
            LIMIT 1
            FOR UPDATE
            """,
            {"source_id": source},
        )
        source_rows = _rows(source_result)
        if not source_rows:
            raise ResultApplicationError("merge source issue was not found")
        target_result = await self._execute(
            session,
            """
            SELECT id
            FROM issues
            WHERE id = :target_id
            LIMIT 1
            FOR UPDATE
            """,
            {"target_id": target},
        )
        if not _rows(target_result):
            source_row = source_rows[0]
            source_title = str(_row(source_row, "title", "Untitled issue") or "Untitled issue")
            source_summary = _row(source_row, "summary")
            await self._execute(
                session,
                """
                INSERT INTO issues
                  (id, title, summary, status, opened_at, last_activity_at, version)
                VALUES (:target_id, :title, :summary, 'candidate', :now, :now, 1)
                """,
                {
                    "target_id": target,
                    "title": source_title,
                    "summary": source_summary,
                    "now": now,
                },
            )
        await self._execute(
            session,
            """
            INSERT INTO issue_memberships (issue_id, article_id, confidence, created_at)
            SELECT :target_id, article_id, confidence, :created_at
            FROM issue_memberships WHERE issue_id = :source_id
            ON DUPLICATE KEY UPDATE confidence = GREATEST(confidence, VALUES(confidence))
            """,
            {"target_id": target, "source_id": source, "created_at": now},
        )
        # A merge moves membership.  Leaving source rows active causes feed
        # queries to surface the same article under both issues.
        await self._execute(
            session,
            "DELETE FROM issue_memberships WHERE issue_id = :source_id",
            {"source_id": source},
        )
        await self._execute(
            session,
            "UPDATE issues SET status = 'merged', version = version + 1, last_activity_at = :now WHERE id = :source_id AND status <> 'merged'",
            {"source_id": source, "now": now},
        )
        await self._execute(
            session,
            "UPDATE issues SET version = version + 1, last_activity_at = :now WHERE id = :target_id",
            {"target_id": target, "now": now},
        )
        target_member = await self._execute(
            session,
            "SELECT article_id FROM issue_memberships WHERE issue_id = :issue_id ORDER BY article_id LIMIT 1",
            {"issue_id": target},
        )
        target_rows = _rows(target_member)
        if target_rows:
            await self._enqueue_issue_comparisons_for_article(
                session,
                article_id=str(_row(target_rows[0], "article_id")),
                request_id=self._request_id(job, result),
                now=now,
            )

    async def _apply_split_issue(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        issue_id = str(result.get("issue_id") or job.payload.get("issue_id"))
        article_ids = result.get("article_ids") or job.payload.get("article_ids") or []
        if not issue_id or not isinstance(article_ids, (list, tuple)) or not article_ids:
            raise ResultApplicationError("split result requires issue_id and article_ids")
        new_ids = result.get("new_issue_ids") or job.payload.get("new_issue_ids") or []
        new_ids = [str(item) for item in new_ids] if isinstance(new_ids, (list, tuple)) else []
        if len(new_ids) == 1:
            new_ids = new_ids * len(article_ids)
        if not new_ids:
            new_ids = [
                _stable_id(f"{issue_id}:split:{str(article_id)}")
                for article_id in article_ids
            ]
        for index, article_id in enumerate(article_ids):
            new_id = new_ids[index] if index < len(new_ids) else new_ids[-1]
            await self._execute(
                session,
                """
                INSERT INTO issues (id, title, summary, status, opened_at, last_activity_at, version)
                SELECT :new_id, CONCAT(title, ' (split)'), summary, 'candidate', :now, :now, 1
                FROM issues WHERE id = :source_id
                ON DUPLICATE KEY UPDATE last_activity_at = VALUES(last_activity_at)
                """,
                {"new_id": new_id, "source_id": issue_id, "now": now},
            )
            await self._execute(
                session,
                """
                INSERT INTO issue_memberships (issue_id, article_id, confidence, created_at)
                SELECT :new_id, article_id, confidence, :created_at
                FROM issue_memberships WHERE issue_id = :source_id AND article_id = :article_id
                ON DUPLICATE KEY UPDATE confidence = VALUES(confidence)
                """,
                {"new_id": new_id, "source_id": issue_id, "article_id": str(article_id), "created_at": now},
            )
            # Splitting moves the selected membership to its new issue.  The
            # insert and delete are part of the same transaction, so a failed
            # copy cannot silently lose the source membership.
            if new_id != issue_id:
                await self._execute(
                    session,
                    "DELETE FROM issue_memberships WHERE issue_id = :source_id AND article_id = :article_id",
                    {"source_id": issue_id, "article_id": str(article_id)},
                )
                await self._enqueue_issue_comparisons_for_article(
                    session,
                    article_id=str(article_id),
                    request_id=self._request_id(job, result),
                    now=now,
                )
        await self._execute(
            session,
            "UPDATE issues SET version = version + 1, last_activity_at = :now WHERE id = :source_id",
            {"source_id": issue_id, "now": now},
        )
        source_member = await self._execute(
            session,
            "SELECT article_id FROM issue_memberships WHERE issue_id = :issue_id ORDER BY article_id LIMIT 1",
            {"issue_id": issue_id},
        )
        source_rows = _rows(source_member)
        if source_rows:
            await self._enqueue_issue_comparisons_for_article(
                session,
                article_id=str(_row(source_rows[0], "article_id")),
                request_id=self._request_id(job, result),
                now=now,
            )

    async def _apply_analyze(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        version_id = str(result.get("article_version_id") or job.payload.get("article_version_id") or "")
        if not version_id:
            raise ResultApplicationError("analysis result is missing article_version_id")
        assessments = result.get("assessments") or []
        if not isinstance(assessments, (list, tuple)):
            raise ResultApplicationError("analysis assessments must be a list")
        assessment_ids: list[str] = []
        for assessment_index, item in enumerate(assessments):
            if not isinstance(item, Mapping):
                continue
            alias = str(item.get("model_alias") or item.get("alias") or "unknown")
            requested_alias_id = str(item.get("model_alias_id") or _new_id())
            await self._execute(
                session,
                """
                INSERT INTO model_aliases (id, alias, provider, actual_model_id, status, config_json)
                VALUES (:id, :alias, :provider, :actual_model_id, 'ACTIVE', :config_json)
                ON DUPLICATE KEY UPDATE actual_model_id = VALUES(actual_model_id), provider = VALUES(provider)
                """,
                {"id": requested_alias_id, "alias": alias, "provider": str(item.get("provider", "worker")), "actual_model_id": str(item.get("actual_model_id", alias)), "config_json": _json({})},
            )
            # ``alias`` is the durable identity.  On a duplicate-key upsert,
            # the requested/generated ID is not the canonical row's ID; using
            # it for the assessment would violate model_assessments' FK on the
            # second analysis of an alias.  Read the row while the transaction
            # is locked and always use the database-owned ID.
            alias_result = await self._execute(
                session,
                "SELECT id FROM model_aliases WHERE alias = :alias LIMIT 1 FOR UPDATE",
                {"alias": alias},
            )
            alias_rows = _rows(alias_result)
            if not alias_rows:
                raise ResultApplicationError("model alias upsert did not return a canonical ID")
            alias_id = str(_row(alias_rows[0], "id", ""))
            if not alias_id:
                raise ResultApplicationError("model alias canonical ID is empty")
            stored_evidence = item.get("evidence_json")
            if isinstance(stored_evidence, Mapping):
                evidence = dict(stored_evidence)
                evidence.setdefault("evidence", item.get("evidence", []))
            else:
                evidence = {
                    "evidence": item.get(
                        "evidence",
                        stored_evidence if stored_evidence is not None else [],
                    )
                }
            rationale_summary = item.get("rationale_summary")
            if isinstance(rationale_summary, str) and rationale_summary.strip():
                evidence["rationale_summary"] = rationale_summary.strip()
            assessment_id = str(
                item.get("id")
                or item.get("assessment_id")
                or _stable_id(
                    "assessment:"
                    f"{job.id}:{version_id}:{alias}:"
                    f"{item.get('prompt_version') or result.get('prompt_version', 'unknown')}:"
                    f"{assessment_index}"
                )
            )
            assessment_ids.append(assessment_id)
            await self._execute(
                session,
                """
                INSERT INTO model_assessments
                  (id, article_version_id, model_alias_id, prompt_version, x, y, z,
                   sensationalism, confidence, evidence_json,
                   token_usage, latency_ms, status, created_at)
                VALUES
                  (:id, :version_id, :alias_id, :prompt_version, :x, :y, :z,
                   :sensationalism, :confidence, :evidence_json,
                   :token_usage, :latency_ms, :status, :created_at)
                ON DUPLICATE KEY UPDATE x = VALUES(x), y = VALUES(y), z = VALUES(z),
                  sensationalism = VALUES(sensationalism), confidence = VALUES(confidence),
                  evidence_json = VALUES(evidence_json),
                  token_usage = VALUES(token_usage), latency_ms = VALUES(latency_ms), status = VALUES(status)
                """,
                {
                    "id": assessment_id,
                    "version_id": str(item.get("article_version_id") or version_id),
                    "alias_id": alias_id,
                    "prompt_version": str(item.get("prompt_version") or result.get("prompt_version", "unknown")),
                    "x": int(item.get("x", 0)),
                    "y": int(item.get("y", 0)),
                    "z": int(item.get("z", 0)),
                    "sensationalism": int(item.get("sensationalism", 0)),
                    "confidence": _database_confidence(item.get("confidence", 0)),
                    "evidence_json": _json(evidence),
                    "token_usage": int(item.get("token_usage", 0)),
                    "latency_ms": int(item.get("latency_ms", 0)),
                    "status": str(item.get("status", "SUCCEEDED")).upper(),
                    "created_at": now,
                },
            )

        request_id = self._request_id(job, result)
        score_payload: dict[str, Any] = {
            "article_version_id": version_id,
            # The analysis queue row is the stable generation identity: it is
            # unchanged by lease replay, but changes for an explicit reanalysis.
            # Assessment IDs make the exact inputs visible to score provenance.
            "analysis_job_id": job.id,
            "assessment_ids": sorted(assessment_ids),
        }
        for key in ("weight_revision_id", "weight_id", "fact_check"):
            value = result.get(key, job.payload.get(key))
            if value is not None:
                score_payload[key] = value
        if request_id is not None:
            score_payload["request_id"] = request_id
        weight_id = score_payload.get("weight_revision_id") or score_payload.get("weight_id")
        score_generation = hashlib.sha256(
            _json(
                {
                    "analysis_job_id": job.id,
                    "assessment_ids": sorted(assessment_ids),
                }
            ).encode("utf-8")
        ).hexdigest()[:24]
        score_dedupe = f"article-version:{version_id}:analysis:{score_generation}"
        if weight_id is not None:
            score_dedupe = f"{score_dedupe}:weight:{weight_id}"
        await self._enqueue_job(
            session,
            "calculate_score",
            score_payload,
            dedupe_key=score_dedupe,
            now=now,
        )

        # Analysis results from the built-in handler identify the article
        # version, while integrations may include the article directly.  Use
        # the direct value when present and fall back to the durable FK lookup
        # so the cluster payload always satisfies its transport contract.
        article_ids: list[str] = []
        direct_ids = result.get("article_ids") or job.payload.get("article_ids")
        if isinstance(direct_ids, (list, tuple, set)):
            article_ids.extend(str(item) for item in direct_ids if str(item))
        for candidate in (
            result.get("article_id"),
            job.payload.get("article_id"),
        ):
            if candidate:
                article_ids.append(str(candidate))
        if not article_ids:
            article_result = await self._execute(
                session,
                "SELECT article_id FROM article_versions WHERE id = :version_id LIMIT 1",
                {"version_id": version_id},
            )
            article_rows = _rows(article_result)
            if article_rows:
                article_id = _row(article_rows[0], "article_id")
                if article_id:
                    article_ids.append(str(article_id))
        # Crawls enqueue one rolling cross-source sweep for the full recent
        # window. Analysis completion must not create singleton issue jobs.
        for article_id in sorted(set(article_ids)):
            await self._enqueue_issue_comparisons_for_article(
                session,
                article_id=article_id,
                request_id=request_id,
                now=now,
            )

    async def _enqueue_issue_comparisons_for_article(
        self,
        session: Any,
        *,
        article_id: str,
        request_id: str | None,
        now: datetime,
    ) -> None:
        issue_result = await self._execute(
            session,
            """
            SELECT i.id, i.version
            FROM issues i
            JOIN issue_memberships im ON im.issue_id = i.id
            WHERE im.article_id = :article_id
              AND i.status NOT IN ('merged', 'closed', 'archived')
            """,
            {"article_id": article_id},
        )
        for issue_row in _rows(issue_result):
            issue_id = str(_row(issue_row, "id", "") or "")
            issue_version = int(_row(issue_row, "version", 0) or 0)
            if not issue_id or issue_version < 1:
                continue
            article_result = await self._execute(
                session,
                """
                SELECT a.id AS article_id, a.current_version_id AS article_version_id
                FROM issue_memberships im
                JOIN articles a ON a.id = im.article_id
                WHERE im.issue_id = :issue_id AND a.current_version_id IS NOT NULL
                ORDER BY a.id
                """,
                {"issue_id": issue_id},
            )
            article_rows = _rows(article_result)
            if not 2 <= len(article_rows) <= 4:
                continue
            article_ids = [str(_row(row, "article_id")) for row in article_rows]
            version_ids = [str(_row(row, "article_version_id")) for row in article_rows]
            if any(not value for value in article_ids + version_ids):
                continue
            prompt_version = "issue-comparison-v1"
            payload: dict[str, Any] = {
                "issue_id": issue_id,
                "issue_version": issue_version,
                "article_ids": article_ids,
                "article_version_ids": version_ids,
                "prompt_version": prompt_version,
            }
            if request_id is not None:
                payload["request_id"] = request_id
            await self._enqueue_job(
                session,
                "build_issue_comparison",
                payload,
                dedupe_key=(
                    f"{issue_id}:{issue_version}:{':'.join(sorted(version_ids))}:"
                    f"{prompt_version}"
                ),
                now=now,
            )

    async def _apply_aggregate(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        article_id = str(result.get("article_id") or job.payload.get("article_id") or "")
        if not article_id:
            raise ResultApplicationError("vote aggregate result is missing article_id")
        raw_revision = result.get(
            "vote_revision",
            result.get(
                "source_revision",
                result.get("version", job.payload.get("vote_revision", job.payload.get("version", 1))),
            ),
        )
        if isinstance(raw_revision, bool):
            raise ResultApplicationError("vote aggregate revision must be a positive integer")
        try:
            version = int(raw_revision)
        except (TypeError, ValueError) as exc:
            raise ResultApplicationError("vote aggregate revision must be a positive integer") from exc
        if version < 1 or (isinstance(raw_revision, float) and raw_revision != version):
            raise ResultApplicationError("vote aggregate revision must be a positive integer")

        # Lock a stable parent row before reading the latest snapshot.  A
        # ``FOR UPDATE`` on an empty snapshot set would lock nothing, allowing
        # two first aggregates to race into the same version.
        await self._execute(
            session,
            "SELECT id FROM articles WHERE id = :article_id LIMIT 1 FOR UPDATE",
            {"article_id": article_id},
        )
        latest_result = await self._execute(
            session,
            """
            SELECT version FROM vote_aggregate_snapshots
            WHERE article_id = :article_id
            ORDER BY version DESC
            LIMIT 1 FOR UPDATE
            """,
            {"article_id": article_id},
        )
        latest_rows = _rows(latest_result)
        if latest_rows:
            latest_version = int(_row(latest_rows[0], "version", 0) or 0)
            if version <= latest_version:
                raise ResultApplicationError(
                    "stale vote aggregate revision",
                )
        aggregate = result.get("aggregate", result)
        segments = result.get("segments", {})
        await self._execute(
            session,
            """
            INSERT INTO vote_aggregate_snapshots
              (id, article_id, version, aggregate_json, segment_json, created_at)
            VALUES (:id, :article_id, :version, :aggregate_json, :segment_json, :created_at)
            """,
            {"id": str(result.get("snapshot_id") or _new_id()), "article_id": article_id, "version": version, "aggregate_json": _json(aggregate), "segment_json": _json(segments), "created_at": now},
        )

    async def _apply_score(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        version_id = str(result.get("article_version_id") or job.payload.get("article_version_id") or "")
        weight_id = str(result.get("weight_revision_id") or job.payload.get("weight_revision_id") or job.payload.get("weight_id") or "")
        if not version_id or not weight_id:
            raise ResultApplicationError("score result requires article_version_id and weight_revision_id")
        # Serialize all score promotions for an article version, including the
        # first one.  Locking an empty score range is not sufficient under every
        # isolation/proxy configuration; the durable article-version row is.
        version_lock = await self._execute(
            session,
            "SELECT id FROM article_versions WHERE id = :version_id LIMIT 1 FOR UPDATE",
            {"version_id": version_id},
        )
        if not _rows(version_lock):
            raise ResultApplicationError("score article version was not found")
        requested_score_id = str(
            result.get("score_version_id")
            or _stable_id(f"score:{version_id}:{weight_id}:job:{job.id}")
        )
        await self._execute(
            session,
            """
            INSERT INTO score_versions
              (id, article_version_id, weight_revision_id, x, y, z, sensationalism,
               confidence, components_json, status, created_at)
            VALUES (:id, :version_id, :weight_id, :x, :y, :z, :sensationalism,
                    :confidence, :components_json, 'draft', :created_at)
            ON DUPLICATE KEY UPDATE x = VALUES(x), y = VALUES(y), z = VALUES(z),
              sensationalism = VALUES(sensationalism), confidence = VALUES(confidence),
              components_json = VALUES(components_json)
            """,
            {"id": requested_score_id, "version_id": version_id, "weight_id": weight_id, "x": int(result.get("x", 0)), "y": int(result.get("y", 0)), "z": int(result.get("z", 0)), "sensationalism": int(result.get("sensationalism", 0)), "confidence": _database_confidence(result.get("confidence", 0)), "components_json": _json(result.get("components", {})), "created_at": now},
        )
        canonical_result = await self._execute(
            session,
            """
            SELECT id FROM score_versions
            WHERE id = :score_id
              AND article_version_id = :version_id
              AND weight_revision_id = :weight_id
            LIMIT 1 FOR UPDATE
            """,
            {
                "score_id": requested_score_id,
                "version_id": version_id,
                "weight_id": weight_id,
            },
        )
        canonical_rows = _rows(canonical_result)
        if not canonical_rows:
            raise ResultApplicationError("score upsert did not return a canonical row")
        canonical_score_id = str(_row(canonical_rows[0], "id", "") or "")
        if not canonical_score_id:
            raise ResultApplicationError("score canonical ID is empty")
        # Promotion and demotion are in the outer result-application
        # transaction.  Any failure rolls both back, preserving the previous
        # ACTIVE score instead of leaving an article temporarily scoreless.
        await self._execute(
            session,
            """
            UPDATE score_versions
            SET status = 'superseded'
            WHERE article_version_id = :version_id
              AND status = 'active'
              AND id <> :score_id
            """,
            {"version_id": version_id, "score_id": canonical_score_id},
        )
        promoted = await self._execute(
            session,
            """
            UPDATE score_versions
            SET status = 'active'
            WHERE id = :score_id
              AND article_version_id = :version_id
              AND weight_revision_id = :weight_id
            """,
            {
                "score_id": canonical_score_id,
                "version_id": version_id,
                "weight_id": weight_id,
            },
        )
        # MySQL may report zero affected rows when an idempotent replay targets
        # an already-active row, so verify canonical state before declaring a
        # conflict rather than relying solely on rowcount.
        if _rowcount(promoted) != 1:
            active_result = await self._execute(
                session,
                """
                SELECT id FROM score_versions
                WHERE id = :score_id AND status = 'active'
                LIMIT 1
                """,
                {"score_id": canonical_score_id},
            )
            if not _rows(active_result):
                raise ResultApplicationError("score activation failed")

    async def _apply_recommendation(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        recommendation_id = str(result.get("recommendation_id") or job.payload.get("recommendation_id") or "")
        base_id = str(result.get("base_revision_id") or job.payload.get("base_revision_id") or job.payload.get("weight_id") or "")
        if not recommendation_id or not base_id:
            raise ResultApplicationError("recommendation result requires recommendation_id and base_revision_id")
        weights = result.get("weights", result.get("proposed_weights", {}))
        evidence_id = result.get("evidence_snapshot_id")
        evidence = result.get("evidence_snapshot") or result.get("evidence")
        if evidence_id is None and evidence is not None:
            evidence_id = _new_id()
        if evidence_id is not None:
            await self._execute(
                session,
                """
                INSERT INTO weight_evidence_snapshots
                  (id, evidence_json, window_start, window_end, created_at)
                VALUES (:id, :evidence_json, :window_start, :window_end, :created_at)
                ON DUPLICATE KEY UPDATE evidence_json = VALUES(evidence_json)
                """,
                {
                    "id": str(evidence_id),
                    "evidence_json": _json(evidence or {}),
                    "window_start": result.get("window_start"),
                    "window_end": result.get("window_end"),
                    "created_at": now,
                },
            )
        await self._execute(
            session,
            """
            INSERT INTO weight_recommendations
              (id, base_revision_id, proposed_weights_json, evidence_snapshot_id,
               provider_assessment_ref, status, created_at)
            VALUES (:id, :base_id, :weights_json, :evidence_id, :provider_ref, 'PENDING_REVIEW', :created_at)
            ON DUPLICATE KEY UPDATE proposed_weights_json = VALUES(proposed_weights_json), provider_assessment_ref = VALUES(provider_assessment_ref)
            """,
            {"id": recommendation_id, "base_id": base_id, "weights_json": _json(weights), "evidence_id": evidence_id, "provider_ref": result.get("provider_assessment_ref"), "created_at": now},
        )

    async def _apply_simulation(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        recommendation_id = str(result.get("recommendation_id") or job.payload.get("recommendation_id") or job.payload.get("weight_id") or "")
        if not recommendation_id:
            raise ResultApplicationError("simulation result requires recommendation_id")
        windows = result.get("windows") or job.payload.get("windows") or [result.get("window_days", 7)]
        if not isinstance(windows, (list, tuple)):
            windows = [windows]
        for window in windows:
            await self._execute(
                session,
                """
                INSERT INTO weight_simulations
                  (id, recommendation_id, window_days, metrics_json, guardrail_result, created_at)
                VALUES (:id, :recommendation_id, :window_days, :metrics_json, :guardrail_result, :created_at)
                """,
                {"id": _stable_id(f"{job.id}:simulation:{int(window)}"), "recommendation_id": recommendation_id, "window_days": int(window), "metrics_json": _json({k: v for k, v in result.items() if k not in {"recommendation_id", "window_days"}}), "guardrail_result": _json(result.get("guardrail_result", {"status": result.get("status", "simulation")})), "created_at": now},
            )

    async def _apply_share_card(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        card_id = str(result.get("share_card_id") or job.payload.get("share_card_id") or "")
        if not card_id:
            raise ResultApplicationError("share result requires share_card_id")
        blob_id = result.get("blob_id")
        if not blob_id and result.get("png_base64"):
            try:
                png = base64.b64decode(str(result["png_base64"]), validate=True)
            except (ValueError, TypeError) as exc:
                raise ResultApplicationError("share result contains invalid PNG base64") from exc
            blob_id = await self._store_blob(session, png, mime_type=str(result.get("mime_type", "image/png")), expires_at=job.payload.get("expires_at"))
        if not blob_id:
            raise ResultApplicationError("share result requires blob_id or png_base64")
        updated = await self._execute(
            session,
            "UPDATE share_cards SET status = 'ready', blob_id = :blob_id WHERE id = :id AND status IN ('queued', 'rendering', 'ready')",
            {"id": card_id, "blob_id": str(blob_id)},
        )
        if _rowcount(updated) != 1:
            raise ResultApplicationError("share card could not be updated")

    async def _apply_export(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        user_id = str(result.get("user_id") or job.payload.get("user_id") or "")
        if not user_id:
            raise ResultApplicationError("export result requires user_id")
        artifact = result.get("artifact") or result.get("manifest") or result
        payload = _bytes(_json(artifact))
        blob_id = await self._store_blob(session, payload, mime_type="application/json", expires_at=now + timedelta(days=7))
        artifact_ref = result.get("artifact_ref") or result.get("export_key") or blob_id
        # There is intentionally no mutable export table in 0001.  The audit
        # result record is the durable, user-scoped artifact pointer.
        if isinstance(result, dict):
            result.clear()
            result.update({"artifact_ref": artifact_ref, "blob_id": blob_id, "user_id": user_id})

    async def _apply_delete(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        user_id = str(result.get("user_id") or job.payload.get("user_id") or "")
        if not user_id:
            raise ResultApplicationError("deletion result requires user_id")
        revoke = result.get("revoke", ["sessions", "share_tokens"])
        purge = result.get(
            "purge_or_anonymize",
            [
                "oauth_accounts",
                "demographics",
                "questionnaire_responses",
                "profiles",
                "votes",
                "read_history",
                "feed_impressions",
                "efficacy_responses",
                "share_artifacts",
            ],
        )
        if "sessions" in revoke:
            await self._execute(session, "UPDATE sessions SET revoked_at = :now WHERE user_id = :user_id AND revoked_at IS NULL", {"user_id": user_id, "now": now})
        if "share_tokens" in revoke:
            await self._execute(session, "UPDATE share_cards SET status = 'revoked', revoked_at = :now WHERE user_id = :user_id AND revoked_at IS NULL", {"user_id": user_id, "now": now})
        if "oauth_accounts" in purge:
            await self._execute(
                session,
                "DELETE FROM oauth_accounts WHERE user_id = :user_id",
                {"user_id": user_id},
            )
        if "demographics" in purge:
            await self._execute(session, "UPDATE user_demographics SET age_band = NULL, gender_response = NULL, updated_at = :now WHERE user_id = :user_id", {"user_id": user_id, "now": now})
        if "questionnaire_responses" in purge:
            await self._execute(session, "DELETE FROM questionnaire_responses WHERE user_id = :user_id", {"user_id": user_id})
        if "profiles" in purge:
            await self._execute(
                session,
                "DELETE FROM user_profiles WHERE user_id = :user_id",
                {"user_id": user_id},
            )
        if "votes" in purge:
            await self._execute(session, "DELETE FROM votes WHERE user_id = :user_id", {"user_id": user_id})
        if "read_history" in purge:
            await self._execute(session, "DELETE FROM read_sessions WHERE user_id = :user_id", {"user_id": user_id})
        if "feed_impressions" in purge:
            await self._execute(
                session,
                "DELETE FROM feed_impressions WHERE user_id = :user_id",
                {"user_id": user_id},
            )
        if "efficacy_responses" in purge:
            await self._execute(
                session,
                "DELETE FROM efficacy_responses WHERE user_id = :user_id",
                {"user_id": user_id},
            )
        if "share_artifacts" in purge:
            # Remove only blobs that become unreferenced after this user's
            # cards are redacted.  ``stored_blobs.sha256`` is globally
            # deduplicated, so deleting every blob selected by the user's
            # cards would break another user's card that points at the same
            # row.  Keep the checks for the other string-based blob references
            # as well; those legacy columns do not have FK constraints.
            await self._execute(
                session,
                """
                DELETE FROM stored_blobs
                WHERE id IN (
                    SELECT blob_id FROM share_cards
                    WHERE user_id = :user_id AND blob_id IS NOT NULL
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM share_cards other_cards
                    WHERE other_cards.blob_id = stored_blobs.id
                      AND other_cards.user_id <> :user_id
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM article_versions versions
                    WHERE versions.normalized_text_ref = stored_blobs.id
                  )
                """,
                {"user_id": user_id},
            )
            await self._execute(
                session,
                "UPDATE share_cards SET display_name = NULL, snapshot_json = '{}', blob_id = NULL, status = 'revoked', revoked_at = COALESCE(revoked_at, :now) WHERE user_id = :user_id",
                {"user_id": user_id, "now": now},
            )
        # Consent rows are retained as the minimum legal grant/withdrawal
        # evidence, but every still-open consent is withdrawn at deletion.
        await self._execute(
            session,
            "UPDATE user_consents SET withdrawn_at = COALESCE(withdrawn_at, :now) WHERE user_id = :user_id",
            {"user_id": user_id, "now": now},
        )
        await self._execute(
            session,
            "UPDATE users SET status = 'DELETED', display_name = 'Deleted member', deleted_at = :now WHERE id = :user_id AND status <> 'DELETED'",
            {"user_id": user_id, "now": now},
        )


__all__ = [
    "MariaDBIdempotencyStore",
    "MariaDBResultApplier",
    "MemoryResultApplier",
    "ResultApplier",
    "ResultApplicationError",
]
