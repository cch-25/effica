from types import SimpleNamespace
from typing import Any

from apps.api.app.domains.content.trust import (
    is_trusted_openai_assessment,
    public_assessment_evidence,
    public_assessment_summary,
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
