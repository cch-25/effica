"""Render a deterministic, privacy-bounded user-coordinate share card PNG."""

from __future__ import annotations

import base64
import hashlib
import inspect
import io
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .base import (
    HandlerContext,
    HandlerResult,
    NonRetryableHandlerError,
    lookup_service,
    require_mapping,
)

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
    snapshot = public["snapshot"]
    coordinate = snapshot.get("coordinate", snapshot)
    x = max(-100.0, min(100.0, float(coordinate.get("x", 0))))
    y = max(-100.0, min(100.0, float(coordinate.get("y", 0))))
    z = max(-100.0, min(100.0, float(coordinate.get("z", 0))))
    image = Image.new("RGB", (1200, 630), "#F4F0E8")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=32)
    small = ImageFont.load_default(size=22)
    draw.rounded_rectangle((45, 45, 1155, 585), radius=32, fill="#FFFDF8", outline="#1F3D35", width=4)
    draw.text((90, 90), "Perspective snapshot", fill="#17352E", font=font)
    display_name = str(public.get("display_name") or "Anonymous member")[:80]
    draw.text((90, 145), display_name, fill="#48655D", font=small)
    left, top, size = 90, 220, 320
    draw.rectangle((left, top, left + size, top + size), outline="#78928B", width=3)
    draw.line((left + size / 2, top, left + size / 2, top + size), fill="#B7C5C0", width=2)
    draw.line((left, top + size / 2, left + size, top + size / 2), fill="#B7C5C0", width=2)
    px = left + (x + 100) / 200 * size
    py = top + (100 - y) / 200 * size
    draw.ellipse((px - 12, py - 12, px + 12, py + 12), fill="#D8664A", outline="#7A2D1B", width=3)
    draw.text((480, 240), f"Economic X  {x:+.0f}", fill="#17352E", font=small)
    draw.text((480, 295), f"Social Y       {y:+.0f}", fill="#17352E", font=small)
    draw.text((480, 350), f"National Z    {z:+.0f}", fill="#17352E", font=small)
    draw.text((480, 425), f"Tier  {snapshot.get('tier', 'Explorer')}", fill="#48655D", font=small)
    credit_total = snapshot.get("credit_total", snapshot.get("activity", 0))
    draw.text((480, 470), f"Activity credits  {int(credit_total)}", fill="#48655D", font=small)
    draw.text((90, 555), "Response-based coordinates are observations, not identity or truth labels.", fill="#60736D", font=small)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


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


run = handle
