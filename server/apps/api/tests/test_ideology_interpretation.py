import pytest

from apps.api.app.domains.sharing.ideology import interpret_ideology
from apps.api.app.domains.users.political_questionnaire import (
    political_questionnaire_schema,
    political_questionnaire_scoring,
    score_political_questionnaire,
)


@pytest.mark.parametrize(("x", "y", "label"), [
    (-80, -60, "권위주의 좌파 성향"), (80, -60, "권위주의 우파 성향"),
    (-80, 60, "자유주의 좌파 성향"), (80, 60, "자유주의 우파 성향"),
    (0, 0, "중도 성향"), (-10, 10, "중도 성향"), (10, -10, "중도 성향"),
    (-11, 0, "좌파 성향"), (11, 0, "우파 성향"),
    (0, -11, "권위주의 중도 성향"), (0, 11, "자유주의 중도 성향"),
])
def test_ideology_labels(x, y, label):
    assert interpret_ideology(x, y, 0)["label"] == label


@pytest.mark.parametrize("x", [-100, 100])
@pytest.mark.parametrize("y", [-100, 100])
@pytest.mark.parametrize("z", [-100, 100])
def test_questionnaire_directions_reach_all_eight_ideology_regions(x, y, z):
    schema = political_questionnaire_schema()
    target = {"x": x, "y": y, "z": z}
    answers = {
        question["id"]: 5 if target[question["axis"]] * question["direction"] > 0 else 1
        for question in schema["questions"]
    }
    score = score_political_questionnaire(
        schema_json=schema, scoring_json=political_questionnaire_scoring(), answers=answers,
    )
    assert (score.x, score.y, score.z) == (x, y, z)
    result = interpret_ideology(score.x, score.y, score.z)
    assert result["economic"] == ("좌파" if x < 0 else "우파")
    assert result["authority"] == ("권위주의" if y < 0 else "자유주의")
    assert result["international"] == ("주권주의" if z < 0 else "국제주의")


def test_internationalism_does_not_change_left_right():
    assert interpret_ideology(-24, 37, -100)["label"] == interpret_ideology(-24, 37, 100)["label"]
    assert interpret_ideology(-24, 37, 10)["international"] == "혼합"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 101, -101])
def test_invalid_coordinates_are_not_interpreted(value):
    with pytest.raises(ValueError):
        interpret_ideology(value, 0, 0)
