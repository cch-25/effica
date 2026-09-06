"""Cheap deterministic gate that keeps irrelevant pages away from the LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass

try:
    from apps.api.app.domains.issues.topics import infer_issue_topic
except ImportError:  # pragma: no cover - supports PYTHONPATH=apps/worker.
    from api.app.domains.issues.topics import infer_issue_topic  # type: ignore


_GENERIC_TITLE_PATTERNS = (
    re.compile(r"^보도자료(?:\s*[-|:].*)?$", re.IGNORECASE),
    re.compile(r"^(?:정부|부처|위원회)?\s*(?:소식|알림마당)$", re.IGNORECASE),
    re.compile(r"^[가-힣A-Za-z0-9]{2,20}(?:부|처|청|위원회|공사|공단)$", re.IGNORECASE),
)


@dataclass(frozen=True)
class AnalysisEligibility:
    eligible: bool
    reason: str
    topic: str


def assess_analysis_eligibility(
    title: str,
    content: str,
    *,
    minimum_content_chars: int = 200,
) -> AnalysisEligibility:
    normalized_title = " ".join(str(title or "").split())
    normalized_content = str(content or "").strip()
    topic = infer_issue_topic(normalized_title, normalized_content[:4_000])
    if len(normalized_title) < 8:
        return AnalysisEligibility(False, "TITLE_TOO_SHORT", topic)
    if any(pattern.fullmatch(normalized_title) for pattern in _GENERIC_TITLE_PATTERNS):
        return AnalysisEligibility(False, "GENERIC_INDEX_TITLE", topic)
    if len(normalized_content) < max(1, int(minimum_content_chars)):
        return AnalysisEligibility(False, "CONTENT_TOO_SHORT", topic)
    return AnalysisEligibility(True, "ARTICLE_CONTENT", topic)
