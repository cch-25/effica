"""Byte-stable multi-component article score calculation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from apps.api.app.domains.scoring import calculate_article_score, canonical_score_json

from .base import (
    HandlerContext,
    HandlerResult,
    NonRetryableHandlerError,
    RetryableHandlerError,
    lookup_service,
)

JOB_TYPE = "calculate_score"


async def handle(
    payload: Mapping[str, Any], context: HandlerContext | None = None
) -> HandlerResult:
    components = payload.get("components")
    loaded_components = components is None
    component_identifier = payload.get("article_version_id") or payload.get("article_id")
    provenance: Mapping[str, Any] = {}
    if components is None:
        loaded = await lookup_service(
            context,
            ("score_components_lookup", "load_score_components", "article_score_components"),
            identifier=component_identifier,
            payload=payload,
        )
        if isinstance(loaded, Mapping) and isinstance(loaded.get("components"), Mapping):
            loaded_provenance = loaded.get("provenance")
            if isinstance(loaded_provenance, Mapping):
                provenance = loaded_provenance
            loaded = loaded["components"]
        components = loaded
    if not isinstance(components, Mapping):
        if loaded_components and component_identifier:
            raise RetryableHandlerError(
                "score components are not ready",
                code="SCORE_ANALYSIS_NOT_READY",
                details={"article_version_id": payload.get("article_version_id")},
            )
        raise NonRetryableHandlerError(
            "score components are required", code="INVALID_SCORE_PAYLOAD"
        )
    components = dict(components)
    if loaded_components and str(provenance.get("analysis_provider", "")).casefold() == "openai":
        assessment_ids = provenance.get("assessment_ids")
        actual_model_ids = provenance.get("actual_model_ids")
        if (
            not isinstance(assessment_ids, (list, tuple))
            or not any(str(value).strip() for value in assessment_ids)
            or not isinstance(actual_model_ids, (list, tuple))
            or not any(str(value).strip() for value in actual_model_ids)
        ):
            raise RetryableHandlerError(
                "trusted OpenAI assessment components are not ready",
                code="SCORE_ANALYSIS_NOT_READY",
                details={"article_version_id": payload.get("article_version_id")},
            )
        # The production policy uses one configured model as a complete
        # assessment. Legacy lookup snapshots divided evidence quality by
        # three and calculated spread across x/y/z, which degraded a valid
        # single-model result solely because compatibility axes are zero.
        if len(assessment_ids) == 1:
            components["model_spread"] = 0.0
            legacy_quality = components.get("evidence_quality")
            if (
                isinstance(legacy_quality, (int, float))
                and not isinstance(legacy_quality, bool)
                and math.isclose(
                    float(legacy_quality), 1.0 / 3.0, rel_tol=0.0, abs_tol=1e-6
                )
            ):
                components["evidence_quality"] = 1.0
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
    value["components"] = {**value["components"], **provenance}
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
