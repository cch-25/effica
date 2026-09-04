"""Database primitives shared by the API and worker.

The package deliberately has no application-specific configuration import.  This
keeps migration tooling and worker processes able to import the model metadata
without importing the FastAPI application.
"""

from .base import Base, metadata
from .blob import BlobError, BlobNotFoundError, BlobRepository, BlobTooLargeError
from .session import (
    create_engine,
    get_session,
    session_factory,
)
from .types import BlobPayloadType, TinyIntType
from .ulid import ULIDType, is_valid_ulid, new_ulid
from .utc import UTCDateTime, ensure_utc, utc_now

__all__ = [
    "Base",
    "BlobPayloadType",
    "TinyIntType",
    "metadata",
    "BlobError",
    "BlobNotFoundError",
    "BlobRepository",
    "BlobTooLargeError",
    "UTCDateTime",
    "ULIDType",
    "create_engine",
    "ensure_utc",
    "get_session",
    "is_valid_ulid",
    "new_ulid",
    "session_factory",
    "utc_now",
]
