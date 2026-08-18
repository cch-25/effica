"""MariaDB-backed product reads and engagement mutations.

The mixin keeps HTTP concerns out of persistence.  Callers translate ``None``
and the small domain exceptions below into the stable API error envelope.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
from datetime import timedelta
from statistics import fmean
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from apps.api.app.db.enums import (
    CreditStatus,
    ProfileKind,
    QuestionnaireKind,
    ReadSessionStatus,
    ShareCardStatus,
    VoteQualityStatus,
)
from apps.api.app.db.models import (
    Article,
    ArticleVersion,
    ConsentVersion,
    CreditLedger,
    EfficacyResponse,
    Issue,
    IssueMembership,
    ModelAlias,
    ModelAssessment,
    QuestionnaireVersion,
    ReadSession,
    ScoreVersion,
    ShareCard,
    Source,
    StoredBlob,
    User,
    UserConsent,
    UserProfile,
    Vote,
)
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.domains.engagement.read import evaluate_read_eligibility
from apps.api.app.domains.feed.ranking import FeedCandidate, rank_feed
from apps.api.app.domains.scoring.behavior import (
    BehavioralProfile,
    BehaviorEvent,
    update_behavioral_profile,
)


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _event_count_from_confidence(confidence: float) -> int:
    """Invert ``confidence = total / (total + 10)`` for profile reconstruction."""

    value = float(confidence)
    if value >= 0.999:
        return 10_000
    if value <= 0:
        return 0
    return max(1, round(10.0 * value / (1.0 - value)))


_TERMINAL_ISSUE_STATUSES = ("merged", "closed", "archived")


class ProductConflictError(RuntimeError):
    """A valid request conflicts with current durable state."""


class ProductValidationError(ValueError):
    """A product mutation failed domain validation."""


class ProductRepositoryMixin:
    """Methods mixed into ``MariaDBPlatformRepository``."""

    session: Any
    _encryption_key: bytes

    async def enqueue(
        self, job_type: str, dedupe_key: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def _score_view(row: ScoreVersion) -> dict[str, Any]:
        return {
            "id": row.id,
            "score_version_id": row.id,
            "article_version_id": row.article_version_id,
            "weight_revision_id": row.weight_revision_id,
            "x": row.x,
            "y": row.y,
            "z": row.z,
            "sensationalism": row.sensationalism,
            "confidence": float(row.confidence),
            "components": row.components_json,
            "components_json": row.components_json,
            "status": _value(row.status),
            "created_at": row.created_at,
        }

    @staticmethod
    def _article_view(
        article: Article,
        source: Source,
        issue_id: str | None,
    ) -> dict[str, Any]:
        return {
            "id": article.id,
            "source_id": article.source_id,
            "source": source.name,
            "issue_id": issue_id,
            "canonical_url": article.canonical_url,
            "title": article.title,
            "author": article.author,
            "published_at": article.published_at,
            "current_version_id": article.current_version_id,
            "status": _value(article.status),
        }

    async def _article_context(self, article_id: str) -> tuple[Article, Source, str | None] | None:
        row = (
            await self.session.execute(
                select(Article, Source, IssueMembership.issue_id)
                .join(Source, Article.source_id == Source.id)
                .outerjoin(IssueMembership, IssueMembership.article_id == Article.id)
                .outerjoin(Issue, Issue.id == IssueMembership.issue_id)
                .where(
                    Article.id == article_id,
                    or_(
                        Issue.id.is_(None),
                        Issue.status.not_in(_TERMINAL_ISSUE_STATUSES),
                    ),
                )
                .limit(1)
            )
        ).first()
        return None if row is None else (row[0], row[1], row[2])

    async def _latest_scores(self) -> dict[str, ScoreVersion]:
        rows = list(
            (
                await self.session.scalars(
                    select(ScoreVersion).order_by(
                        ScoreVersion.article_version_id,
                        ScoreVersion.created_at.desc(),
                        ScoreVersion.id.desc(),
                    )
                )
            ).all()
        )
        latest: dict[str, ScoreVersion] = {}
        for row in rows:
            latest.setdefault(row.article_version_id, row)
        return latest

    async def feed_items(
        self, *, user_id: str | None, personalized_requested: bool
    ) -> tuple[list[dict[str, Any]], bool]:
        profile = None
        if user_id:
            profile = await self.session.scalar(
                select(UserProfile)
                .where(UserProfile.user_id == user_id, UserProfile.active.is_(True))
                .order_by(UserProfile.created_at.desc())
            )
        personalized = bool(personalized_requested and profile)
        contexts = list(
            (
                await self.session.execute(
                    select(Article, Source, IssueMembership.issue_id)
                    .join(Source, Article.source_id == Source.id)
                    .outerjoin(IssueMembership, IssueMembership.article_id == Article.id)
                    .outerjoin(Issue, Issue.id == IssueMembership.issue_id)
                    .where(
                        Article.current_version_id.is_not(None),
                        or_(
                            Issue.id.is_(None),
                            Issue.status.not_in(_TERMINAL_ISSUE_STATUSES),
                        ),
                    )
                    .order_by(
                        Article.published_at.desc(),
                        Article.id.desc(),
                        IssueMembership.issue_id.asc(),
                    )
                )
            ).all()
        )
        # A merge/split transition and retries can leave more than one active
        # membership while the transaction settles.  Feed has one invariant:
        # an article may be emitted at most once.  Terminal memberships were
        # filtered in SQL above; retain the first deterministic live context.
        unique_contexts: list[tuple[Article, Source, str | None]] = []
        seen_article_ids: set[str] = set()
        for context in contexts:
            article = context[0]
            if article.id in seen_article_ids:
                continue
            seen_article_ids.add(article.id)
            unique_contexts.append(context)
        contexts = unique_contexts
        latest = await self._latest_scores()
        candidates: list[tuple[Article, Source, str | None, ScoreVersion]] = []
        for article, source, issue_id in contexts:
            score = latest.get(article.current_version_id or "")
            if score is not None:
                candidates.append((article, source, issue_id, score))
        context_by_article = {item[0].id: item for item in candidates}
        profile_sensationalism = 0.0
        if profile is not None and _value(profile.kind) == ProfileKind.BEHAVIORAL.value:
            profile_sensationalism = float(profile.y)
        ranked = rank_feed(
            [
                FeedCandidate(
                    article_id=article.id,
                    issue_id=issue_id,
                    source_id=source.id,
                    x=score.x,
                    y=score.y,
                    z=score.z,
                    quality=float(score.confidence),
                    confidence=float(score.confidence),
                    published_at=article.published_at,
                    sensationalism=score.sensationalism,
                )
                for article, source, issue_id, score in candidates
            ],
            user_coordinates=(profile.x, profile_sensationalism)
            if personalized and profile is not None
            else None,
            # The HTTP layer owns cursor pagination.  Ranking only a fixed
            # prefix here would make every candidate after that prefix
            # permanently unreachable, regardless of the requested cursor.
            limit=max(1, len(candidates)),
            max_consecutive_source=1,
            max_per_issue=1,
        )
        items: list[dict[str, Any]] = []
        for ranked_item in ranked:
            article, source, issue_id, score = context_by_article[ranked_item.article_id]
            rank = ranked_item.rank
            reason = ranked_item.reason_code
            items.append(
                {
                    "article_id": article.id,
                    "issue_id": issue_id or "unclustered",
                    "title": article.title,
                    "source": source.name,
                    "coordinate": {
                        "x": score.x,
                        "y": score.y,
                        "z": score.z,
                        "sensationalism": score.sensationalism,
                        "confidence": float(score.confidence),
                    },
                    "reason_code": reason,
                    "rank": rank,
                }
            )
        return items, personalized

    async def list_issue_rows(
        self,
        *,
        topic: str | None = None,
        from_time: Any = None,
        to_time: Any = None,
        recent_first: bool = True,
    ) -> list[dict[str, Any]]:
        statement = select(Issue)
        if topic:
            pattern = f"%{topic}%"
            statement = statement.where(Issue.title.ilike(pattern) | Issue.summary.ilike(pattern))
        if from_time:
            statement = statement.where(Issue.last_activity_at >= from_time)
        if to_time:
            statement = statement.where(Issue.last_activity_at <= to_time)
        order = Issue.last_activity_at.desc() if recent_first else Issue.last_activity_at.asc()
        rows = list((await self.session.scalars(statement.order_by(order, Issue.id))).all())
        memberships = list(
            (
                await self.session.execute(
                    select(IssueMembership.issue_id, IssueMembership.article_id)
                )
            ).all()
        )
        by_issue: dict[str, list[str]] = {}
        for issue_id, article_id in memberships:
            by_issue.setdefault(issue_id, []).append(article_id)
        return [
            {
                "id": row.id,
                "title": row.title,
                "summary": row.summary or "",
                "status": _value(row.status),
                "opened_at": row.opened_at,
                "last_activity_at": row.last_activity_at,
                "version": row.version,
                "article_ids": by_issue.get(row.id, []),
            }
            for row in rows
        ]

    async def issue_view(self, issue_id: str) -> dict[str, Any] | None:
        issues = await self.list_issue_rows()
        issue = next((item for item in issues if item["id"] == issue_id), None)
        if issue is None:
            return None
        latest = await self._latest_scores()
        axes: list[int] = []
        if issue["article_ids"]:
            articles = list(
                (
                    await self.session.scalars(
                        select(Article).where(Article.id.in_(issue["article_ids"]))
                    )
                ).all()
            )
            axes = [
                latest[row.current_version_id].x
                for row in articles
                if row.current_version_id in latest
            ]
        return {
            **issue,
            "distribution": {
                "minimum_x": min(axes) if axes else None,
                "maximum_x": max(axes) if axes else None,
                "count": len(axes),
            },
        }

    async def issue_article_rows(
        self, issue_id: str, *, perspective: str = "all"
    ) -> list[dict[str, Any]] | None:
        if await self.session.get(Issue, issue_id) is None:
            return None
        rows = list(
            (
                await self.session.execute(
                    select(Article, Source)
                    .join(IssueMembership, IssueMembership.article_id == Article.id)
                    .join(Source, Source.id == Article.source_id)
                    .where(IssueMembership.issue_id == issue_id)
                    .order_by(Article.published_at.desc(), Article.id.desc())
                )
            ).all()
        )
        latest = await self._latest_scores()
        output: list[dict[str, Any]] = []
        for article, source in rows:
            score = latest.get(article.current_version_id or "")
            if score is None:
                continue
            if perspective == "negative_x" and score.x >= -10:
                continue
            if perspective == "center" and abs(score.x) > 10:
                continue
            if perspective == "positive_x" and score.x <= 10:
                continue
            output.append(
                {
                    **self._article_view(article, source, issue_id),
                    "coordinate": {
                        "x": score.x,
                        "y": score.y,
                        "z": score.z,
                        "sensationalism": score.sensationalism,
                        "confidence": float(score.confidence),
                    },
                }
            )
        return output

    async def article_view(self, article_id: str) -> dict[str, Any] | None:
        context = await self._article_context(article_id)
        return None if context is None else self._article_view(*context)

    async def assessment_view(self, article_id: str) -> dict[str, Any] | None:
        context = await self._article_context(article_id)
        if context is None:
            return None
        article = context[0]
        rows = list(
            (
                await self.session.execute(
                    select(ModelAssessment, ModelAlias)
                    .join(ModelAlias, ModelAlias.id == ModelAssessment.model_alias_id)
                    .where(ModelAssessment.article_version_id == article.current_version_id)
                    .order_by(ModelAssessment.created_at, ModelAssessment.id)
                )
            ).all()
        )
        return {
            "article_version_id": article.current_version_id,
            "assessments": [
                {
                    "id": assessment.id,
                    "model_alias": alias.alias,
                    "prompt_version": assessment.prompt_version,
                    "x": assessment.x,
                    "y": assessment.y,
                    "z": assessment.z,
                    "sensationalism": assessment.sensationalism,
                    "confidence": float(assessment.confidence),
                    "evidence": assessment.evidence_json,
                    "status": _value(assessment.status),
                    "created_at": assessment.created_at,
                }
                for assessment, alias in rows
            ],
        }

    async def score_history(self, article_id: str) -> list[dict[str, Any]] | None:
        article = await self.session.get(Article, article_id)
        if article is None:
            return None
        version_ids = list(
            (
                await self.session.scalars(
                    select(ArticleVersion.id).where(ArticleVersion.article_id == article_id)
                )
            ).all()
        )
        if not version_ids:
            return []
        rows = list(
            (
                await self.session.scalars(
                    select(ScoreVersion)
                    .where(ScoreVersion.article_version_id.in_(version_ids))
                    .order_by(ScoreVersion.created_at.desc(), ScoreVersion.id.desc())
                )
            ).all()
        )
        return [self._score_view(row) for row in rows]

    async def current_score(self, article_id: str) -> dict[str, Any] | None:
        article = await self.session.get(Article, article_id)
        if article is None or not article.current_version_id:
            return None
        row = await self.session.scalar(
            select(ScoreVersion)
            .where(ScoreVersion.article_version_id == article.current_version_id)
            .order_by(ScoreVersion.created_at.desc(), ScoreVersion.id.desc())
        )
        return None if row is None else self._score_view(row)

    async def source_summary(self, source_id: str) -> dict[str, Any] | None:
        source = await self.session.get(Source, source_id)
        if source is None:
            return None
        articles = list(
            (
                await self.session.scalars(select(Article).where(Article.source_id == source_id))
            ).all()
        )
        latest = await self._latest_scores()
        values = [
            latest[row.current_version_id].x for row in articles if row.current_version_id in latest
        ]
        return {
            "id": source.id,
            "name": source.name,
            "source_type": _value(source.source_type),
            "canonical_url": source.canonical_url,
            "policy_status": _value(source.policy_status),
            "robots_status": _value(source.robots_status),
            "terms_status": _value(source.terms_status),
            "active": source.active,
            "period_days": 90,
            "article_count": len(values),
            "distribution": values,
            "confidence": min(1.0, len(values) / 20),
        }

    async def create_read_session_row(
        self,
        *,
        session_id: str,
        user_id: str,
        article_id: str,
        token: str,
        expires_at: Any,
    ) -> bool:
        if await self.session.get(Article, article_id) is None:
            return False
        # Lock a stable parent row before checking for an active session.  A
        # missing active-session row cannot itself be locked, so this parent
        # lock serializes concurrent create requests for the same user.
        user = await self.session.scalar(
            select(User).where(User.id == user_id).with_for_update()
        )
        if user is None:
            return False
        active = await self.session.scalar(
            select(ReadSession).where(
                ReadSession.user_id == user_id,
                ReadSession.status.in_([ReadSessionStatus.CREATED, ReadSessionStatus.OUTBOUND]),
                ReadSession.expires_at > utc_now(),
            ).with_for_update()
        )
        if active:
            raise ProductConflictError("READ_SESSION_OVERLAP")
        self.session.add(
            ReadSession(
                id=session_id,
                user_id=user_id,
                article_id=article_id,
                token_hash=hashlib.sha256(token.encode()).digest(),
                expires_at=expires_at,
                status=ReadSessionStatus.CREATED,
                outbound_at=None,
                returned_at=None,
                client_elapsed_ms=None,
                policy_version="read-v1",
            )
        )
        await self.session.commit()
        return True

    async def use_read_redirect(
        self, *, session_id: str, user_id: str, article_id: str, token: str
    ) -> str:
        row = await self.session.scalar(
            select(ReadSession).where(ReadSession.id == session_id).with_for_update()
        )
        if (
            row is None
            or row.user_id != user_id
            or row.article_id != article_id
            or not hmac.compare_digest(row.token_hash, hashlib.sha256(token.encode()).digest())
        ):
            raise KeyError("READ_TOKEN_INVALID")
        if row.expires_at <= utc_now():
            row.status = ReadSessionStatus.EXPIRED
            await self.session.commit()
            raise ProductConflictError("READ_SESSION_EXPIRED")
        if _value(row.status) != ReadSessionStatus.CREATED.value:
            raise ProductConflictError("READ_REDIRECT_REPLAY")
        article = await self.session.get(Article, row.article_id)
        if article is None:
            raise KeyError("READ_TOKEN_INVALID")
        row.status = ReadSessionStatus.OUTBOUND
        row.outbound_at = utc_now()
        await self.session.commit()
        return article.canonical_url

    async def return_read_session_row(
        self, *, session_id: str, user_id: str, client_elapsed_ms: int | None
    ) -> dict[str, Any] | None:
        row = await self.session.scalar(
            select(ReadSession).where(ReadSession.id == session_id).with_for_update()
        )
        if row is None or row.user_id != user_id:
            return None
        now = utc_now()
        if _value(row.status) in {
            ReadSessionStatus.RETURNED.value,
            ReadSessionStatus.ELIGIBLE.value,
            ReadSessionStatus.REJECTED.value,
        }:
            return {
                "status": "rejected",
                "reason_code": "REPEAT_RETURN",
                "server_elapsed_ms": 0,
                "credit_delta": 0,
            }
        if row.expires_at <= now:
            row.status = ReadSessionStatus.EXPIRED
            await self.session.commit()
            return {
                "status": "expired",
                "reason_code": "SESSION_EXPIRED",
                "server_elapsed_ms": 0,
                "credit_delta": 0,
            }
        if _value(row.status) != ReadSessionStatus.OUTBOUND.value or row.outbound_at is None:
            return {
                "status": "rejected",
                "reason_code": "OUTBOUND_NOT_RECORDED",
                "server_elapsed_ms": 0,
                "credit_delta": 0,
            }
        result = evaluate_read_eligibility(
            outbound_at=row.outbound_at,
            returned_at=now,
            client_elapsed_ms=client_elapsed_ms,
            expires_at=row.expires_at,
            min_elapsed_ms=15_000,
            max_elapsed_ms=30 * 60_000,
        )
        eligible, reason = result.eligible, result.reason_code
        row.returned_at = now
        row.client_elapsed_ms = client_elapsed_ms
        row.status = ReadSessionStatus.ELIGIBLE if eligible else ReadSessionStatus.REJECTED
        delta = 10 if eligible else 0
        event_key = f"read:{session_id}"
        existing = await self.session.scalar(
            select(CreditLedger).where(
                CreditLedger.user_id == user_id,
                CreditLedger.event_type == "QUALIFIED_READ",
                CreditLedger.event_key == event_key,
            ).with_for_update()
        )
        credited_delta = delta
        if delta and existing is None:
            self.session.add(
                CreditLedger(
                    id=new_ulid(),
                    user_id=user_id,
                    event_type="QUALIFIED_READ",
                    event_key=event_key,
                    delta=delta,
                    policy_version="credit-v1",
                    status="posted",
                    reversed_ledger_id=None,
                    created_at=now,
                )
            )
            await self._append_behavior_event(user_id=user_id, article_id=row.article_id)
        elif delta:
            # The response must describe the durable insert, not merely the
            # eligibility calculation.  A recovered/duplicate ledger row is
            # a zero-credit replay even if the session had not yet advanced.
            credited_delta = 0
        await self.session.commit()
        return {
            "status": "eligible" if eligible else "rejected",
            "reason_code": reason,
            "server_elapsed_ms": result.server_elapsed_ms,
            "credit_delta": credited_delta,
        }

    async def vote_aggregate(self, article_id: str) -> dict[str, Any] | None:
        if await self.session.get(Article, article_id) is None:
            return None
        active = list(
            (
                await self.session.scalars(
                    select(Vote).where(Vote.article_id == article_id, Vote.active.is_(True))
                )
            ).all()
        )
        qualified = [
            row for row in active if _value(row.quality_status) == VoteQualityStatus.QUALIFIED.value
        ]

        def aggregate(rows: list[Vote], key: str) -> float | None:
            return round(fmean(float(getattr(row, key)) for row in rows), 4) if rows else None

        return {
            "raw": {key: aggregate(active, key) for key in ("x", "y", "z", "sensationalism")},
            "qualified": {
                key: aggregate(qualified, key) for key in ("x", "y", "z", "sensationalism")
            },
            "raw_count": len(active),
            "qualified_count": len(qualified),
            "segments": {} if len(qualified) < 5 else {"all": {"count": len(qualified)}},
            "small_segments_suppressed": len(qualified) < 5,
        }

    async def get_vote_row(self, *, user_id: str, article_id: str) -> dict[str, Any] | None:
        if await self.session.get(Article, article_id) is None:
            raise KeyError("article")
        row = await self.session.scalar(
            select(Vote).where(
                Vote.user_id == user_id,
                Vote.article_id == article_id,
                Vote.active.is_(True),
            )
        )
        if row is None:
            return None
        return {
            "x": row.x,
            "y": row.y,
            "z": row.z,
            "sensationalism": row.sensationalism,
            "revision": row.revision,
            "quality_status": _value(row.quality_status),
            "active": bool(row.active),
        }

    async def put_vote_row(
        self, *, user_id: str, article_id: str, values: dict[str, int]
    ) -> dict[str, Any] | None:
        # Article is the stable serialization point for the aggregate version.
        # Per-user vote rows cannot provide a global sequence because two users
        # can both submit their first vote at revision 1.
        article = await self.session.scalar(
            select(Article).where(Article.id == article_id).with_for_update()
        )
        if article is None:
            return None
        # First votes have no child row to lock.  The user row is a stable
        # serialization point for revision allocation and also protects the
        # active-row transition below.
        user = await self.session.scalar(
            select(User).where(User.id == user_id).with_for_update()
        )
        if user is None:
            return None
        rows = list(
            (
                await self.session.scalars(
                    select(Vote)
                    .where(Vote.user_id == user_id, Vote.article_id == article_id)
                    .order_by(Vote.revision.desc())
                    .with_for_update()
                )
            ).all()
        )
        for row in rows:
            if row.active:
                row.active = False
                row.updated_at = utc_now()
        # Use a locking read here.  Under MariaDB's default REPEATABLE READ,
        # a plain MAX() can keep the transaction's earlier snapshot even after
        # waiting for the article lock, causing two users to allocate the same
        # global revision.
        latest_revision = int(
            await self.session.scalar(
                select(Vote.revision)
                .where(Vote.article_id == article_id)
                .order_by(Vote.revision.desc())
                .limit(1)
                .with_for_update()
            )
            or 0
        )
        revision = latest_revision + 1
        now = utc_now()
        vote = Vote(
            id=new_ulid(),
            user_id=user_id,
            article_id=article_id,
            revision=revision,
            quality_status=VoteQualityStatus.QUALIFIED,
            active=True,
            created_at=now,
            updated_at=now,
            **values,
        )
        self.session.add(vote)
        await self._append_behavior_event(
            user_id=user_id,
            article_id=article_id,
            vote_values=values,
        )
        await self.session.flush()
        await self.enqueue(
            "aggregate_votes",
            f"{article_id}:{revision}",
            {"article_id": article_id, "version": revision},
        )
        return {**values, "revision": revision, "quality_status": "QUALIFIED", "active": True}

    async def _append_behavior_event(
        self,
        *,
        user_id: str,
        article_id: str,
        vote_values: dict[str, int] | None = None,
    ) -> None:
        sensitive_consent = await self.session.scalar(
            select(func.count())
            .select_from(UserConsent)
            .join(ConsentVersion, ConsentVersion.id == UserConsent.consent_version_id)
            .where(
                UserConsent.user_id == user_id,
                UserConsent.withdrawn_at.is_(None),
                ConsentVersion.purpose == "SENSITIVE_POLITICAL",
            )
        )
        if not sensitive_consent:
            return
        score = await self.current_score(article_id)
        if score is None:
            return
        existing = await self.session.scalar(
            select(UserProfile)
            .where(
                UserProfile.user_id == user_id,
                UserProfile.kind == ProfileKind.BEHAVIORAL,
                UserProfile.active.is_(True),
            )
            .order_by(UserProfile.created_at.desc())
        )
        current = (
            BehavioralProfile()
            if existing is None
            else BehavioralProfile(
                x=existing.x,
                y=0.0,
                z=existing.z,
                sensationalism=float(existing.y),
                confidence=float(existing.confidence),
                event_count=_event_count_from_confidence(existing.confidence),
                active=existing.active,
                policy_version=existing.source_version,
            )
        )
        updated_profile = update_behavioral_profile(
            current,
            [
                BehaviorEvent(
                    article_x=score["x"],
                    article_y=score["y"],
                    article_z=score["z"],
                    article_sensationalism=float(score.get("sensationalism") or 0),
                    kind="vote" if vote_values else "read",
                    vote_x=None if vote_values is None else vote_values["x"],
                    vote_y=None if vote_values is None else vote_values["y"],
                    vote_z=None if vote_values is None else vote_values["z"],
                    vote_sensationalism=(
                        None if vote_values is None else float(vote_values["sensationalism"])
                    ),
                )
            ],
            activate=True,
        )
        if existing is not None:
            existing.active = False
        self.session.add(
            UserProfile(
                id=new_ulid(),
                user_id=user_id,
                kind=ProfileKind.BEHAVIORAL,
                x=round(updated_profile.x),
                y=round(updated_profile.sensationalism),
                z=round(updated_profile.z),
                confidence=round(updated_profile.confidence, 4),
                source_version=updated_profile.policy_version,
                active=True,
                created_at=utc_now(),
            )
        )

    async def delete_vote_row(self, *, user_id: str, article_id: str) -> bool:
        article = await self.session.scalar(
            select(Article).where(Article.id == article_id).with_for_update()
        )
        if article is None:
            return False
        row = await self.session.scalar(
            select(Vote)
            .where(Vote.user_id == user_id, Vote.article_id == article_id, Vote.active.is_(True))
            .order_by(Vote.revision.desc())
            .with_for_update()
        )
        if row is None:
            return False
        latest_revision = int(
            await self.session.scalar(
                select(Vote.revision)
                .where(Vote.article_id == article_id)
                .order_by(Vote.revision.desc())
                .limit(1)
                .with_for_update()
            )
            or 0
        )
        row.revision = latest_revision + 1
        row.active = False
        row.updated_at = utc_now()
        await self.session.flush()
        await self.enqueue(
            "aggregate_votes",
            f"{article_id}:{row.revision}",
            {"article_id": article_id, "version": row.revision},
        )
        return True

    async def credit_rows(self, user_id: str) -> list[dict[str, Any]]:
        rows = list(
            (
                await self.session.scalars(
                    select(CreditLedger)
                    .where(CreditLedger.user_id == user_id)
                    .order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc())
                )
            ).all()
        )
        return [
            {
                "id": row.id,
                "event_type": row.event_type,
                "event_key": row.event_key,
                "delta": row.delta,
                "policy_version": row.policy_version,
                "status": _value(row.status),
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def reverse_credit_row(
        self,
        *,
        user_id: str,
        original_ledger_id: str,
        event_key: str,
        policy_version: str,
    ) -> dict[str, Any] | None:
        """Create one durable reversal for an original ledger entry.

        The original row is the serialization point: locking it prevents two
        requests from both observing an un-reversed entry.  The unique
        ``reversed_ledger_id`` constraint remains the database backstop for
        dialects that do not honor row locks (and for independent writers).
        """

        original = await self.session.scalar(
            select(CreditLedger)
            .where(CreditLedger.id == original_ledger_id, CreditLedger.user_id == user_id)
            .with_for_update()
        )
        if original is None:
            return None
        if _value(original.status) == CreditStatus.REVERSED.value or str(
            original.event_type
        ).upper() == "REVERSAL":
            raise ProductConflictError("CREDIT_REVERSAL_CHAIN")
        existing = await self.session.scalar(
            select(CreditLedger)
            .where(CreditLedger.reversed_ledger_id == original.id)
            .with_for_update()
        )
        if existing is not None:
            if existing.event_key == event_key:
                return {
                    "id": existing.id,
                    "event_type": existing.event_type,
                    "event_key": existing.event_key,
                    "delta": existing.delta,
                    "policy_version": existing.policy_version,
                    "status": _value(existing.status),
                    "reversed_ledger_id": existing.reversed_ledger_id,
                    "created_at": existing.created_at,
                }
            raise ProductConflictError("CREDIT_ALREADY_REVERSED")
        reversal = CreditLedger(
            id=new_ulid(),
            user_id=user_id,
            event_type="REVERSAL",
            event_key=event_key,
            delta=-original.delta,
            policy_version=policy_version,
            status=CreditStatus.REVERSED,
            reversed_ledger_id=original.id,
            created_at=utc_now(),
        )
        self.session.add(reversal)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ProductConflictError("CREDIT_ALREADY_REVERSED") from exc
        await self.session.commit()
        return {
            "id": reversal.id,
            "event_type": reversal.event_type,
            "event_key": reversal.event_key,
            "delta": reversal.delta,
            "policy_version": reversal.policy_version,
            "status": _value(reversal.status),
            "reversed_ledger_id": reversal.reversed_ledger_id,
            "created_at": reversal.created_at,
        }

    async def progress_view(self, user_id: str) -> dict[str, Any]:
        total = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(CreditLedger.delta), 0)).where(
                    CreditLedger.user_id == user_id
                )
            )
            or 0
        )
        level = max(1, total // 100 + 1)
        tier = "Explorer" if level < 3 else "Bridge Builder" if level < 6 else "Navigator"
        return {"credit_total": total, "level": level, "tier": tier, "policy_version": "tier-v1"}

    async def efficacy_view(self, user_id: str) -> dict[str, Any]:
        rows = list(
            (
                await self.session.scalars(
                    select(EfficacyResponse)
                    .where(EfficacyResponse.user_id == user_id)
                    .order_by(EfficacyResponse.submitted_at, EfficacyResponse.id)
                )
            ).all()
        )
        serialized = [
            {
                "id": row.id,
                "questionnaire_version_id": row.questionnaire_version_id,
                "normalized_score": float(row.normalized_score),
                "submitted_at": row.submitted_at,
            }
            for row in rows
        ]
        baseline = serialized[0]["normalized_score"] if serialized else None
        return {
            "baseline": baseline,
            "responses": serialized,
            "due_survey": not rows or (utc_now() - rows[-1].submitted_at).days >= 30,
        }

    async def submit_efficacy_row(
        self, *, user_id: str, questionnaire_version_id: str, answers: dict[str, Any]
    ) -> dict[str, Any] | None:
        version = await self.session.get(QuestionnaireVersion, questionnaire_version_id)
        if version is None or _value(version.kind) != QuestionnaireKind.EFFICACY.value:
            return None
        numeric: list[float] = []
        for value in answers.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ProductValidationError("EFFICACY_ANSWERS_INVALID")
            number = float(value)
            if not math.isfinite(number):
                raise ProductValidationError("EFFICACY_ANSWERS_INVALID")
            numeric.append(number)
        if not numeric:
            raise ProductValidationError("EFFICACY_ANSWERS_INVALID")
        normalized = round(max(0.0, min(100.0, fmean(numeric))), 4)
        baseline = await self.session.scalar(
            select(EfficacyResponse)
            .where(EfficacyResponse.user_id == user_id)
            .order_by(EfficacyResponse.submitted_at, EfficacyResponse.id)
        )
        delta = (
            None if baseline is None else round(normalized - float(baseline.normalized_score), 4)
        )
        self.session.add(
            EfficacyResponse(
                id=new_ulid(),
                user_id=user_id,
                questionnaire_version_id=questionnaire_version_id,
                normalized_score=normalized,
                submitted_at=utc_now(),
            )
        )
        await self.session.commit()
        return {"normalized_score": normalized, "baseline_delta": delta, "due_survey": False}

    def _share_token(self, card_id: str) -> str:
        digest = hmac.new(
            self._encryption_key, f"share:{card_id}".encode(), hashlib.sha256
        ).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    async def create_share_card_row(
        self,
        *,
        user_id: str,
        template: str,
        display_name: str | None,
        publication_confirmed: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        profile = await self.session.scalar(
            select(UserProfile)
            .where(UserProfile.user_id == user_id, UserProfile.active.is_(True))
            .order_by(UserProfile.created_at.desc())
        )
        if profile is None:
            raise ProductConflictError("PROFILE_REQUIRED")
        progress = await self.progress_view(user_id)
        card_id = new_ulid()
        token = self._share_token(card_id)
        confirmed_at = utc_now()
        kind = _value(profile.kind)
        sensationalism = (
            float(profile.y) if kind == ProfileKind.BEHAVIORAL.value else None
        )
        snapshot = {
            "x": profile.x,
            "y": profile.y,
            "z": profile.z,
            "sensationalism": sensationalism,
            "confidence": float(profile.confidence),
            "coordinate": {
                "x": profile.x,
                "y": profile.y,
                "z": profile.z,
                "sensationalism": sensationalism,
                "confidence": float(profile.confidence),
            },
            "tier": progress["tier"],
            "activity": progress["credit_total"],
            "credit_total": progress["credit_total"],
            "created_at": confirmed_at.isoformat(),
            "political_data_publication_confirmed": bool(publication_confirmed),
            "publication_consent": {
                "confirmation_version": "share-card-publication-v1",
                "confirmed_at": confirmed_at.isoformat(),
                "actor_id": user_id,
            },
        }
        card = ShareCard(
            id=card_id,
            user_id=user_id,
            public_token_hash=hashlib.sha256(token.encode()).digest(),
            template=template,
            display_name=display_name,
            snapshot_json=snapshot,
            status=ShareCardStatus.QUEUED,
            blob_id=None,
            expires_at=utc_now() + timedelta(days=30),
            revoked_at=None,
            created_at=utc_now(),
        )
        self.session.add(card)
        await self.session.flush()
        job = await self.enqueue(
            "render_share_card",
            card_id,
            {
                "share_card_id": card_id,
                "template": template,
                "display_name": display_name,
                "snapshot": snapshot,
                "expires_at": card.expires_at.isoformat(),
            },
        )
        return job, {
            "id": card_id,
            "status": "queued",
            "public_token": token,
            "etag": None,
            "snapshot": snapshot,
        }

    async def owner_share_card(self, *, card_id: str, user_id: str) -> dict[str, Any] | None:
        card = await self.session.get(ShareCard, card_id)
        if card is None or card.user_id != user_id:
            return None
        blob = await self.session.get(StoredBlob, card.blob_id) if card.blob_id else None
        return {
            "id": card.id,
            "status": _value(card.status),
            "public_token": self._share_token(card.id),
            "etag": None if blob is None else f'"{blob.sha256.hex()}"',
            "snapshot": card.snapshot_json,
        }

    async def public_share_card(self, token: str) -> tuple[ShareCard, StoredBlob | None] | None:
        card = await self.session.scalar(
            select(ShareCard).where(
                ShareCard.public_token_hash == hashlib.sha256(token.encode()).digest()
            )
        )
        if (
            card is None
            or _value(card.status) == ShareCardStatus.REVOKED.value
            or card.revoked_at is not None
            or (card.expires_at is not None and card.expires_at <= utc_now())
        ):
            return None
        blob = await self.session.get(StoredBlob, card.blob_id) if card.blob_id else None
        if blob is not None and blob.expires_at is not None and blob.expires_at <= utc_now():
            blob = None
        return card, blob

    async def revoke_share_card(self, *, card_id: str, user_id: str) -> bool:
        card = await self.session.get(ShareCard, card_id)
        if card is None or card.user_id != user_id:
            return False
        card.status = ShareCardStatus.REVOKED
        card.revoked_at = utc_now()
        await self.session.commit()
        return True

    async def visualization_rows(
        self, *, entity_type: str, issue_id: str | None, user_id: str | None
    ) -> list[dict[str, Any]]:
        if entity_type == "user":
            if not user_id:
                return []
            profiles = list(
                (
                    await self.session.scalars(
                        select(UserProfile).where(
                            UserProfile.user_id == user_id, UserProfile.active.is_(True)
                        )
                    )
                ).all()
            )
            return [
                {
                    "entity_type": "user",
                    "entity_id": user_id,
                    "label": "Your response-based coordinate",
                    "x": row.x,
                    "y": row.y,
                    "z": row.z,
                    "sensationalism": (
                        float(row.y)
                        if _value(row.kind) == ProfileKind.BEHAVIORAL.value
                        else None
                    ),
                    "confidence": float(row.confidence),
                }
                for row in profiles
            ]
        contexts = list(
            (
                await self.session.execute(
                    select(Article, Source, IssueMembership.issue_id)
                    .join(Source, Source.id == Article.source_id)
                    .outerjoin(IssueMembership, IssueMembership.article_id == Article.id)
                )
            ).all()
        )
        latest = await self._latest_scores()
        if entity_type == "article":
            seen: set[str] = set()
            rows: list[dict[str, Any]] = []
            for article, _source, row_issue_id in contexts:
                if article.id in seen:
                    continue
                if article.current_version_id not in latest:
                    continue
                if issue_id and row_issue_id != issue_id:
                    continue
                seen.add(article.id)
                score = latest[article.current_version_id]
                rows.append(
                    {
                        "entity_type": "article",
                        "entity_id": article.id,
                        "label": article.title,
                        "x": score.x,
                        "y": score.y,
                        "z": score.z,
                        "sensationalism": score.sensationalism,
                        "confidence": float(score.confidence),
                    }
                )
            return rows
        grouped: dict[str, tuple[Source, list[ScoreVersion]]] = {}
        for article, source, _ in contexts:
            if article.current_version_id in latest:
                grouped.setdefault(source.id, (source, []))[1].append(
                    latest[article.current_version_id]
                )
        return [
            {
                "entity_type": "source",
                "entity_id": source.id,
                "label": source.name,
                "x": round(fmean(row.x for row in scores), 2),
                "y": round(fmean(row.y for row in scores), 2),
                "z": round(fmean(row.z for row in scores), 2),
                "sensationalism": round(fmean(row.sensationalism for row in scores), 2),
                "confidence": min(1.0, len(scores) / 20),
            }
            for source, scores in grouped.values()
        ]

    async def visualization_timeline_rows(
        self, *, entity_type: str, entity_id: str
    ) -> list[dict[str, Any]]:
        if entity_type == "user":
            profiles = list(
                (
                    await self.session.scalars(
                        select(UserProfile)
                        .where(UserProfile.user_id == entity_id)
                        .order_by(UserProfile.created_at)
                    )
                ).all()
            )
            return [
                {
                    "id": row.id,
                    "x": row.x,
                    "y": row.y,
                    "z": row.z,
                    "confidence": float(row.confidence),
                    "created_at": row.created_at,
                }
                for row in profiles
            ]
        if entity_type == "article":
            return (await self.score_history(entity_id)) or []
        articles = list(
            (
                await self.session.scalars(select(Article).where(Article.source_id == entity_id))
            ).all()
        )
        rows: list[dict[str, Any]] = []
        for article in articles:
            rows.extend((await self.score_history(article.id)) or [])
        return sorted(rows, key=lambda item: item["created_at"])
