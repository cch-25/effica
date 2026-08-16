"""Deterministic issue clustering and merge/split state transitions.

This module intentionally treats clustering as a candidate generator.  A
reviewer can merge or split the resulting groups through ``IssueClusterStore``
without mutating the original operation history.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_TOKEN_RE = re.compile(r"[\w가-힣]{2,}", re.UNICODE)
_STOPWORDS = {
    "about",
    "after",
    "also",
    "been",
    "from",
    "have",
    "into",
    "that",
    "their",
    "this",
    "with",
    "the",
    "and",
    "for",
    "are",
    "was",
    "were",
    "has",
    "not",
    "will",
    "일",
    "및",
    "관련",
    "대한",
    "하는",
    "있는",
}


@dataclass(frozen=True)
class ArticleForClustering:
    article_id: str
    title: str
    body: str = ""
    source_id: str | None = None
    published_at: datetime | None = None

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> ArticleForClustering:
        article_id = item.get("article_id", item.get("id"))
        if not article_id:
            raise ValueError("article needs article_id")
        return cls(
            str(article_id),
            str(item.get("title", item.get("headline", ""))),
            str(item.get("body", item.get("content", item.get("summary", ""))) or ""),
            item.get("source_id"),
            item.get("published_at"),
        )


@dataclass(frozen=True)
class IssueMembership:
    issue_id: str
    article_id: str
    confidence: float
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(self.confidence))))


@dataclass
class Issue:
    issue_id: str
    title: str
    status: str = "active"
    version: int = 1
    memberships: dict[str, IssueMembership] = field(default_factory=dict)

    @property
    def article_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.memberships))


def _tokens(value: str) -> set[str]:
    value = unicodedata.normalize("NFKC", value or "").lower()
    return {token for token in _TOKEN_RE.findall(value) if token not in _STOPWORDS}


def issue_similarity(
    left: ArticleForClustering | Mapping[str, Any], right: ArticleForClustering | Mapping[str, Any]
) -> float:
    """Weighted lexical similarity in ``[0, 1]``.

    Titles are weighted three times more than bodies because they provide a
    stable event signal while preserving a fully deterministic, no-network
    implementation suitable for fixture tests.
    """

    if not isinstance(left, ArticleForClustering):
        left = ArticleForClustering.from_mapping(left)
    if not isinstance(right, ArticleForClustering):
        right = ArticleForClustering.from_mapping(right)
    lt, rt = _tokens(left.title), _tokens(right.title)
    lb, rb = _tokens(left.body), _tokens(right.body)
    title = len(lt & rt) / len(lt | rt) if lt or rt else 0.0
    body = len(lb & rb) / len(lb | rb) if lb or rb else 0.0
    # If only one title has content, body overlap still provides a candidate.
    return max(0.0, min(1.0, (3.0 * title + body) / 4.0))


def cluster_articles(
    articles: Iterable[ArticleForClustering | Mapping[str, Any]],
    *,
    threshold: float = 0.30,
) -> list[list[ArticleForClustering]]:
    """Cluster articles using deterministic connected components.

    Input order never affects output ordering: groups and members are sorted by
    article id.  ``threshold`` is inclusive and must lie in ``[0, 1]``.
    """

    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    normalised = [
        a if isinstance(a, ArticleForClustering) else ArticleForClustering.from_mapping(a)
        for a in articles
    ]
    normalised.sort(key=lambda item: item.article_id)
    parent = {item.article_id: item.article_id for item in normalised}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(first: str, second: str) -> None:
        root_first, root_second = find(first), find(second)
        if root_first != root_second:
            parent[max(root_first, root_second)] = min(root_first, root_second)

    for index, left in enumerate(normalised):
        for right in normalised[index + 1 :]:
            if issue_similarity(left, right) >= threshold:
                union(left.article_id, right.article_id)
    groups: dict[str, list[ArticleForClustering]] = {}
    by_id = {item.article_id: item for item in normalised}
    for article_id in sorted(parent):
        groups.setdefault(find(article_id), []).append(by_id[article_id])
    return sorted(
        (sorted(group, key=lambda item: item.article_id) for group in groups.values()),
        key=lambda g: g[0].article_id,
    )


def cluster_issue_candidates(
    articles: Iterable[ArticleForClustering | Mapping[str, Any]], *, threshold: float = 0.30
) -> list[dict[str, Any]]:
    """Return serialisable candidate issue groups for a worker/API boundary."""

    groups = cluster_articles(articles, threshold=threshold)
    candidates: list[dict[str, Any]] = []
    for group in groups:
        ids = [article.article_id for article in group]
        title = min((article.title for article in group if article.title), default="Untitled issue")
        digest = hashlib.sha256("|".join(ids).encode()).hexdigest()[:16]
        candidates.append(
            {
                "candidate_id": digest,
                "title": title,
                "article_ids": ids,
                "confidence": _group_confidence(group),
            }
        )
    return candidates


def _group_confidence(group: Sequence[ArticleForClustering]) -> float:
    if len(group) <= 1:
        return 0.5
    values = [issue_similarity(group[0], other) for other in group[1:]]
    return round(sum(values) / len(values), 6)


class IssueClusterStore:
    """Small in-memory store modelling idempotent merge and split jobs.

    It is intentionally persistence-agnostic.  Production services can replay
    the same operation key against a transaction-backed implementation while
    retaining these exact transition semantics.
    """

    def __init__(self, issues: Iterable[Issue] | None = None) -> None:
        self.issues: dict[str, Issue] = {issue.issue_id: issue for issue in (issues or [])}
        self._operations: dict[str, Any] = {}

    def add_issue(self, issue: Issue) -> Issue:
        existing = self.issues.get(issue.issue_id)
        if existing is not None and existing != issue:
            raise ValueError(f"issue {issue.issue_id} already exists")
        self.issues[issue.issue_id] = issue
        return issue

    def add_membership(
        self, issue_id: str, article_id: str, confidence: float = 1.0
    ) -> IssueMembership:
        issue = self._require(issue_id)
        membership = issue.memberships.get(article_id)
        if membership is None:
            membership = IssueMembership(issue_id, article_id, confidence)
            issue.memberships[article_id] = membership
        return membership

    def merge(
        self,
        source_issue_ids: Iterable[str],
        *,
        target_issue_id: str,
        operation_key: str,
        title: str | None = None,
    ) -> Issue:
        """Merge issues once; replaying ``operation_key`` returns same result."""

        if operation_key in self._operations:
            return self._operations[operation_key]
        source_ids = sorted(set(source_issue_ids) | {target_issue_id})
        source = [self._require(item) for item in source_ids]
        target = self.issues.get(target_issue_id)
        if target is None:
            target = Issue(
                target_issue_id,
                title or min((i.title for i in source if i.title), default="Untitled issue"),
            )
            self.issues[target_issue_id] = target
        for issue in source:
            for article_id, membership in issue.memberships.items():
                prior = target.memberships.get(article_id)
                if prior is None or membership.confidence > prior.confidence:
                    target.memberships[article_id] = IssueMembership(
                        target_issue_id, article_id, membership.confidence
                    )
            if issue.issue_id != target_issue_id:
                issue.status = "merged"
                issue.version += 1
        target.version += 1
        if title:
            target.title = title
        self._operations[operation_key] = target
        return target

    def split(
        self,
        issue_id: str,
        groups: Iterable[Iterable[str]],
        *,
        operation_key: str,
        new_issue_ids: Iterable[str] | None = None,
    ) -> list[Issue]:
        """Split memberships into new issues idempotently.

        Each article appears in at most one requested group; unknown article ids
        are rejected before mutation.  Empty groups are ignored.
        """

        if operation_key in self._operations:
            return self._operations[operation_key]
        source = self._require(issue_id)
        groups_clean = [sorted(set(group)) for group in groups if set(group)]
        known = set(source.memberships)
        requested = {item for group in groups_clean for item in group}
        if not requested <= known:
            raise ValueError("split contains article not in issue")
        if len(requested) != sum(len(group) for group in groups_clean):
            raise ValueError("split groups overlap")
        ids = list(new_issue_ids or [])
        if ids and len(ids) != len(groups_clean):
            raise ValueError("new_issue_ids must match non-empty groups")
        if not ids:
            ids = [f"{issue_id}-split-{index + 1}" for index in range(len(groups_clean))]
        if len(set(ids)) != len(ids):
            raise ValueError("new issue ids must be unique")
        result: list[Issue] = []
        for index, (group, new_id) in enumerate(zip(groups_clean, ids, strict=True)):
            new_issue = self.issues.get(new_id)
            if new_issue is None:
                new_issue = Issue(new_id, f"{source.title} ({index + 1})")
                self.issues[new_id] = new_issue
            for article_id in group:
                new_issue.memberships[article_id] = IssueMembership(
                    new_id, article_id, source.memberships[article_id].confidence
                )
            new_issue.version += 1
            result.append(new_issue)
        source.status = "split"
        source.version += 1
        self._operations[operation_key] = result
        return result

    def _require(self, issue_id: str) -> Issue:
        try:
            return self.issues[issue_id]
        except KeyError as exc:
            raise KeyError(f"unknown issue {issue_id}") from exc
