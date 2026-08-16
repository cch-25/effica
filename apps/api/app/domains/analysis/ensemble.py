"""Ensemble, spread and confidence calculations."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from statistics import mean

from .schema import ModelAssessment


@dataclass(frozen=True)
class EnsembleResult:
    article_version_id: str
    successful_model_count: int
    required_model_count: int
    eligible: bool
    reason_code: str
    x: int | None
    y: int | None
    z: int | None
    sensationalism: int | None
    confidence: float
    spread: float
    model_aliases: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def ensemble_assessments(
    assessments: Iterable[ModelAssessment],
    *,
    min_success_models: int = 2,
    max_spread: float = 40.0,
) -> EnsembleResult:
    """Aggregate valid assessments, enforcing minimum count and spread.

    Spread is the maximum coordinate range across x/y/z/sensationalism.  A
    failed/rejected model is ignored; callers can persist it separately.
    """

    if min_success_models < 1 or max_spread < 0:
        raise ValueError("invalid ensemble policy")
    normalised = [
        item if isinstance(item, ModelAssessment) else ModelAssessment.model_validate(item)
        for item in assessments
    ]
    values = [item for item in normalised if item.status.value == "SUCCEEDED"]
    if not values:
        version = normalised[0].article_version_id if normalised else ""
        return EnsembleResult(
            version,
            0,
            min_success_models,
            False,
            "NO_SUCCESSFUL_MODELS",
            None,
            None,
            None,
            None,
            0.0,
            float("inf"),
            (),
        )
    article_ids = {item.article_version_id for item in values}
    if len(article_ids) != 1:
        raise ValueError("all assessments must reference one article version")
    version = values[0].article_version_id
    spread = max(
        max(item.x for item in values) - min(item.x for item in values),
        max(item.y for item in values) - min(item.y for item in values),
        max(item.z for item in values) - min(item.z for item in values),
        max(item.sensationalism for item in values) - min(item.sensationalism for item in values),
    )
    eligible = len(values) >= min_success_models and spread <= max_spread
    reason = (
        "OK"
        if eligible
        else (
            "INSUFFICIENT_MODELS" if len(values) < min_success_models else "MODEL_SPREAD_TOO_WIDE"
        )
    )
    confidence = _confidence(values, spread, max_spread) if eligible else 0.0
    return EnsembleResult(
        version,
        len(values),
        min_success_models,
        eligible,
        reason,
        round(mean(item.x for item in values)) if eligible else None,
        round(mean(item.y for item in values)) if eligible else None,
        round(mean(item.z for item in values)) if eligible else None,
        round(mean(item.sensationalism for item in values)) if eligible else None,
        confidence,
        float(spread),
        tuple(sorted(item.model_alias for item in values)),
    )


def _confidence(values: Sequence[ModelAssessment], spread: float, max_spread: float) -> float:
    base = mean(item.confidence for item in values)
    spread_factor = 1.0 if max_spread == 0 else max(0.0, 1.0 - spread / max_spread)
    count_factor = min(1.0, len(values) / 3.0)
    return round(
        max(0.0, min(1.0, base * (0.5 + 0.5 * spread_factor) * (0.75 + 0.25 * count_factor))), 6
    )


def fact_check_does_not_change_axes(
    assessment: ModelAssessment, verdict: str | None = None
) -> ModelAssessment:
    """Attachable fact-checks never mutate ideological coordinates."""

    return assessment.model_copy(deep=True)
