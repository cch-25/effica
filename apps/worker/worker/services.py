"""Worker-side durable outcome application services.

Handlers intentionally return serialisable values.  This module is the
side-effect boundary that turns those values into MariaDB rows in one
transaction, records a job-linked audit event, and makes replay safe.  It
uses SQL text rather than importing API ORM models so the worker can start
without constructing the FastAPI application and so SQL contract tests can
run with tiny fake sessions.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import re
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from .handlers.base import HandlerContext, HandlerResult
from .queue import Job

try:
    from apps.api.app.jobs.types import generate_job_id, utc_now
except ImportError:  # pragma: no cover - supports PYTHONPATH=apps/worker.
    from api.app.jobs.types import generate_job_id, utc_now  # type: ignore


class ResultApplicationError(RuntimeError):
    """Raised when a handler result cannot be durably applied."""


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


class MariaDBIdempotencyStore:
    """Durable replay lookup backed by job-linked audit rows.

    The 0001 schema has no result column on ``jobs``.  A successful result is
    therefore indexed through the immutable ``JOB_RESULT_APPLIED`` audit
    record.  The row lock taken by :class:`MariaDBResultApplier` serialises
    replay with the original application; newer schemas may add a dedicated
    result table without changing this read contract.
    """

    def __init__(self, session_factory: Callable[[], Any]) -> None:
        self.session_factory = session_factory

    async def begin(self, key: str) -> tuple[str, Any]:
        # Keys are ``job_type:dedupe_key``.  The audit target is the job id, so
        # use the dedupe suffix as a fallback target lookup as well.
        token = uuid.uuid4().hex
        suffix = key.split(":", 1)[1] if ":" in key else key
        query = _sql(
            """
            SELECT after_json FROM audit_logs
            WHERE action = 'JOB_RESULT_APPLIED'
              AND target_type = 'job'
              AND (target_id = :target_id OR request_id = :idempotency_key)
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """.strip()
        )
        async with _session_scope(self.session_factory) as session:
            # An operational error here must reach the worker runtime.  A
            # missing/failed idempotency read is not evidence that no result
            # exists; treating it as a cache miss would permit a replayed
            # domain side effect during a DB outage.
            result = await _maybe_await(
                session.execute(query, {"target_id": suffix, "idempotency_key": key})
            )
            rows = _rows(result)
        if rows:
            value = _row(rows[0], "after_json")
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

    _SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        clock: Callable[[], datetime] = utc_now,
        result_table: str | None = None,
    ) -> None:
        if result_table is not None and not self._SAFE_IDENTIFIER.fullmatch(result_table):
            raise ValueError("unsafe result table name")
        self.session_factory = session_factory
        self.clock = clock
        self.result_table = result_table

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
            SELECT after_json FROM audit_logs
            WHERE action = 'JOB_RESULT_APPLIED'
              AND target_type = 'job' AND target_id = :job_id
            ORDER BY created_at DESC, id DESC
            LIMIT 1 FOR UPDATE
            """.strip()
        )
        result = await _maybe_await(session.execute(query, {"job_id": job_id}))
        rows = _rows(result)
        if not rows:
            return None
        value = _row(rows[0], "after_json")
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
        record = {
            "job_id": job.id,
            "job_type": job.job_type,
            "idempotency_key": f"{job.job_type}:{job.dedupe_key or job.id}",
            "result": dict(value),
        }
        # Existing schema support: audit_logs is the durable job result index
        # and keeps request_id/job_id linkage visible to operations tooling.
        await _maybe_await(
            session.execute(
                _sql(
                    """
                    INSERT INTO audit_logs
                      (id, actor_id, action, target_type, target_id,
                       before_json, after_json, reason, request_id, created_at)
                    VALUES
                      (:id, NULL, 'JOB_RESULT_APPLIED', 'job', :target_id,
                       NULL, :after_json, :reason, :request_id, :created_at)
                    """.strip()
                ),
                {
                    "id": _new_id(),
                    "target_id": job.id,
                    "after_json": _json(record),
                    "reason": f"worker result applied: {job.job_type}",
                    "request_id": request_id
                    or job.payload.get("request_id")
                    or f"{job.job_type}:{job.dedupe_key or job.id}",
                    "created_at": now,
                },
            )
        )
        if self.result_table is not None:
            # Optional additive 0002 table.  It is opt-in so the worker stays
            # compatible with 0001 while deployments can persist a compact
            # result projection in addition to the audit record.
            await _maybe_await(
                session.execute(
                    _sql(
                        f"""
                        INSERT INTO {self.result_table}
                          (job_id, job_type, result_json, applied_at)
                        VALUES (:job_id, :job_type, :result_json, :applied_at)
                        ON DUPLICATE KEY UPDATE result_json = VALUES(result_json), applied_at = VALUES(applied_at)
                        """.strip()
                    ),
                    {
                        "job_id": job.id,
                        "job_type": job.job_type,
                        "result_json": _json(value),
                        "applied_at": now,
                    },
                )
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

    async def _execute(self, session: Any, statement: str, params: Mapping[str, Any]) -> Any:
        return await _maybe_await(session.execute(_sql(statement.strip()), dict(params)))

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
                "expires_at": expires_at,
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
        for article in articles:
            if not isinstance(article, Mapping):
                continue
            url = str(article.get("url") or article.get("canonical_url") or result.get("url") or "")
            title = str(article.get("title") or "Untitled article")[:500]
            if not url:
                continue
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
                   NULL, 'active', :created_at, :updated_at)
                ON DUPLICATE KEY UPDATE title = VALUES(title), author = VALUES(author), updated_at = VALUES(updated_at)
                """,
                {
                    "id": article_id,
                    "source_id": source_id or article.get("source_id"),
                    "url": url,
                    "url_hash": canonical_hash,
                    "title": title,
                    "author": article.get("author"),
                    "published_at": article.get("published_at"),
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
            content = article.get("content") or article.get("text")
            if (
                content is None
                and article.get("raw_payload_ref") is None
                and article.get("raw_payload") is None
            ):
                continue
            version_id = str(article.get("article_version_id") or article.get("version_id") or _new_id())
            normalized_ref = None
            if content is not None:
                normalized_ref = await self._store_blob(
                    session, _bytes(content), mime_type="text/plain; charset=utf-8"
                )
            existing_raw_ref = article.get("raw_payload_ref")
            raw_payload = article.get("raw_payload")
            if existing_raw_ref is not None:
                raw_ref = str(existing_raw_ref)
            elif raw_payload is not None:
                is_json = isinstance(raw_payload, (Mapping, list, tuple))
                raw_bytes = _bytes(_json(raw_payload) if is_json else raw_payload)
                raw_ref = await self._store_blob(
                    session,
                    raw_bytes,
                    mime_type=(
                        "application/json" if is_json else str(article.get("raw_mime_type") or "application/octet-stream")
                    ),
                    expires_at=article.get("raw_payload_expires_at"),
                )
            else:
                raw_ref = None
            content_hash = hashlib.sha256(
                _bytes(content if content is not None else raw_payload or raw_ref or "")
            ).digest()
            await self._execute(
                session,
                """
                INSERT INTO article_versions
                  (id, article_id, content_hash, normalized_text_ref, raw_payload_ref,
                   raw_payload_expires_at, fetched_at, modified_at)
                VALUES (:id, :article_id, :content_hash, :normalized_ref, :raw_ref,
                        :raw_expires_at, :fetched_at, :modified_at)
                ON DUPLICATE KEY UPDATE normalized_text_ref = VALUES(normalized_text_ref),
                  raw_payload_ref = VALUES(raw_payload_ref),
                  raw_payload_expires_at = VALUES(raw_payload_expires_at),
                  modified_at = VALUES(modified_at)
                """,
                {
                    "id": version_id,
                    "article_id": article_id,
                    "content_hash": content_hash,
                    "normalized_ref": normalized_ref,
                    "raw_ref": raw_ref,
                    "raw_expires_at": article.get("raw_payload_expires_at"),
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

    async def _apply_cluster(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        candidates = result.get("candidates") or result.get("groups") or []
        if isinstance(candidates, Mapping):
            candidates = list(candidates.values())
        for candidate in candidates if isinstance(candidates, (list, tuple)) else ():
            if not isinstance(candidate, Mapping):
                continue
            issue_id = str(
                candidate.get("issue_id")
                or _stable_id(f"cluster:{candidate.get('candidate_id', _json(candidate))}")
            )
            title = str(candidate.get("title") or "Untitled issue")[:500]
            await self._execute(
                session,
                """
                INSERT INTO issues
                  (id, title, summary, status, opened_at, last_activity_at, version)
                VALUES (:id, :title, :summary, 'candidate', :opened_at, :last_activity_at, 1)
                ON DUPLICATE KEY UPDATE title = VALUES(title), last_activity_at = VALUES(last_activity_at), version = version + 1
                """,
                {"id": issue_id, "title": title, "summary": candidate.get("summary"), "opened_at": now, "last_activity_at": now},
            )
            articles = candidate.get("article_ids") or candidate.get("articles") or []
            for item in articles if isinstance(articles, (list, tuple)) else ():
                article_id = str(item.get("article_id") if isinstance(item, Mapping) else item)
                confidence = float(item.get("confidence", 0.0) if isinstance(item, Mapping) else candidate.get("confidence", 0.0))
                await self._execute(
                    session,
                    """
                    INSERT INTO issue_memberships (issue_id, article_id, confidence, created_at)
                    VALUES (:issue_id, :article_id, :confidence, :created_at)
                    ON DUPLICATE KEY UPDATE confidence = VALUES(confidence)
                    """,
                    {"issue_id": issue_id, "article_id": article_id, "confidence": max(0.0, min(1.0, confidence)), "created_at": now},
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
        await self._execute(
            session,
            "UPDATE issues SET version = version + 1, last_activity_at = :now WHERE id = :source_id",
            {"source_id": issue_id, "now": now},
        )

    async def _apply_analyze(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        version_id = str(result.get("article_version_id") or job.payload.get("article_version_id") or "")
        if not version_id:
            raise ResultApplicationError("analysis result is missing article_version_id")
        assessments = result.get("assessments") or []
        if not isinstance(assessments, (list, tuple)):
            raise ResultApplicationError("analysis assessments must be a list")
        raw_ref: str | None = None
        raw_response = result.get("raw_response")
        if raw_response is not None:
            raw_ref = await self._store_blob(session, _bytes(_json(raw_response)), mime_type="application/json")
        for item in assessments:
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
            evidence = item.get("evidence", item.get("evidence_json", []))
            assessment_id = str(item.get("id") or item.get("assessment_id") or _new_id())
            await self._execute(
                session,
                """
                INSERT INTO model_assessments
                  (id, article_version_id, model_alias_id, prompt_version, x, y, z,
                   sensationalism, confidence, evidence_json, raw_response_ref,
                   token_usage, latency_ms, status, created_at)
                VALUES
                  (:id, :version_id, :alias_id, :prompt_version, :x, :y, :z,
                   :sensationalism, :confidence, :evidence_json, :raw_ref,
                   :token_usage, :latency_ms, :status, :created_at)
                ON DUPLICATE KEY UPDATE x = VALUES(x), y = VALUES(y), z = VALUES(z),
                  sensationalism = VALUES(sensationalism), confidence = VALUES(confidence),
                  evidence_json = VALUES(evidence_json), raw_response_ref = VALUES(raw_response_ref),
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
                    "confidence": float(item.get("confidence", 0)),
                    "evidence_json": _json(evidence),
                    "raw_ref": str(item.get("raw_response_ref") or raw_ref) if (item.get("raw_response_ref") or raw_ref) else None,
                    "token_usage": int(item.get("token_usage", 0)),
                    "latency_ms": int(item.get("latency_ms", 0)),
                    "status": str(item.get("status", "SUCCEEDED")).upper(),
                    "created_at": now,
                },
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
              components_json = VALUES(components_json), status = VALUES(status)
            """,
            {"id": str(result.get("score_version_id") or _new_id()), "version_id": version_id, "weight_id": weight_id, "x": int(result.get("x", 0)), "y": int(result.get("y", 0)), "z": int(result.get("z", 0)), "sensationalism": int(result.get("sensationalism", 0)), "confidence": float(result.get("confidence", 0)), "components_json": _json(result.get("components", {})), "created_at": now},
        )

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
        await self._execute(
            session,
            "UPDATE share_cards SET status = 'ready', blob_id = :blob_id WHERE id = :id AND status IN ('queued', 'rendering', 'ready')",
            {"id": card_id, "blob_id": str(blob_id)},
        )

    async def _apply_export(self, session: Any, job: Job, result: Mapping[str, Any], now: datetime) -> None:
        user_id = str(result.get("user_id") or job.payload.get("user_id") or "")
        if not user_id:
            raise ResultApplicationError("export result requires user_id")
        artifact = result.get("artifact") or result.get("manifest") or result
        payload = _bytes(_json(artifact))
        blob_id = await self._store_blob(session, payload, mime_type="application/json")
        artifact_ref = result.get("artifact_ref") or result.get("export_key") or blob_id
        # There is intentionally no mutable export table in 0001.  The audit
        # result record is the durable, user-scoped artifact pointer.
        await self._execute(
            session,
            "INSERT INTO audit_logs (id, actor_id, action, target_type, target_id, before_json, after_json, reason, request_id, created_at) VALUES (:id, NULL, 'USER_EXPORT_READY', 'user', :target_id, NULL, :after_json, :reason, :request_id, :created_at)",
            {"id": _new_id(), "target_id": user_id, "after_json": _json({"artifact_ref": artifact_ref, "blob_id": blob_id, "user_id": user_id}), "reason": f"export artifact for job {job.id}", "request_id": job.payload.get("request_id") or job.id, "created_at": now},
        )

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
                       OR versions.raw_payload_ref = stored_blobs.id
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM model_assessments assessments
                    WHERE assessments.raw_response_ref = stored_blobs.id
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
            "UPDATE audit_logs SET actor_id = NULL WHERE actor_id = :user_id",
            {"user_id": user_id},
        )
        await self._execute(
            session,
            "UPDATE users SET status = 'DELETED', display_name = 'Deleted member', deleted_at = :now WHERE id = :user_id AND status <> 'DELETED'",
            {"user_id": user_id, "now": now},
        )


# Compatibility names for callers that describe the component as a worker
# service rather than an outcome applier.
MariaDBWorkerService = MariaDBResultApplier
DurableResultApplier = MariaDBResultApplier
MemoryWorkerService = MemoryResultApplier


__all__ = [
    "DurableResultApplier",
    "MariaDBIdempotencyStore",
    "MariaDBResultApplier",
    "MariaDBWorkerService",
    "MemoryResultApplier",
    "MemoryWorkerService",
    "ResultApplier",
    "ResultApplicationError",
]
