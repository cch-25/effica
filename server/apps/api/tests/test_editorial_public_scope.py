"""Public reads must never fall back to uncurated or single-publisher news."""
from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.api.v1.dependencies import get_repository, get_state
from apps.api.app.api.v1.routes import router
from apps.api.app.core.errors import install_error_handlers
from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    ArticleStatus,
    IssueKind,
    IssueStatus,
    SourcePolicyStatus,
    SourceType,
)
from apps.api.app.db.models import Article, ArticleVersion, Issue, IssueMembership, Source
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.domains.issues.editorial_policy import is_current_article, publisher_identity
from apps.api.app.domains.issues.topics import PUBLIC_ISSUE_TOPICS
from apps.api.app.repositories.platform import MariaDBPlatformRepository
from apps.api.app.repositories.product import ProductComparisonError
from apps.api.app.state import PlatformState


def _client(state: PlatformState) -> TestClient:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_state] = lambda: state
    app.dependency_overrides[get_repository] = lambda: None
    return TestClient(app)


def test_publisher_identity_and_publication_bounds() -> None:
    assert PUBLIC_ISSUE_TOPICS == ("정치", "경제", "사회")
    assert publisher_identity("https://m.newsis.com/view/a") == "newsis.com"
    assert publisher_identity("https://www.etoday.co.kr/a") == "etoday.co.kr"
    assert publisher_identity("https://m.etoday.co.kr/b") == "etoday.co.kr"
    assert publisher_identity("https://news.naver.com/a") == publisher_identity("https://sports.naver.com/b")
    assert publisher_identity("javascript:alert(1)") is None
    now = utc_now()
    assert is_current_article(now - timedelta(days=7), now)
    assert not is_current_article(now - timedelta(days=7, microseconds=1), now)
    assert not is_current_article(now + timedelta(microseconds=1), now)
    assert not is_current_article(None, now)
    assert is_current_article(now.isoformat(), now)
    assert is_current_article(now.isoformat().replace("+00:00", "Z"), now)
    assert not is_current_article("invalid-date", now)
    assert not is_current_article((now + timedelta(days=1)).isoformat(), now)


@pytest.mark.parametrize("violation", ["legacy", "sports", "two_sources", "same_publisher", "expired", "future", "undated", "blocked_source", "unfetched"])
def test_memory_public_surfaces_fail_closed_together(violation: str) -> None:
    state = PlatformState()
    issue = next(iter(state.issues.values()))
    articles = [state.articles[article_id] for article_id in issue["article_ids"]]
    article_id = articles[0]["id"]
    client = _client(state)
    assert client.get("/api/v1/issues").json()["items"]
    if violation == "legacy":
        issue.pop("editorial_key", None)
    elif violation == "sports":
        issue["topic"] = "스포츠"
    elif violation == "two_sources":
        issue["article_ids"] = issue["article_ids"][:2]
    elif violation == "same_publisher":
        for index, article in enumerate(articles):
            article["canonical_url"] = f"https://sub{index}.same-news.co.kr/{index}"
    elif violation == "expired":
        articles[-1]["published_at"] = utc_now() - timedelta(days=8)
    elif violation == "future":
        articles[-1]["published_at"] = utc_now() + timedelta(days=1)
    elif violation == "undated":
        articles[-1]["published_at"] = None
    elif violation == "unfetched":
        articles[-1]["current_version_id"] = None
    else:
        state.sources[articles[-1]["source_id"]]["active"] = False
    for path in ("/issues", "/feed", "/visualization/points", "/visualization/points?type=source"):
        response = client.get("/api/v1" + path)
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
    for path in (f"/issues/{issue['id']}", f"/issues/{issue['id']}/articles", f"/articles/{article_id}", f"/articles/{article_id}/score", f"/articles/{article_id}/assessments", f"/articles/{article_id}/score-history"):
        assert client.get("/api/v1" + path).status_code == 404
    response = client.get(f"/api/v1/issues/{issue['id']}/comparison", params=[("article_ids", item["id"]) for item in articles[:2]])
    assert response.status_code == 404
    assert client.get("/api/v1/visualization/timeline", params={"entity_type": "article", "entity_id": article_id}).json()["snapshots"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("violation", ["legacy", "sports", "same_publisher", "expired", "future", "undated", "blocked_source", "unfetched"])
async def test_repository_rechecks_real_membership_coverage(violation: str) -> None:
    now = utc_now()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        issue = Issue(id=new_ulid(), title="정책 개편 논쟁", summary="정부안과 반대안의 비용 부담 논쟁", topic="정치", status=IssueStatus.ACTIVE, issue_kind=IssueKind.EVENT, editorial_key="daily-issue:test", opened_at=now, last_activity_at=now)
        session.add(issue)
        articles = []
        sources = []
        for index in range(3):
            url = f"https://publisher{index}.co.kr/report"
            source = Source(id=new_ulid(), name=f"Publisher {index}", source_type=SourceType.RSS, canonical_url=f"https://publisher{index}.co.kr/feed", active=True, policy_status=SourcePolicyStatus.APPROVED)
            article = Article(id=new_ulid(), source_id=source.id, canonical_url=url, canonical_url_hash=hashlib.sha256(url.encode()).digest(), title=f"정책 논쟁 {index}", published_at=now - timedelta(days=6), status=ArticleStatus.ACTIVE)
            session.add_all([source, article])
            articles.append(article)
            sources.append(source)
        await session.flush()
        for article in articles:
            version_id = new_ulid()
            session.add(ArticleVersion(id=version_id, article_id=article.id,
                                       content_hash=hashlib.sha256(article.id.encode()).digest(),
                                       normalized_text_ref="fixture://policy", fetched_at=now))
            await session.flush()
            article.current_version_id = version_id
            session.add(IssueMembership(issue_id=issue.id, article_id=article.id, confidence=1))
        await session.commit()
        repo = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
        rows = await repo.list_issue_rows()
        assert len(rows) == 1
        assert rows[0]["source_count"] == 3
        assert rows[0]["data_as_of"] == now - timedelta(days=6)
        assert len((await repo.issue_article_rows(issue.id)) or []) == 3
        assert await repo.article_view(articles[0].id) is not None
        with pytest.raises(ProductComparisonError, match="COMPARISON_NOT_READY"):
            await repo.issue_comparison_view(issue_id=issue.id, article_ids=[article.id for article in articles[:2]])
        if violation == "legacy":
            issue.editorial_key = None
        elif violation == "sports":
            issue.topic = "스포츠"
        elif violation == "same_publisher":
            for index, article in enumerate(articles):
                article.canonical_url = f"https://sub{index}.same-news.co.kr/{index}"
        elif violation == "expired":
            articles[-1].published_at = now - timedelta(days=8)
        elif violation == "future":
            articles[-1].published_at = now + timedelta(days=1)
        elif violation == "undated":
            articles[-1].published_at = None
        elif violation == "unfetched":
            articles[-1].current_version_id = None
        else:
            sources[-1].active = False
        await session.commit()
        assert await repo.list_issue_rows() == []
        assert await repo.issue_view(issue.id) is None
        assert await repo.issue_article_rows(issue.id) is None
        assert await repo.article_view(articles[0].id) is None
        assert await repo.assessment_view(articles[0].id) is None
        assert await repo.score_history(articles[0].id) is None
        assert await repo.current_score(articles[0].id) is None
        assert await repo.issue_comparison_view(issue_id=issue.id, article_ids=[article.id for article in articles[:2]]) is None
        assert await repo.feed_items(user_id=None, personalized_requested=False) == ([], False)
        assert await repo.visualization_rows(entity_type="article", issue_id=None, user_id=None) == []
    await engine.dispose()
