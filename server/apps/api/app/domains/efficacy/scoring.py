"""Versioned efficacy scoring without exposing small cohorts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class EfficacyResponse:
    response_id: str
    user_id: str
    questionnaire_version: str
    answers: tuple[int, ...]
    submitted_at: datetime
    cohort_key: str | None = None
    kind: str = "baseline"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> EfficacyResponse:
        stamp = value.get("submitted_at", datetime.now(UTC))
        if isinstance(stamp, str):
            stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return cls(
            str(value["response_id"]),
            str(value["user_id"]),
            str(value["questionnaire_version"]),
            tuple(int(item) for item in value["answers"]),
            stamp,
            value.get("cohort_key"),
            str(value.get("kind", "baseline")),
        )


@dataclass(frozen=True)
class EfficacyScore:
    response_id: str
    questionnaire_version: str
    normalized_score: float
    answer_count: int
    kind: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_efficacy_score(
    answers: Sequence[int],
    *,
    min_answer: int = 1,
    max_answer: int = 5,
    reverse_indices: Iterable[int] = (),
) -> float:
    """Normalize Likert answers to ``0..100`` with optional reverse items."""

    if max_answer <= min_answer:
        raise ValueError("max_answer must exceed min_answer")
    values = list(answers)
    if not values:
        raise ValueError("at least one efficacy answer is required")
    reverse = set(reverse_indices)
    for index, answer in enumerate(values):
        if (
            not isinstance(answer, int)
            or isinstance(answer, bool)
            or not min_answer <= answer <= max_answer
        ):
            raise ValueError("efficacy answer outside questionnaire range")
        if index in reverse:
            values[index] = max_answer + min_answer - answer
    return round(
        mean((answer - min_answer) / (max_answer - min_answer) * 100 for answer in values), 6
    )


def calculate_efficacy_score(
    response: EfficacyResponse | Mapping[str, Any],
    *,
    reverse_indices: Iterable[int] = (),
    min_answer: int = 1,
    max_answer: int = 5,
) -> EfficacyScore:
    if not isinstance(response, EfficacyResponse):
        response = EfficacyResponse.from_mapping(response)
    return EfficacyScore(
        response.response_id,
        response.questionnaire_version,
        normalize_efficacy_score(
            response.answers,
            min_answer=min_answer,
            max_answer=max_answer,
            reverse_indices=reverse_indices,
        ),
        len(response.answers),
        response.kind,
    )


def efficacy_delta(baseline: EfficacyScore | None, followup: EfficacyScore | None) -> float | None:
    if baseline is None or followup is None:
        return None
    return round(followup.normalized_score - baseline.normalized_score, 6)


def followup_due(
    last_response_at: datetime | None, *, now: datetime | None = None, interval_days: int = 30
) -> bool:
    if interval_days < 1:
        raise ValueError("interval_days must be positive")
    if last_response_at is None:
        return True
    now = now or datetime.now(UTC)
    last = (
        last_response_at
        if last_response_at.tzinfo
        else last_response_at.replace(tzinfo=UTC)
    )
    current = now if now.tzinfo else now.replace(tzinfo=UTC)
    return current >= last + timedelta(days=interval_days)


def aggregate_efficacy(
    responses: Iterable[EfficacyResponse | Mapping[str, Any]],
    *,
    min_cohort_size: int = 10,
    reverse_indices: Iterable[int] = (),
) -> dict[str, Any]:
    """Return aggregate scores and suppress cohorts below the privacy floor."""

    if min_cohort_size < 1:
        raise ValueError("min_cohort_size must be positive")
    values = [
        item if isinstance(item, EfficacyResponse) else EfficacyResponse.from_mapping(item)
        for item in responses
    ]
    scored = [
        (item, normalize_efficacy_score(item.answers, reverse_indices=reverse_indices))
        for item in values
    ]
    result: dict[str, Any] = {
        "count": len(scored),
        "mean": round(mean(value for _, value in scored), 6) if scored else None,
        "cohorts": {},
        "suppressed_cohorts": 0,
    }
    groups: dict[str, dict[str, tuple[EfficacyResponse, float]]] = {}
    for item, score in scored:
        if item.cohort_key:
            cohort_group = groups.setdefault(item.cohort_key, {})
            prior = cohort_group.get(item.user_id)
            if prior is None or _response_order(item) > _response_order(prior[0]):
                cohort_group[item.user_id] = (item, score)
    for cohort, by_user in sorted(groups.items()):
        scores = [item[1] for item in by_user.values()]
        if len(scores) >= min_cohort_size:
            result["cohorts"][cohort] = {"count": len(scores), "mean": round(mean(scores), 6)}
        else:
            result["suppressed_cohorts"] += 1
    return result


def _response_order(response: EfficacyResponse) -> tuple[float, str]:
    stamp = response.submitted_at
    if isinstance(stamp, str):
        try:
            stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            return float("-inf"), response.response_id
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp.timestamp(), response.response_id
