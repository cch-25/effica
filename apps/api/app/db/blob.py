"""Safe, deduplicating BLOB persistence for rendered share artifacts."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import StoredBlob
from .utc import ensure_utc, utc_now

MAX_BLOB_SIZE = 10 * 1024 * 1024
_MIME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$")


class BlobError(ValueError):
    """Base class for application-level BLOB validation failures."""


class BlobTooLargeError(BlobError):
    """Raised when a payload exceeds the 10 MiB application limit."""


class BlobNotFoundError(LookupError):
    """Raised when a requested BLOB ID does not exist."""


class BlobRepository:
    """Persist and retrieve immutable, SHA-256-addressed BLOBs.

    Methods flush rows but do not commit the caller's transaction.  This keeps
    a share-card creation and its BLOB atomic, while the nested insert retry
    handles two workers racing to store the same digest.
    """

    max_size = MAX_BLOB_SIZE

    @staticmethod
    def _coerce_payload(payload: bytes | bytearray | memoryview) -> bytes:
        if isinstance(payload, bytes):
            data = payload
        elif isinstance(payload, (bytearray, memoryview)):
            data = bytes(payload)
        else:
            raise BlobError("payload must be bytes-like")
        if len(data) > MAX_BLOB_SIZE:
            raise BlobTooLargeError(
                f"BLOB payload is {len(data)} bytes; maximum is {MAX_BLOB_SIZE}"
            )
        return data

    @staticmethod
    def _validate_mime_type(mime_type: str) -> str:
        if not isinstance(mime_type, str):
            raise BlobError("mime_type must be a string")
        value = mime_type.strip().lower()
        if len(value) > 255 or not _MIME_RE.fullmatch(value):
            raise BlobError("mime_type must be a valid media type")
        return value

    async def put(
        self,
        session: AsyncSession,
        payload: bytes | bytearray | memoryview,
        *,
        mime_type: str,
        expires_at: datetime | None = None,
    ) -> StoredBlob:
        """Insert or return the immutable row for a payload's SHA-256 digest."""

        data = self._coerce_payload(payload)
        media_type = self._validate_mime_type(mime_type)
        digest = hashlib.sha256(data).digest()
        existing = await session.scalar(select(StoredBlob).where(StoredBlob.sha256 == digest))
        if existing is not None:
            # A digest collision is cryptographically impractical, but do not
            # silently return corrupt data if a malformed legacy row exists.
            if existing.byte_size != len(data) or existing.payload != data:
                raise BlobError("stored SHA-256 digest does not match payload")
            return existing

        row = StoredBlob(
            sha256=digest,
            mime_type=media_type,
            byte_size=len(data),
            payload=data,
            expires_at=ensure_utc(expires_at) if expires_at is not None else None,
        )
        try:
            # SAVEPOINT allows a uniqueness race to be recovered without
            # invalidating unrelated work in the caller's transaction.
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError as exc:
            existing = await session.scalar(select(StoredBlob).where(StoredBlob.sha256 == digest))
            if existing is None:
                raise
            if existing.byte_size != len(data) or existing.payload != data:
                raise BlobError("stored SHA-256 digest does not match payload") from exc
            return existing
        return row

    async def get(self, session: AsyncSession, blob_id: str) -> StoredBlob:
        """Return a BLOB row by ULID, rejecting expired artifacts."""

        row = await session.get(StoredBlob, blob_id)
        if row is None:
            raise BlobNotFoundError(blob_id)
        if row.expires_at is not None and row.expires_at <= utc_now():
            raise BlobNotFoundError(blob_id)
        return row

    async def delete_expired(self, session: AsyncSession, *, now: datetime | None = None) -> int:
        """Delete expired BLOBs and return the number of rows removed."""

        cutoff = ensure_utc(now) if now is not None else utc_now()
        result = await session.execute(
            delete(StoredBlob).where(
                StoredBlob.expires_at.is_not(None),
                StoredBlob.expires_at <= cutoff,
            )
        )
        return int(result.rowcount or 0)


__all__ = [
    "BlobError",
    "BlobNotFoundError",
    "BlobRepository",
    "BlobTooLargeError",
    "MAX_BLOB_SIZE",
]
