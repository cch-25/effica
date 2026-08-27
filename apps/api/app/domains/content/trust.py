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
    """Apply the public provenance predicate to ORM-like rows.

    Alias status controls whether a model may receive *new* outbound work; it
    is not a retroactive verdict on an immutable successful assessment.  An
    operator must be able to rotate the single ACTIVE alias without making all
    historical articles disappear.  Explicit synthetic markers and non-GPT
    providers remain fail-closed.
    """

    assessment_status = getattr(getattr(assessment, "status", None), "value", None) or getattr(
        assessment, "status", None
    )
    provider = str(getattr(alias, "provider", "")).casefold()
    alias_name = str(getattr(alias, "alias", "")).casefold()
    actual_model_id = str(getattr(alias, "actual_model_id", "")).strip()
    return (
        str(assessment_status).upper() == "SUCCEEDED"
        and provider == "openai"
        and actual_model_id.startswith("gpt-")
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
    if str(components.get("analysis_provider", "")).casefold() != "openai":
        return False
    identifiers = components.get("assessment_ids")
    if not isinstance(identifiers, Sequence) or isinstance(identifiers, (str, bytes, bytearray)):
        return False
    declared = {str(value) for value in identifiers}
    trusted = {str(getattr(assessment, "id", "")) for assessment, _ in trusted_assessments}
    return bool(declared & trusted)


def public_assessment_summary(evidence: Any) -> str:
    """Build a bounded public summary without exposing a raw model response."""

    if isinstance(evidence, Mapping):
        for key in ("summary", "rationale_summary", "reason", "근거요약"):
            value = evidence.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
        values = evidence.get("evidence")
        if values is not None:
            return public_assessment_summary(values)
    if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes, bytearray)):
        rationales = [
            str(item.get("rationale", "")).strip()
            for item in evidence
            if isinstance(item, Mapping) and str(item.get("rationale", "")).strip()
        ]
        if rationales:
            return " ".join(rationales)[:500]
    return "공개 가능한 근거 인용이 제공되지 않았습니다."


def public_assessment_evidence(evidence: Any) -> list[dict[str, Any]]:
    """Return only the bounded public evidence list from a model payload."""

    values = evidence.get("evidence") if isinstance(evidence, Mapping) else evidence
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in values if isinstance(item, Mapping)][:5]
