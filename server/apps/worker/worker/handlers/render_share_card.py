"""Render a deterministic, privacy-bounded user-coordinate share card PNG."""

from __future__ import annotations

import base64
import hashlib
import inspect
from collections.abc import Mapping
from typing import Any

from .base import (
    HandlerContext,
    HandlerResult,
    NonRetryableHandlerError,
    lookup_service,
    require_mapping,
)
from .consumption_card_image import ImageDraw as ImageDraw

JOB_TYPE = "render_share_card"


FORBIDDEN_KEYS = {
    "email",
    "oauth_subject",
    "provider_subject",
    "questionnaire",
    "answers",
    "votes",
    "access_token",
    "session_token",
}


def _assert_public(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if normalized in FORBIDDEN_KEYS or any(part in normalized for part in ("secret", "password")):
                raise NonRetryableHandlerError(
                    "share card contains a forbidden sensitive field",
                    code="SENSITIVE_SHARE_CARD_PAYLOAD",
                    details={"field": f"{path}.{key}"},
                )
            _assert_public(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_public(nested, f"{path}[{index}]")


def _render_png(public: Mapping[str, Any]) -> bytes:
    from .consumption_card_image import render_consumption_card

    return render_consumption_card(public)


async def handle(payload: Mapping[str, Any], context: HandlerContext | None = None) -> HandlerResult:
    require_mapping(payload, "share_card_id")
    source = dict(payload)
    if source.get("snapshot") is None:
        loaded = await lookup_service(
            context,
            ("share_card_lookup", "load_share_card", "share_cards"),
            identifier=source.get("share_card_id"),
            payload=source,
        )
        if isinstance(loaded, Mapping):
            source = {**dict(loaded), **source}
    if not isinstance(source.get("snapshot"), Mapping):
        raise NonRetryableHandlerError(
            "share card snapshot is required directly or through share_card lookup",
            code="INVALID_SHARE_CARD_PAYLOAD",
        )
    _assert_public(source)
    public = {
        "share_card_id": str(source["share_card_id"]),
        "template": str(source.get("template", "default"))[:40],
        "display_name": str(source.get("display_name") or "")[:80] or None,
        "snapshot": dict(source["snapshot"]),
    }
    png = _render_png(public)
    digest = hashlib.sha256(png).hexdigest()
    blob_id = None
    if context and (store := context.services.get("store_blob")):
        stored = store(
            payload=png,
            mime_type="image/png",
            expires_at=source.get("expires_at"),
        )
        if inspect.isawaitable(stored):
            stored = await stored
        blob_id = getattr(stored, "id", None) or (
            stored.get("id") if isinstance(stored, Mapping) else None
        )
    return HandlerResult(
        value={
            "blob_id": blob_id,
            "sha256": digest,
            "mime_type": "image/png",
            "byte_size": len(png),
            "png_base64": None if blob_id else base64.b64encode(png).decode("ascii"),
            "public_payload": public,
        },
        side_effect_key=(context.idempotency_key if context else None),
    )
