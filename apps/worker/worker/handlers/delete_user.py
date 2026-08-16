"""Return an auditable deletion plan for the user domain service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import HandlerContext, HandlerResult, NonRetryableHandlerError, lookup_service

JOB_TYPE = "delete_user"


async def handle(payload: Mapping[str, Any], context: HandlerContext | None = None) -> HandlerResult:
    user_id = payload.get("user_id")
    if user_id in (None, ""):
        raise NonRetryableHandlerError("user_id is required", code="INVALID_DELETE_PAYLOAD")
    confirmed = payload.get("confirmed") is True or payload.get("confirmation") == "DELETE MY ACCOUNT"
    if not confirmed:
        raise NonRetryableHandlerError("account deletion requires explicit confirmation", code="DELETE_CONFIRMATION_REQUIRED")
    policy = await lookup_service(
        context,
        ("deletion_policy_lookup", "load_deletion_policy", "deletion_policy"),
        identifier=user_id,
        payload=payload,
    )
    if not isinstance(policy, Mapping):
        policy = {}
    return HandlerResult(
        value={
            "user_id": str(user_id),
            "status": "scheduled",
            "revoke": list(policy.get("revoke", ["sessions", "share_tokens"])),
            "purge_or_anonymize": list(
                policy.get(
                    "purge_or_anonymize",
                    [
                        "oauth_accounts",
                        "demographics",
                        "questionnaire_responses",
                        "profiles",
                        "votes",
                        "read_history",
                        "feed_impressions",
                        "efficacy_responses",
                        "share_artifacts",
                    ],
                )
            ),
            "preserve_aggregates": bool(policy.get("preserve_aggregates", payload.get("preserve_aggregates", True))),
        },
        side_effect_key=(context.idempotency_key if context else None),
    )


run = handle
