from types import SimpleNamespace
from typing import Any

from apps.api.app.domains.content.trust import (
    is_trusted_openai_assessment,
    public_assessment_evidence,
    public_assessment_summary,
    public_score_assessment_summary,
    score_matches_trusted_assessments,
)


def test_public_assessment_without_evidence_does_not_claim_evidence_exists() -> None:
    payload: dict[str, Any] = {"evidence": []}

    assert public_assessment_evidence(payload) == []
    assert public_assessment_summary(payload) == "공개 가능한 근거 인용이 제공되지 않았습니다."


def test_public_assessment_normalizes_nested_evidence_to_a_bounded_list() -> None:
    payload: dict[str, Any] = {
        "summary": "공개 요약",
        "evidence": [{"quote": str(index)} for index in range(7)],
    }

    assert public_assessment_summary(payload) == "공개 요약"
    assert public_assessment_evidence(payload) == [
        {"quote": str(index)} for index in range(5)
    ]


def test_legacy_score_summary_requires_matching_trusted_assessment() -> None:
    assessment = SimpleNamespace(id="assessment-1")
    score = SimpleNamespace(
        components_json={
            "분석방식": "LLM",
            "모델평가ID": "assessment-1",
            "근거요약": " 기존 시드의 공개 요약 ",
        }
    )

    assert score_matches_trusted_assessments(score, [(assessment, SimpleNamespace())])
    assert public_score_assessment_summary(score, assessment.id) == "기존 시드의 공개 요약"
    assert public_assessment_summary(
        [], fallback=public_score_assessment_summary(score, assessment.id)
    ) == "기존 시드의 공개 요약"
    assert public_score_assessment_summary(score, "assessment-2") is None


def test_current_non_openai_provenance_cannot_fall_back_to_legacy_fields() -> None:
    assessment = SimpleNamespace(id="assessment-1")
    score = SimpleNamespace(
        components_json={
            "analysis_provider": "other",
            "assessment_ids": ["assessment-1"],
            "분석방식": "LLM",
            "모델평가ID": "assessment-1",
            "근거요약": "신뢰하면 안 되는 요약",
        }
    )

    assert not score_matches_trusted_assessments(
        score, [(assessment, SimpleNamespace())]
    )
    assert public_score_assessment_summary(score, assessment.id) is None


def test_historical_openai_assessment_survives_alias_rotation() -> None:
    assessment = SimpleNamespace(
        status="SUCCEEDED",
        evidence_json={"synthetic": False},
    )
    alias = SimpleNamespace(
        alias="openai-previous",
        provider="openai",
        actual_model_id="gpt-5.6-luna",
        status="DEPRECATED",
    )

    assert is_trusted_openai_assessment(assessment, alias)

    non_gpt = SimpleNamespace(**{**vars(alias), "actual_model_id": "third-party-model"})
    assert not is_trusted_openai_assessment(assessment, non_gpt)

    synthetic_alias = SimpleNamespace(**{**vars(alias), "alias": "deterministic-stub"})
    assert not is_trusted_openai_assessment(assessment, synthetic_alias)
