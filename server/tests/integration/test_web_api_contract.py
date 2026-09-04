from fastapi.testclient import TestClient

from apps.api.app.api.v1.schemas import (
    ArticleView,
    FeedPage,
    IssuePage,
    VisualizationPointPage,
)
from apps.api.app.main import app


def test_web_read_endpoints_match_the_published_dto_contracts() -> None:
    with TestClient(app) as client:
        feed_response = client.get("/api/v1/feed")
        assert feed_response.status_code == 200
        feed = FeedPage.model_validate(feed_response.json())
        assert feed.items

        issues_response = client.get("/api/v1/issues")
        assert issues_response.status_code == 200
        issues = IssuePage.model_validate(issues_response.json())
        assert issues.items

        article_response = client.get(f"/api/v1/articles/{feed.items[0].article_id}")
        assert article_response.status_code == 200
        article = ArticleView.model_validate(article_response.json())
        assert article.id == feed.items[0].article_id

        points_response = client.get("/api/v1/visualization/points")
        assert points_response.status_code == 200
        points = VisualizationPointPage.model_validate(points_response.json())
        assert points.items
        assert {point.entity_type for point in points.items} == {"article"}
