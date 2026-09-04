"""Public share token and BLOB metadata helpers without rendering/UI code."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

MAX_BLOB_BYTES = 10 * 1024 * 1024


class BlobLimitError(ValueError):
    pass


class ShareCardStatus(str, Enum):
    QUEUED = "queued"
    RENDERING = "rendering"
    READY = "ready"
    FAILED = "failed"
    REVOKED = "revoked"


@dataclass(frozen=True)
class ShareSnapshot:
    x: float
    y: float
    z: float
    confidence: float
    tier: str
    activity: int
    score_version: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if any(not -100 <= float(value) <= 100 for value in (self.x, self.y, self.z)):
            raise ValueError("share coordinates must be in [-100,100]")
        if not 0 <= self.confidence <= 1 or self.activity < 0:
            raise ValueError("invalid share confidence or activity")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StoredBlob:
    blob_id: str
    sha256: bytes
    mime_type: str
    byte_size: int
    payload: bytes
    expires_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ShareCard:
    card_id: str
    user_id: str
    public_token_hash: bytes
    template: str
    display_name: str | None
    snapshot: ShareSnapshot
    status: ShareCardStatus = ShareCardStatus.QUEUED
    blob_id: str | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def snapshot_as_bytes(self) -> bytes:
        import json

        return json.dumps(
            self.snapshot.as_dict(), sort_keys=True, separators=(",", ":"), default=str
        ).encode()


def create_public_token(*, entropy_bytes: int = 32) -> str:
    if entropy_bytes < 16:
        raise ValueError("public token needs at least 128 bits of entropy")
    return secrets.token_urlsafe(entropy_bytes)


def hash_public_token(token: str, *, pepper: bytes | str | None = None) -> bytes:
    if not token:
        raise ValueError("token is required")
    value = token.encode("utf-8")
    if pepper is not None:
        secret = pepper.encode() if isinstance(pepper, str) else pepper
        return hmac.new(secret, value, hashlib.sha256).digest()
    return hashlib.sha256(value).digest()


def make_share_snapshot(
    *,
    coordinates: tuple[float, float, float] | Mapping[str, Any],
    confidence: float,
    tier: str,
    activity: int,
    score_version: str | None = None,
) -> ShareSnapshot:
    """Create the minimal public snapshot; reject sensitive fields by design."""

    if isinstance(coordinates, Mapping):
        values = tuple(float(coordinates.get(axis, 0)) for axis in ("x", "y", "z"))
    else:
        if len(coordinates) != 3:
            raise ValueError("coordinates need x, y and z")
        values = tuple(float(value) for value in coordinates)
    if (
        any(not -100 <= value <= 100 for value in values)
        or not 0 <= confidence <= 1
        or activity < 0
    ):
        raise ValueError("invalid public share snapshot")
    return ShareSnapshot(
        x=values[0],
        y=values[1],
        z=values[2],
        confidence=round(float(confidence), 6),
        tier=str(tier),
        activity=int(activity),
        score_version=score_version,
    )


class BlobStore:
    """In-memory content-addressed BLOB store with size and expiry limits."""

    def __init__(self, *, max_bytes: int = MAX_BLOB_BYTES) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self._blobs: dict[str, StoredBlob] = {}
        self._by_hash: dict[bytes, str] = {}

    def put(
        self,
        *,
        blob_id: str,
        payload: bytes,
        mime_type: str = "image/png",
        expires_at: datetime | None = None,
    ) -> StoredBlob:
        if not isinstance(payload, bytes):
            payload = bytes(payload)
        if len(payload) > self.max_bytes:
            raise BlobLimitError(f"stored blob exceeds {self.max_bytes} bytes")
        digest = hashlib.sha256(payload).digest()
        existing_by_id = self._blobs.get(blob_id)
        if existing_by_id is not None:
            if existing_by_id.sha256 != digest:
                raise ValueError("blob id reused with different payload")
            return existing_by_id
        existing_id = self._by_hash.get(digest)
        if existing_id is not None:
            return self._blobs[existing_id]
        blob = StoredBlob(blob_id, digest, mime_type, len(payload), payload, expires_at)
        self._blobs[blob_id] = blob
        self._by_hash[digest] = blob_id
        return blob

    def get(self, blob_id: str, *, now: datetime | None = None) -> StoredBlob | None:
        blob = self._blobs.get(blob_id)
        if blob is None:
            return None
        stamp = _utc(now or datetime.now(UTC))
        if blob.expires_at is not None and stamp > _utc(blob.expires_at):
            return None
        return blob

    def etag(self, blob_id: str) -> str:
        blob = self._blobs[blob_id]
        return '"' + blob.sha256.hex() + '"'

    def purge_expired(self, *, now: datetime | None = None) -> list[str]:
        stamp = _utc(now or datetime.now(UTC))
        expired = [
            blob_id
            for blob_id, blob in self._blobs.items()
            if blob.expires_at is not None and stamp > _utc(blob.expires_at)
        ]
        for blob_id in expired:
            blob = self._blobs.pop(blob_id)
            self._by_hash.pop(blob.sha256, None)
        return sorted(expired)


class ShareCardStore:
    """Share-card metadata lookup by hashed public token."""

    def __init__(self) -> None:
        self.cards: dict[str, ShareCard] = {}
        self._by_token: dict[bytes, str] = {}

    def add(self, card: ShareCard) -> ShareCard:
        if card.card_id in self.cards:
            return self.cards[card.card_id]
        if card.public_token_hash in self._by_token:
            raise ValueError("public token hash already exists")
        self.cards[card.card_id] = card
        self._by_token[card.public_token_hash] = card.card_id
        return card

    def public_get(
        self,
        token: str,
        *,
        now: datetime | None = None,
        if_none_match: str | None = None,
        pepper: bytes | str | None = None,
    ) -> tuple[int, ShareCard | None, str | None]:
        card_id = self._by_token.get(hash_public_token(token, pepper=pepper))
        if card_id is None:
            return 404, None, None
        card = self.cards[card_id]
        stamp = _utc(now or datetime.now(UTC))
        if card.status == ShareCardStatus.REVOKED or (
            card.expires_at is not None and stamp > _utc(card.expires_at)
        ):
            return 404, None, None
        etag = hashlib.sha256(card.snapshot_as_bytes()).hexdigest()
        if if_none_match and if_none_match.strip('"') == etag:
            return 304, None, etag
        return 200, card, etag

    def revoke(self, card_id: str, *, when: datetime | None = None) -> ShareCard:
        card = self.cards[card_id]
        card.status = ShareCardStatus.REVOKED
        card.revoked_at = _utc(when or datetime.now(UTC))
        return card


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
