"""Conservative deterministic weight recommendation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from apps.api.app.domains.admin.autopilot import recommend_weights as domain_recommend_weights

from .base import HandlerContext, HandlerResult, NonRetryableHandlerError, lookup_service

JOB_TYPE = "recommend_weights"

# Evidence-snapshot metadata and lookup envelope keys must never become a
# weight vector.  ``window_days`` is numeric, so a naive float() coercion
# would otherwise treat it as a ranking weight.
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


def _merge_evidence(*candidates: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            merged.update(dict(candidate))
    return merged


async def handle(payload: Mapping[str, Any], context: HandlerContext | None = None) -> HandlerResult:
    recommendation: Mapping[str, Any] = {}
    if payload.get("recommendation_id"):
        loaded = await lookup_service(
            context,
            ("recommendation_lookup", "load_recommendation", "recommendations"),
            identifier=payload.get("recommendation_id"),
            payload=payload,
        )
        if isinstance(loaded, Mapping):
            recommendation = loaded

    evidence = _merge_evidence(
        recommendation.get("evidence_snapshot"),
        recommendation.get("evidence"),
        payload.get("evidence_snapshot"),
        payload.get("evidence"),
        payload.get("metrics"),
        payload.get("outcomes"),
    )

    base_revision_id = payload.get("base_revision_id") or recommendation.get("base_revision_id")
    base = _coerce_weight_vector(payload.get("base_weights"))
    if base is None:
        loaded_base = await lookup_service(
            context,
            ("weights_lookup", "load_weights", "weights"),
            identifier=base_revision_id or "active",
            payload=payload,
        )
        if isinstance(loaded_base, Mapping):
            base = _coerce_weight_vector(loaded_base)
    if base is None:
        # The recommendation row is seeded from the active/base revision at
        # enqueue time; use that copy when a live weights lookup is absent.
        base = _coerce_weight_vector(recommendation.get("proposed_weights"))
    if base is None:
        base = _coerce_weight_vector(payload.get("weights"))
    if base is None:
        raise NonRetryableHandlerError(
            "base weights from the active or base revision are required",
            code="INVALID_WEIGHT_PAYLOAD",
        )

    evidence_snapshot_id = payload.get("evidence_snapshot_id") or recommendation.get(
        "evidence_snapshot_id"
    )
    recommendation_id = payload.get("recommendation_id") or recommendation.get("recommendation_id")
    try:
        proposed = domain_recommend_weights(
            base,
            evidence_snapshot_id=str(evidence_snapshot_id or recommendation_id or "evidence"),
            base_revision_id=None if base_revision_id is None else str(base_revision_id),
            evidence=evidence,
            recommendation_id=None if recommendation_id is None else str(recommendation_id),
        )
    except (TypeError, ValueError) as exc:
        raise NonRetryableHandlerError(str(exc), code="INVALID_WEIGHT_PAYLOAD") from exc

    weights = dict(proposed.proposed_weights)
    return HandlerResult(
        value={
            "weights": weights,
            "proposed_weights": weights,
            "guardrail": {"max_delta": 0.1, "requires_review": True},
            "revision": str(payload.get("revision", "draft")),
            "recommendation_id": proposed.recommendation_id,
            "base_revision_id": proposed.base_revision_id or base_revision_id,
            "evidence_snapshot_id": proposed.evidence_snapshot_id,
            "evidence_snapshot": evidence,
            "status": proposed.status,
        },
        side_effect_key=(context.idempotency_key if context else None),
    )
