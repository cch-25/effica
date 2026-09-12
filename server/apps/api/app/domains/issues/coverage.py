"""Shared reading-section and discovery-diversity rules, never issue identity.

Related coverage keeps its original article memberships and comparison scores.
Title matching is a navigation heuristic, not evidence that events are identical.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from apps.api.app.db.utc import ensure_utc

_GENERIC_WORDS = frozenset("""
정부 국회 정치 사회 경제 한국 대한민국 대통령 여당 야당 여야
장관 후보 후보자 의원 대표 국회의원 국무위원 법무부 성평등가족부 국방부
청문회 인사청문회 논란 의혹 검증 공방 관련 각종 대한 둘러싼
정책 문제 논의 쟁점 입장 추진 발표 요구 검토 가능성 여부
""".split())
_APPOINTMENT = re.compile(r"인사청문회|장관.{0,12}후보|후보.{0,12}장관")
_SUFFIX = re.compile(r"(?:에서|으로|과의|와의|에|의|은|는|을|를)$")


def _words(title: str) -> set[str]:
    words = re.findall(r"[가-힣a-z0-9]+", unicodedata.normalize("NFKC", title).lower())
    return {word for raw in words
            if len(word := _SUFFIX.sub("", raw) if len(raw) > 3 else raw) >= 2
            and word not in _GENERIC_WORDS}


def _date(item: Mapping[str, Any]) -> datetime | None:
    value = item.get("data_as_of") or item.get("last_activity_at")
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return ensure_utc(value) if isinstance(value, datetime) else None


def related_coverage(left: Mapping[str, Any], right: Mapping[str, Any], *, dated: bool = True) -> bool:
    if left.get("topic") != right.get("topic"):
        return False
    if dated:
        a_date, b_date = _date(left), _date(right)
        if a_date is None or b_date is None or abs(a_date - b_date) > timedelta(days=7):
            return False
    if set(left.get("article_ids", ())) & set(right.get("article_ids", ())):
        return True
    a_title, b_title = str(left.get("title") or ""), str(right.get("title") or "")
    a, b = _words(a_title), _words(b_title)
    shared = len(a & b)
    return bool(
        (_APPOINTMENT.search(a_title) and _APPOINTMENT.search(b_title) and shared >= 1)
        or (shared >= 2 and shared / max(len(a), len(b)) >= 0.4)
    )


def _components(items: Sequence[Mapping[str, Any]], *, dated: bool) -> list[list[int]]:
    groups: list[list[int]] = []
    for index, item in enumerate(items):
        matches = [group for group in groups
                   if any(related_coverage(items[member], item, dated=dated) for member in group)]
        if not matches:
            groups.append([index])
            continue
        target = matches[0]
        target.append(index)
        for group in matches[1:]:
            target.extend(group)
            groups.remove(group)
    return groups


def _importance(item: Mapping[str, Any]) -> tuple[Any, ...]:
    date = _date({"last_activity_at": item.get("last_activity_at")})
    return (
        item.get("editorial_priority") or 2_147_483_647,
        -int(item.get("source_count") or 0),
        -len(item.get("article_ids", ())),
        -date.timestamp() if date else 0,
        str(item["id"]),
    )


def annotate_coverage_groups(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Annotate the full eligible corpus before pagination, preserving row order."""
    output = [dict(item) for item in items]
    for indices in _components(items, dated=True):
        members = sorted((items[index] for index in indices), key=_importance)
        title = str(members[0]["title"])
        if len(members) > 1 and all(_APPOINTMENT.search(str(item["title"])) for item in members):
            title = "장관 후보자 인사청문회"
        for index in indices:
            output[index]["coverage_group_id"] = str(members[0]["id"])
            output[index]["coverage_group_title"] = title
    return output


def diversify_coverage[T: Mapping[str, Any]](
    items: Sequence[T], *, represented: Sequence[Mapping[str, Any]] = (),
) -> list[T]:
    """Interleave already-ranked current candidates before spending or capping.

    Within each round retain input importance order. Previously selected events
    count toward their family's representation when filling the remaining slots.
    Eligibility, source quorum and paid request limits stay with the caller.
    """
    combined = [*represented, *items]
    offset = len(represented)
    groups = _components(combined, dated=False)
    counts = [sum(index < offset for index in group) for group in groups]
    membership = {index - offset: group_id for group_id, group in enumerate(groups)
                  for index in group if index >= offset}
    pending = set(range(len(items)))
    output = []
    while pending:
        index = min(pending, key=lambda value: (counts[membership[value]], value))
        pending.remove(index)
        output.append(items[index])
        counts[membership[index]] += 1
    return output
