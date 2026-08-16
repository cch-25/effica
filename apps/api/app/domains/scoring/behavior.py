"""Consumption/vote-derived behavioural profile coordinates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class BehaviorEvent:
    article_x: float
    article_y: float
    article_z: float
    kind: str = "read"
    weight: float = 1.0
    vote_x: float | None = None
    vote_y: float | None = None
    vote_z: float | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class BehavioralProfile:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    confidence: float = 0.0
    event_count: int = 0
    active: bool = False
    policy_version: str = "behavior-v1"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def update_behavioral_profile(
    profile: BehavioralProfile,
    events: Iterable[BehaviorEvent],
    *,
    decay: float = 1.0,
    activate: bool = False,
) -> BehavioralProfile:
    """Update a profile from weighted reads/votes without identity inference."""

    if not 0 < decay <= 1:
        raise ValueError("decay must be in (0,1]")
    current = [float(profile.x), float(profile.y), float(profile.z)]
    total = float(profile.event_count)
    count = profile.event_count
    for event in events:
        if event.weight < 0:
            raise ValueError("event weight must be non-negative")
        values = [event.article_x, event.article_y, event.article_z]
        if event.vote_x is not None and event.vote_y is not None and event.vote_z is not None:
            # A qualified vote is a stronger signal but never mandatory.
            values = [event.vote_x, event.vote_y, event.vote_z]
        weight = float(event.weight)
        if weight == 0:
            continue
        if total:
            current = [
                ((axis * total * decay) + value * weight) / (total * decay + weight)
                for axis, value in zip(current, values, strict=True)
            ]
            total = total * decay + weight
        else:
            current = values[:]
            total = weight
        count += 1
    confidence = round(min(1.0, total / (total + 10.0)), 6)
    coordinates = [round(max(-100.0, min(100.0, axis)), 6) for axis in current]
    return BehavioralProfile(
        x=coordinates[0],
        y=coordinates[1],
        z=coordinates[2],
        confidence=confidence,
        event_count=count,
        active=profile.active or activate,
        policy_version=profile.policy_version,
    )
