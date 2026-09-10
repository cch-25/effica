"""Provisional three-axis political questionnaire and deterministic scoring.

The product owner has not supplied the final instrument or validation criteria.
This revision is therefore explicitly versioned as a beta and must remain
immutable once responses reference it.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from typing import Any

POLITICAL_QUESTIONNAIRE_VERSION = "2.0-beta"
POLITICAL_QUESTIONNAIRE_STATUS = "beta"


@dataclass(frozen=True)
class PoliticalQuestionnaireScore:
    x: int
    y: int
    z: int
    confidence: float


_AXES = (
    {
        "id": "x",
        "key": "economic",
        "label": "경제",
        "negative_label": "경제적 좌파",
        "negative_description": "재분배와 국가 개입",
        "positive_label": "경제적 우파",
        "positive_description": "시장과 개인 선택",
    },
    {
        "id": "y",
        "key": "social",
        "label": "사회문화",
        "negative_label": "권위주의",
        "negative_description": "질서와 통제",
        "positive_label": "자유주의",
        "positive_description": "자유와 다양성",
    },
    {
        "id": "z",
        "key": "international",
        "label": "국제",
        "negative_label": "민족주의 및 주권주의",
        "negative_description": "국가 주권과 국내 우선",
        "positive_label": "국제주의 및 세계주의",
        "positive_description": "국제 협력과 공동 대응",
    },
)


_QUESTION_ROWS = (
    ("economic_01", "소득 격차를 줄이기 위해 정부의 재분배 정책을 강화해야 한다.", "x", -1),
    ("economic_02", "경제 성장을 위해 기업과 시장의 자율성을 우선해야 한다.", "x", 1),
    ("economic_03", "고소득층에 더 높은 세율을 적용해 공공서비스 재원을 늘려야 한다.", "x", -1),
    ("economic_04", "일자리와 투자를 늘리려면 기업 규제를 줄여야 한다.", "x", 1),
    ("economic_05", "의료와 주거 같은 기본 서비스는 국가가 더 넓게 보장해야 한다.", "x", -1),
    ("economic_06", "공공서비스에도 민간 경쟁을 확대하면 효율성이 높아질 수 있다.", "x", 1),
    ("economic_07", "기업의 비용이 늘더라도 노동자의 고용과 협상 권리를 더 보호해야 한다.", "x", -1),
    ("economic_08", "복지보다 개인의 선택과 책임을 중심에 둔 경제정책이 바람직하다.", "x", 1),
    ("economic_09", "전기와 교통 같은 핵심 기반 서비스는 공공 부문이 주도해야 한다.", "x", -1),
    ("economic_10", "정부 지출을 줄일 수 있다면 세금 부담도 낮추는 편이 낫다.", "x", 1),
    ("social_01", "사회 질서를 지키기 위해 개인의 자유를 일부 제한할 수 있다.", "y", -1),
    ("social_02", "불편하거나 인기 없는 주장도 표현의 자유로 보호해야 한다.", "y", 1),
    ("social_03", "긴 토론보다 강한 지도자의 신속한 결정이 더 효과적일 때가 많다.", "y", -1),
    ("social_04", "다수와 다른 생활방식과 가족 형태도 동등하게 보호해야 한다.", "y", 1),
    ("social_05", "범죄 예방을 위해 국가의 정보 수집과 감시 권한을 넓힐 수 있다.", "y", -1),
    ("social_06", "법과 제도는 새로운 가치관과 생활방식을 적극 반영해야 한다.", "y", 1),
    ("social_07", "사회 통합을 위해 공동체가 공유하는 가치와 규범을 강조해야 한다.", "y", -1),
    ("social_08", "타인에게 직접 피해를 주지 않는 사적 선택에는 국가가 개입하지 않아야 한다.", "y", 1),
    ("social_09", "중대한 범죄에는 교화보다 강한 처벌을 우선해야 한다.", "y", -1),
    ("social_10", "효율적인 정책 집행보다 권력에 대한 견제와 절차가 더 중요하다.", "y", 1),
    ("international_01", "국제 협약보다 국가의 독자적인 결정권을 우선해야 한다.", "z", -1),
    ("international_02", "기후와 감염병 문제는 다자 협력을 중심으로 해결해야 한다.", "z", 1),
    ("international_03", "무역 갈등이 생기더라도 국내 산업과 일자리를 먼저 보호해야 한다.", "z", -1),
    ("international_04", "국가 간 공통 규범을 넓히면 장기적으로 모두에게 도움이 된다.", "z", 1),
    ("international_05", "국가 정체성과 사회 안정을 위해 이민을 엄격히 제한해야 한다.", "z", -1),
    ("international_06", "난민 보호와 인도적 책임은 여러 국가가 함께 분담해야 한다.", "z", 1),
    ("international_07", "안보는 국제기구보다 자국의 군사력과 동맹 선택에 맡겨야 한다.", "z", -1),
    ("international_08", "분쟁 해결에서 국제기구의 조정 권한을 더 강화해야 한다.", "z", 1),
    ("international_09", "국내 문제가 충분히 해결되기 전에는 해외 원조를 줄여야 한다.", "z", -1),
    ("international_10", "국경을 넘는 문제에는 국내 정책 일부를 국제 기준과 조정할 필요가 있다.", "z", 1),
)


def political_questionnaire_schema() -> dict[str, Any]:
    """Return a fresh JSON-compatible beta questionnaire definition."""

    return {
        "title": "3차원 이념 성향 검사",
        "description": "경제, 사회문화, 국제 관점을 각각 10개 문항으로 확인합니다.",
        "provisional": True,
        "status": POLITICAL_QUESTIONNAIRE_STATUS,
        "scale": {
            "minimum": 1,
            "maximum": 5,
            "labels": {
                "1": "전혀 동의하지 않음",
                "2": "동의하지 않음",
                "3": "보통",
                "4": "동의함",
                "5": "매우 동의함",
            },
        },
        "axes": [dict(axis) for axis in _AXES],
        "questions": [
            {
                "id": question_id,
                "label": label,
                "axis": axis,
                "required": True,
                "minimum": 1,
                "maximum": 5,
                "direction": direction,
            }
            for question_id, label, axis, direction in _QUESTION_ROWS
        ],
    }


def political_questionnaire_scoring() -> dict[str, Any]:
    """Return public scoring metadata needed to explain and render the beta."""

    return {
        "method": "balanced_likert_mean_v1",
        "provisional": True,
        "status": POLITICAL_QUESTIONNAIRE_STATUS,
        "input_scale": {"minimum": 1, "neutral": 3, "maximum": 5},
        "coordinate_range": {"minimum": -100, "maximum": 100},
        "axes": {axis["id"]: axis["key"] for axis in _AXES},
        "question_directions": {
            question_id: direction for question_id, _label, _axis, direction in _QUESTION_ROWS
        },
        "items_per_axis": 10,
    }


def score_political_questionnaire(
    *,
    schema_json: Mapping[str, Any],
    scoring_json: Mapping[str, Any],
    answers: Mapping[str, Any],
) -> PoliticalQuestionnaireScore:
    """Validate a complete beta response and normalize every axis to -100..100."""

    if scoring_json.get("method") != "balanced_likert_mean_v1":
        raise ValueError("QUESTIONNAIRE_SCORING_UNSUPPORTED")
    questions = schema_json.get("questions")
    if not isinstance(questions, list) or len(questions) != 30:
        raise ValueError("QUESTIONNAIRE_DEFINITION_INVALID")
    if not isinstance(answers, Mapping):
        raise ValueError("QUESTIONNAIRE_ANSWER_INVALID")

    expected = {
        str(question.get("id"))
        for question in questions
        if isinstance(question, Mapping) and question.get("id")
    }
    if len(expected) != 30 or set(answers) != expected:
        raise ValueError("QUESTIONNAIRE_ANSWER_INVALID")

    totals = {"x": 0.0, "y": 0.0, "z": 0.0}
    counts: Counter[str] = Counter()
    for question in questions:
        if not isinstance(question, Mapping):
            raise ValueError("QUESTIONNAIRE_DEFINITION_INVALID")
        question_id = str(question.get("id", ""))
        axis = str(question.get("axis", ""))
        direction = question.get("direction")
        answer = answers.get(question_id)
        if axis not in totals or direction not in {-1, 1}:
            raise ValueError("QUESTIONNAIRE_DEFINITION_INVALID")
        if isinstance(answer, bool) or not isinstance(answer, Real):
            raise ValueError("QUESTIONNAIRE_ANSWER_INVALID")
        numeric = float(answer)
        if not math.isfinite(numeric) or not numeric.is_integer() or not 1 <= numeric <= 5:
            raise ValueError("QUESTIONNAIRE_ANSWER_INVALID")
        totals[axis] += ((numeric - 3.0) * 50.0) * int(direction)
        counts[axis] += 1

    if counts != Counter({"x": 10, "y": 10, "z": 10}):
        raise ValueError("QUESTIONNAIRE_DEFINITION_INVALID")
    return PoliticalQuestionnaireScore(
        x=round(totals["x"] / counts["x"]),
        y=round(totals["y"] / counts["y"]),
        z=round(totals["z"] / counts["z"]),
        confidence=1.0,
    )


__all__ = [
    "POLITICAL_QUESTIONNAIRE_STATUS",
    "POLITICAL_QUESTIONNAIRE_VERSION",
    "PoliticalQuestionnaireScore",
    "political_questionnaire_schema",
    "political_questionnaire_scoring",
    "score_political_questionnaire",
]
