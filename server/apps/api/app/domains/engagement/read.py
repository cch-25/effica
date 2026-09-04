"""Signed outbound/read-return sessions and anti-abuse eligibility rules."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ReadSessionStatus(str, Enum):
    CREATED = "CREATED"
    OUTBOUND = "OUTBOUND"
    RETURNED = "RETURNED"
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ReadReason(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    MISSING_OUTBOUND = "MISSING_OUTBOUND"
    RETURN_BEFORE_OUTBOUND = "RETURN_BEFORE_OUTBOUND"
    TOO_FAST = "TOO_FAST"
    TOO_LONG = "TOO_LONG"
    EXPIRED = "EXPIRED"
    REPEATED = "REPEATED"
    OVERLAP = "OVERLAP"
    INVALID_TOKEN = "INVALID_TOKEN"


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    status: ReadSessionStatus
    reason_code: str
    elapsed_ms: int | None = None

    @property
    def server_elapsed_ms(self) -> int:
        """Route-contract alias for the server-derived elapsed duration."""

        return self.elapsed_ms or 0


@dataclass
class ReadSession:
    session_id: str
    user_id: str
    article_id: str
    token_hash: bytes
    expires_at: datetime
    policy_version: str = "read-v1"
    status: ReadSessionStatus = ReadSessionStatus.CREATED
    outbound_at: datetime | None = None
    returned_at: datetime | None = None
    client_elapsed_ms: int | None = None
    reason_code: str | None = None

    def mark_outbound(self, when: datetime | None = None) -> None:
        if self.status not in {ReadSessionStatus.CREATED, ReadSessionStatus.OUTBOUND}:
            raise ValueError("read session cannot be sent outbound from current state")
        self.outbound_at = _utc(when or datetime.now(UTC))
        self.status = ReadSessionStatus.OUTBOUND

    def mark_return(
        self,
        when: datetime | None = None,
        *,
        client_elapsed_ms: int | None = None,
        repeated: bool = False,
        overlapping: bool = False,
        min_elapsed_ms: int = 15_000,
        max_elapsed_ms: int = 86_400_000,
    ) -> EligibilityResult:
        returned = _utc(when or datetime.now(UTC))
        result = evaluate_read_eligibility(
            outbound_at=self.outbound_at,
            returned_at=returned,
            client_elapsed_ms=client_elapsed_ms,
            expires_at=self.expires_at,
            repeated=repeated,
            overlapping=overlapping,
            min_elapsed_ms=min_elapsed_ms,
            max_elapsed_ms=max_elapsed_ms,
        )
        self.returned_at = returned
        self.client_elapsed_ms = client_elapsed_ms
        self.status = result.status
        self.reason_code = result.reason_code
        return result


def create_redirect_token(
    *,
    session_id: str,
    user_id: str,
    article_id: str,
    secret: bytes | str,
    expires_at: datetime,
    nonce: str | None = None,
) -> str:
    """Create a compact HMAC-signed redirect token."""

    expiry = int(_utc(expires_at).timestamp())
    payload = {
        "sid": session_id,
        "uid": user_id,
        "aid": article_id,
        "exp": expiry,
        "n": nonce or secrets.token_urlsafe(12),
    }
    encoded = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = hmac.new(_secret(secret), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64(signature)}"


def verify_redirect_token(
    token: str, *, secret: bytes | str, now: datetime | None = None
) -> dict[str, Any]:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(_secret(secret), encoded.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(signature), expected):
            raise ValueError("invalid redirect token signature")
        payload = json.loads(_unb64(encoded))
        if int(payload["exp"]) < int(_utc(now or datetime.now(UTC)).timestamp()):
            raise ValueError("redirect token expired")
        if not all(
            isinstance(payload.get(key), str) and payload[key] for key in ("sid", "uid", "aid")
        ):
            raise ValueError("redirect token missing identity")
        return payload
    except (
        ValueError,
        KeyError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        binascii.Error,
    ) as exc:
        raise ValueError("invalid redirect token") from exc


def evaluate_read_eligibility(
    *,
    outbound_at: datetime | None,
    returned_at: datetime | None,
    client_elapsed_ms: int | None = None,
    expires_at: datetime | None = None,
    repeated: bool = False,
    overlapping: bool = False,
    min_elapsed_ms: int = 15_000,
    max_elapsed_ms: int = 86_400_000,
) -> EligibilityResult:
    """Evaluate server timestamps; browser elapsed is only supporting data."""

    if min_elapsed_ms < 0 or max_elapsed_ms < min_elapsed_ms:
        raise ValueError("invalid elapsed policy")
    if outbound_at is None:
        return EligibilityResult(
            False, ReadSessionStatus.REJECTED, ReadReason.MISSING_OUTBOUND.value
        )
    if returned_at is None:
        return EligibilityResult(
            False, ReadSessionStatus.REJECTED, ReadReason.RETURN_BEFORE_OUTBOUND.value
        )
    outbound, returned = _utc(outbound_at), _utc(returned_at)
    if returned < outbound:
        return EligibilityResult(
            False, ReadSessionStatus.REJECTED, ReadReason.RETURN_BEFORE_OUTBOUND.value
        )
    if expires_at is not None and returned > _utc(expires_at):
        return EligibilityResult(False, ReadSessionStatus.EXPIRED, ReadReason.EXPIRED.value)
    if repeated:
        return EligibilityResult(False, ReadSessionStatus.REJECTED, ReadReason.REPEATED.value)
    if overlapping:
        return EligibilityResult(False, ReadSessionStatus.REJECTED, ReadReason.OVERLAP.value)
    elapsed_ms = round((returned - outbound).total_seconds() * 1000)
    if elapsed_ms < min_elapsed_ms:
        return EligibilityResult(
            False, ReadSessionStatus.REJECTED, ReadReason.TOO_FAST.value, elapsed_ms
        )
    if elapsed_ms > max_elapsed_ms:
        return EligibilityResult(
            False, ReadSessionStatus.REJECTED, ReadReason.TOO_LONG.value, elapsed_ms
        )
    # ``client_elapsed_ms`` can be absent or inaccurate; it cannot make a
    # server-eligible session ineligible by itself.
    return EligibilityResult(
        True, ReadSessionStatus.ELIGIBLE, ReadReason.ELIGIBLE.value, elapsed_ms
    )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _secret(value: bytes | str) -> bytes:
    return value.encode() if isinstance(value, str) else value


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
