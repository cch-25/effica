"""Source policy checks for crawler jobs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CrawlerPolicyError(PermissionError):
    """Raised before a crawler starts when source policy is not approved."""


class SourcePolicy(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


_APPROVED = {"APPROVED", "ALLOW", "ALLOWED", "OK", "CONSENTED", "ACTIVE", "TRUE"}


@dataclass(frozen=True)
class CrawlerPolicyGuard:
    """Require both robots and terms permission before crawler use."""

    robots_status: str
    terms_status: str
    policy_version: str | None = None

    @property
    def allowed(self) -> bool:
        return self._is_approved(self.robots_status) and self._is_approved(self.terms_status)

    @staticmethod
    def _is_approved(value: str | SourcePolicy | None) -> bool:
        normalized = value.value if isinstance(value, SourcePolicy) else value
        return str(normalized or "").upper() in _APPROVED

    def check(self) -> None:
        if not self.allowed:
            raise CrawlerPolicyError(
                "crawler requires approved robots and terms policy "
                f"(robots={self.robots_status!r}, terms={self.terms_status!r})"
            )

    def assert_allowed(self) -> None:
        self.check()

    def can_crawl(self) -> bool:
        return self.allowed

    @classmethod
    def from_source(cls, source: object) -> CrawlerPolicyGuard:
        """Build a guard from a source object or mapping used by fixtures."""

        if isinstance(source, dict):
            get = source.get
        else:
            def get(key: str, default: object = None) -> object:
                return getattr(source, key, default)
        return cls(
            str(get("robots_status", get("robots_policy", ""))),
            str(get("terms_status", get("terms_policy", ""))),
            get("policy_version"),
        )
