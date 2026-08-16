"""Conservative deterministic weight recommendation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import HandlerContext, HandlerResult, NonRetryableHandlerError, lookup_service

JOB_TYPE = "recommend_weights"


async def handle(payload: Mapping[str, Any], context: HandlerContext | None = None) -> HandlerResult:
    metrics = payload.get("metrics", payload.get("outcomes", {}))
    recommendation: Mapping[str, Any] = {}
    if (not isinstance(metrics, Mapping) or not metrics) and payload.get("recommendation_id"):
        loaded = await lookup_service(
            context,
            ("recommendation_lookup", "load_recommendation", "recommendations"),
            identifier=payload.get("recommendation_id"),
            payload=payload,
        )
        if isinstance(loaded, Mapping):
            recommendation = loaded
            metrics = loaded.get("metrics", loaded.get("outcomes", loaded.get("evidence_snapshot", {})))
    if not isinstance(metrics, Mapping) or not metrics:
        raise NonRetryableHandlerError("recommendation metrics are required", code="INVALID_WEIGHT_PAYLOAD")
    raw = {}
    for name, value in metrics.items():
        try:
            raw[str(name)] = max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    if not raw or sum(raw.values()) == 0:
        raw = {"relevance": 1.0}
    total = sum(raw.values())
    weights = {name: round(value / total, 6) for name, value in sorted(raw.items())}
    value = {
        "weights": weights,
        "guardrail": {"max_delta": 0.1, "requires_review": True},
        "revision": str(payload.get("revision", "draft")),
        "recommendation_id": payload.get("recommendation_id"),
        "base_revision_id": payload.get("base_revision_id") or recommendation.get("base_revision_id"),
        "evidence_snapshot_id": payload.get("evidence_snapshot_id") or recommendation.get("evidence_snapshot_id"),
        "evidence_snapshot": payload.get("evidence_snapshot") or recommendation.get("evidence_snapshot"),
    }
    return HandlerResult(
        value=value,
        side_effect_key=(context.idempotency_key if context else None),
    )


run = handle
