"""Create a privacy-safe export manifest from injected user data."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import (
    HandlerContext,
    HandlerResult,
    NonRetryableHandlerError,
    RetryableHandlerError,
    lookup_service,
    stable_digest,
)

JOB_TYPE = "export_user"

_LOOKUP_NAMES = ("export_records_lookup", "load_export_records", "export_records")
_PRIVATE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "client_secret",
        "csrf_hash",
        "csrf_token",
        "encryption_key",
        "encryption_secret",
        "id_token",
        "password",
        "password_hash",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
        "token_hash",
    }
)


def _export_value(value: Any) -> Any:
    """Copy export data while removing operational authentication material."""

    if isinstance(value, Mapping):
        exported: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key)
            private_key = normalized_key.strip().lower().replace("-", "_")
            if private_key in _PRIVATE_KEYS:
                continue
            exported[normalized_key] = _export_value(item)
        return exported
    if isinstance(value, (list, tuple)):
        return [_export_value(item) for item in value]
    return value


async def handle(payload: Mapping[str, Any], context: HandlerContext | None = None) -> HandlerResult:
    user_id = payload.get("user_id")
    if user_id in (None, ""):
        raise NonRetryableHandlerError("user_id is required", code="INVALID_EXPORT_PAYLOAD")
    records = payload.get("records")
    loaded_from_lookup = records is None
    if records is None:
        if context is None or not any(name in context.services for name in _LOOKUP_NAMES):
            raise RetryableHandlerError(
                "export data lookup is unavailable",
                code="EXPORT_DATA_UNAVAILABLE",
            )
        records = await lookup_service(
            context,
            _LOOKUP_NAMES,
            identifier=user_id,
            payload=payload,
        )
    if records is None:
        raise RetryableHandlerError(
            "export data lookup returned no result",
            code="EXPORT_DATA_UNAVAILABLE",
        )
    if not isinstance(records, Mapping):
        raise NonRetryableHandlerError("records must be an object", code="INVALID_EXPORT_RECORDS")
    exported_user = records.get("user")
    if loaded_from_lookup and exported_user is None:
        raise NonRetryableHandlerError(
            "export user was not found",
            code="EXPORT_USER_NOT_FOUND",
        )
    if exported_user is not None and (
        not isinstance(exported_user, Mapping)
        or str(exported_user.get("id") or "") != str(user_id)
    ):
        raise NonRetryableHandlerError(
            "export data does not belong to the requested user",
            code="EXPORT_OWNER_MISMATCH",
        )
    normalized_records = _export_value(records)
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
