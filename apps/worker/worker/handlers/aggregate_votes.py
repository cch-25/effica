"""Aggregate revisioned axis votes with small-segment suppression."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from apps.api.app.domains.scoring import aggregate_votes

from .base import HandlerContext, HandlerResult, NonRetryableHandlerError, lookup_service

JOB_TYPE = "aggregate_votes"


def _max_vote_revision(votes: Iterable[Mapping[str, Any]]) -> int | None:
    values: list[int] = []
    for vote in votes:
        raw = vote.get("revision", vote.get("vote_revision", vote.get("version")))
        if raw is None or isinstance(raw, bool):
            continue
        try:
            number = int(raw)
        except (TypeError, ValueError):
            continue
        if number >= 1 and not (isinstance(raw, float) and raw != number):
            values.append(number)
    return max(values) if values else None


def _as_positive_revision(raw: Any) -> int:
    if isinstance(raw, bool):
        raise NonRetryableHandlerError(
            "vote revision must be a positive integer", code="INVALID_VOTE_PAYLOAD"
        )
    try:
        revision = int(raw)
    except (TypeError, ValueError) as exc:
        raise NonRetryableHandlerError(
            "vote revision must be a positive integer", code="INVALID_VOTE_PAYLOAD"
        ) from exc
    if revision < 1 or (isinstance(raw, float) and raw != revision):
        raise NonRetryableHandlerError(
            "vote revision must be a positive integer", code="INVALID_VOTE_PAYLOAD"
        )
    return revision


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
    if "vote_revision" in payload:
        revision = _as_positive_revision(payload.get("vote_revision"))
    elif "version" in payload:
        revision = _as_positive_revision(payload.get("version"))
    else:
        raw_revision = _max_vote_revision(votes)
        if raw_revision is None:
            snapshot = await lookup_service(
                context,
                (
                    "vote_snapshot_lookup",
                    "latest_vote_snapshot",
                    "vote_aggregates",
                    "vote_aggregate_lookup",
                ),
                identifier=payload.get("article_id"),
                payload=payload,
            )
            latest: Any = None
            if isinstance(snapshot, Mapping):
                latest = snapshot.get("version", snapshot.get("vote_revision"))
            elif isinstance(snapshot, (int, str)):
                latest = snapshot
            if latest is None:
                raise NonRetryableHandlerError(
                    "vote revision is required from the payload, votes, or latest snapshot",
                    code="INVALID_VOTE_PAYLOAD",
                )
            revision = _as_positive_revision(latest) + 1
        else:
            revision = raw_revision
    result["version"] = revision
    result["vote_revision"] = revision
    result["source_revision"] = revision
    return HandlerResult(
        value=result,
        side_effect_key=(context.idempotency_key if context else None),
    )


run = handle
