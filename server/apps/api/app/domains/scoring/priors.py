"""Source-prior shrinkage."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SourcePrior:
    x: float
    y: float
    z: float
    sensationalism: float
    sample_size: int
    prior_strength: float
    confidence: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def shrink_source_prior(
    source_mean: dict[str, float] | tuple[float, float, float, float],
    sample_size: int,
    global_mean: dict[str, float] | tuple[float, float, float, float] = (0.0, 0.0, 0.0, 50.0),
    *,
    prior_strength: float = 20.0,
) -> SourcePrior:
    """Shrink a source's observed distribution toward the global mean."""

    if sample_size < 0 or prior_strength <= 0:
        raise ValueError("invalid sample size or prior strength")
    source = _values(source_mean)
    global_values = _values(global_mean)
    factor = sample_size / (sample_size + prior_strength)
    values = tuple(
        round(factor * left + (1.0 - factor) * right, 6)
        for left, right in zip(source, global_values, strict=True)
    )
    confidence = round(sample_size / (sample_size + prior_strength), 6)
    return SourcePrior(
        x=values[0],
        y=values[1],
        z=values[2],
        sensationalism=values[3],
        sample_size=sample_size,
        prior_strength=prior_strength,
        confidence=confidence,
    )


def _values(
    value: dict[str, float] | tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    if isinstance(value, dict):
        return tuple(
            float(value.get(key, 0.0 if key != "sensationalism" else 50.0))
            for key in ("x", "y", "z", "sensationalism")
        )  # type: ignore[return-value]
    if len(value) != 4:
        raise ValueError("source means need four values")
    return tuple(float(item) for item in value)  # type: ignore[return-value]
