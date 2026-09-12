from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from apps.api.app.domains.issues.coverage import (
    annotate_coverage_groups,
    diversify_coverage,
    related_coverage,
)
from apps.api.app.state import PlatformState
from apps.api.tests.test_editorial_public_scope import _client

NOW = datetime(2026, 9, 12, tzinfo=UTC)
TITLES = [
    "김승원 법무부 장관 후보자 신약 청탁 의혹과 인사청문 검증 공방",
    "용혜인 성평등가족부 장관 후보자의 국회의원 겸직 및 공직 적격성 논란",
    "김승원 용혜인 강신철 장관 후보자 인사청문회 증인 채택 무산",
    "호르무즈 해협 파병과 안보 지원을 둘러싼 정부 국회 공방",
    "김승원 용혜인 장관 후보자 인사청문회와 각종 의혹 검증",
]


def issue(index: int, title: str | None = None, **extra):
    return {"id": str(index), "title": title or TITLES[index], "topic": "정치",
            "editorial_priority": index + 1, "data_as_of": NOW,
            "last_activity_at": NOW, "source_count": 3,
            "article_ids": [f"{index}-{n}" for n in range(3)], **extra}


def test_reading_sections_group_related_angles_without_mutating_memberships():
    original = [issue(index) for index in range(5)]
    before = deepcopy(original)
    rows = annotate_coverage_groups(original)
    assert [row["coverage_group_id"] for row in rows] == ["0", "0", "0", "3", "0"]
    assert rows[1]["coverage_group_title"] == "장관 후보자 인사청문회"
    assert rows[3]["coverage_group_title"] == TITLES[3]
    assert original == before
    assert [row["article_ids"] for row in rows] == [row["article_ids"] for row in original]
    reverse = annotate_coverage_groups(list(reversed(original)))
    assert {row["id"]: row["coverage_group_id"] for row in reverse} == {
        row["id"]: row["coverage_group_id"] for row in rows}


@pytest.mark.parametrize("other", [
    issue(5, "김승원 종합부동산세 개편안 발의 논란"),
    issue(5, "이정민 장관 후보자 국회의원 겸직 논란"),
    issue(5, TITLES[0], topic="사회"),
    issue(5, TITLES[0], data_as_of=NOW - timedelta(days=8)),
    issue(5, TITLES[0], data_as_of="invalid"),
    issue(5, TITLES[0], data_as_of=None, last_activity_at=None),
])
def test_names_generic_words_other_topics_and_old_events_stay_separate(other):
    assert not related_coverage(issue(0), other)


def test_shared_article_is_a_reading_relationship_only_and_requires_same_topic_and_window():
    a, b = issue(0), issue(3, article_ids=["0-0", "3-1", "3-2"])
    assert related_coverage(a, b)
    assert not related_coverage(a, {**b, "topic": "사회"})
    assert not related_coverage(a, {**b, "data_as_of": NOW - timedelta(days=8)})
    assert related_coverage(a, {**b, "data_as_of": (NOW - timedelta(days=7)).isoformat()})


def test_diversity_precedes_a_limit_and_counts_already_represented_events():
    candidates = [issue(index) for index in range(5)]
    candidates += [issue(5, "종합부동산세 공제 한도 개편"), issue(6, "주당 노동시간 상한 조정")]
    assert [row["id"] for row in diversify_coverage(candidates)[:5]] == ["0", "3", "5", "6", "1"]
    remaining = diversify_coverage(candidates[1:], represented=candidates[:1])
    assert [row["id"] for row in remaining[:4]] == ["3", "5", "6", "1"]


def test_public_api_computes_groups_before_pagination_and_detail_keeps_memberships():
    state = PlatformState()
    base = deepcopy(next(iter(state.issues.values())))
    originals = [deepcopy(state.articles[article_id]) for article_id in base["article_ids"]]
    state.issues.clear()
    for index, title in enumerate(TITLES):
        members = []
        for number, article in enumerate(originals):
            article_id = f"article-{index}-{number}"
            state.articles[article_id] = {**article, "id": article_id}
            members.append(article_id)
        state.issues[str(index)] = {**base, "id": str(index), "title": title,
                                   "editorial_priority": index + 1, "article_ids": members}
    client = _client(state)
    expected = client.get("/api/v1/issues?limit=250").json()["items"]
    actual = []
    cursor = None
    while True:
        params = {"limit": 1, **({"cursor": cursor} if cursor else {})}
        response = client.get("/api/v1/issues", params=params)
        assert response.status_code == 200
        page = response.json()
        actual.extend(page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert actual == expected
    assert len({row["coverage_group_id"] for row in actual}) == 2
    for row in actual:
        detail = client.get(f"/api/v1/issues/{row['id']}").json()
        assert detail["coverage_group_id"] == row["coverage_group_id"]
        assert detail["article_ids"] == state.issues[row["id"]]["article_ids"]
