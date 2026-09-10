"""Add the provisional 30-item political questionnaire.

Revision ID: 0020_questionnaire_beta
Revises: 0019_llm_request_dedup
Create Date: 2026-09-10

The final research instrument has not been delivered. This immutable beta row
keeps its provisional status and scoring metadata visible to API clients.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_questionnaire_beta"
down_revision = "0019_llm_request_dedup"
branch_labels = None
depends_on = None

_QUESTIONNAIRE_ID = "01K00000000000000000002001"
_VERSION = "2.0-beta"

_AXES = [
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
]

_QUESTION_ROWS = [
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
]


def _schema_json() -> dict[str, object]:
    return {
        "title": "3차원 이념 성향 검사",
        "description": "경제, 사회문화, 국제 관점을 각각 10개 문항으로 확인합니다.",
        "provisional": True,
        "status": "beta",
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
        "axes": _AXES,
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


def _scoring_json() -> dict[str, object]:
    return {
        "method": "balanced_likert_mean_v1",
        "provisional": True,
        "status": "beta",
        "input_scale": {"minimum": 1, "neutral": 3, "maximum": 5},
        "coordinate_range": {"minimum": -100, "maximum": 100},
        "axes": {axis["id"]: axis["key"] for axis in _AXES},
        "question_directions": {
            question_id: direction for question_id, _label, _axis, direction in _QUESTION_ROWS
        },
        "items_per_axis": 10,
    }


def _table() -> sa.TableClause:
    return sa.table(
        "questionnaire_versions",
        sa.column("id", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("version", sa.String()),
        sa.column("schema_json", sa.JSON()),
        sa.column("scoring_json", sa.JSON()),
        sa.column("active_from", sa.DateTime()),
    )


def upgrade() -> None:
    table = _table()
    connection = op.get_bind()
    existing = connection.execute(
        sa.select(table.c.id).where(
            table.c.kind == "onboarding",
            table.c.version == _VERSION,
        )
    ).first()
    if existing is None:
        connection.execute(
            table.insert().values(
                id=_QUESTIONNAIRE_ID,
                kind="onboarding",
                version=_VERSION,
                schema_json=_schema_json(),
                scoring_json=_scoring_json(),
                active_from=sa.func.current_timestamp(),
            )
        )


def downgrade() -> None:
    table = _table()
    op.get_bind().execute(
        table.delete().where(
            table.c.kind == "onboarding",
            table.c.version == _VERSION,
        )
    )
