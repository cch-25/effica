from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from apps.worker.worker.lookups import MariaDBWorkerLookups


class LookupFixture(MariaDBWorkerLookups):
    def __init__(self, *, assessments: list[dict[str, Any]]) -> None:
        super().__init__(lambda: None, encryption_secret="unit-test-secret")
        self.assessments = assessments

    async def _one(
        self, statement: str, params: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        del statement, params
        return {
            "article_version_id": "version-1",
            "article_id": "article-1",
            "source_id": "source-1",
        }

    async def _all(
        self,
        statement: str,
        params: Mapping[str, Any],
        *,
        expanding: str | None = None,
    ) -> list[dict[str, Any]]:
        del statement, params, expanding
        return list(self.assessments)

    async def votes_lookup(self, identifier: Any) -> list[dict[str, Any]]:
        del identifier
        return []


@pytest.mark.asyncio
async def test_score_components_refuse_empty_openai_provenance() -> None:
    lookup = LookupFixture(assessments=[])

    assert await lookup.score_components_lookup("version-1") is None


@pytest.mark.asyncio
async def test_single_model_spread_ignores_legacy_axes_and_has_full_evidence_quality() -> None:
    lookup = LookupFixture(
        assessments=[
            {
                "id": "assessment-1",
                "x": 60,
                "y": 0,
                "z": 0,
                "sensationalism": 25,
                "confidence": 0.8,
                "actual_model_id": "gpt-5.6-luna",
                "evidence_json": [
                    {
                        "article_version_id": "version-1",
                        "start": 0,
                        "end": 12,
                        "quote": "검증 가능한 인용",
                    }
                ],
            }
        ]
    )

    result = await lookup.score_components_lookup("version-1")

    assert result is not None
    assert result["components"]["model_spread"] == 0.0
    assert result["components"]["evidence_quality"] == 1.0
    assert result["provenance"] == {
        "analysis_provider": "openai",
        "assessment_ids": ["assessment-1"],
        "actual_model_ids": ["gpt-5.6-luna"],
    }


@pytest.mark.asyncio
async def test_model_spread_compares_models_on_bias_axis_only() -> None:
    lookup = LookupFixture(
        assessments=[
            {
                "id": "assessment-1",
                "x": -20,
                "y": 90,
                "z": -90,
                "sensationalism": 10,
                "confidence": 0.7,
                "actual_model_id": "gpt-a",
                "evidence_json": [],
            },
            {
                "id": "assessment-2",
                "x": 20,
                "y": -90,
                "z": 90,
                "sensationalism": 30,
                "confidence": 0.9,
                "actual_model_id": "gpt-b",
                "evidence_json": [],
            },
        ]
    )

    result = await lookup.score_components_lookup("version-1")

    assert result is not None
    assert result["components"]["model_spread"] == 20.0
    assert result["components"]["evidence_quality"] == 0.0
