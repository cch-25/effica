from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from app.domains.analysis import (
    AssessmentInput,
    HTTPProvider,
    ProviderConfig,
    ensemble_assessments,
)
from app.domains.scoring import (
    ScoreComponents,
    WeightProfile,
    calculate_article_score,
    canonical_score_json,
)


def test_analysis_request_bounds_pathological_crawl_content_without_changing_offsets() -> None:
    seen: list[dict[str, object]] = []
    content = "opening" + ("x" * 80_000)

    def transport(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "x": 5,
                "sensationalism": 10,
                "confidence": 0.8,
                "evidence": [
                    {
                        "article_version_id": "version-1",
                        "start": 0,
                        "end": 7,
                        "quote": "opening",
                        "rationale": "opening evidence",
                    }
                ],
                "rationale_summary": "bounded assessment",
            },
            request=request,
        )

    provider = HTTPProvider(
        ProviderConfig(
            "test",
            "gpt-test",
            endpoint="https://provider.test/analyze",
            max_retries=0,
        ),
        transport=httpx.MockTransport(transport),
    )
    result = provider.analyze_article(
        AssessmentInput(
            article_version_id="version-1",
            title="Title",
            content=content,
        ),
        "prompt-v1",
    )

    assert result.evidence[0].quote == "opening"
    prompt = str(seen[0]["input"])
    assert "CONTENT_TRUNCATED: true" in prompt
    assert len(prompt) < 62_000


def test_score_snapshot_contains_every_recalculation_input() -> None:
    components = ScoreComponents(
        model=(40, 0, 0),
        relative=(20, 0, 0),
        crowd=(10, 0, 0),
        source=(0, 0, 0),
        model_confidence=0.8,
        evidence_quality=0.7,
        model_spread=8.0,
        vote_count=4,
        source_sample_size=2,
        sensationalism=37,
    )
    weights = WeightProfile(version="v1")
    first = calculate_article_score(components, weights)
    rebuilt = calculate_article_score(ScoreComponents(**first.components), weights)

    assert rebuilt == first
    assert canonical_score_json(rebuilt) == canonical_score_json(first)
    assert set(first.components) == {
        "model",
        "relative",
        "crowd",
        "source",
        "model_spread",
        "model_confidence",
        "evidence_quality",
        "sensationalism",
        "vote_count",
        "source_sample_size",
    }


def test_empty_score_evidence_has_zero_confidence_and_nonfinite_inputs_fail_closed() -> None:
    empty = ScoreComponents((0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0))
    assert calculate_article_score(empty).confidence == 0.0

    with pytest.raises(ValueError):
        ScoreComponents((float("nan"), 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0))
    with pytest.raises(ValueError):
        ScoreComponents((True, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0))
    with pytest.raises(ValueError):
        ScoreComponents(
            (0, 0, 0),
            (0, 0, 0),
            (0, 0, 0),
            (0, 0, 0),
            model_confidence=float("inf"),
        )
    with pytest.raises(ValueError):
        WeightProfile(model=Decimal("NaN"))
    with pytest.raises(ValueError):
        ensemble_assessments([], max_spread=float("nan"))
