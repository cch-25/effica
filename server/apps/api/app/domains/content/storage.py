"""Bounded operational data; article content is stored once for site features."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

JOB_POINTER_KEYS = frozenset({
    "source_id", "adapter_id", "crawl_run_id", "article_id", "article_ids",
    "article_version_id", "article_version_ids", "issue_id", "issue_version",
    "weight_id", "recommendation_id", "user_id", "share_card_id", "prompt_version",
    "guardrail_results", "simulations", "source_issue_ids", "target_issue_id",
})


def compact_job_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key in JOB_POINTER_KEYS}


def job_receipt(job_type: str, value: Mapping[str, Any]) -> dict[str, Any]:
    receipt: dict[str, Any] = {"applied": True}
    if job_type == "discover_issues":
        receipt.update(
            publication_status="PUBLISHED" if value.get("issues") else "NO_ISSUES_PUBLISHED",
            published_issue_count=len(value.get("issues", [])),
            candidate_count=value.get("candidate_count", 0),
            stopped_reason=value.get("stopped_reason"),
            blocked_reason=value.get("blocked_reason"),
            rejected_issues=value.get("rejected_issues", [])[:12],
            rejected_article_count=len(value.get("rejected_articles", [])),
            rejected_source_count=len(value.get("rejected_sources", [])),
        )
    # Exports need a download pointer, not a second copy of the user's data.
    if job_type == "export_user":
        for key in ("user_id", "blob_id", "artifact_ref"):
            if value.get(key) is not None:
                receipt[key] = str(value[key])[:1024]
    return receipt
