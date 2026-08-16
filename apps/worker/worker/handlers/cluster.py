"""Deterministic content-aware issue-clustering candidate handler."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.api.app.domains.issues import cluster_issue_candidates

from .base import HandlerContext, HandlerResult, NonRetryableHandlerError, lookup_service

JOB_TYPE = "cluster"


async def handle(
    payload: Mapping[str, Any], context: HandlerContext | None = None
) -> HandlerResult:
    articles = payload.get("articles")
    if articles is None:
        ids = payload.get("article_ids", [])
        loaded = await lookup_service(
            context,
            ("articles_lookup", "article_lookup", "load_articles", "articles"),
            identifier=ids,
            payload=payload,
        )
        if isinstance(loaded, Mapping):
            loaded = list(loaded.values())
        articles = loaded or [
            {"article_id": str(article_id), "title": str(payload.get("topic", "Untitled issue"))}
            for article_id in ids
        ]
    if not isinstance(articles, (list, tuple)) or not articles:
        raise NonRetryableHandlerError(
            "cluster payload requires a non-empty article list",
            code="INVALID_CLUSTER_PAYLOAD",
        )
    try:
        candidates = cluster_issue_candidates(
            articles, threshold=float(payload.get("threshold", 0.3))
        )
    except (TypeError, ValueError) as exc:
        raise NonRetryableHandlerError(str(exc), code="INVALID_CLUSTER_PAYLOAD") from exc
    return HandlerResult(
        value={"candidates": candidates, "candidate": True},
        side_effect_key=(context.idempotency_key if context else None),
    )


run = handle
