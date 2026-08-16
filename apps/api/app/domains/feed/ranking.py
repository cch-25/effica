"""Pure feed candidate scoring and greedy diversity selection."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class FeedCandidate:
    article_id: str
    issue_id: str | None
    source_id: str | None
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    quality: float = 0.5
    confidence: float = 0.5
    relevance: float = 0.0
    published_at: datetime | None = None
    sensationalism: float = 0.0
    available: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> FeedCandidate:
        return cls(
            article_id=str(value.get("article_id", value.get("id"))),
            issue_id=value.get("issue_id"),
            source_id=value.get("source_id"),
            x=float(value.get("x", 0)),
            y=float(value.get("y", 0)),
            z=float(value.get("z", 0)),
            quality=float(value.get("quality", value.get("quality_score", 0.5))),
            confidence=float(value.get("confidence", 0.5)),
            relevance=float(value.get("relevance", 0)),
            published_at=value.get("published_at"),
            sensationalism=float(value.get("sensationalism", 0)),
            available=bool(value.get("available", True)),
            metadata=value,
        )


@dataclass(frozen=True)
class RankedFeedItem:
    candidate: FeedCandidate
    rank: int
    score: float
    reason_code: str
    adjacent: bool = False

    @property
    def article_id(self) -> str:
        return self.candidate.article_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "rank": self.rank,
            "score": self.score,
            "reason_code": self.reason_code,
            "adjacent": self.adjacent,
        }


def generate_candidates(
    candidates: Iterable[FeedCandidate | Mapping[str, Any]],
    *,
    predicate: Callable[[FeedCandidate], bool] | None = None,
) -> list[FeedCandidate]:
    """Normalise and filter candidate records before ranking."""

    result = [
        item if isinstance(item, FeedCandidate) else FeedCandidate.from_mapping(item)
        for item in candidates
    ]
    return sorted(
        (item for item in result if item.available and (predicate is None or predicate(item))),
        key=lambda item: item.article_id,
    )


def rank_feed(
    candidates: Iterable[FeedCandidate | Mapping[str, Any]],
    *,
    user_coordinates: Sequence[float] | None = None,
    now: datetime | None = None,
    limit: int = 20,
    max_consecutive_source: int = 2,
    max_per_issue: int | None = None,
) -> list[RankedFeedItem]:
    """Rank candidates with source diversity and adjacent-view preference."""

    if limit < 1 or max_consecutive_source < 1 or (max_per_issue is not None and max_per_issue < 1):
        raise ValueError("invalid feed limits")
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    pool = generate_candidates(candidates)
    if not pool:
        return []
    selected: list[RankedFeedItem] = []
    remaining = list(pool)
    source_counts: dict[str | None, int] = {}
    issue_counts: dict[str | None, int] = {}
    profile = _profile_coordinates(user_coordinates)
    while remaining and len(selected) < limit:
        eligible = [
            item
            for item in remaining
            if _allowed(
                item, selected, source_counts, issue_counts, max_consecutive_source, max_per_issue
            )
        ]
        if not eligible:
            # A hard source cap should not make a feed empty when only one
            # source is available; reset the consecutive constraint once.
            eligible = remaining
        ranked = sorted(
            ((_score(item, profile, now, source_counts, issue_counts), item) for item in eligible),
            key=lambda pair: (-pair[0][0], pair[1].article_id),
        )
        (score, adjacent, reason), item = ranked[0]
        remaining.remove(item)
        source_counts[item.source_id] = source_counts.get(item.source_id, 0) + 1
        issue_counts[item.issue_id] = issue_counts.get(item.issue_id, 0) + 1
        selected.append(RankedFeedItem(item, len(selected) + 1, round(score, 6), reason, adjacent))
    return selected


def reason_code_for(
    candidate: FeedCandidate | Mapping[str, Any],
    *,
    user_coordinates: Sequence[float] | None = None,
    now: datetime | None = None,
) -> str:
    item = (
        candidate if isinstance(candidate, FeedCandidate) else FeedCandidate.from_mapping(candidate)
    )
    _, _, reason = _score(
        item, _profile_coordinates(user_coordinates), now or datetime.now(UTC), {}, {}
    )
    return reason


def _allowed(
    item: FeedCandidate,
    selected: Sequence[RankedFeedItem],
    source_counts: Mapping[str | None, int],
    issue_counts: Mapping[str | None, int],
    max_consecutive_source: int,
    max_per_issue: int | None,
) -> bool:
    if max_per_issue is not None and issue_counts.get(item.issue_id, 0) >= max_per_issue:
        return False
    if not selected:
        return True
    trailing = 0
    for prior in reversed(selected):
        if prior.candidate.source_id != item.source_id:
            break
        trailing += 1
    return trailing < max_consecutive_source


def _score(
    item: FeedCandidate,
    profile: tuple[float, float] | None,
    now: datetime,
    source_counts: Mapping[str | None, int],
    issue_counts: Mapping[str | None, int],
) -> tuple[float, bool, str]:
    recency = _recency(item.published_at, now)
    quality = max(0.0, min(1.0, item.quality)) * 0.24 + max(0.0, min(1.0, item.confidence)) * 0.12
    relevance = (
        max(0.0, min(1.0, (item.relevance + 1) / 2 if item.relevance < 0 else item.relevance))
        * 0.30
    )
    diversity = 0.20 / (1 + source_counts.get(item.source_id, 0))
    issue_bonus = 0.08 / (1 + issue_counts.get(item.issue_id, 0))
    adjacent = False
    if profile is None:
        # Small deterministic balance bonus for underrepresented coordinates.
        reason = "FALLBACK_BALANCED"
        distance_term = 0.05
    else:
        distance = _distance(item, profile)
        adjacent = 0.02 < distance <= 0.65
        # Nearby-but-different views outrank ideological extremes.
        distance_term = 0.18 if adjacent else 0.04 * (1.0 - distance)
        reason = (
            "PERSONALIZED_ADJACENT"
            if adjacent
            else ("PERSONALIZED_RELEVANCE" if item.relevance > 0 else "QUALITY")
        )
    score = relevance + recency * 0.14 + quality + diversity + issue_bonus + distance_term
    return score, adjacent, reason


def _profile_coordinates(values: Sequence[float] | None) -> tuple[float, float] | None:
    """Project old/new profile shapes onto bias and sensationalism.

    Preferred callers pass ``(x, sensationalism)`` or the transitional
    ``(x, y, z, sensationalism)`` shape. A legacy three-coordinate tuple has
    no sensationalism value, so y/z are ignored and zero is used.
    """

    if values is None:
        return None
    if len(values) == 2:
        return float(values[0]), float(values[1])
    if len(values) == 3:
        return float(values[0]), 0.0
    if len(values) == 4:
        return float(values[0]), float(values[3])
    raise ValueError("user_coordinates must contain 2, 3, or 4 values")


def _distance(item: FeedCandidate, profile: tuple[float, float]) -> float:
    # Normalize each canonical dimension by its complete range before taking
    # Euclidean distance: x spans 200 points, sensationalism spans 100.
    return min(
        1.0,
        math.sqrt(
            ((item.x - profile[0]) / 200.0) ** 2
            + ((item.sensationalism - profile[1]) / 100.0) ** 2
        )
        / math.sqrt(2.0),
    )


def _recency(published: datetime | None, now: datetime) -> float:
    if published is None:
        return 0.2
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    age_hours = max(0.0, (now - published).total_seconds() / 3600)
    return math.exp(-age_hours / (24 * 7))
