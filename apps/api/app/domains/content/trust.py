"""Public analysis provenance checks shared by repositories and demo tooling."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_SYNTHETIC_ALIASES = frozenset({"dummy-crawl-v1", "deterministic-stub"})


def evidence_is_synthetic(evidence: Any) -> bool:
    """Return true when structured evidence explicitly marks synthetic data."""

    if isinstance(evidence, Mapping):
        marker = evidence.get("synthetic")
        if marker is True or (isinstance(marker, str) and marker.casefold() == "true"):
            return True
        return any(evidence_is_synthetic(value) for value in evidence.values())
    if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes, bytearray)):
        return any(evidence_is_synthetic(value) for value in evidence)
    return False


def is_trusted_openai_assessment(assessment: Any, alias: Any) -> bool:
    """Apply the Phase 1 public provenance predicate to ORM-like rows."""

    assessment_status = getattr(getattr(assessment, "status", None), "value", None) or getattr(
        assessment, "status", None
    )
    alias_status = getattr(getattr(alias, "status", None), "value", None) or getattr(
        alias, "status", None
    )
    provider = str(getattr(alias, "provider", "")).casefold()
    alias_name = str(getattr(alias, "alias", "")).casefold()
    return (
        str(assessment_status).upper() == "SUCCEEDED"
        and provider == "openai"
        and str(alias_status).upper() == "ACTIVE"
        and alias_name not in _SYNTHETIC_ALIASES
        and not evidence_is_synthetic(getattr(assessment, "evidence_json", None))
    )


def score_matches_trusted_assessments(
    score: Any, trusted_assessments: Sequence[tuple[Any, Any]]
) -> bool:
    """Require a score to name at least one trusted assessment it used."""

    components = getattr(score, "components_json", None)
    if not isinstance(components, Mapping):
        return False
    identifiers = components.get("assessment_ids")
    if (
        str(components.get("analysis_provider", "")).casefold() == "openai"
        and isinstance(identifiers, Sequence)
        and not isinstance(identifiers, (str, bytes, bytearray))
    ):
        declared = {str(value) for value in identifiers}
    elif str(components.get("분석방식", "")).casefold() == "llm" and components.get(
        "모델평가ID"
    ):
        declared = {str(components["모델평가ID"])}
    else:
        return False
    trusted = {str(getattr(assessment, "id", "")) for assessment, _ in trusted_assessments}
    return bool(declared & trusted)


def public_score_assessment_summary(score: Any, assessment_id: Any) -> str | None:
    """Return a summary only when a score explicitly links it to the assessment."""

    components = getattr(score, "components_json", None)
    if not isinstance(components, Mapping):
        return None
    identifiers = components.get("assessment_ids")
    declared = (
        {str(value) for value in identifiers}
        if isinstance(identifiers, Sequence)
        and not isinstance(identifiers, (str, bytes, bytearray))
        else {str(components.get("모델평가ID", ""))}
    )
    if str(assessment_id) not in declared:
        return None
    for key in ("rationale_summary", "근거요약"):
        value = components.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    return None


def public_assessment_summary(evidence: Any, *, fallback: str | None = None) -> str:
    """Build a bounded public summary without exposing a raw model response."""

    if isinstance(evidence, Mapping):
        for key in ("rationale_summary", "summary", "reason", "근거요약"):
            value = evidence.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
        values = evidence.get("evidence")
        if values is not None:
            return public_assessment_summary(values, fallback=fallback)
    if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes, bytearray)):
        rationales = [
            str(item.get("rationale", "")).strip()
            for item in evidence
            if isinstance(item, Mapping) and str(item.get("rationale", "")).strip()
        ]
        if rationales:
            return " ".join(rationales)[:500]
    if isinstance(fallback, str) and fallback.strip():
        return fallback.strip()[:500]
    return "공개 가능한 근거 인용이 제공되지 않았습니다."


def public_assessment_evidence(evidence: Any) -> list[dict[str, Any]]:
    """Return only structured public evidence items from old or current storage shapes."""

    values = evidence.get("evidence", []) if isinstance(evidence, Mapping) else evidence
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in values if isinstance(item, Mapping)]
