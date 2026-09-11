"""A stable, bounded set of real articles from distinct event sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from apps.api.app.domains.issues.editorial_policy import publisher_identity

from .analysis_eligibility import assess_analysis_eligibility

COMPARISON_ARTICLES_SQL = """
    SELECT a.id AS article_id, a.current_version_id AS article_version_id,
           a.source_id, a.title, s.name AS source_name, a.canonical_url AS source_url,
           b.payload AS content
    FROM issue_memberships im
    JOIN issues i ON i.id = im.issue_id
    JOIN articles a ON a.id = im.article_id
    JOIN sources s ON s.id = a.source_id
    JOIN article_versions av ON av.id = a.current_version_id
    JOIN stored_blobs b ON b.id = av.normalized_text_ref
    WHERE im.issue_id = :issue_id AND i.issue_kind = 'EVENT' AND i.status = 'active'
      AND i.last_activity_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 7 DAY)
      AND i.editorial_key LIKE 'daily-issue:%'
      AND a.status = 'active' AND s.active = 1 AND s.policy_status = 'approved'
      AND a.published_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 7 DAY)
      AND a.published_at <= UTC_TIMESTAMP()
    ORDER BY a.id
"""


def select_comparison_cohort(
    rows: Sequence[Mapping[str, Any]], *, minimum_content_chars: int = 200,
) -> list[dict[str, Any]]:
    selected = []
    sources: set[str] = set()
    for row in sorted(rows, key=lambda row: str(row["article_id"])):
        source = publisher_identity(str(row.get("source_url") or ""))
        content = row.get("content")
        body = bytes(content).decode("utf-8", errors="replace") if isinstance(content, (bytes, bytearray)) else str(content or "")
        if not source or source in sources or not assess_analysis_eligibility(
            str(row.get("title") or ""), body, minimum_content_chars=minimum_content_chars,
        ).eligible:
            continue
        selected.append({**row, "content": body})
        sources.add(source)
        # One bounded snapshot covers every publisher in a curated event. The
        # public view selects any two to four frames without another paid call.
        if len(selected) == 8:
            break
    return selected if len(selected) >= 3 else []
