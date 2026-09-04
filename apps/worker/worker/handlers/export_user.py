"""Create a privacy-safe export manifest from injected user data."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import (
    HandlerContext,
    HandlerResult,
    NonRetryableHandlerError,
    lookup_service,
    stable_digest,
)

JOB_TYPE = "export_user"


async def handle(payload: Mapping[str, Any], context: HandlerContext | None = None) -> HandlerResult:
    user_id = payload.get("user_id")
    if user_id in (None, ""):
        raise NonRetryableHandlerError("user_id is required", code="INVALID_EXPORT_PAYLOAD")
    records = payload.get("records")
    if records is None:
        records = await lookup_service(
            context,
            ("export_records_lookup", "load_export_records", "export_records"),
            identifier=user_id,
            payload=payload,
        )
    records = {} if records is None else records
    if not isinstance(records, Mapping):
        raise NonRetryableHandlerError("records must be an object", code="INVALID_EXPORT_RECORDS")
    normalized_records = {str(key): value for key, value in records.items()}
    manifest = {
        "user_id": str(user_id),
        "sections": sorted(normalized_records),
        "record_count": len(normalized_records),
    }
    # The lookup service is the privacy boundary: it returns only fields the
    # authenticated data subject may receive and removes token hashes,
    # provider credentials, and other operational secrets.  Preserve those
    # records in the artifact instead of reducing an export to a manifest.
    artifact = {
        "schema_version": "1",
        "user_id": str(user_id),
        "manifest": manifest,
        "records": normalized_records,
    }
    return HandlerResult(
        value={
            "user_id": str(user_id),
            "manifest": manifest,
            "artifact": artifact,
            "export_key": "exports/" + stable_digest(artifact),
            "status": "ready",
        },
        side_effect_key=(context.idempotency_key if context else None),
    )
