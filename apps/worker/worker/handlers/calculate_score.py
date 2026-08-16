"""Byte-stable multi-component article score calculation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.api.app.domains.scoring import calculate_article_score, canonical_score_json

from .base import HandlerContext, HandlerResult, NonRetryableHandlerError, lookup_service

JOB_TYPE = "calculate_score"


async def handle(
    payload: Mapping[str, Any], context: HandlerContext | None = None
) -> HandlerResult:
    components = payload.get("components")
    if components is None:
        identifier = payload.get("article_version_id") or payload.get("article_id")
        loaded = await lookup_service(
            context,
            ("score_components_lookup", "load_score_components", "article_score_components"),
            identifier=identifier,
            payload=payload,
        )
        if isinstance(loaded, Mapping) and isinstance(loaded.get("components"), Mapping):
            loaded = loaded["components"]
        components = loaded
    if not isinstance(components, Mapping):
        raise NonRetryableHandlerError(
            "score components are required", code="INVALID_SCORE_PAYLOAD"
        )
    weights = payload.get("weights")
    loaded_weights: Mapping[str, Any] | None = None
    if weights is None:
        loaded = await lookup_service(
            context,
            ("weights_lookup", "active_weight_lookup", "load_weights", "weight_revisions"),
            identifier=payload.get("weight_revision_id") or payload.get("weight_id") or "active",
            payload=payload,
        )
        if isinstance(loaded, Mapping):
            loaded_weights = loaded
            weights = loaded.get("weights", loaded.get("weights_json", loaded))
    if weights is not None and not isinstance(weights, Mapping):
        raise NonRetryableHandlerError(
            "weights must be an object", code="INVALID_SCORE_WEIGHTS"
        )
    try:
        score = calculate_article_score(components, weights, fact_check=payload.get("fact_check"))
    except (TypeError, ValueError) as exc:
        raise NonRetryableHandlerError(
            str(exc), code="INVALID_SCORE_PAYLOAD"
        ) from exc
    value = score.as_dict()
    value["canonical_sha256"] = __import__("hashlib").sha256(
        canonical_score_json(score)
    ).hexdigest()
    value["article_version_id"] = payload.get("article_version_id")
    value["weight_revision_id"] = (
        payload.get("weight_revision_id")
        or payload.get("weight_id")
        or (loaded_weights or {}).get("weight_revision_id")
        or (loaded_weights or {}).get("id")
    )
    return HandlerResult(
        value=value,
        side_effect_key=(context.idempotency_key if context else None),
    )


run = handle
