"""Pure, byte-stable article score calculation."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


@dataclass(frozen=True)
class WeightProfile:
    model: Decimal = Decimal("0.50")
    relative: Decimal = Decimal("0.20")
    crowd: Decimal = Decimal("0.20")
    source: Decimal = Decimal("0.10")
    version: str = "default"

    def __post_init__(self) -> None:
        values = tuple(
            Decimal(str(value)) for value in (self.model, self.relative, self.crowd, self.source)
        )
        object.__setattr__(self, "model", values[0])
        object.__setattr__(self, "relative", values[1])
        object.__setattr__(self, "crowd", values[2])
        object.__setattr__(self, "source", values[3])
        if (
            any(not value.is_finite() or value < 0 for value in values)
            or sum(values, Decimal(0)) <= 0
        ):
            raise ValueError("weights must be non-negative and have a positive total")

    @property
    def total(self) -> Decimal:
        return sum((self.model, self.relative, self.crowd, self.source), Decimal(0))

    def as_dict(self) -> dict[str, str]:
        return {
            "model": str(self.model),
            "relative": str(self.relative),
            "crowd": str(self.crowd),
            "source": str(self.source),
            "version": self.version,
        }


@dataclass(frozen=True)
class ScoreComponents:
    model: tuple[float, float, float]
    relative: tuple[float, float, float]
    crowd: tuple[float, float, float]
    source: tuple[float, float, float]
    model_confidence: float = 0.0
    vote_count: int = 0
    source_sample_size: int = 0
    model_spread: float = 0.0
    sensationalism: float = 0.0
    evidence_quality: float = 0.0

    def __post_init__(self) -> None:
        for name in ("model", "relative", "crowd", "source"):
            value = getattr(self, name)
            if isinstance(value, Mapping):
                value = tuple(value.get(axis, 0) for axis in ("x", "y", "z"))
            if isinstance(value, (str, bytes)):
                raise ValueError(f"{name} must contain three coordinates in [-100,100]")
            try:
                raw_coordinates = tuple(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{name} must contain three coordinates in [-100,100]"
                ) from exc
            if any(isinstance(item, bool) for item in raw_coordinates):
                raise ValueError(f"{name} must contain three coordinates in [-100,100]")
            try:
                coordinates = tuple(float(item) for item in raw_coordinates)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{name} must contain three coordinates in [-100,100]"
                ) from exc
            if len(coordinates) != 3 or any(
                not math.isfinite(item) or not -100 <= item <= 100
                for item in coordinates
            ):
                raise ValueError(f"{name} must contain three coordinates in [-100,100]")
            # Only x is a canonical political-bias coordinate. Keep the
            # physical tuple shape for old callers while preventing legacy
            # y/z values from entering any new score calculation or snapshot.
            object.__setattr__(self, name, (coordinates[0], 0.0, 0.0))
        if (
            not isinstance(self.vote_count, int)
            or isinstance(self.vote_count, bool)
            or not isinstance(self.source_sample_size, int)
            or isinstance(self.source_sample_size, bool)
        ):
            raise ValueError("score component counts must be integers")
        numeric_metadata = (
            self.sensationalism,
            self.model_spread,
            self.model_confidence,
            self.evidence_quality,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in numeric_metadata
        ):
            raise ValueError("score component metadata must be finite numbers")
        if not 0 <= self.sensationalism <= 100:
            raise ValueError("sensationalism must be in [0,100]")
        if (
            self.vote_count < 0
            or self.source_sample_size < 0
            or self.model_spread < 0
            or not 0 <= self.model_confidence <= 1
            or not 0 <= self.evidence_quality <= 1
        ):
            raise ValueError("invalid score component metadata")


@dataclass(frozen=True)
class ArticleScore:
    x: int
    y: int
    z: int
    sensationalism: int
    confidence: float
    weight_version: str
    components: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "sensationalism": self.sensationalism,
            "confidence": self.confidence,
            "weight_version": self.weight_version,
            "components": self.components,
        }


def calculate_article_score(
    components: ScoreComponents | Mapping[str, Any],
    weights: WeightProfile | Mapping[str, Any] | None = None,
    *,
    fact_check: Any = None,
) -> ArticleScore:
    """Calculate a reproducible score; ``fact_check`` is intentionally ignored."""

    if not isinstance(components, ScoreComponents):
        components = ScoreComponents(**components)
    if weights is None:
        weights = WeightProfile()
    elif not isinstance(weights, WeightProfile):
        component_keys = ("model", "relative", "crowd", "source")
        if not any(key in weights for key in component_keys):
            weights = WeightProfile(version=str(weights.get("version", "default")))
        else:
            # A partial mapping is intentional: omitted component keys are 0,
            # not WeightProfile defaults (0.50/0.20/0.20/0.10).
            weights = WeightProfile(
                model=Decimal(str(weights.get("model", "0"))),
                relative=Decimal(str(weights.get("relative", "0"))),
                crowd=Decimal(str(weights.get("crowd", "0"))),
                source=Decimal(str(weights.get("source", "0"))),
                version=str(weights.get("version", "default")),
            )
    total = weights.total

    def combine(axis: int) -> int:
        values = (
            components.model[axis],
            components.relative[axis],
            components.crowd[axis],
            components.source[axis],
        )
        raw = (
            sum(
                (
                    weight * Decimal(str(value))
                    for weight, value in zip(
                        (weights.model, weights.relative, weights.crowd, weights.source),
                        values,
                        strict=True,
                    )
                ),
                Decimal(0),
            )
            / total
        )
        return _round_clamp(raw, -100, 100)

    # Crowd and source evidence contribute to confidence without changing the
    # ideological direction of any fact-check result.
    vote_factor = min(1.0, components.vote_count / 20.0)
    source_factor = min(1.0, components.source_sample_size / 20.0)
    spread_factor = max(0.0, 1.0 - min(1.0, components.model_spread / 100.0))
    spread_confidence = spread_factor * 0.05 if components.model_confidence > 0 else 0.0
    confidence = round(
        max(
            0.0,
            min(
                1.0,
                components.model_confidence * 0.45
                + components.evidence_quality * 0.25
                + vote_factor * 0.15
                + source_factor * 0.10
                + spread_confidence,
            ),
        ),
        6,
    )
    return ArticleScore(
        combine(0),
        0,
        0,
        _round_clamp(Decimal(str(components.sensationalism)), 0, 100),
        confidence,
        weights.version,
        {
            "model": list(components.model),
            "relative": list(components.relative),
            "crowd": list(components.crowd),
            "source": list(components.source),
            "model_spread": components.model_spread,
            "model_confidence": components.model_confidence,
            "evidence_quality": components.evidence_quality,
            "sensationalism": components.sensationalism,
            "vote_count": components.vote_count,
            "source_sample_size": components.source_sample_size,
        },
    )


def canonical_score_json(score: ArticleScore | Mapping[str, Any]) -> bytes:
    """Canonical JSON bytes for snapshot hashes and reproducibility tests."""

    value = score.as_dict() if isinstance(score, ArticleScore) else dict(score)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _round_clamp(value: Decimal, low: int, high: int) -> int:
    return max(low, min(high, int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))))
