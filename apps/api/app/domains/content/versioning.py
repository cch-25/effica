"""Article version and stale-analysis decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .canonical import content_hash, normalize_text


class VersionDecision(str, Enum):
    INITIAL = "initial"
    UNCHANGED = "unchanged"
    NEW_VERSION = "new_version"


class AnalysisStatus(str, Enum):
    CURRENT = "current"
    STALE = "stale"


@dataclass(frozen=True)
class ArticleVersion:
    version_id: str
    article_id: str
    content_hash: bytes
    normalized_text: str
    fetched_at: datetime
    modified_at: datetime | None = None
    previous_version_id: str | None = None

    @classmethod
    def from_text(
        cls,
        version_id: str,
        article_id: str,
        text: str,
        *,
        fetched_at: datetime | None = None,
        modified_at: datetime | None = None,
        previous_version_id: str | None = None,
    ) -> ArticleVersion:
        normalized = normalize_text(text)
        stamp = fetched_at or datetime.now(UTC)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return cls(
            version_id,
            article_id,
            content_hash(normalized),
            normalized,
            stamp,
            modified_at,
            previous_version_id,
        )


def decide_version(previous: ArticleVersion | bytes | str | None, text: str) -> VersionDecision:
    """Decide whether a fetched body starts a new version.

    ``previous`` may be a prior :class:`ArticleVersion`, a raw digest, or the
    prior text to keep the helper convenient for ingestion workers.
    """

    if previous is None:
        return VersionDecision.INITIAL
    current_digest = content_hash(text)
    if isinstance(previous, ArticleVersion):
        prior_digest = previous.content_hash
    elif isinstance(previous, bytes):
        prior_digest = previous
    else:
        prior_digest = content_hash(previous)
    return (
        VersionDecision.UNCHANGED if prior_digest == current_digest else VersionDecision.NEW_VERSION
    )


def analysis_is_stale(analysis_version_id: str | None, current_version_id: str | None) -> bool:
    """An analysis is stale whenever it is not attached to current content."""

    return (
        not analysis_version_id
        or not current_version_id
        or analysis_version_id != current_version_id
    )


def analysis_status(
    analysis_version_id: str | None, current_version_id: str | None
) -> AnalysisStatus:
    return (
        AnalysisStatus.STALE
        if analysis_is_stale(analysis_version_id, current_version_id)
        else AnalysisStatus.CURRENT
    )




def mark_stale(records: list[Any], current_version_id: str) -> list[Any]:
    """Return a copy of analysis-like records with status marked stale.

    Records may be dataclasses or mappings.  This is useful for worker output;
    persistence remains outside this module.
    """

    result: list[Any] = []
    for record in records:
        version = (
            record.get("article_version_id")
            if isinstance(record, dict)
            else getattr(record, "article_version_id", None)
        )
        stale = analysis_is_stale(version, current_version_id)
        if isinstance(record, dict):
            item = dict(record)
            item["status"] = AnalysisStatus.STALE.value if stale else AnalysisStatus.CURRENT.value
            result.append(item)
        else:
            try:
                from dataclasses import replace

                result.append(
                    replace(
                        record, status=AnalysisStatus.STALE if stale else AnalysisStatus.CURRENT
                    )
                )
            except (TypeError, ValueError):
                result.append(record)
    return result
