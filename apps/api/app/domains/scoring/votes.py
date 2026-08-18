"""Revisioned votes and aggregate snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from statistics import mean
from typing import Any


class VoteQuality(str, Enum):
    VALID = "VALID"
    # ``QUALIFIED`` is the persisted/database status for a normal vote. Keep
    # VALID as a legacy compatibility value while accepting both at the
    # domain boundary during the enum migration.
    QUALIFIED = "QUALIFIED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Vote:
    vote_id: str
    user_id: str
    article_id: str
    revision: int
    x: int
    y: int
    z: int
    sensationalism: int
    quality_status: VoteQuality = VoteQuality.VALID
    active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "quality_status", VoteQuality(self.quality_status))
        for name in ("x", "y", "z"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or not -100 <= value <= 100:
                raise ValueError(f"{name} must be an integer in [-100, 100]")
        if (
            not isinstance(self.sensationalism, int)
            or isinstance(self.sensationalism, bool)
            or not 0 <= self.sensationalism <= 100
        ):
            raise ValueError("sensationalism must be in [0, 100]")
        if self.revision < 1:
            raise ValueError("revision must be positive")
        # Retain legacy columns but make every newly materialized domain vote
        # canonical to political bias + sensationalism.
        object.__setattr__(self, "y", 0)
        object.__setattr__(self, "z", 0)


class VoteRevisionStore:
    """In-memory model of one active vote and immutable revision history."""

    def __init__(self) -> None:
        self._votes: dict[tuple[str, str], list[Vote]] = {}

    def submit(
        self,
        *,
        vote_id: str,
        user_id: str,
        article_id: str,
        x: int,
        y: int,
        z: int,
        sensationalism: int,
        quality_status: VoteQuality = VoteQuality.VALID,
    ) -> Vote:
        y = 0
        z = 0
        key = (user_id, article_id)
        history = self._votes.setdefault(key, [])
        existing_id = next((vote for vote in history if vote.vote_id == vote_id), None)
        if existing_id is not None:
            if (
                existing_id.x,
                existing_id.y,
                existing_id.z,
                existing_id.sensationalism,
                existing_id.quality_status,
            ) != (x, y, z, sensationalism, VoteQuality(quality_status)):
                raise ValueError("vote id reused with a different payload")
            return existing_id
        revision = len(history) + 1
        for prior in history:
            if prior.active:
                # dataclasses are frozen; preserve immutable revision rows and
                # store an inactive copy as a transition projection.
                history[history.index(prior)] = Vote(
                    prior.vote_id,
                    prior.user_id,
                    prior.article_id,
                    prior.revision,
                    prior.x,
                    prior.y,
                    prior.z,
                    prior.sensationalism,
                    prior.quality_status,
                    False,
                    prior.created_at,
                    datetime.now(UTC),
                )
        vote = Vote(
            vote_id, user_id, article_id, revision, x, y, z, sensationalism, quality_status, True
        )
        history.append(vote)
        return vote

    def revise(self, vote_id: str, **changes: Any) -> Vote:
        active = next(
            (
                vote
                for values in self._votes.values()
                for vote in values
                if vote.vote_id == vote_id and vote.active
            ),
            None,
        )
        if active is None:
            raise KeyError("active vote not found")
        allowed = {"x", "y", "z", "sensationalism", "quality_status"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unknown vote fields: {sorted(unknown)}")
        values = {field: getattr(active, field) for field in allowed}
        values.update(changes)
        return self.submit(
            vote_id=f"{active.vote_id}:r{active.revision + 1}",
            user_id=active.user_id,
            article_id=active.article_id,
            **values,
        )

    def deactivate(self, user_id: str, article_id: str) -> bool:
        key = (user_id, article_id)
        history = self._votes.get(key, [])
        changed = False
        for index, prior in enumerate(history):
            if prior.active:
                history[index] = Vote(
                    prior.vote_id,
                    prior.user_id,
                    prior.article_id,
                    prior.revision,
                    prior.x,
                    prior.y,
                    prior.z,
                    prior.sensationalism,
                    prior.quality_status,
                    False,
                    prior.created_at,
                    datetime.now(UTC),
                )
                changed = True
        return changed

    def active(self, *, article_id: str | None = None) -> list[Vote]:
        values = [vote for history in self._votes.values() for vote in history if vote.active]
        return sorted(
            (vote for vote in values if article_id is None or vote.article_id == article_id),
            key=lambda item: (item.article_id, item.user_id),
        )

    def history(self, user_id: str, article_id: str) -> tuple[Vote, ...]:
        return tuple(self._votes.get((user_id, article_id), []))


def aggregate_votes(
    votes: Iterable[Vote | Mapping[str, Any]],
    *,
    segment_by_user: Mapping[str, str] | None = None,
    min_segment_size: int = 5,
) -> dict[str, Any]:
    """Aggregate valid active votes and suppress small demographic segments."""

    if min_segment_size < 1:
        raise ValueError("min_segment_size must be positive")
    active: list[Vote] = []
    for item in votes:
        vote = item if isinstance(item, Vote) else Vote(**item)
        if vote.active and vote.quality_status in {VoteQuality.VALID, VoteQuality.QUALIFIED}:
            active.append(vote)
    result: dict[str, Any] = {
        "count": len(active),
        "aggregate": _mean_values(active),
        "segments": {},
    }
    if segment_by_user:
        grouped: dict[str, list[Vote]] = {}
        for vote in active:
            segment = segment_by_user.get(vote.user_id)
            if segment is not None:
                grouped.setdefault(segment, []).append(vote)
        # A cohort is a set of people, not a count of response rows. A user
        # can have multiple records in a worker payload, so select one
        # deterministic latest representative before privacy counting and
        # averaging.
        representatives = {
            segment: _latest_per_user(values) for segment, values in grouped.items()
        }
        result["segments"] = {
            segment: {"count": len(values), "aggregate": _mean_values(values)}
            for segment, values in sorted(representatives.items())
            if len(values) >= min_segment_size
        }
        result["suppressed_segment_count"] = sum(
            1 for values in representatives.values() if len(values) < min_segment_size
        )
    return result


def hide_small_segments(aggregate: Mapping[str, Any], *, min_size: int = 5) -> dict[str, Any]:
    """Defensive projection that removes under-sized precomputed segments."""

    segments = aggregate.get("segments", {})
    result = dict(aggregate)
    result["segments"] = {
        key: value for key, value in segments.items() if int(value.get("count", 0)) >= min_size
    }
    return result


def detect_vote_anomaly(
    vote: Vote, *, prior_votes: Iterable[Vote] = (), max_duplicate_distance: float = 0.0
) -> bool:
    """Flag repeated two-axis voting patterns without changing the vote."""

    if max_duplicate_distance < 0:
        raise ValueError("max_duplicate_distance cannot be negative")
    for prior in prior_votes:
        distance = abs(vote.x - prior.x) + abs(vote.sensationalism - prior.sensationalism)
        if (
            vote.user_id == prior.user_id
            and vote.article_id != prior.article_id
            and distance <= max_duplicate_distance
        ):
            return True
    return False


def quality_status_for(vote: Vote, *, prior_votes: Iterable[Vote] = ()) -> VoteQuality:
    return (
        VoteQuality.FLAGGED
        if detect_vote_anomaly(vote, prior_votes=prior_votes)
        else vote.quality_status
    )


aggregate_vote_snapshots = aggregate_votes


def _mean_values(votes: list[Vote]) -> dict[str, int | None]:
    if not votes:
        return {"x": None, "y": 0, "z": 0, "sensationalism": None}
    return {
        "x": round(mean(vote.x for vote in votes)),
        "y": 0,
        "z": 0,
        "sensationalism": round(mean(vote.sensationalism for vote in votes)),
    }


def _latest_per_user(votes: Iterable[Vote]) -> list[Vote]:
    """Return one stable representative vote per user."""

    latest: dict[str, Vote] = {}
    for vote in votes:
        prior = latest.get(vote.user_id)
        if prior is None or _vote_order(vote) > _vote_order(prior):
            latest[vote.user_id] = vote
    return [latest[user_id] for user_id in sorted(latest)]


def _vote_order(vote: Vote) -> tuple[int, float, str]:
    stamp = vote.updated_at or vote.created_at
    if isinstance(stamp, str):
        try:
            stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            # A malformed persistence timestamp must not make privacy
            # aggregation crash; revision and vote id remain deterministic
            # tie-breakers.
            return vote.revision, float("-inf"), vote.vote_id
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return vote.revision, stamp.timestamp(), vote.vote_id
