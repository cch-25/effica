"""Durable repository operations for the administrator API.

The HTTP layer deliberately stays thin.  This mixin owns the state transitions
used by the ``/admin`` endpoints and is mixed into
``MariaDBPlatformRepository`` by the API composition root.  There is no
admin-only table in the physical schema: idempotency records are represented by
``AuditLog`` rows and source/model versions are derived from their audit
history because those legacy tables do not have a version column.

Methods return JSON-friendly dictionaries (or lists of dictionaries) so route
handlers can apply their normal cursor and response-model handling.  All
mutating methods accept an optional ``idempotency_key``; production routes are
expected to require it, while the optional form keeps the repository useful to
workers and migrations that do not originate from HTTP.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.logging import redact
from apps.api.app.db.enums import (
    AdapterType,
    AutoPilotMode,
    CrawlStatus,
    IssueStatus,
    JobStatus,
    ModelStatus,
    RecommendationStatus,
    RevisionStatus,
    SourcePolicyStatus,
    SourceType,
)
from apps.api.app.db.models import (
    Article,
    AuditLog,
    AutopilotSetting,
    CrawlRun,
    EfficacyAggregateSnapshot,
    EfficacyResponse,
    Issue,
    IssueComparisonSnapshot,
    IssueMembership,
    Job,
    ModelAlias,
    ModelAssessment,
    Source,
    SourceAdapter,
    WeightEvidenceSnapshot,
    WeightProfileRevision,
    WeightRecommendation,
    WeightSimulation,
)
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.jobs.payloads import JobPayloadError, validate_job_payload

T = TypeVar("T")

_OPENAI_PROVIDER = "openai"
_OPENAI_SECRET_ENV = "OPENAI_API_KEY"
_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})


def _validate_gpt_model(value: Any) -> str:
    model = str(value or "").strip()
    if not model.startswith("gpt-"):
        raise AdminValidationError("actual_model_id must be an OpenAI GPT model ID.")
    return model


def _validate_reasoning_effort(value: Any) -> str:
    effort = str(value or "").strip()
    if effort not in _REASONING_EFFORTS:
        raise AdminValidationError(
            "reasoning_effort must be none, low, medium, high, xhigh, or max."
        )
    return effort


class AdminRepositoryError(Exception):
    """Base error that route adapters can translate into a stable API error."""

    status_code = 409
    code = "ADMIN_REPOSITORY_ERROR"
    retryable = False

    def __init__(self, message: str | None = None, *, details: Mapping[str, Any] | None = None):
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = dict(details or {})


class AdminNotFoundError(AdminRepositoryError):
    status_code = 404
    code = "NOT_FOUND"


class AdminValidationError(AdminRepositoryError):
    status_code = 400
    code = "ADMIN_VALIDATION_ERROR"


class AdminForbiddenError(AdminRepositoryError):
    status_code = 403
    code = "ADMIN_FORBIDDEN"


class AdminPreconditionError(AdminRepositoryError):
    status_code = 428
    code = "IF_MATCH_REQUIRED"


class AdminConflictError(AdminRepositoryError):
    status_code = 409
    code = "VERSION_CONFLICT"


class IdempotencyConflictError(AdminConflictError):
    code = "IDEMPOTENCY_KEY_REUSED"


class CrawlerPolicyError(AdminForbiddenError):
    code = "CRAWLER_POLICY_NOT_APPROVED"


class GuardrailError(AdminConflictError):
    code = "GUARDRAIL_NOT_SATISFIED"


def _value(value: Any) -> Any:
    """Return an enum's persisted value without assuming a concrete enum type."""

    return getattr(value, "value", value)


def _jsonable(value: Any) -> Any:
    """Convert SQLAlchemy values to values accepted by a JSON column."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _safe_json(value: Any) -> Any:
    """Normalize and redact values before writing audit/idempotency JSON."""

    return redact(_jsonable(value))


def _safe_response(value: Any, *, key: str | None = None) -> Any:
    """Redact response secrets while retaining the safe env-var selector.

    ``secret_env_name`` identifies which server-side credential to load; it
    is explicitly part of the admin response contract.  The credential value
    itself is never present in repository results.  The generic logging
    redactor treats every key containing ``secret`` as sensitive, so response
    replay needs this narrowly scoped exception to remain byte-for-byte
    idempotent with the original response.
    """

    if key == "secret_env_name":
        return _jsonable(value)
    normalized = _jsonable(value)
    if isinstance(normalized, Mapping):
        return {str(name): _safe_response(item, key=str(name)) for name, item in normalized.items()}
    if isinstance(normalized, list):
        return [_safe_response(item) for item in normalized]
    return redact(normalized, key=key)


def _payload_digest(payload: Mapping[str, Any] | Any) -> str:
    canonical = json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalise_status(value: Any, enum_type: type[Enum], *, field: str) -> Any:
    candidate = _value(value)
    # SourceCreate historically used UNKNOWN for a not-yet-recorded policy;
    # the physical source policy enum uses PENDING for that state.
    if candidate == "UNKNOWN" and enum_type is SourcePolicyStatus:
        candidate = SourcePolicyStatus.PENDING.value
    try:
        return enum_type(candidate)
    except (TypeError, ValueError) as exc:
        if isinstance(candidate, str):
            folded = candidate.casefold()
            for member in enum_type:
                if str(member.value).casefold() == folded:
                    return member
        allowed = [item.value for item in enum_type]
        raise AdminValidationError(
            f"{field} must be one of {', '.join(allowed)}",
            details={"field": field, "allowed": allowed},
        ) from exc


def _if_match_version(if_match: str | int | None, *, resource: str) -> int:
    if if_match is None or str(if_match).strip() == "":
        raise AdminPreconditionError(
            f"If-Match is required for {resource} updates.",
            details={"resource": resource},
        )
    raw = str(if_match).strip().strip('"')
    try:
        version = int(raw)
    except ValueError as exc:
        raise AdminConflictError(
            f"If-Match does not match the {resource} version.",
            details={"resource": resource, "expected": raw},
        ) from exc
    if version < 1:
        raise AdminConflictError(
            f"If-Match does not match the {resource} version.",
            details={"resource": resource, "expected": raw},
        )
    return version


def _row_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


class AdminRepositoryMixin:
    """Async SQLAlchemy persistence boundary for all administrator actions.

    The host class is expected to provide ``session: AsyncSession``.  The
    methods intentionally do not depend on any in-memory ``PlatformState``.
    """

    session: AsyncSession

    # ------------------------------------------------------------------
    # Transaction, audit, and idempotency primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _idempotency_target(scope: str, key: str) -> str:
        # A digest keeps arbitrary client keys inside AuditLog.target_id's
        # 128-character limit and avoids putting secrets in operational logs.
        return hashlib.sha256(f"{scope}\x00{key}".encode()).hexdigest()

    async def _idempotency_record(
        self,
        scope: str,
        key: str | None,
    ) -> AuditLog | None:
        if not key:
            return None
        return await self.session.scalar(
            select(AuditLog)
            .where(
                AuditLog.action == "IDEMPOTENCY_RECORDED",
                AuditLog.target_type == "idempotency",
                AuditLog.target_id == self._idempotency_target(scope, key),
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .with_for_update()
        )

    async def _run_mutation(
        self,
        *,
        scope: str,
        idempotency_key: str | None,
        payload: Mapping[str, Any] | Any,
        actor_id: str | None,
        action: str,
        target_type: str,
        target_id: str | None,
        reason: str | None,
        request_id: str | None,
        operation: Callable[[], Awaitable[tuple[T, Any, Any]]],
    ) -> T:
        """Run a mutation, write its audit record, and persist replay data.

        The repository owns its request-scoped session.  A prior authentication
        read may have opened an implicit SQLAlchemy transaction, so this method
        deliberately commits the active transaction after the mutation rather
        than assuming ``session.begin()`` is always available.
        """

        digest = _payload_digest(payload)
        try:
            prior = await self._idempotency_record(scope, idempotency_key)
            if prior is not None:
                stored = prior.after_json or {}
                if stored.get("request_digest") != digest:
                    raise IdempotencyConflictError(
                        "This Idempotency-Key was already used with another request.",
                        details={"scope": scope},
                    )
                return deepcopy(stored.get("response"))

            result, before, after = await operation()
            await self.session.flush()

            resolved_target_id = target_id
            if resolved_target_id is None and isinstance(result, Mapping):
                resolved_target_id = next(
                    (
                        candidate
                        for candidate in (
                            result.get("id"),
                            result.get("source_id"),
                            result.get("model_id"),
                            result.get("weight_id"),
                            result.get("recommendation_id"),
                        )
                        if candidate is not None
                    ),
                    None,
                )

            self.session.add(
                AuditLog(
                    id=new_ulid(),
                    actor_id=actor_id,
                    action=action,
                    target_type=target_type,
                    target_id=resolved_target_id,
                    before_json=_safe_json(before),
                    after_json=_safe_json(after),
                    reason=reason,
                    request_id=request_id,
                    created_at=utc_now(),
                )
            )

            if idempotency_key:
                self.session.add(
                    AuditLog(
                        id=new_ulid(),
                        actor_id=actor_id,
                        action="IDEMPOTENCY_RECORDED",
                        target_type="idempotency",
                        target_id=self._idempotency_target(scope, idempotency_key),
                        before_json=None,
                        after_json={
                            "request_digest": digest,
                            "scope": scope,
                            "response": _safe_response(result),
                        },
                        reason="durable idempotency record",
                        request_id=request_id,
                        created_at=utc_now(),
                    )
                )
            await self.session.commit()
            return result
        except BaseException:
            await self.session.rollback()
            raise

    async def _audit_version(self, target_type: str, target_id: str, actions: Sequence[str]) -> int:
        count = await self.session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.target_type == target_type,
                AuditLog.target_id == target_id,
                AuditLog.action.in_(tuple(actions)),
            )
        )
        return max(1, int(count or 0))

    async def _autopilot_row(self, *, lock: bool = False) -> AutopilotSetting | None:
        query = select(AutopilotSetting).where(AutopilotSetting.singleton_key == "global")
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def _ensure_autopilot_row(self, *, actor_id: str | None = None) -> AutopilotSetting:
        row = await self._autopilot_row(lock=True)
        if row is not None:
            return row
        row = AutopilotSetting(
            id=new_ulid(),
            singleton_key="global",
            mode=AutoPilotMode.OFF,
            guardrails_json={"guardrails": {}, "manual_locks": []},
            version=1,
            updated_by=actor_id,
            updated_at=utc_now(),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    # ------------------------------------------------------------------
    # Row views
    # ------------------------------------------------------------------

    async def _source_view(self, row: Source, *, version: int | None = None) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "source_type": _value(row.source_type),
            "canonical_url": row.canonical_url,
            "policy_status": _value(row.policy_status),
            "robots_status": _value(row.robots_status),
            "terms_status": _value(row.terms_status),
            "active": row.active,
            # Sources predate an explicit version column.  Audit-backed
            # monotonic versions preserve If-Match semantics for callers.
            "version": version
            if version is not None
            else await self._audit_version("source", row.id, ("SOURCE_CREATED", "SOURCE_UPDATED")),
        }

    async def _model_view(self, row: ModelAlias, *, version: int | None = None) -> dict[str, Any]:
        config = deepcopy(row.config_json or {})
        configured_secret = config.get("secret_env_name")
        # ``secret_env_name`` is an operational selector, not the secret
        # itself.  It is exposed only at the top level; config_json is safe to
        # log and return to callers.
        if "secret_env_name" in config:
            config["secret_env_name"] = "[REDACTED]"
        return {
            "id": row.id,
            "alias": row.alias,
            "provider": row.provider,
            "actual_model_id": row.actual_model_id,
            "reasoning_effort": config.get("reasoning_effort", "xhigh"),
            "secret_env_name": configured_secret,
            "status": _value(row.status),
            "config_json": _safe_json(config),
            "version": version
            if version is not None
            else await self._audit_version("model", row.id, ("MODEL_CREATED", "MODEL_UPDATED")),
        }

    @staticmethod
    def _weight_view(row: WeightProfileRevision) -> dict[str, Any]:
        return {
            "id": row.id,
            "revision": row.revision,
            "status": _value(row.status),
            "weights": deepcopy(row.weights_json or {}),
            "guardrails": deepcopy(row.guardrails_json or {}),
            "based_on_revision_id": row.based_on_revision_id,
            "created_by": row.created_by,
            "created_at": _row_datetime(row.created_at),
            "published_at": _row_datetime(row.published_at),
        }

    @staticmethod
    def _job_view(row: Job) -> dict[str, Any]:
        payload = deepcopy(row.payload_json or {})
        return {
            "id": row.id,
            "job_id": row.id,
            "job_type": row.job_type,
            "dedupe_key": row.dedupe_key,
            "status": _value(row.status),
            "priority": row.priority,
            "available_at": _row_datetime(row.available_at),
            "lease_owner": row.lease_owner,
            "lease_expires_at": _row_datetime(row.lease_expires_at),
            "attempts": row.attempts,
            "max_attempts": row.max_attempts,
            "payload": _safe_json(payload),
            "payload_json": _safe_json(payload),
            "last_error": _safe_json(row.last_error_json),
            "last_error_json": _safe_json(row.last_error_json),
            "created_at": _row_datetime(row.created_at),
            "updated_at": _row_datetime(row.updated_at),
        }

    @staticmethod
    def _settings_view(row: AutopilotSetting) -> dict[str, Any]:
        stored = deepcopy(row.guardrails_json or {})
        if "guardrails" in stored:
            guardrails = stored.get("guardrails") or {}
            locks = stored.get("manual_locks") or []
        else:
            # Rows from the first migration stored guardrails directly.
            locks = stored.pop("manual_locks", []) if isinstance(stored, dict) else []
            guardrails = stored if isinstance(stored, dict) else {}
        return {
            "mode": _value(row.mode),
            "guardrails": guardrails,
            "manual_locks": list(locks),
            "version": row.version,
            "updated_by": row.updated_by,
            "updated_at": _row_datetime(row.updated_at),
        }

    # ------------------------------------------------------------------
    # Sources and crawling
    # ------------------------------------------------------------------

    async def list_sources(self) -> list[dict[str, Any]]:
        rows = list((await self.session.scalars(select(Source).order_by(Source.id))).all())
        return [await self._source_view(row) for row in rows]

    async def get_source(self, source_id: str) -> dict[str, Any]:
        row = await self.session.get(Source, source_id)
        if row is None:
            raise AdminNotFoundError("Source was not found.", details={"source_id": source_id})
        return await self._source_view(row)

    async def create_source(
        self,
        values: Mapping[str, Any],
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str = "create source",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(values)

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            source_type = _normalise_status(
                payload.get("source_type"), SourceType, field="source_type"
            )
            policy = _normalise_status(
                payload.get("policy_status", SourcePolicyStatus.PENDING.value),
                SourcePolicyStatus,
                field="policy_status",
            )
            robots_value = payload.get("robots_status", SourcePolicyStatus.PENDING.value)
            terms_value = payload.get("terms_status", SourcePolicyStatus.PENDING.value)
            robots = _normalise_status(
                SourcePolicyStatus.PENDING.value if robots_value == "UNKNOWN" else robots_value,
                SourcePolicyStatus,
                field="robots_status",
            )
            terms = _normalise_status(
                SourcePolicyStatus.PENDING.value if terms_value == "UNKNOWN" else terms_value,
                SourcePolicyStatus,
                field="terms_status",
            )
            name = str(payload.get("name", "")).strip()
            url = str(payload.get("canonical_url", "")).strip()
            if not name or not url:
                raise AdminValidationError("Source name and canonical_url are required.")
            duplicate = await self.session.scalar(
                select(Source).where(Source.canonical_url == url).with_for_update()
            )
            if duplicate is not None:
                raise AdminConflictError(
                    "A source with this canonical_url already exists.",
                    details={"code": "SOURCE_ALREADY_EXISTS", "source_id": duplicate.id},
                )
            row = Source(
                id=new_ulid(),
                name=name,
                source_type=source_type,
                canonical_url=url,
                policy_status=policy,
                robots_status=robots,
                terms_status=terms,
                active=bool(payload.get("active", True)),
            )
            self.session.add(row)
            await self.session.flush()
            # Optional adapter metadata is accepted without changing the
            # Source API shape, useful for callers that already have it.
            adapter_type = payload.get("adapter_type")
            # A source created through the public contract may provide
            # adapter settings without repeating the source type.  Infer the
            # compatible adapter only when settings were actually supplied;
            # legacy source rows still remain adapter-less.
            if adapter_type is None and any(
                payload.get(field) not in (None, {}, "")
                for field in ("config_json", "rate_limit", "raw_payload_retention_days")
            ):
                adapter_type = source_type
            if adapter_type is not None:
                adapter = SourceAdapter(
                    id=new_ulid(),
                    source_id=row.id,
                    adapter_type=_normalise_status(adapter_type, AdapterType, field="adapter_type"),
                    config_json=deepcopy(payload.get("config_json") or {}),
                    rate_limit=payload.get("rate_limit"),
                    raw_payload_retention_days=payload.get("raw_payload_retention_days"),
                    active=bool(payload.get("adapter_active", True)),
                )
                self.session.add(adapter)
                await self.session.flush()
            result = await self._source_view(row, version=1)
            return result, None, result

        return await self._run_mutation(
            scope="admin:create-source",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="SOURCE_CREATED",
            target_type="source",
            target_id=None,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    async def update_source(
        self,
        source_id: str,
        values: Mapping[str, Any],
        *,
        if_match: str | int | None,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(values)
        expected = _if_match_version(if_match, resource="source")

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            row = await self.session.scalar(
                select(Source).where(Source.id == source_id).with_for_update()
            )
            if row is None:
                raise AdminNotFoundError("Source was not found.", details={"source_id": source_id})
            current = await self._audit_version(
                "source", source_id, ("SOURCE_CREATED", "SOURCE_UPDATED")
            )
            if current != expected:
                raise AdminConflictError(
                    "If-Match does not match the source version.",
                    details={"resource": "source", "expected": expected, "actual": current},
                )
            before = await self._source_view(row, version=current)
            allowed = {"name", "policy_status", "robots_status", "terms_status", "active"}
            for field, value in payload.items():
                if field not in allowed:
                    continue
                if field == "name":
                    if not str(value).strip():
                        raise AdminValidationError("Source name cannot be empty.")
                    row.name = str(value).strip()
                elif field in {"policy_status", "robots_status", "terms_status"}:
                    if field in {"robots_status", "terms_status"} and value == "UNKNOWN":
                        value = SourcePolicyStatus.PENDING.value
                    setattr(
                        row,
                        field,
                        _normalise_status(value, SourcePolicyStatus, field=field),
                    )
                else:
                    row.active = bool(value)
            await self.session.flush()
            after = await self._source_view(row, version=current + 1)
            return after, before, after

        return await self._run_mutation(
            scope=f"admin:source:{source_id}",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="SOURCE_UPDATED",
            target_type="source",
            target_id=source_id,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    patch_source = update_source

    async def enqueue_crawl(
        self,
        source_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str = "enqueue crawl",
        request_id: str | None = None,
        mode: str = "live",
    ) -> dict[str, Any]:
        payload_input = {"source_id": source_id, "mode": mode, "reason": reason}

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            source = await self.session.get(Source, source_id)
            if source is None:
                raise AdminNotFoundError("Source was not found.", details={"source_id": source_id})
            source_type = str(_value(source.source_type))
            statuses = {
                "policy_status": str(_value(source.policy_status)),
                "robots_status": str(_value(source.robots_status)),
                "terms_status": str(_value(source.terms_status)),
            }
            if source_type == SourceType.CRAWLER.value and any(
                statuses[name] != SourcePolicyStatus.APPROVED.value for name in statuses
            ):
                raise CrawlerPolicyError(
                    "Crawler policy, robots and terms approval are required.",
                    details=statuses,
                )
            job_payload = {
                "source_id": source.id,
                "url": source.canonical_url,
                "source_type": source_type,
                **statuses,
                "actor_id": actor_id,
                "reason": reason,
                "mode": mode,
            }
            dedupe = f"{source.id}:{idempotency_key or _payload_digest(job_payload)}"
            job = await self._enqueue_job_row("crawl", dedupe, job_payload)
            # CrawlRun gives the admin listing durable execution/error/stats
            # fields even before a worker claims the queue item.  Replays find
            # the existing run by the deterministic job id.
            run = await self.session.get(CrawlRun, job.id)
            if run is None:
                run = CrawlRun(
                    id=job.id,
                    source_id=source.id,
                    status=CrawlStatus.PENDING,
                    started_at=None,
                    finished_at=None,
                    stats_json=None,
                    error_json=None,
                )
                self.session.add(run)
                await self.session.flush()
            result = {"job_id": job.id, "status": JobStatus.PENDING.value}
            return result, None, {"job": result, "source_id": source.id}

        return await self._run_mutation(
            scope=f"admin:crawl:{source_id}",
            idempotency_key=idempotency_key,
            payload=payload_input,
            actor_id=actor_id,
            action="CRAWL_ENQUEUED",
            target_type="source",
            target_id=source_id,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    async def list_crawls(self) -> list[dict[str, Any]]:
        runs = list(
            (await self.session.scalars(select(CrawlRun).order_by(CrawlRun.id.desc()))).all()
        )
        if not runs:
            # Preserve visibility for queue rows created by older producers.
            jobs_rows = list(
                (
                    await self.session.scalars(
                        select(Job).where(Job.job_type == "crawl").order_by(Job.created_at.desc())
                    )
                ).all()
            )
            return [self._job_view(job) for job in jobs_rows]
        jobs_by_id = {
            job.id: job
            for job in (
                await self.session.scalars(select(Job).where(Job.job_type == "crawl"))
            ).all()
        }
        result: list[dict[str, Any]] = []
        for run in runs:
            job = jobs_by_id.get(run.id)
            row = {
                "id": run.id,
                "crawl_run_id": run.id,
                "job_id": run.id if job is not None else None,
                "source_id": run.source_id,
                "status": _value(run.status),
                "started_at": _row_datetime(run.started_at),
                "finished_at": _row_datetime(run.finished_at),
                "stats": _safe_json(run.stats_json),
                "stats_json": _safe_json(run.stats_json),
                "error": _safe_json(run.error_json),
                "error_json": _safe_json(run.error_json),
            }
            if job is not None:
                row["job_status"] = _value(job.status)
            result.append(row)
        return result

    # ------------------------------------------------------------------
    # Issue operations
    # ------------------------------------------------------------------

    async def enqueue_merge_issue(
        self,
        issue_id: str,
        target_issue_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str = "enqueue issue merge",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {"source_issue_id": issue_id, "target_issue_id": target_issue_id, "reason": reason}

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            if issue_id == target_issue_id:
                raise AdminValidationError(
                    "An issue cannot be merged into itself.",
                    details={"code": "INVALID_ISSUE_OPERATION_PAYLOAD"},
                )
            # Lock the source before deriving a missing target.  The merge
            # output is allowed to be a new issue; only the source must exist
            # at enqueue time.  Creating the target in this same mutation
            # keeps the target row, queue row, and enqueue audit atomic.
            source = await self.session.scalar(
                select(Issue).where(Issue.id == issue_id).with_for_update()
            )
            if source is None:
                raise AdminNotFoundError(
                    "Source issue was not found.", details={"issue_id": issue_id}
                )
            target = await self.session.scalar(
                select(Issue).where(Issue.id == target_issue_id).with_for_update()
            )
            target_created = target is None
            if target_created:
                now = utc_now()
                target = Issue(
                    id=target_issue_id,
                    title=source.title,
                    summary=source.summary,
                    status=IssueStatus.CANDIDATE,
                    opened_at=now,
                    last_activity_at=now,
                    version=1,
                )
                self.session.add(target)
                await self.session.flush()
            job_payload = {**payload, "actor_id": actor_id}
            dedupe = (
                f"{issue_id}:{target_issue_id}:{idempotency_key or _payload_digest(job_payload)}"
            )
            job = await self._enqueue_job_row("merge_issue", dedupe, job_payload)
            result = {"job_id": job.id, "status": JobStatus.PENDING.value}
            return result, None, {
                "job": result,
                **payload,
                "target_created": target_created,
            }

        return await self._run_mutation(
            scope=f"admin:merge-issue:{issue_id}:{target_issue_id}",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="ISSUE_MERGE_ENQUEUED",
            target_type="issue",
            target_id=issue_id,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    async def enqueue_split_issue(
        self,
        issue_id: str,
        article_ids: Sequence[str],
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str = "enqueue issue split",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        article_list = [str(item) for item in article_ids]
        payload = {"issue_id": issue_id, "article_ids": article_list, "reason": reason}

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            if not article_list or len(set(article_list)) != len(article_list):
                raise AdminValidationError(
                    "article_ids must be a non-empty list of unique identifiers.",
                    details={"code": "ISSUE_SPLIT_INVALID"},
                )
            issue = await self.session.get(Issue, issue_id)
            if issue is None:
                raise AdminNotFoundError("Issue was not found.", details={"issue_id": issue_id})
            members = set(
                (
                    await self.session.scalars(
                        select(IssueMembership.article_id).where(
                            IssueMembership.issue_id == issue_id,
                            IssueMembership.article_id.in_(article_list),
                        )
                    )
                ).all()
            )
            if members != set(article_list):
                raise AdminValidationError(
                    "All split articles must belong to the issue.",
                    details={"code": "ISSUE_SPLIT_INVALID"},
                )
            job_payload = {**payload, "actor_id": actor_id}
            digest = _payload_digest(sorted(article_list))
            dedupe = f"{issue_id}:{digest}:{idempotency_key or _payload_digest(job_payload)}"
            job = await self._enqueue_job_row("split_issue", dedupe, job_payload)
            result = {"job_id": job.id, "status": JobStatus.PENDING.value}
            return result, None, {"job": result, **payload}

        return await self._run_mutation(
            scope=f"admin:split-issue:{issue_id}",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="ISSUE_SPLIT_ENQUEUED",
            target_type="issue",
            target_id=issue_id,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    async def patch_issue(
        self,
        issue_id: str,
        values: Mapping[str, Any],
        *,
        if_match: str | int | None,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(values)
        expected = _if_match_version(if_match, resource="issue")

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            issue = await self.session.scalar(
                select(Issue).where(Issue.id == issue_id).with_for_update()
            )
            if issue is None:
                raise AdminNotFoundError("Issue was not found.", details={"issue_id": issue_id})
            if issue.version != expected:
                raise AdminConflictError(
                    "If-Match does not match the issue version.",
                    details={"resource": "issue", "expected": expected, "actual": issue.version},
                )
            before = {
                "id": issue.id,
                "title": issue.title,
                "summary": issue.summary,
                "status": _value(issue.status),
                "version": issue.version,
                "last_activity_at": _row_datetime(issue.last_activity_at),
            }
            allowed = {"title", "summary", "status"}
            for field, value in payload.items():
                if field not in allowed:
                    continue
                if field == "title":
                    title = str(value).strip()
                    if not title:
                        raise AdminValidationError("Issue title cannot be empty.")
                    issue.title = title
                elif field == "status":
                    issue.status = _normalise_status(value, IssueStatus, field="status")
                else:
                    issue.summary = None if value is None else str(value)
            issue.version += 1
            issue.last_activity_at = utc_now()
            await self.session.flush()
            after = {
                "id": issue.id,
                "title": issue.title,
                "summary": issue.summary,
                "status": _value(issue.status),
                "version": issue.version,
                "last_activity_at": _row_datetime(issue.last_activity_at),
            }
            return after, before, after

        return await self._run_mutation(
            scope=f"admin:issue:{issue_id}",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="ISSUE_UPDATED",
            target_type="issue",
            target_id=issue_id,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    update_issue = patch_issue

    async def get_issue_comparison_for_review(self, issue_id: str) -> dict[str, Any]:
        issue = await self.session.get(Issue, issue_id)
        if issue is None:
            raise AdminNotFoundError("Issue was not found.", details={"issue_id": issue_id})
        snapshot = await self.session.scalar(
            select(IssueComparisonSnapshot)
            .where(
                IssueComparisonSnapshot.issue_id == issue_id,
                IssueComparisonSnapshot.issue_version == issue.version,
            )
            .order_by(IssueComparisonSnapshot.created_at.desc())
            .limit(1)
        )
        if snapshot is None:
            raise AdminNotFoundError(
                "Issue comparison was not found.", details={"issue_id": issue_id}
            )
        model = await self.session.get(ModelAlias, snapshot.model_alias_id)
        if model is None:
            raise AdminValidationError("Comparison model provenance is missing.")
        common_facts_payload = snapshot.common_facts_json
        dimensions_payload = snapshot.framing_dimensions_json
        frames_payload = snapshot.article_frames_json
        common_facts = (
            common_facts_payload.get("common_facts")
            if isinstance(common_facts_payload, Mapping)
            else None
        )
        dimensions = (
            dimensions_payload.get("dimensions")
            if isinstance(dimensions_payload, Mapping)
            else None
        )
        article_frames = (
            frames_payload.get("article_frames")
            if isinstance(frames_payload, Mapping)
            else None
        )
        article_version_ids = (
            frames_payload.get("article_version_ids")
            if isinstance(frames_payload, Mapping)
            else None
        )
        if not all(
            (
                isinstance(common_facts, list),
                isinstance(dimensions, list),
                isinstance(article_frames, Mapping),
                isinstance(article_version_ids, Mapping),
            )
        ):
            raise AdminValidationError("Comparison snapshot payload is malformed.")
        return {
            "snapshot_id": snapshot.id,
            "issue_id": issue_id,
            "issue_version": snapshot.issue_version,
            "status": _value(snapshot.status),
            "prompt_version": snapshot.prompt_version,
            "model_alias": model.alias,
            "actual_model_id": model.actual_model_id,
            "common_facts": common_facts,
            "dimensions": dimensions,
            "article_frames": article_frames,
            "article_version_ids": article_version_ids,
            "confidence": float(snapshot.confidence),
            "created_at": snapshot.created_at,
            "reviewed_at": snapshot.reviewed_at,
            "reviewed_by": snapshot.reviewed_by,
        }

    async def review_issue_comparison(
        self,
        issue_id: str,
        *,
        snapshot_id: str,
        actor_id: str,
        idempotency_key: str,
        reason: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        expected_snapshot_id = str(snapshot_id).strip().strip('"')
        if not expected_snapshot_id:
            raise AdminPreconditionError("If-Match must identify the comparison snapshot.")

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            issue = await self.session.scalar(
                select(Issue).where(Issue.id == issue_id).with_for_update()
            )
            if issue is None:
                raise AdminNotFoundError("Issue was not found.", details={"issue_id": issue_id})
            snapshot = await self.session.scalar(
                select(IssueComparisonSnapshot)
                .where(
                    IssueComparisonSnapshot.issue_id == issue_id,
                    IssueComparisonSnapshot.id == expected_snapshot_id,
                )
                .with_for_update()
            )
            if snapshot is None:
                raise AdminNotFoundError(
                    "Comparison snapshot was not found.",
                    details={"issue_id": issue_id, "snapshot_id": expected_snapshot_id},
                )
            if snapshot.issue_version != issue.version or _value(snapshot.status) != "SUCCEEDED":
                raise AdminConflictError(
                    "Only the current successful comparison can be reviewed.",
                    details={
                        "issue_version": issue.version,
                        "snapshot_issue_version": snapshot.issue_version,
                        "snapshot_status": _value(snapshot.status),
                    },
                )
            model = await self.session.get(ModelAlias, snapshot.model_alias_id)
            if (
                model is None
                or model.provider != _OPENAI_PROVIDER
                or not model.actual_model_id.startswith("gpt-")
                or _value(model.status) != ModelStatus.ACTIVE.value
            ):
                raise AdminValidationError("Comparison model provenance is not trusted.")
            frame_payload = snapshot.article_frames_json
            version_map = (
                frame_payload.get("article_version_ids")
                if isinstance(frame_payload, Mapping)
                else None
            )
            article_frames = (
                frame_payload.get("article_frames")
                if isinstance(frame_payload, Mapping)
                else None
            )
            if (
                not isinstance(version_map, Mapping)
                or not isinstance(article_frames, Mapping)
                or not 2 <= len(version_map) <= 4
                or set(version_map) != set(article_frames)
            ):
                raise AdminValidationError("Comparison article-version provenance is missing.")
            current_rows = list(
                (
                    await self.session.execute(
                        select(Article.id, Article.current_version_id)
                        .join(IssueMembership, IssueMembership.article_id == Article.id)
                        .where(
                            IssueMembership.issue_id == issue_id,
                            Article.id.in_(list(version_map)),
                        )
                    )
                ).all()
            )
            current_versions = {
                str(article_id): str(version_id)
                for article_id, version_id in current_rows
                if version_id is not None
            }
            expected_versions = {
                str(article_id): str(version_id)
                for article_id, version_id in version_map.items()
            }
            if current_versions != expected_versions:
                raise AdminConflictError("Comparison inputs changed before review.")
            before = {
                "snapshot_id": snapshot.id,
                "reviewed_at": snapshot.reviewed_at,
                "reviewed_by": snapshot.reviewed_by,
            }
            snapshot.reviewed_at = utc_now()
            snapshot.reviewed_by = actor_id
            await self.session.flush()
            after = {
                "snapshot_id": snapshot.id,
                "issue_id": issue_id,
                "issue_version": snapshot.issue_version,
                "reviewed_at": snapshot.reviewed_at,
                "reviewed_by": snapshot.reviewed_by,
            }
            return after, before, after

        return await self._run_mutation(
            scope=f"admin:issue-comparison-review:{issue_id}",
            idempotency_key=idempotency_key,
            payload={"snapshot_id": expected_snapshot_id, "reason": reason},
            actor_id=actor_id,
            action="ISSUE_COMPARISON_REVIEWED",
            target_type="issue_comparison_snapshot",
            target_id=expected_snapshot_id,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    # ------------------------------------------------------------------
    # Model aliases
    # ------------------------------------------------------------------

    async def list_model_aliases(self) -> list[dict[str, Any]]:
        rows = list((await self.session.scalars(select(ModelAlias).order_by(ModelAlias.id))).all())
        return [await self._model_view(row) for row in rows]

    async def get_model_alias(self, model_id: str) -> dict[str, Any]:
        row = await self.session.get(ModelAlias, model_id)
        if row is None:
            raise AdminNotFoundError("Model alias was not found.", details={"model_id": model_id})
        return await self._model_view(row)

    async def create_model_alias(
        self,
        values: Mapping[str, Any],
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str = "create model alias",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(values)

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            alias = str(payload.get("alias", "")).strip()
            provider = str(payload.get("provider", _OPENAI_PROVIDER)).strip().lower()
            actual = _validate_gpt_model(payload.get("actual_model_id"))
            if not alias or not provider or not actual:
                raise AdminValidationError("alias, provider, and actual_model_id are required.")
            if provider != _OPENAI_PROVIDER:
                raise AdminValidationError("Only the OpenAI provider is allowed.")
            secret_env_name = payload.get("secret_env_name", _OPENAI_SECRET_ENV)
            if secret_env_name not in {None, _OPENAI_SECRET_ENV}:
                raise AdminValidationError("secret_env_name must be OPENAI_API_KEY.")
            reasoning_effort = _validate_reasoning_effort(
                payload.get("reasoning_effort", "xhigh")
            )
            status = _normalise_status(
                payload.get("status", ModelStatus.ACTIVE.value), ModelStatus, field="status"
            )
            duplicate = await self.session.scalar(
                select(ModelAlias).where(ModelAlias.alias == alias).with_for_update()
            )
            if duplicate is not None:
                raise AdminConflictError(
                    "A model alias with this name already exists.",
                    details={"code": "MODEL_ALIAS_ALREADY_EXISTS", "model_id": duplicate.id},
                )
            if status == ModelStatus.ACTIVE:
                active = await self.session.scalar(
                    select(ModelAlias).where(
                        ModelAlias.provider == _OPENAI_PROVIDER,
                        ModelAlias.status == ModelStatus.ACTIVE,
                    )
                )
                if active is not None:
                    raise AdminConflictError(
                        "Disable the current active OpenAI model before creating another.",
                        details={"code": "ACTIVE_OPENAI_MODEL_EXISTS", "model_id": active.id},
                    )
            config = {
                "reasoning_effort": reasoning_effort,
                "secret_env_name": secret_env_name or _OPENAI_SECRET_ENV,
            }
            row = ModelAlias(
                id=new_ulid(),
                alias=alias,
                provider=provider,
                actual_model_id=actual,
                status=status,
                config_json=config,
            )
            self.session.add(row)
            await self.session.flush()
            result = await self._model_view(row, version=1)
            return result, None, result

        return await self._run_mutation(
            scope="admin:create-model",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="MODEL_CREATED",
            target_type="model",
            target_id=None,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    async def update_model_alias(
        self,
        model_id: str,
        values: Mapping[str, Any],
        *,
        if_match: str | int | None,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(values)
        expected = _if_match_version(if_match, resource="model")

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            row = await self.session.scalar(
                select(ModelAlias).where(ModelAlias.id == model_id).with_for_update()
            )
            if row is None:
                raise AdminNotFoundError(
                    "Model alias was not found.", details={"model_id": model_id}
                )
            current = await self._audit_version(
                "model", model_id, ("MODEL_CREATED", "MODEL_UPDATED")
            )
            if current != expected:
                raise AdminConflictError(
                    "If-Match does not match the model version.",
                    details={"resource": "model", "expected": expected, "actual": current},
                )
            before = await self._model_view(row, version=current)
            for field, value in payload.items():
                if field == "alias":
                    if not str(value).strip():
                        raise AdminValidationError("Model alias cannot be empty.")
                    duplicate = await self.session.scalar(
                        select(ModelAlias)
                        .where(ModelAlias.alias == str(value).strip(), ModelAlias.id != model_id)
                        .with_for_update()
                    )
                    if duplicate is not None:
                        raise AdminConflictError(
                            "A model alias with this name already exists.",
                            details={
                                "code": "MODEL_ALIAS_ALREADY_EXISTS",
                                "model_id": duplicate.id,
                            },
                        )
                    row.alias = str(value).strip()
                elif field == "provider":
                    if str(value).strip().lower() != _OPENAI_PROVIDER:
                        raise AdminValidationError("Only the OpenAI provider is allowed.")
                    row.provider = _OPENAI_PROVIDER
                elif field == "actual_model_id":
                    row.actual_model_id = _validate_gpt_model(value)
                elif field == "status":
                    resolved_status = _normalise_status(value, ModelStatus, field="status")
                    if resolved_status == ModelStatus.ACTIVE:
                        active = await self.session.scalar(
                            select(ModelAlias).where(
                                ModelAlias.provider == _OPENAI_PROVIDER,
                                ModelAlias.status == ModelStatus.ACTIVE,
                                ModelAlias.id != model_id,
                            )
                        )
                        if active is not None:
                            raise AdminConflictError(
                                "Disable the current active OpenAI model before activating another.",
                                details={
                                    "code": "ACTIVE_OPENAI_MODEL_EXISTS",
                                    "model_id": active.id,
                                },
                            )
                    row.status = resolved_status
                elif field == "secret_env_name":
                    if value not in {None, _OPENAI_SECRET_ENV}:
                        raise AdminValidationError(
                            "secret_env_name must be OPENAI_API_KEY."
                        )
                    config = deepcopy(row.config_json or {})
                    if value is None:
                        config.pop("secret_env_name", None)
                    else:
                        config["secret_env_name"] = value
                    row.config_json = config
                elif field == "reasoning_effort":
                    config = deepcopy(row.config_json or {})
                    config["reasoning_effort"] = _validate_reasoning_effort(value)
                    config.setdefault("secret_env_name", _OPENAI_SECRET_ENV)
                    row.config_json = config
                elif field in {"config_json", "config"}:
                    requested = deepcopy(value or {})
                    unknown = set(requested) - {"reasoning_effort", "secret_env_name"}
                    if unknown:
                        raise AdminValidationError(
                            "OpenAI model config only supports reasoning_effort and secret_env_name.",
                            details={"unsupported_fields": sorted(unknown)},
                        )
                    secret = requested.get(
                        "secret_env_name",
                        (row.config_json or {}).get("secret_env_name", _OPENAI_SECRET_ENV),
                    )
                    if secret != _OPENAI_SECRET_ENV:
                        raise AdminValidationError(
                            "secret_env_name must be OPENAI_API_KEY."
                        )
                    row.config_json = {
                        "reasoning_effort": _validate_reasoning_effort(
                            requested.get(
                                "reasoning_effort",
                                (row.config_json or {}).get("reasoning_effort", "xhigh"),
                            )
                        ),
                        "secret_env_name": _OPENAI_SECRET_ENV,
                    }
            if row.provider != _OPENAI_PROVIDER:
                raise AdminValidationError("Only the OpenAI provider is allowed.")
            _validate_gpt_model(row.actual_model_id)
            final_config = deepcopy(row.config_json or {})
            row.config_json = {
                "reasoning_effort": _validate_reasoning_effort(
                    final_config.get("reasoning_effort", "xhigh")
                ),
                "secret_env_name": _OPENAI_SECRET_ENV,
            }
            await self.session.flush()
            after = await self._model_view(row, version=current + 1)
            return after, before, after

        return await self._run_mutation(
            scope=f"admin:model:{model_id}",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="MODEL_UPDATED",
            target_type="model",
            target_id=model_id,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    patch_model = update_model_alias

    # ------------------------------------------------------------------
    # Analysis and queue helpers
    # ------------------------------------------------------------------

    async def _enqueue_job_row(
        self, job_type: str, dedupe_key: str, payload: Mapping[str, Any]
    ) -> Job:
        try:
            validated_payload = validate_job_payload(job_type, payload)
        except JobPayloadError as exc:
            raise AdminValidationError(
                str(exc) or "invalid job payload",
                details=exc.as_dict().get("details", {}),
            ) from exc
        existing = await self.session.scalar(
            select(Job)
            .where(Job.job_type == job_type, Job.dedupe_key == dedupe_key)
            .with_for_update()
        )
        if existing is not None:
            if _payload_digest(existing.payload_json or {}) != _payload_digest(validated_payload):
                raise IdempotencyConflictError(
                    "A queue job already exists for this operation with a different payload.",
                    details={"job_type": job_type, "dedupe_key": dedupe_key},
                )
            return existing
        row = Job(
            id=new_ulid(),
            job_type=job_type,
            dedupe_key=dedupe_key,
            status=JobStatus.PENDING,
            priority=0,
            available_at=utc_now(),
            lease_owner=None,
            lease_expires_at=None,
            attempts=0,
            max_attempts=5,
            payload_json=deepcopy(validated_payload),
            last_error_json=None,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def enqueue_analysis(
        self,
        article_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {"article_id": article_id}

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            article = await self.session.get(Article, article_id)
            if article is None:
                raise AdminNotFoundError(
                    "Article was not found.", details={"article_id": article_id}
                )
            if not article.current_version_id:
                raise AdminConflictError(
                    "The article has no current version to analyze.",
                    details={"code": "ARTICLE_VERSION_REQUIRED"},
                )
            job_payload = {
                "article_id": article.id,
                "article_version_id": article.current_version_id,
                "actor_id": actor_id,
            }
            dedupe = (
                f"{article.current_version_id}:{idempotency_key or _payload_digest(job_payload)}"
            )
            job = await self._enqueue_job_row("analyze", dedupe, job_payload)
            result = {"job_id": job.id, "status": JobStatus.PENDING.value}
            return result, None, {"job": result, **job_payload}

        return await self._run_mutation(
            scope=f"admin:analyze:{article_id}",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="ANALYSIS_ENQUEUED",
            target_type="article",
            target_id=article_id,
            reason="enqueue article analysis",
            request_id=request_id,
            operation=operation,
        )

    async def get_analysis_run(self, run_id: str) -> dict[str, Any]:
        job = await self.session.get(Job, run_id)
        if job is None or job.job_type != "analyze":
            raise AdminNotFoundError("Analysis run was not found.", details={"run_id": run_id})
        result = self._job_view(job)
        payload = job.payload_json or {}
        version_id = payload.get("article_version_id")
        if version_id:
            assessments = list(
                (
                    await self.session.scalars(
                        select(ModelAssessment).where(
                            ModelAssessment.article_version_id == version_id
                        )
                    )
                ).all()
            )
            result["article_version_id"] = version_id
            result["assessments"] = [
                {
                    "id": item.id,
                    "model_alias_id": item.model_alias_id,
                    "prompt_version": item.prompt_version,
                    "x": item.x,
                    "y": item.y,
                    "z": item.z,
                    "sensationalism": item.sensationalism,
                    "confidence": float(item.confidence),
                    "status": _value(item.status),
                    "created_at": _row_datetime(item.created_at),
                }
                for item in assessments
            ]
        return result

    # ------------------------------------------------------------------
    # Weights, simulations, recommendations, and Auto Pilot
    # ------------------------------------------------------------------

    async def list_weights(self) -> list[dict[str, Any]]:
        rows = list(
            (
                await self.session.scalars(
                    select(WeightProfileRevision).order_by(WeightProfileRevision.revision.desc())
                )
            ).all()
        )
        return [self._weight_view(row) for row in rows]

    async def create_weight(
        self,
        values: Mapping[str, Any],
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str = "create immutable weight draft",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(values)

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            weights = payload.get("weights")
            guardrails = payload.get("guardrails") or {}
            if not isinstance(weights, Mapping) or not weights:
                raise AdminValidationError(
                    "weights must be a non-empty object.",
                    details={"code": "WEIGHT_PROFILE_INVALID"},
                )
            normalized: dict[str, float] = {}
            for name, value in weights.items():
                try:
                    number = float(value)
                except (TypeError, ValueError) as exc:
                    raise AdminValidationError(
                        "Weight values must be numeric.", details={"code": "WEIGHT_PROFILE_INVALID"}
                    ) from exc
                if not math.isfinite(number) or number < 0 or number > 1:
                    raise AdminValidationError(
                        "Weights must each be in [0,1].", details={"code": "WEIGHT_PROFILE_INVALID"}
                    )
                normalized[str(name)] = number
            if abs(sum(normalized.values()) - 1.0) > 1e-9:
                raise AdminValidationError(
                    "Weights must sum to 1.", details={"code": "WEIGHT_PROFILE_INVALID"}
                )
            if not isinstance(guardrails, Mapping):
                raise AdminValidationError("guardrails must be an object.")
            revisions = list(
                (
                    await self.session.scalars(
                        select(WeightProfileRevision)
                        .order_by(WeightProfileRevision.revision.desc())
                        .with_for_update()
                    )
                ).all()
            )
            revision = (revisions[0].revision if revisions else 0) + 1
            based_on = payload.get("based_on_revision_id")
            if based_on is not None and not any(row.id == based_on for row in revisions):
                raise AdminNotFoundError(
                    "Base weight revision was not found.", details={"revision_id": based_on}
                )
            row = WeightProfileRevision(
                id=new_ulid(),
                revision=revision,
                status=RevisionStatus.DRAFT,
                weights_json=normalized,
                guardrails_json=deepcopy(dict(guardrails)),
                based_on_revision_id=based_on,
                created_by=actor_id,
                created_at=utc_now(),
                published_at=None,
            )
            self.session.add(row)
            await self.session.flush()
            result = self._weight_view(row)
            return result, None, result

        return await self._run_mutation(
            scope="admin:create-weight",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="WEIGHT_DRAFT_CREATED",
            target_type="weight",
            target_id=None,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    @staticmethod
    def _simulation_passed(row: WeightSimulation) -> bool:
        result = row.guardrail_result or {}
        if isinstance(result, str):
            normalized = result.strip()
            if normalized.upper() in {"PASS", "PASSED", "OK"}:
                return True
            try:
                result = json.loads(normalized)
            except (TypeError, ValueError):
                return False
        if isinstance(result, Mapping):
            return bool(
                result.get("passed", result.get("pass", result.get("status") in {"PASS", "PASSED"}))
            )
        return False

    async def simulate_weight(
        self,
        weight_id: str,
        windows: Sequence[int] | Mapping[str, Any],
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str = "enqueue 7/30 weight simulation",
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(windows, Mapping):
            windows = windows.get("windows", [])
        window_values = [int(item) for item in windows]
        payload = {"weight_id": weight_id, "windows": window_values, "reason": reason}

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            if set(window_values) != {7, 30} or len(window_values) != 2:
                raise AdminValidationError(
                    "Both 7-day and 30-day simulations are required.",
                    details={"code": "SIMULATION_WINDOWS_REQUIRED"},
                )
            row = await self.session.scalar(
                select(WeightProfileRevision)
                .where(WeightProfileRevision.id == weight_id)
                .with_for_update()
            )
            if row is None:
                raise AdminNotFoundError(
                    "Weight revision was not found.", details={"weight_id": weight_id}
                )
            if _value(row.status) in {RevisionStatus.ACTIVE.value, RevisionStatus.ARCHIVED.value}:
                raise AdminConflictError(
                    "Only a draft weight can be simulated.",
                    details={"code": "WEIGHT_STATE_INVALID"},
                )
            row.status = RevisionStatus.SIMULATION
            recommendation = await self.session.get(WeightRecommendation, weight_id)
            if recommendation is None:
                evidence_snapshot = WeightEvidenceSnapshot(
                    id=new_ulid(),
                    evidence_json={"kind": "manual_weight_simulation", "weight_id": weight_id},
                    window_start=None,
                    window_end=utc_now(),
                    created_at=utc_now(),
                )
                recommendation = WeightRecommendation(
                    id=weight_id,
                    base_revision_id=weight_id,
                    proposed_weights_json=deepcopy(row.weights_json or {}),
                    evidence_snapshot_id=evidence_snapshot.id,
                    provider_assessment_ref="manual-weight",
                    status=RecommendationStatus.PENDING_REVIEW,
                    created_at=utc_now(),
                )
                self.session.add_all([evidence_snapshot, recommendation])
                await self.session.flush()
            job_payload = {
                "weight_id": weight_id,
                "recommendation_id": recommendation.id,
                "weights": deepcopy(row.weights_json or {}),
                "windows": window_values,
                "actor_id": actor_id,
                "reason": reason,
            }
            dedupe = f"{weight_id}:{idempotency_key or _payload_digest(job_payload)}"
            job = await self._enqueue_job_row("simulate_weights", dedupe, job_payload)
            result = {"job_id": job.id, "status": JobStatus.PENDING.value}
            guardrail_results = [
                {
                    "window_days": days,
                    "passed": False,
                    "guardrail_result": "PENDING",
                    "metrics": {},
                }
                for days in window_values
            ]
            return (
                result,
                None,
                {
                    "job": result,
                    "weight_id": weight_id,
                    "windows": window_values,
                    "guardrail_results": guardrail_results,
                },
            )

        return await self._run_mutation(
            scope=f"admin:simulate-weight:{weight_id}",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="WEIGHT_SIMULATION_ENQUEUED",
            target_type="weight",
            target_id=weight_id,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    async def _weight_guardrails_pass(self, weight_id: str) -> bool:
        # WeightSimulation historically references recommendations rather than
        # revisions.  Accept direct evidence if a caller stores a matching
        # recommendation id, while also accepting queue-completed results in
        # AuditLog.  This keeps the method compatible with both schema eras.
        rows = list(
            (
                await self.session.scalars(
                    select(WeightSimulation).where(WeightSimulation.recommendation_id == weight_id)
                )
            ).all()
        )
        passed = {row.window_days for row in rows if self._simulation_passed(row)}
        if passed >= {7, 30}:
            return True
        simulation_audits = list(
            (
                await self.session.scalars(
                    select(AuditLog)
                    .where(
                        AuditLog.target_type == "weight",
                        AuditLog.target_id == weight_id,
                        AuditLog.action.in_(
                            ("WEIGHT_SIMULATION_ENQUEUED", "WEIGHT_SIMULATION_COMPLETED")
                        ),
                    )
                    .order_by(AuditLog.created_at.desc())
                )
            ).all()
        )
        for audit in simulation_audits:
            evidence = (audit.after_json or {}).get("guardrail_results", [])
            if isinstance(evidence, Mapping):
                evidence = list(evidence.values())
            if isinstance(evidence, list):
                for item in evidence:
                    if (
                        isinstance(item, Mapping)
                        and item.get("window_days") in {7, 30}
                        and bool(
                            item.get("passed", item.get("guardrail_result") in {"PASS", "PASSED"})
                        )
                    ):
                        passed.add(int(item["window_days"]))
        if passed >= {7, 30}:
            return True
        jobs = list(
            (
                await self.session.scalars(select(Job).where(Job.job_type == "simulate_weights"))
            ).all()
        )
        # A successful simulation job may carry explicit per-window guardrail
        # evidence in payload_json or last_error_json/result JSON.  Pending
        # jobs are deliberately not enough to publish.
        for job in jobs:
            payload = job.payload_json or {}
            if (
                payload.get("weight_id") != weight_id
                or _value(job.status) != JobStatus.SUCCEEDED.value
            ):
                continue
            evidence = payload.get("guardrail_results", payload.get("simulations", []))
            if isinstance(evidence, Mapping):
                evidence = list(evidence.values())
            if isinstance(evidence, list):
                for item in evidence:
                    if (
                        isinstance(item, Mapping)
                        and item.get("window_days") in {7, 30}
                        and bool(
                            item.get("passed", item.get("guardrail_result") in {"PASS", "PASSED"})
                        )
                    ):
                        passed.add(int(item["window_days"]))
        return passed >= {7, 30}

    async def publish_weight(
        self,
        weight_id: str,
        *,
        if_match: str | int | None,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {"weight_id": weight_id, "reason": reason}
        expected = _if_match_version(if_match, resource="active profile")

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            row = await self.session.scalar(
                select(WeightProfileRevision)
                .where(WeightProfileRevision.id == weight_id)
                .with_for_update()
            )
            if row is None:
                raise AdminNotFoundError(
                    "Weight revision was not found.", details={"weight_id": weight_id}
                )
            settings = await self._ensure_autopilot_row(actor_id=actor_id)
            if settings.version != expected:
                raise AdminConflictError(
                    "If-Match does not match the active-profile version.",
                    details={
                        "resource": "active-profile",
                        "expected": expected,
                        "actual": settings.version,
                    },
                )
            if not await self._weight_guardrails_pass(weight_id):
                raise GuardrailError("Passing 7-day and 30-day simulations are required.")
            recommendation = await self.session.get(WeightRecommendation, weight_id)
            if (
                recommendation is None
                or _value(recommendation.status) != RecommendationStatus.APPROVED.value
            ):
                raise GuardrailError(
                    "Reviewer approval is required before publishing a weight revision.",
                    details={"code": "REVIEWER_APPROVAL_REQUIRED"},
                )
            if _value(row.status) not in {
                RevisionStatus.DRAFT.value,
                RevisionStatus.SIMULATION.value,
            }:
                raise AdminConflictError(
                    "Only a draft or simulated weight can be published.",
                    details={"code": "WEIGHT_STATE_INVALID"},
                )
            active_rows = list(
                (
                    await self.session.scalars(
                        select(WeightProfileRevision)
                        .where(WeightProfileRevision.status == RevisionStatus.ACTIVE)
                        .with_for_update()
                    )
                ).all()
            )
            before = {
                "active": [self._weight_view(item) for item in active_rows],
                "profile_version": settings.version,
            }
            for active in active_rows:
                active.status = RevisionStatus.ARCHIVED
            row.status = RevisionStatus.ACTIVE
            row.published_at = utc_now()
            settings.version += 1
            settings.updated_by = actor_id
            settings.updated_at = utc_now()
            await self.session.flush()
            result = {**self._weight_view(row), "profile_version": settings.version}
            after = {"published": result, "profile_version": settings.version}
            return result, before, after

        return await self._run_mutation(
            scope=f"admin:publish-weight:{weight_id}",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="WEIGHT_PUBLISHED",
            target_type="weight",
            target_id=weight_id,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    async def rollback_weight(
        self,
        active_weight_id: str,
        target_revision_id: str,
        *,
        if_match: str | int | None,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "active_weight_id": active_weight_id,
            "target_revision_id": target_revision_id,
            "reason": reason,
        }
        expected = _if_match_version(if_match, resource="active profile")

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            active = await self.session.scalar(
                select(WeightProfileRevision)
                .where(WeightProfileRevision.id == active_weight_id)
                .with_for_update()
            )
            target = await self.session.scalar(
                select(WeightProfileRevision)
                .where(WeightProfileRevision.id == target_revision_id)
                .with_for_update()
            )
            if (
                active is None
                or target is None
                or _value(active.status) != RevisionStatus.ACTIVE.value
            ):
                raise AdminConflictError(
                    "Active and target revisions are required.",
                    details={"code": "ROLLBACK_TARGET_INVALID"},
                )
            # Rollback is a lifecycle transition from an older immutable
            # profile.  A draft/simulation/active row or a self-target must
            # not be promoted by this endpoint.  ``published_at`` remains
            # nullable for legacy archived rows, so status and revision are
            # the portable lifecycle markers here.
            if (
                active.id == target.id
                or _value(target.status) != RevisionStatus.ARCHIVED.value
                or int(target.revision) >= int(active.revision)
            ):
                raise AdminConflictError(
                    "Only an older archived revision can be used as a rollback target.",
                    details={"code": "ROLLBACK_TARGET_INVALID"},
                )
            settings = await self._ensure_autopilot_row(actor_id=actor_id)
            if settings.version != expected:
                raise AdminConflictError(
                    "If-Match does not match the active-profile version.",
                    details={
                        "resource": "active-profile",
                        "expected": expected,
                        "actual": settings.version,
                    },
                )
            recommendation = await self.session.get(WeightRecommendation, target.id)
            if recommendation is not None and _value(recommendation.status) not in {
                RecommendationStatus.APPROVED.value,
                RecommendationStatus.PUBLISHED.value,
            }:
                raise GuardrailError(
                    "The archived revision does not have reviewer approval.",
                    details={"code": "REVIEWER_APPROVAL_REQUIRED"},
                )
            # A recommendation may be present for a manually archived row;
            # when simulation evidence exists, require both production
            # windows to have passed just as publishing does.
            simulations = list(
                (
                    await self.session.scalars(
                        select(WeightSimulation).where(
                            WeightSimulation.recommendation_id == target.id
                        )
                    )
                ).all()
            )
            if simulations and not await self._weight_guardrails_pass(target.id):
                raise GuardrailError(
                    "Passing 7-day and 30-day simulations are required.",
                    details={"code": "GUARDRAIL_NOT_SATISFIED"},
                )
            revisions = list(
                (
                    await self.session.scalars(
                        select(WeightProfileRevision)
                        .order_by(WeightProfileRevision.revision.desc())
                        .with_for_update()
                    )
                ).all()
            )
            before = {
                "active": self._weight_view(active),
                "target": self._weight_view(target),
                "profile_version": settings.version,
            }
            active.status = RevisionStatus.ARCHIVED
            row = WeightProfileRevision(
                id=new_ulid(),
                revision=(revisions[0].revision if revisions else 0) + 1,
                status=RevisionStatus.ACTIVE,
                weights_json=deepcopy(target.weights_json or {}),
                guardrails_json=deepcopy(target.guardrails_json or {}),
                based_on_revision_id=target.id,
                created_by=actor_id,
                created_at=utc_now(),
                published_at=utc_now(),
            )
            self.session.add(row)
            settings.version += 1
            settings.updated_by = actor_id
            settings.updated_at = utc_now()
            await self.session.flush()
            result = {**self._weight_view(row), "profile_version": settings.version}
            return result, before, {"rollback": result, "profile_version": settings.version}

        return await self._run_mutation(
            scope=f"admin:rollback-weight:{active_weight_id}",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="WEIGHT_ROLLED_BACK",
            target_type="weight",
            target_id=active_weight_id,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    async def list_recommendations(self) -> list[dict[str, Any]]:
        rows = list(
            (
                await self.session.scalars(
                    select(WeightRecommendation).order_by(WeightRecommendation.created_at.desc())
                )
            ).all()
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            evidence = None
            if row.evidence_snapshot_id:
                snapshot = await self.session.get(WeightEvidenceSnapshot, row.evidence_snapshot_id)
                if snapshot is not None:
                    evidence = {
                        "id": snapshot.id,
                        **_safe_json(snapshot.evidence_json or {}),
                        "created_at": _row_datetime(snapshot.created_at),
                    }
            result.append(
                {
                    "id": row.id,
                    "base_revision_id": row.base_revision_id,
                    "proposed_weights": deepcopy(row.proposed_weights_json or {}),
                    "proposed_weights_json": deepcopy(row.proposed_weights_json or {}),
                    "evidence_snapshot_id": row.evidence_snapshot_id,
                    "evidence_snapshot": evidence,
                    "provider_assessment_ref": row.provider_assessment_ref,
                    "status": _value(row.status),
                    "created_at": _row_datetime(row.created_at),
                }
            )
        return result

    async def generate_recommendation(
        self,
        evidence_window_days: int | Mapping[str, Any],
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        evidence: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if isinstance(evidence_window_days, Mapping):
            body = dict(evidence_window_days)
            evidence_window_days = int(body.get("evidence_window_days", 0))
            if evidence is None:
                evidence = (
                    body.get("evidence") if isinstance(body.get("evidence"), Mapping) else None
                )
        payload = {
            "evidence_window_days": int(evidence_window_days),
            "evidence": dict(evidence or {}),
        }

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            if int(evidence_window_days) < 7 or int(evidence_window_days) > 365:
                raise AdminValidationError("Evidence window must be between 7 and 365 days.")
            active = await self.session.scalar(
                select(WeightProfileRevision)
                .where(WeightProfileRevision.status == RevisionStatus.ACTIVE)
                .order_by(WeightProfileRevision.revision.desc())
            )
            if active is None:
                raise AdminConflictError(
                    "An active weight revision is required.",
                    details={"code": "ACTIVE_WEIGHT_REQUIRED"},
                )
            evidence_json = {
                "window_days": int(evidence_window_days),
                "captured_at": utc_now(),
                **dict(evidence or {}),
            }
            snapshot = WeightEvidenceSnapshot(
                id=new_ulid(),
                evidence_json=evidence_json,
                window_start=None,
                window_end=utc_now(),
                created_at=utc_now(),
            )
            self.session.add(snapshot)
            # The durable recommendation starts conservatively from the active
            # profile; a worker may replace the proposed values only by adding
            # a new recommendation, never by rewriting this row.
            recommendation = WeightRecommendation(
                id=new_ulid(),
                base_revision_id=active.id,
                proposed_weights_json=deepcopy(active.weights_json or {}),
                evidence_snapshot_id=snapshot.id,
                provider_assessment_ref="pending",
                status=RecommendationStatus.PENDING_REVIEW,
                created_at=utc_now(),
            )
            self.session.add(recommendation)
            await self.session.flush()
            job_payload = {
                "recommendation_id": recommendation.id,
                "evidence_window_days": int(evidence_window_days),
                "metrics": dict(evidence or {}),
                "actor_id": actor_id,
            }
            dedupe = f"{evidence_window_days}:{idempotency_key or _payload_digest(job_payload)}"
            job = await self._enqueue_job_row("recommend_weights", dedupe, job_payload)
            result = {
                "job_id": job.id,
                "status": JobStatus.PENDING.value,
                "recommendation_id": recommendation.id,
            }
            return result, None, {"recommendation_id": recommendation.id, "job": result}

        return await self._run_mutation(
            scope="admin:generate-recommendation",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="RECOMMENDATION_GENERATED",
            target_type="recommendation",
            target_id=None,
            reason="generate weight recommendation",
            request_id=request_id,
            operation=operation,
        )

    async def review_recommendation(
        self,
        recommendation_id: str,
        decision: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        decision_value = str(_value(decision)).upper()
        payload = {
            "recommendation_id": recommendation_id,
            "decision": decision_value,
            "reason": reason,
        }
        if decision_value not in {
            RecommendationStatus.APPROVED.value,
            RecommendationStatus.REJECTED.value,
        }:
            raise AdminValidationError("Recommendation decision must be APPROVED or REJECTED.")

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            row = await self.session.scalar(
                select(WeightRecommendation)
                .where(WeightRecommendation.id == recommendation_id)
                .with_for_update()
            )
            if row is None:
                raise AdminNotFoundError(
                    "Recommendation was not found.",
                    details={"recommendation_id": recommendation_id},
                )
            if _value(row.status) != RecommendationStatus.PENDING_REVIEW.value:
                raise AdminConflictError(
                    "Recommendation review is immutable.",
                    details={"code": "RECOMMENDATION_ALREADY_REVIEWED"},
                )
            before = {"id": row.id, "status": _value(row.status)}
            row.status = RecommendationStatus(decision_value)
            # No review columns exist in the schema; preserve reviewer metadata
            # in the immutable audit after_json while the row remains append-ish.
            await self.session.flush()
            result = {
                "id": row.id,
                "status": _value(row.status),
                "base_revision_id": row.base_revision_id,
                "proposed_weights": deepcopy(row.proposed_weights_json or {}),
                "reviewed_by": actor_id,
                "review_reason": reason,
            }
            return result, before, result

        return await self._run_mutation(
            scope=f"admin:recommendation:{recommendation_id}:{decision_value}",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action=f"RECOMMENDATION_{decision_value}",
            target_type="recommendation",
            target_id=recommendation_id,
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    async def get_autopilot_settings(self) -> dict[str, Any]:
        row = await self._autopilot_row()
        if row is None:
            return {
                "mode": AutoPilotMode.OFF.value,
                "guardrails": {},
                "manual_locks": [],
                "version": 1,
                "updated_by": None,
                "updated_at": None,
            }
        return self._settings_view(row)

    async def update_autopilot_settings(
        self,
        values: Mapping[str, Any],
        *,
        if_match: str | int | None,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(values)
        expected = _if_match_version(if_match, resource="Auto Pilot settings")

        async def operation() -> tuple[dict[str, Any], Any, Any]:
            row = await self._ensure_autopilot_row(actor_id=actor_id)
            if row.version != expected:
                raise AdminConflictError(
                    "If-Match does not match Auto Pilot settings.",
                    details={"resource": "autopilot", "expected": expected, "actual": row.version},
                )
            mode = _normalise_status(
                payload.get("mode", _value(row.mode)), AutoPilotMode, field="mode"
            )
            guardrails = payload.get("guardrails", {})
            manual_locks = payload.get("manual_locks", [])
            if not isinstance(guardrails, Mapping):
                raise AdminValidationError("guardrails must be an object.")
            if mode == AutoPilotMode.LIMITED_AUTO and not guardrails:
                raise AdminValidationError(
                    "LIMITED_AUTO requires explicit guardrails.",
                    details={"code": "LIMITED_AUTO_GUARDRAILS_REQUIRED"},
                )
            if not isinstance(manual_locks, Sequence) or isinstance(manual_locks, (str, bytes)):
                raise AdminValidationError("manual_locks must be a list.")
            locks = list(dict.fromkeys(str(item) for item in manual_locks))
            before = self._settings_view(row)
            row.mode = mode
            row.guardrails_json = {"guardrails": deepcopy(dict(guardrails)), "manual_locks": locks}
            row.version += 1
            row.updated_by = actor_id
            row.updated_at = utc_now()
            await self.session.flush()
            after = self._settings_view(row)
            return after, before, after

        return await self._run_mutation(
            scope="admin:autopilot-settings",
            idempotency_key=idempotency_key,
            payload=payload,
            actor_id=actor_id,
            action="AUTOPILOT_SETTINGS_UPDATED",
            target_type="autopilot",
            target_id="singleton",
            reason=reason,
            request_id=request_id,
            operation=operation,
        )

    put_autopilot_settings = update_autopilot_settings

    # ------------------------------------------------------------------
    # Jobs, audit, and protected efficacy metrics
    # ------------------------------------------------------------------

    async def list_jobs(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
    ) -> list[dict[str, Any]]:
        query = select(Job).order_by(Job.created_at.desc(), Job.id.desc())
        if status:
            try:
                query = query.where(Job.status == JobStatus(status))
            except ValueError as exc:
                raise AdminValidationError(
                    "Unknown job status.", details={"status": status}
                ) from exc
        if job_type:
            query = query.where(Job.job_type == job_type)
        rows = list((await self.session.scalars(query)).all())
        return [self._job_view(row) for row in rows]

    async def retry_job(
        self,
        job_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        async def operation() -> tuple[dict[str, Any], Any, Any]:
            row = await self.session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if row is None:
                raise AdminNotFoundError("Job was not found.", details={"job_id": job_id})
            if _value(row.status) not in {
                JobStatus.FAILED.value,
                JobStatus.DEAD.value,
                JobStatus.CANCELLED.value,
            }:
                raise AdminConflictError(
                    "Only failed, dead, or cancelled jobs can be retried.",
                    details={"code": "JOB_NOT_RETRYABLE"},
                )
            before = self._job_view(row)
            row.status = JobStatus.PENDING
            # A manual retry starts a fresh queue attempt budget.  Leaving a
            # DEAD row at max_attempts makes its next claim terminal again
            # without invoking the handler.
            row.attempts = 0
            row.available_at = utc_now()
            row.lease_owner = None
            row.lease_expires_at = None
            row.last_error_json = None
            row.updated_at = utc_now()
            await self.session.flush()
            result = {"job_id": row.id, "status": JobStatus.PENDING.value}
            return result, before, result

        return await self._run_mutation(
            scope=f"admin:retry-job:{job_id}",
            idempotency_key=idempotency_key,
            payload={},
            actor_id=actor_id,
            action="JOB_RETRIED",
            target_type="job",
            target_id=job_id,
            reason="manual retry",
            request_id=request_id,
            operation=operation,
        )

    async def cancel_job(
        self,
        job_id: str,
        *,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        async def operation() -> tuple[dict[str, Any], Any, Any]:
            row = await self.session.scalar(select(Job).where(Job.id == job_id).with_for_update())
            if row is None:
                raise AdminNotFoundError("Job was not found.", details={"job_id": job_id})
            if _value(row.status) != JobStatus.PENDING.value:
                raise AdminConflictError(
                    "Only pending jobs can be cancelled.",
                    details={"code": "JOB_NOT_CANCELLABLE"},
                )
            before = self._job_view(row)
            row.status = JobStatus.CANCELLED
            row.updated_at = utc_now()
            await self.session.flush()
            result = {"job_id": row.id, "status": JobStatus.CANCELLED.value}
            return result, before, result

        return await self._run_mutation(
            scope=f"admin:cancel-job:{job_id}",
            idempotency_key=idempotency_key,
            payload={},
            actor_id=actor_id,
            action="JOB_CANCELLED",
            target_type="job",
            target_id=job_id,
            reason="manual cancel",
            request_id=request_id,
            operation=operation,
        )

    async def list_audit(
        self,
        *,
        actor: str | None = None,
        action: str | None = None,
        target: str | None = None,
    ) -> list[dict[str, Any]]:
        query = select(AuditLog).where(AuditLog.target_type != "idempotency")
        if actor:
            query = query.where(AuditLog.actor_id == actor)
        if action:
            query = query.where(AuditLog.action == action)
        if target:
            query = query.where((AuditLog.target_id == target) | (AuditLog.target_type == target))
        rows = list(
            (
                await self.session.scalars(
                    query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                )
            ).all()
        )
        return [
            {
                "id": row.id,
                "actor_id": row.actor_id,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "before": _safe_json(row.before_json),
                "before_json": _safe_json(row.before_json),
                "after": _safe_json(row.after_json),
                "after_json": _safe_json(row.after_json),
                "reason": row.reason,
                "request_id": row.request_id,
                "created_at": _row_datetime(row.created_at),
            }
            for row in rows
        ]

    async def get_efficacy_metrics(self, *, minimum_cohort_size: int = 5) -> dict[str, Any]:
        if minimum_cohort_size < 1:
            raise AdminValidationError("minimum_cohort_size must be positive.")
        snapshots = list(
            (
                await self.session.scalars(
                    select(EfficacyAggregateSnapshot).order_by(
                        EfficacyAggregateSnapshot.period.desc(),
                        EfficacyAggregateSnapshot.created_at.desc(),
                    )
                )
            ).all()
        )
        cohorts: list[dict[str, Any]] = []
        if snapshots:
            latest: dict[str, EfficacyAggregateSnapshot] = {}
            for row in snapshots:
                latest.setdefault(row.cohort_key, row)
            for cohort_key, row in sorted(latest.items()):
                aggregate = row.aggregate_json or {}
                count = int(aggregate.get("count", 0) or 0)
                if count < minimum_cohort_size:
                    continue
                cohorts.append(
                    {
                        "cohort_key": cohort_key,
                        "count": count,
                        "mean": aggregate.get("mean"),
                        "period": row.period.isoformat(),
                    }
                )
            total = sum(
                int((row.aggregate_json or {}).get("count", 0) or 0) for row in latest.values()
            )
        else:
            # Efficacy is longitudinal: a user can have a baseline and many
            # follow-up responses.  Administrative cohorts must represent
            # people, not response rows.  Read the newest deterministic row
            # per user before applying the small-cohort suppression and mean.
            responses = list(
                (
                    await self.session.scalars(
                        select(EfficacyResponse).order_by(
                            EfficacyResponse.submitted_at.desc(), EfficacyResponse.id.desc()
                        )
                    )
                ).all()
            )
            latest_by_user: dict[str, EfficacyResponse] = {}
            for response in responses:
                latest_by_user.setdefault(response.user_id, response)
            representatives = list(latest_by_user.values())
            count = len(representatives)
            total = count
            if count >= minimum_cohort_size:
                mean = (
                    sum(float(response.normalized_score) for response in representatives) / count
                    if representatives
                    else None
                )
                cohorts.append(
                    {
                        "cohort_key": "all",
                        "count": count,
                        "mean": None if mean is None else round(float(mean), 4),
                    }
                )
        if total < minimum_cohort_size or not cohorts:
            return {
                "suppressed": True,
                "minimum_cohort_size": minimum_cohort_size,
                "cohorts": [],
            }
        return {
            "suppressed": False,
            "minimum_cohort_size": minimum_cohort_size,
            "cohorts": cohorts,
        }

    # Compatibility spellings used by route adapters.
    admin_list_sources = list_sources
    admin_get_source = get_source
    admin_create_source = create_source
    admin_update_source = update_source
    admin_patch_source = update_source
    admin_crawl_source = enqueue_crawl
    admin_list_crawls = list_crawls
    admin_merge_issue = enqueue_merge_issue
    admin_split_issue = enqueue_split_issue
    admin_patch_issue = patch_issue
    admin_get_issue_comparison = get_issue_comparison_for_review
    admin_review_issue_comparison = review_issue_comparison
    admin_list_models = list_model_aliases
    list_models = list_model_aliases
    admin_get_model = get_model_alias
    get_model = get_model_alias
    admin_create_model = create_model_alias
    create_model = create_model_alias
    admin_update_model = update_model_alias
    update_model = update_model_alias
    admin_patch_model = update_model_alias
    admin_analyze_article = enqueue_analysis
    analyze_article = enqueue_analysis
    admin_get_analysis_run = get_analysis_run
    admin_list_weights = list_weights
    admin_create_weight = create_weight
    admin_simulate_weight = simulate_weight
    simulate_weights = simulate_weight
    admin_publish_weight = publish_weight
    admin_rollback_weight = rollback_weight
    admin_list_recommendations = list_recommendations
    admin_generate_recommendation = generate_recommendation
    generate_weight_recommendation = generate_recommendation
    admin_review_recommendation = review_recommendation
    admin_get_autopilot_settings = get_autopilot_settings
    admin_update_autopilot_settings = update_autopilot_settings
    admin_put_autopilot_settings = update_autopilot_settings
    admin_list_jobs = list_jobs
    admin_retry_job = retry_job
    admin_cancel_job = cancel_job
    admin_list_audit = list_audit
    admin_efficacy_metrics = get_efficacy_metrics


__all__ = [
    "AdminConflictError",
    "AdminForbiddenError",
    "AdminNotFoundError",
    "AdminPreconditionError",
    "AdminRepositoryError",
    "AdminValidationError",
    "AdminRepositoryMixin",
    "CrawlerPolicyError",
    "GuardrailError",
    "IdempotencyConflictError",
]
