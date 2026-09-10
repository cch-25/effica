"""Handler for a single KST day's editorial issue discovery."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

from ..issue_discovery import IssueDiscoveryError
from ..llm_budget import DailyLLMBudgetExceeded, LLMRequestSuppressed
from .base import HandlerContext, HandlerResult, NonRetryableHandlerError, require_mapping

JOB_TYPE = "discover_issues"


async def discover_issues(
    payload: Mapping[str, Any], context: HandlerContext | None = None,
) -> HandlerResult:
    require_mapping(payload, "run_date")
    services = context.services if context else {}
    discovery = services.get("issue_discovery")
    sources = services.get("allowed_sources")
    if discovery is None or sources is None:
        raise NonRetryableHandlerError(
            "daily discovery services are not configured", code="DISCOVERY_NOT_CONFIGURED",
        )
    if callable(sources):
        sources = sources()
    if inspect.isawaitable(sources):
        sources = await sources
    try:
        value = await discovery.discover(
            run_date=str(payload["run_date"]), allowed_sources=sources,
            now=context.now if context else None,
        )
    except (IssueDiscoveryError, DailyLLMBudgetExceeded, LLMRequestSuppressed, ValueError) as exc:
        raise NonRetryableHandlerError(
            str(exc), code=getattr(exc, "code", "ISSUE_DISCOVERY_FAILED"),
        ) from exc
    return HandlerResult(value=value, metadata={"pipeline": "daily_topic_first"})


handle = discover_issues
