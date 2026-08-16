"""Small deterministic shadow simulation for proposed feed weights."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.api.app.domains.admin.autopilot import (
    GuardrailConfig,
    evaluate_guardrails,
    simulate_weights,
)

from .base import HandlerContext, HandlerResult, NonRetryableHandlerError, lookup_service

JOB_TYPE = "simulate_weights"


async def handle(
    payload: Mapping[str, Any], context: HandlerContext | None = None
) -> HandlerResult:
    weights = payload.get("weights")
    loaded_weights: Mapping[str, Any] = {}
    if (not isinstance(weights, Mapping) or not weights) and (
        payload.get("recommendation_id") or payload.get("weight_id")
    ):
        loaded = await lookup_service(
            context,
            ("weights_lookup", "recommendation_lookup", "load_weights", "weights"),
            identifier=payload.get("recommendation_id") or payload.get("weight_id"),
            payload=payload,
        )
        if isinstance(loaded, Mapping):
            loaded_weights = loaded
            weights = loaded.get("weights", loaded.get("proposed_weights", loaded))
    if not isinstance(weights, Mapping) or not weights:
        raise NonRetryableHandlerError("weights are required", code="INVALID_SIMULATION_PAYLOAD")
    try:
        normalized = {str(key): float(value) for key, value in weights.items()}
    except (TypeError, ValueError) as exc:
        raise NonRetryableHandlerError(
            "weights must be numeric", code="INVALID_SIMULATION_WEIGHTS"
        ) from exc
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
    simulations = [
        simulate_weights(normalized, normalized, window_days=int(window)) for window in windows
    ]
    guardrails = evaluate_guardrails(
        normalized,
        normalized,
        simulations,
        baseline_metrics=simulations[0],
        config=GuardrailConfig(require_reviewer=False),
    )
    score = sum(normalized.values()) / max(1, len(normalized))
    return HandlerResult(
        value={
            "windows": [int(window) for window in windows],
            "sample_size": sample_size,
            "projected_score": round(score, 6),
            "weights": normalized,
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
