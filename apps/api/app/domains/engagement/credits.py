"""Immutable credit ledger with idempotency and reversal entries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class CreditEventType(str, Enum):
    READ_ELIGIBLE = "READ_ELIGIBLE"
    QUALIFIED_VOTE = "QUALIFIED_VOTE"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


@dataclass(frozen=True)
class CreditEntry:
    ledger_id: str
    user_id: str
    event_type: CreditEventType
    event_key: str
    delta: int
    policy_version: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reversed_ledger_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_key or not self.policy_version:
            raise ValueError("credit event key and policy version are required")
        if not isinstance(self.delta, int) or isinstance(self.delta, bool):
            raise ValueError("credit delta must be an integer")

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        return data


@dataclass(frozen=True)
class TierSnapshot:
    user_id: str
    credit_total: int
    level: int
    tier: str
    policy_version: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class CreditLedger:
    """Append-only ledger; duplicate event keys return the original entry."""

    def __init__(self) -> None:
        self._entries: list[CreditEntry] = []
        self._by_event: dict[tuple[str, str, str], CreditEntry] = {}

    def append(
        self,
        *,
        ledger_id: str,
        user_id: str,
        event_type: CreditEventType | str,
        event_key: str,
        delta: int,
        policy_version: str,
    ) -> CreditEntry:
        kind = CreditEventType(event_type)
        key = (user_id, kind.value, event_key)
        existing = self._by_event.get(key)
        if existing is not None:
            # Idempotent replay must not silently turn into a different credit.
            if existing.delta != delta or existing.policy_version != policy_version:
                raise ValueError("idempotency key reused with different credit payload")
            return existing
        entry = CreditEntry(ledger_id, user_id, kind, event_key, delta, policy_version)
        self._entries.append(entry)
        self._by_event[key] = entry
        return entry

    def reverse(
        self, original_ledger_id: str, *, ledger_id: str, event_key: str, policy_version: str
    ) -> CreditEntry:
        original = next(
            (entry for entry in self._entries if entry.ledger_id == original_ledger_id), None
        )
        if original is None:
            raise KeyError("credit entry not found")
        if original.reversed_ledger_id:
            existing = next(
                entry for entry in self._entries if entry.ledger_id == original.reversed_ledger_id
            )
            return existing
        entry = self.append(
            user_id=original.user_id,
            event_type=CreditEventType.REVERSAL,
            event_key=event_key,
            delta=-original.delta,
            policy_version=policy_version,
            ledger_id=ledger_id,
        )
        # The original object is frozen; preserve reversal link in a separate
        # projection rather than mutating historical data.
        self._entries[self._entries.index(original)] = CreditEntry(
            original.ledger_id,
            original.user_id,
            original.event_type,
            original.event_key,
            original.delta,
            original.policy_version,
            original.created_at,
            entry.ledger_id,
        )
        return entry

    def entries(self, user_id: str | None = None) -> tuple[CreditEntry, ...]:
        return tuple(
            entry for entry in self._entries if user_id is None or entry.user_id == user_id
        )

    def total(self, user_id: str) -> int:
        return sum(entry.delta for entry in self._entries if entry.user_id == user_id)

    def snapshot(self, user_id: str, *, policy_version: str = "tier-v1") -> TierSnapshot:
        total = self.total(user_id)
        return credit_tier(user_id, total, policy_version=policy_version)


def credit_tier(
    user_id: str, credit_total: int, *, policy_version: str = "tier-v1"
) -> TierSnapshot:
    if credit_total < 0:
        credit_total = 0
    if credit_total >= 500:
        level, tier = 5, "expert"
    elif credit_total >= 250:
        level, tier = 4, "advanced"
    elif credit_total >= 100:
        level, tier = 3, "engaged"
    elif credit_total >= 25:
        level, tier = 2, "participant"
    else:
        level, tier = 1, "new"
    return TierSnapshot(user_id, credit_total, level, tier, policy_version)
