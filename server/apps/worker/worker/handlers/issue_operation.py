"""Idempotent merge/split issue job handlers.

The handler owns only the job boundary.  A production ``issue_operation``
service may apply the operation immediately (for example, to an in-memory
domain store); the MariaDB result applier remains the authoritative durable
write and repeats the operation safely when a lease is recovered.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

from .base import HandlerContext, HandlerResult, NonRetryableHandlerError


def _ids(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise NonRetryableHandlerError(
            f"{field} must be a non-empty list",
            code="INVALID_ISSUE_OPERATION_PAYLOAD",
            details={"field": field},
        )
    result = [str(item) for item in value]
    if any(not item for item in result) or len(set(result)) != len(result):
        raise NonRetryableHandlerError(
            f"{field} must contain unique non-empty identifiers",
            code="INVALID_ISSUE_OPERATION_PAYLOAD",
            details={"field": field},
        )
    return result


async def _apply_injected_operation(
    payload: Mapping[str, Any], context: HandlerContext | None, operation: str
) -> Any:
    if context is None:
        return None
    service = context.services.get("issue_operation") or context.services.get("issue_store")
    if service is None:
        return None
    if not callable(service):
        service = getattr(service, operation, None) or getattr(service, "apply", None)
    if service is None or not callable(service):
        return None
    values = dict(payload)
    values["operation"] = operation
    values["operation_key"] = context.idempotency_key
    attempts = ((values, context), (values,), (context, values))
    for args in attempts:
        try:
            result = service(*args)
        except TypeError:
            continue
        if inspect.isawaitable(result):
            result = await result
        return result
    try:
        result = service(**values)
    except TypeError:
        return None
    if inspect.isawaitable(result):
        result = await result
    return result


async def handle_merge(
    payload: Mapping[str, Any], context: HandlerContext | None = None
) -> HandlerResult:
    source = payload.get("source_issue_id")
    target = payload.get("target_issue_id")
    if source in (None, "") or target in (None, "") or str(source) == str(target):
        raise NonRetryableHandlerError(
            "merge requires distinct source_issue_id and target_issue_id",
            code="INVALID_ISSUE_OPERATION_PAYLOAD",
        )
    operation_result = await _apply_injected_operation(payload, context, "merge")
    value: dict[str, Any] = {
        "operation": "merge",
        "source_issue_id": str(source),
        "target_issue_id": str(target),
    }
    if operation_result is not None:
        value["applied"] = operation_result
    return HandlerResult(
        value=value,
        side_effect_key=(context.idempotency_key if context else None),
    )


async def handle_split(
    payload: Mapping[str, Any], context: HandlerContext | None = None
) -> HandlerResult:
    issue_id = payload.get("issue_id")
    if issue_id in (None, ""):
        raise NonRetryableHandlerError(
            "split requires issue_id",
            code="INVALID_ISSUE_OPERATION_PAYLOAD",
        )
    article_ids = _ids(payload.get("article_ids"), field="article_ids")
    new_issue_ids = payload.get("new_issue_ids")
    if new_issue_ids is not None:
        new_issue_ids = _ids(new_issue_ids, field="new_issue_ids")
        if len(new_issue_ids) not in {1, len(article_ids)}:
            raise NonRetryableHandlerError(
                "new_issue_ids must contain one id or one id per split article",
                code="INVALID_ISSUE_OPERATION_PAYLOAD",
            )
    operation_result = await _apply_injected_operation(payload, context, "split")
    value: dict[str, Any] = {
        "operation": "split",
        "issue_id": str(issue_id),
        "article_ids": article_ids,
    }
    if new_issue_ids is not None:
        value["new_issue_ids"] = new_issue_ids
    if operation_result is not None:
        value["applied"] = operation_result
    return HandlerResult(
        value=value,
        side_effect_key=(context.idempotency_key if context else None),
    )


JOB_TYPE_MERGE = "merge_issue"
JOB_TYPE_SPLIT = "split_issue"

__all__ = ["JOB_TYPE_MERGE", "JOB_TYPE_SPLIT", "handle_merge", "handle_split"]
