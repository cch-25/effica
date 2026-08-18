"""Pure Auto Pilot weight lifecycle with immutable revisions and guardrails."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class WeightRevisionStatus(str, Enum):
    DRAFT = "draft"
    SIMULATION = "simulation"
    ACTIVE = "active"
    ARCHIVED = "archived"


class AutoPilotMode(str, Enum):
    OFF = "OFF"
    RECOMMEND = "RECOMMEND"
    LIMITED_AUTO = "LIMITED_AUTO"


@dataclass(frozen=True)
class GuardrailConfig:
    min_model_success_rate: float = 0.90
    max_provider_cost: float = 100.0
    max_provider_latency_ms: float = 10_000.0
    max_axis_change: float = 0.10
    min_weight: float = 0.0
    max_weight: float = 1.0
    max_gold_error_increase: float = 0.02
    max_diversity_drop: float = 0.05
    max_distribution_shift: float = 0.15
    require_reviewer: bool = True

    def __post_init__(self) -> None:
        if (
            not 0 <= self.min_model_success_rate <= 1
            or self.max_provider_cost < 0
            or self.max_provider_latency_ms < 0
            or self.max_axis_change < 0
            or self.min_weight < 0
            or self.max_weight < self.min_weight
            or self.max_gold_error_increase < 0
            or self.max_diversity_drop < 0
            or self.max_distribution_shift < 0
        ):
            raise ValueError("invalid Auto Pilot guardrail bounds")


@dataclass(frozen=True)
class SimulationMetrics:
    window_days: int
    gold_error: float
    diversity: float
    distribution_shift: float
    model_success_rate: float
    provider_cost: float
    provider_latency_ms: float

    def __post_init__(self) -> None:
        if (
            self.window_days < 1
            or not 0 <= self.gold_error <= 1
            or not 0 <= self.diversity <= 1
            or self.distribution_shift < 0
            or not 0 <= self.model_success_rate <= 1
            or self.provider_cost < 0
            or self.provider_latency_ms < 0
        ):
            raise ValueError("invalid simulation metrics")


@dataclass(frozen=True)
class GuardrailResult:
    passed: bool
    failures: tuple[str, ...]

    @property
    def reason_code(self) -> str:
        return "PASSED" if self.passed else "GUARDRAIL_FAILED"


@dataclass(frozen=True)
class WeightRecommendation:
    recommendation_id: str
    base_revision_id: str
    proposed_weights: dict[str, float]
    evidence_snapshot_id: str
    status: str = "pending"


@dataclass(frozen=True)
class WeightRevision:
    revision_id: str
    revision: int
    weights: dict[str, float]
    status: WeightRevisionStatus
    based_on_revision_id: str | None = None
    created_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    published_at: datetime | None = None
    guardrail_result: GuardrailResult | None = None


def validate_weights(
    weights: Mapping[str, Any], *, config: GuardrailConfig | None = None
) -> dict[str, float]:
    config = config or GuardrailConfig()
    if not weights:
        raise ValueError("weights cannot be empty")
    result: dict[str, float] = {}
    for key, value in sorted(weights.items()):
        if not isinstance(key, str) or not key:
            raise ValueError("weight keys must be non-empty strings")
        if isinstance(value, bool):
            raise ValueError(f"weight {key} is not numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"weight {key} is not numeric") from exc
        if not math.isfinite(number) or number < config.min_weight or number > config.max_weight:
            raise ValueError(f"weight {key} outside allowed range")
        result[key] = round(number, 8)
    if not math.isclose(sum(result.values()), 1.0, rel_tol=0.0, abs_tol=1e-8):
        raise ValueError("weights must sum to 1")
    return result


def _normalise_weight_total(weights: Mapping[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0 or not math.isfinite(total):
        return dict(weights)
    return {key: round(value / total, 8) for key, value in weights.items()}


def recommend_weights(
    base_weights: Mapping[str, Any],
    *,
    evidence_snapshot_id: str,
    base_revision_id: str | None = None,
    evidence: Mapping[str, Any] | None = None,
    recommendation_id: str | None = None,
    config: GuardrailConfig | None = None,
) -> WeightRecommendation:
    """Create a deterministic bounded recommendation from evidence metrics."""

    config = config or GuardrailConfig()
    base = validate_weights(base_weights, config=config)
    evidence = evidence or {}
    # Explicit per-key deltas are preferred; otherwise use a conservative
    # signal from a named metric.  Never recommend beyond max_axis_change.
    deltas = evidence.get("deltas", {})
    proposed: dict[str, float] = {}
    for key, value in base.items():
        raw_delta = deltas.get(key, 0.0) if isinstance(deltas, Mapping) else 0.0
        try:
            delta = max(-config.max_axis_change, min(config.max_axis_change, float(raw_delta)))
        except (TypeError, ValueError):
            delta = 0.0
        proposed[key] = round(max(config.min_weight, min(config.max_weight, value + delta)), 8)
    proposed = _normalise_weight_total(proposed)
    digest = (
        recommendation_id
        or hashlib.sha256((evidence_snapshot_id + _canonical(proposed)).encode()).hexdigest()[:26]
    )
    return WeightRecommendation(
        digest,
        base_revision_id or str(evidence.get("base_revision_id", "")),
        proposed,
        evidence_snapshot_id,
    )


def simulate_weights(
    base_weights: Mapping[str, Any],
    proposed_weights: Mapping[str, Any],
    *,
    window_days: int,
    evidence: Mapping[str, Any] | None = None,
) -> SimulationMetrics:
    """Run a deterministic shadow simulation over supplied evidence metrics."""

    if window_days not in {7, 30}:
        raise ValueError("simulations must use 7 or 30 day windows")
    base = validate_weights(base_weights)
    proposed = validate_weights(proposed_weights)
    evidence = evidence or {}
    distance = sum(
        abs(proposed.get(key, 0) - base.get(key, 0)) for key in set(base) | set(proposed)
    )
    metrics = evidence.get("metrics", evidence)
    return SimulationMetrics(
        window_days,
        max(
            0.0,
            min(
                1.0,
                float(metrics.get("gold_error", 0.10))
                + distance * float(metrics.get("gold_error_slope", 0.05)),
            ),
        ),
        max(
            0.0,
            min(
                1.0,
                float(metrics.get("diversity", 0.70))
                - distance * float(metrics.get("diversity_slope", 0.05)),
            ),
        ),
        max(0.0, float(metrics.get("distribution_shift", 0.01)) + distance),
        max(0.0, min(1.0, float(metrics.get("model_success_rate", 0.99)))),
        max(
            0.0,
            float(metrics.get("provider_cost", 1.0))
            + distance * float(metrics.get("cost_slope", 1.0)),
        ),
        max(
            0.0,
            float(metrics.get("provider_latency_ms", 100.0))
            + distance * float(metrics.get("latency_slope", 100.0)),
        ),
    )


def evaluate_guardrails(
    base_weights: Mapping[str, Any],
    proposed_weights: Mapping[str, Any],
    simulations: Iterable[SimulationMetrics],
    *,
    baseline_metrics: SimulationMetrics | None = None,
    config: GuardrailConfig | None = None,
    reviewer_approved: bool = False,
) -> GuardrailResult:
    config = config or GuardrailConfig()
    failures: list[str] = []
    try:
        base = validate_weights(base_weights, config=config)
        proposed = validate_weights(proposed_weights, config=config)
    except ValueError as exc:
        return GuardrailResult(False, (f"INVALID_WEIGHTS:{exc}",))
    for key in set(base) | set(proposed):
        if abs(proposed.get(key, 0) - base.get(key, 0)) > config.max_axis_change:
            failures.append(f"MAX_CHANGE:{key}")
    runs = list(simulations)
    windows = {run.window_days for run in runs}
    for needed in (7, 30):
        if needed not in windows:
            failures.append(f"MISSING_SIMULATION:{needed}")
    if baseline_metrics is None and runs:
        baseline_metrics = SimulationMetrics(0 if False else 1, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for run in runs:
        if run.model_success_rate < config.min_model_success_rate:
            failures.append(f"MODEL_SUCCESS:{run.window_days}")
        if run.provider_cost > config.max_provider_cost:
            failures.append(f"PROVIDER_COST:{run.window_days}")
        if run.provider_latency_ms > config.max_provider_latency_ms:
            failures.append(f"PROVIDER_LATENCY:{run.window_days}")
        if run.distribution_shift > config.max_distribution_shift:
            failures.append(f"DISTRIBUTION_SHIFT:{run.window_days}")
        if baseline_metrics is not None:
            if run.gold_error - baseline_metrics.gold_error > config.max_gold_error_increase:
                failures.append(f"GOLD_ERROR:{run.window_days}")
            if baseline_metrics.diversity - run.diversity > config.max_diversity_drop:
                failures.append(f"DIVERSITY:{run.window_days}")
    if config.require_reviewer and not reviewer_approved:
        failures.append("REVIEWER_REQUIRED")
    return GuardrailResult(not failures, tuple(sorted(set(failures))))


class AutoPilotManager:
    """Revision manager enforcing If-Match, idempotency and immutable rollback."""

    def __init__(self, initial: WeightRevision, *, mode: AutoPilotMode = AutoPilotMode.OFF) -> None:
        validate_weights(initial.weights)
        self.mode = mode
        self.revisions: dict[str, WeightRevision] = {initial.revision_id: initial}
        self.active_revision_id = (
            initial.revision_id if initial.status == WeightRevisionStatus.ACTIVE else None
        )
        self._idempotency: dict[str, WeightRevision] = {}
        self._lock = threading.RLock()

    @property
    def active(self) -> WeightRevision | None:
        return self.revisions.get(self.active_revision_id) if self.active_revision_id else None

    def add_draft(self, revision: WeightRevision) -> WeightRevision:
        with self._lock:
            if revision.revision_id in self.revisions:
                return self.revisions[revision.revision_id]
            if revision.status not in {WeightRevisionStatus.DRAFT, WeightRevisionStatus.SIMULATION}:
                raise ValueError("new revision must be draft or simulation")
            validate_weights(revision.weights)
            self.revisions[revision.revision_id] = revision
            return revision

    def publish(
        self,
        revision_id: str,
        *,
        if_match: str,
        idempotency_key: str,
        guardrail_result: GuardrailResult,
        reviewer_approved: bool = False,
    ) -> WeightRevision:
        with self._lock:
            if idempotency_key in self._idempotency:
                return self._idempotency[idempotency_key]
            if self.active_revision_id != if_match:
                raise ValueError("If-Match revision conflict")
            revision = self.revisions.get(revision_id)
            if revision is None:
                raise KeyError("weight revision not found")
            if revision.status is not WeightRevisionStatus.SIMULATION:
                raise ValueError("only simulated revisions can be published")
            validate_weights(revision.weights)
            if not guardrail_result.passed:
                raise ValueError("guardrails failed")
            if revision.guardrail_result is not None and not revision.guardrail_result.passed:
                raise ValueError("revision guardrails failed")
            if reviewer_approved is False and self.mode != AutoPilotMode.LIMITED_AUTO:
                # Keep approval explicit for RECOMMEND/OFF. LIMITED_AUTO may
                # publish only when caller has already passed guardrails.
                raise ValueError("reviewer approval required")
            old = self.active
            if old is not None:
                self.revisions[old.revision_id] = WeightRevision(
                    old.revision_id,
                    old.revision,
                    old.weights,
                    WeightRevisionStatus.ARCHIVED,
                    old.based_on_revision_id,
                    old.created_by,
                    old.created_at,
                    old.published_at,
                    old.guardrail_result,
                )
            published = WeightRevision(
                revision.revision_id,
                revision.revision,
                dict(revision.weights),
                WeightRevisionStatus.ACTIVE,
                revision.based_on_revision_id,
                revision.created_by,
                revision.created_at,
                datetime.now(UTC),
                guardrail_result,
            )
            self.revisions[revision_id] = published
            self.active_revision_id = revision_id
            self._idempotency[idempotency_key] = published
            return published

    def rollback(
        self,
        target_revision_id: str,
        *,
        if_match: str,
        idempotency_key: str,
        actor: str | None = None,
    ) -> WeightRevision:
        with self._lock:
            if idempotency_key in self._idempotency:
                return self._idempotency[idempotency_key]
            if self.active_revision_id != if_match:
                raise ValueError("If-Match revision conflict")
            target = self.revisions.get(target_revision_id)
            if target is None:
                raise KeyError("target revision not found")
            if target.status is not WeightRevisionStatus.ARCHIVED:
                raise ValueError("rollback target must be an archived revision")
            validate_weights(target.weights)
            active = self.active
            next_number = max(item.revision for item in self.revisions.values()) + 1
            digest = hashlib.sha256(
                f"rollback:{target_revision_id}:{next_number}".encode()
            ).hexdigest()[:26]
            rollback = WeightRevision(
                digest,
                next_number,
                dict(target.weights),
                WeightRevisionStatus.ACTIVE,
                target.revision_id,
                actor,
                datetime.now(UTC),
                datetime.now(UTC),
                GuardrailResult(True, ()),
            )
            if active is not None:
                self.revisions[active.revision_id] = WeightRevision(
                    active.revision_id,
                    active.revision,
                    active.weights,
                    WeightRevisionStatus.ARCHIVED,
                    active.based_on_revision_id,
                    active.created_by,
                    active.created_at,
                    active.published_at,
                    active.guardrail_result,
                )
            self.revisions[rollback.revision_id] = rollback
            self.active_revision_id = rollback.revision_id
            self._idempotency[idempotency_key] = rollback
            return rollback


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
