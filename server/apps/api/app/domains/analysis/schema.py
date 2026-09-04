"""Pydantic v2 models used at the pure analysis boundary."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator


class AssessmentStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    article_version_id: StrictStr
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: StrictStr = Field(min_length=1, max_length=500)
    rationale: StrictStr = Field(default="", max_length=500)

    @field_validator("end")
    @classmethod
    def end_after_start(cls, value: int, info: Any) -> int:
        start = info.data.get("start")
        if start is not None and value <= start:
            raise ValueError("evidence end must be greater than start")
        return value


class AssessmentInput(BaseModel):
    """Content-first model input; source identity can be masked before use."""

    model_config = ConfigDict(extra="forbid", strict=True)

    article_version_id: StrictStr
    title: StrictStr = Field(min_length=1)
    content: StrictStr = Field(min_length=1)
    source_name: StrictStr | None = None
    source_url: StrictStr | None = None
    author: StrictStr | None = None


class ModelAssessment(BaseModel):
    """Strict, serialisable model output.

    ``x`` is the canonical political-bias coordinate (-100 left to +100
    right), while ``sensationalism`` is the independent exaggeration score.
    ``y`` and ``z`` are retained as zero-valued compatibility fields for
    persisted records and older API clients. ``evidence`` is explicitly
    linked to the analyzed article version for reproducibility.
    """

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    article_version_id: StrictStr
    model_alias: StrictStr
    actual_model_id: StrictStr
    prompt_version: StrictStr
    x: StrictInt = Field(ge=-100, le=100)
    y: StrictInt = Field(default=0, ge=-100, le=100)
    z: StrictInt = Field(default=0, ge=-100, le=100)
    sensationalism: StrictInt = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list, max_length=20)
    rationale_summary: StrictStr = Field(default="", max_length=500)
    token_usage: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    status: AssessmentStatus = AssessmentStatus.SUCCEEDED
    error_code: StrictStr | None = None

    @field_validator("evidence")
    @classmethod
    def evidence_matches_version(cls, value: list[Evidence], info: Any) -> list[Evidence]:
        version = info.data.get("article_version_id")
        if version and any(item.article_version_id != version for item in value):
            raise ValueError("evidence must reference the analyzed article version")
        return value

    @field_validator("confidence")
    @classmethod
    def finite_confidence(cls, value: float) -> float:
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("confidence must be finite")
        return round(float(value), 6)
