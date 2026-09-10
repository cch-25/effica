"""Shared server-side eligibility for protected event analysis capacity."""

from __future__ import annotations


def essential_article_exists(version_sql: str, now_sql: str) -> str:
    """SQL fragments are supplied by worker code, never by job payloads."""
    return f"""EXISTS (
        SELECT 1 FROM articles essential_article
        JOIN sources essential_source ON essential_source.id = essential_article.source_id
        JOIN issue_memberships essential_member ON essential_member.article_id = essential_article.id
        JOIN issues essential_issue ON essential_issue.id = essential_member.issue_id
        WHERE essential_article.current_version_id = {version_sql}
          AND essential_article.status = 'active'
          AND essential_article.published_at >= DATE_SUB({now_sql}, INTERVAL 7 DAY)
          AND essential_article.published_at <= {now_sql}
          AND essential_source.active = 1 AND essential_source.policy_status = 'approved'
          AND essential_issue.issue_kind = 'EVENT' AND essential_issue.status = 'active'
          AND essential_issue.editorial_key LIKE 'daily-issue:%'
          AND essential_issue.last_activity_at >= DATE_SUB({now_sql}, INTERVAL 7 DAY)
    )"""
