"""Aggregate revisioned axis votes with small-segment suppression."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.api.app.domains.scoring import aggregate_votes

from .base import HandlerContext, HandlerResult, NonRetryableHandlerError, lookup_service

JOB_TYPE = "aggregate_votes"


async def handle(
    payload: Mapping[str, Any], context: HandlerContext | None = None
) -> HandlerResult:
    votes = payload.get("votes")
    if votes is None and payload.get("article_id"):
        votes = await lookup_service(
            context,
            ("votes_lookup", "load_votes", "article_votes", "votes"),
            identifier=payload.get("article_id"),
            payload=payload,
        )
    votes = [] if votes is None else votes
    if not isinstance(votes, (list, tuple)):
        raise NonRetryableHandlerError("votes must be a list", code="INVALID_VOTE_PAYLOAD")
    if votes and not all(isinstance(vote, Mapping) for vote in votes):
        raise NonRetryableHandlerError(
            "axis votes must be objects", code="INVALID_VOTE_PAYLOAD"
        )
    try:
        result = aggregate_votes(
            votes,
            segment_by_user=payload.get("segment_by_user"),
            min_segment_size=int(payload.get("min_segment_size", 5)),
        )
    except (TypeError, ValueError) as exc:
        raise NonRetryableHandlerError(str(exc), code="INVALID_VOTE_PAYLOAD") from exc
    result["article_id"] = payload.get("article_id")
    # Producers historically called this field ``version`` while the vote
    # repository calls it ``vote_revision``.  Preserve both names at the
    # worker boundary so the durable applier can reject stale revisions and
    # allocate a monotonic snapshot version instead of silently defaulting to
    # one for every job.
    raw_revision = payload.get("vote_revision", payload.get("version", 1))
    if isinstance(raw_revision, bool):
        raise NonRetryableHandlerError(
            "vote revision must be a positive integer", code="INVALID_VOTE_PAYLOAD"
        )
    try:
        revision = int(raw_revision)
    except (TypeError, ValueError) as exc:
        raise NonRetryableHandlerError(
            "vote revision must be a positive integer", code="INVALID_VOTE_PAYLOAD"
        ) from exc
    if revision < 1 or (isinstance(raw_revision, float) and raw_revision != revision):
        raise NonRetryableHandlerError(
            "vote revision must be a positive integer", code="INVALID_VOTE_PAYLOAD"
        )
    result["version"] = revision
    result["vote_revision"] = revision
    result["source_revision"] = revision
    return HandlerResult(
        value=result,
        side_effect_key=(context.idempotency_key if context else None),
    )


run = handle
