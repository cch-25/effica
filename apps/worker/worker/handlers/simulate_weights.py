"""Small deterministic shadow simulation for proposed feed weights."""

from __future__ import annotations

import inspect
import math
from collections.abc import Mapping
from typing import Any

from apps.api.app.domains.admin.autopilot import (
    GuardrailConfig,
    evaluate_guardrails,
)
from apps.api.app.domains.admin.autopilot import (
    simulate_weights as domain_simulate_weights,
)

from .base import HandlerContext, HandlerResult, NonRetryableHandlerError, lookup_service

JOB_TYPE = "simulate_weights"

_NON_WEIGHT_KEYS = frozenset(
    {
        "base_revision_id",
        "base_weights",
        "based_on_revision_id",
        "captured_at",
        "deltas",
        "evidence",
        "evidence_snapshot",
        "evidence_snapshot_id",
        "guardrails",
        "id",
        "kind",
        "metrics",
        "outcomes",
        "proposed_weights",
        "recommendation_id",
        "revision",
        "status",
        "version",
        "weight_revision_id",
        "weights",
        "window_days",
        "windows",
    }
)


def _coerce_weight_vector(value: Any) -> dict[str, float] | None:
    if not isinstance(value, Mapping) or not value:
        return None
    source: Mapping[str, Any] = value
    nested = value.get("weights")
    if isinstance(nested, Mapping) and nested:
        source = nested
    else:
        nested = value.get("proposed_weights")
        if isinstance(nested, Mapping) and nested:
            source = nested
    raw: dict[str, float] = {}
    for key, item in source.items():
        name = str(key)
        if name in _NON_WEIGHT_KEYS or isinstance(item, (bool, Mapping)):
            continue
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            raw[name] = number
    return raw or None


def _call_simulate(
    base: Mapping[str, float],
    proposed: Mapping[str, float],
    *,
    window_days: int,
    evidence: Mapping[str, Any] | None,
) -> Any:
    kwargs: dict[str, Any] = {"window_days": window_days}
    parameters: Mapping[str, inspect.Parameter]
    try:
        parameters = inspect.signature(domain_simulate_weights).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "evidence" in parameters:
        kwargs["evidence"] = evidence
    return domain_simulate_weights(base, proposed, **kwargs)


async def handle(
    payload: Mapping[str, Any], context: HandlerContext | None = None
) -> HandlerResult:
    loaded_weights: Mapping[str, Any] = {}
    if payload.get("recommendation_id") or payload.get("weight_id"):
        loaded = await lookup_service(
            context,
            ("weights_lookup", "recommendation_lookup", "load_weights", "weights"),
            identifier=payload.get("recommendation_id") or payload.get("weight_id"),
            payload=payload,
        )
        if isinstance(loaded, Mapping):
            loaded_weights = loaded

    proposed = (
        _coerce_weight_vector(payload.get("weights"))
        or _coerce_weight_vector(payload.get("proposed_weights"))
        or _coerce_weight_vector(loaded_weights)
    )
    if proposed is None:
        raise NonRetryableHandlerError("weights are required", code="INVALID_SIMULATION_PAYLOAD")

    base = _coerce_weight_vector(payload.get("base_weights"))
    if base is None:
        active = await lookup_service(
            context,
            ("weights_lookup", "load_weights", "weights"),
            identifier="active",
            payload=payload,
        )
        if isinstance(active, Mapping):
            base = _coerce_weight_vector(active)
    if base is None:
        base_id = (
            payload.get("base_revision_id")
            or loaded_weights.get("based_on_revision_id")
            or loaded_weights.get("base_revision_id")
        )
        if base_id not in (None, ""):
            loaded_base = await lookup_service(
                context,
                ("weights_lookup", "load_weights", "weights"),
                identifier=base_id,
                payload=payload,
            )
            if isinstance(loaded_base, Mapping):
                base = _coerce_weight_vector(loaded_base)
    if base is None:
        raise NonRetryableHandlerError(
            "base weights from the active or base revision are required",
            code="INVALID_SIMULATION_PAYLOAD",
        )

    evidence: Mapping[str, Any] | None = None
    for candidate in (
        payload.get("evidence"),
        payload.get("evidence_snapshot"),
        loaded_weights.get("evidence_snapshot"),
        loaded_weights.get("evidence"),
    ):
        if isinstance(candidate, Mapping) and candidate:
            evidence = candidate
            break

    articles = payload.get("articles", [])
    sample_size = (
        len(articles)
        if isinstance(articles, (list, tuple))
        else int(payload.get("sample_size", 0) or 0)
    )
    windows = payload.get("windows") or [7, 30]
    if not isinstance(windows, (list, tuple)) or set(windows) != {7, 30}:
        raise NonRetryableHandlerError(
            "7-day and 30-day windows are required",
            code="SIMULATION_WINDOWS_REQUIRED",
        )
    try:
        simulations = [
            _call_simulate(base, proposed, window_days=int(window), evidence=evidence)
            for window in windows
        ]
        guardrails = evaluate_guardrails(
            base,
            proposed,
            simulations,
            baseline_metrics=simulations[0],
            config=GuardrailConfig(require_reviewer=False),
        )
    except (TypeError, ValueError) as exc:
        raise NonRetryableHandlerError(
            str(exc) or "weights must be numeric",
            code="INVALID_SIMULATION_WEIGHTS",
        ) from exc
    score = sum(proposed.values()) / max(1, len(proposed))
    return HandlerResult(
        value={
            "windows": [int(window) for window in windows],
            "sample_size": sample_size,
            "projected_score": round(score, 6),
            "weights": proposed,
            "base_weights": base,
            "recommendation_id": payload.get("recommendation_id")
            or loaded_weights.get("recommendation_id"),
            "simulations": [
                {
                    "window_days": item.window_days,
                    "gold_error": item.gold_error,
                    "diversity": item.diversity,
                    "distribution_shift": item.distribution_shift,
                    "model_success_rate": item.model_success_rate,
                    "provider_cost": item.provider_cost,
                    "provider_latency_ms": item.provider_latency_ms,
                }
                for item in simulations
            ],
            "guardrail_result": {
                "status": "PASS" if guardrails.passed else "FAILED",
                "passed": guardrails.passed,
                "failures": list(guardrails.failures),
            },
            "status": "simulation",
        },
        side_effect_key=(context.idempotency_key if context else None),
    )


run = handle
