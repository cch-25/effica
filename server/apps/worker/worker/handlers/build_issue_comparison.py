"""Validate a structured issue-level comparison before durable publication review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .base import HandlerContext, HandlerResult, NonRetryableHandlerError, lookup_service

JOB_TYPE = "build_issue_comparison"


def _objects(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise NonRetryableHandlerError(
            f"{field} must be a list", code="INVALID_COMPARISON_OUTPUT"
        )
    rows = [dict(item) for item in value if isinstance(item, Mapping)]
    if len(rows) != len(value):
        raise NonRetryableHandlerError(
            f"{field} items must be objects", code="INVALID_COMPARISON_OUTPUT"
        )
    return rows


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise NonRetryableHandlerError(
            f"{field} must be a list", code="INVALID_COMPARISON_OUTPUT"
        )
    rows = [str(item).strip() for item in value]
    if any(not item for item in rows):
        raise NonRetryableHandlerError(
            f"{field} items must be non-empty strings",
            code="INVALID_COMPARISON_OUTPUT",
        )
    return rows


async def handle(
    payload: Mapping[str, Any], context: HandlerContext | None = None
) -> HandlerResult:
    source = dict(payload)
    generated = source.get("comparison")
    if not isinstance(generated, Mapping):
        generated = await lookup_service(
            context,
            (
                "issue_comparison_analysis",
                "build_issue_comparison",
                "issue_comparison_lookup",
            ),
            identifier=source.get("issue_id"),
            payload=source,
        )
    if not isinstance(generated, Mapping):
        raise NonRetryableHandlerError(
            "structured comparison analysis is required",
            code="COMPARISON_ANALYSIS_REQUIRED",
        )
    if str(generated.get("status") or "").strip().upper() == "SKIPPED":
        skip_reason = str(generated.get("skip_reason") or "").strip()
        if not skip_reason:
            raise NonRetryableHandlerError(
                "skipped comparison requires a reason",
                code="INVALID_COMPARISON_OUTPUT",
            )
        return HandlerResult(
            value={
                "issue_id": str(source["issue_id"]),
                "issue_version": int(source["issue_version"]),
                "prompt_version": str(source["prompt_version"]),
                "status": "SKIPPED",
                "skip_reason": skip_reason,
                "expected_article_versions": int(
                    generated.get("expected_article_versions") or 0
                ),
                "current_article_versions": int(
                    generated.get("current_article_versions") or 0
                ),
            },
            side_effect_key=(context.idempotency_key if context else None),
        )
    common_facts = _objects(generated.get("common_facts"), "common_facts")
    dimensions = _objects(generated.get("dimensions"), "dimensions")
    frames = generated.get("article_frames")
    if not isinstance(frames, Mapping):
        raise NonRetryableHandlerError(
            "article_frames must be an object", code="INVALID_COMPARISON_OUTPUT"
        )
    requested_article_ids = source.get("article_ids")
    if requested_article_ids is None:
        requested_article_ids = list(frames)
    article_id_list = _string_list(requested_article_ids, "article_ids")
    if not 2 <= len(article_id_list) <= 4 or len(set(article_id_list)) != len(
        article_id_list
    ):
        raise NonRetryableHandlerError(
            "article_ids must contain two to four unique items",
            code="INVALID_COMPARISON_OUTPUT",
        )
    article_ids = set(article_id_list)
    if set(map(str, frames)) != article_ids:
        raise NonRetryableHandlerError(
            "article_frames must match the requested articles",
            code="INVALID_COMPARISON_OUTPUT",
        )
    requested_version_ids = _string_list(
        source.get("article_version_ids"), "article_version_ids"
    )
    if len(requested_version_ids) != len(article_id_list):
        raise NonRetryableHandlerError(
            "article and article-version identities must align",
            code="INVALID_COMPARISON_OUTPUT",
        )
    generated_versions = generated.get("article_version_ids")
    if isinstance(generated_versions, Mapping):
        article_version_ids = {
            str(key): str(value) for key, value in generated_versions.items()
        }
    else:
        article_version_ids = dict(zip(article_id_list, requested_version_ids, strict=True))
    if set(article_version_ids) != article_ids or set(article_version_ids.values()) != set(
        requested_version_ids
    ):
        raise NonRetryableHandlerError(
            "article version map must match the requested inputs",
            code="INVALID_COMPARISON_OUTPUT",
        )
    for fact in common_facts:
        if not str(fact.get("id") or "").strip() or not str(fact.get("text") or "").strip():
            raise NonRetryableHandlerError(
                "common facts require an id and text",
                code="INVALID_COMPARISON_OUTPUT",
            )
        supporting = set(_string_list(fact.get("article_ids"), "common_facts.article_ids"))
        _string_list(fact.get("evidence_refs", []), "common_facts.evidence_refs")
        if len(supporting) < 2 or not supporting.issubset(article_ids):
            raise NonRetryableHandlerError(
                "every common fact needs at least two supporting articles",
                code="INVALID_COMPARISON_OUTPUT",
            )
    for dimension in dimensions:
        if not str(dimension.get("key") or "").strip() or not str(
            dimension.get("label") or ""
        ).strip():
            raise NonRetryableHandlerError(
                "dimensions require a key and label",
                code="INVALID_COMPARISON_OUTPUT",
            )
    normalized_frames: dict[str, dict[str, Any]] = {}
    for article_id, frame in frames.items():
        if not isinstance(frame, Mapping) or not str(frame.get("headline_frame") or "").strip():
            raise NonRetryableHandlerError(
                "every article frame requires a headline frame",
                code="INVALID_COMPARISON_OUTPUT",
            )
        normalized = dict(frame)
        normalized["emphasis"] = _string_list(
            normalized.get("emphasis", []), "article_frames.emphasis"
        )
        normalized["evidence_refs"] = _string_list(
            normalized.get("evidence_refs", []), "article_frames.evidence_refs"
        )
        omissions = normalized.get("omissions_note")
        if omissions is not None and not isinstance(omissions, str):
            raise NonRetryableHandlerError(
                "omissions_note must be a string or null",
                code="INVALID_COMPARISON_OUTPUT",
            )
        normalized_frames[str(article_id)] = normalized
    try:
        confidence = float(generated.get("confidence", 0))
    except (TypeError, ValueError) as exc:
        raise NonRetryableHandlerError(
            "confidence must be between zero and one",
            code="INVALID_COMPARISON_OUTPUT",
        ) from exc
    if not 0 <= confidence <= 1:
        raise NonRetryableHandlerError(
            "confidence must be between zero and one",
            code="INVALID_COMPARISON_OUTPUT",
        )
    model_alias_id = generated.get("model_alias_id") or source.get("model_alias_id")
    if not model_alias_id:
        raise NonRetryableHandlerError(
            "model_alias_id is required", code="INVALID_COMPARISON_OUTPUT"
        )
    return HandlerResult(
        value={
            "issue_id": str(source["issue_id"]),
            "issue_version": int(source["issue_version"]),
            "prompt_version": str(source["prompt_version"]),
            "model_alias_id": str(model_alias_id),
            "common_facts": common_facts,
            "dimensions": dimensions,
            "article_frames": normalized_frames,
            "article_version_ids": article_version_ids,
            "confidence": confidence,
            "status": "SUCCEEDED",
        },
        side_effect_key=(context.idempotency_key if context else None),
    )
