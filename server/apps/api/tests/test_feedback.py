from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.api.v1.dependencies import get_state
from apps.api.app.api.v1.feedback import feedback_session, router
from apps.api.app.core.config import Settings, get_settings
from apps.api.app.core.errors import install_error_handlers
from apps.api.app.db.models import FeedbackEntry
from apps.api.app.state import PlatformState


@pytest.fixture(params=["memory", "sqlite"])
def client(request, tmp_path):
    app = FastAPI()
    app.include_router(router)
    install_error_handlers(app)
    state = PlatformState()
    app.dependency_overrides[get_state] = lambda: state
    app.dependency_overrides[get_settings] = lambda: Settings(app_backend="memory")

    async def database_session():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'feedback.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(FeedbackEntry.__table__.create, checkfirst=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                yield session
        finally:
            await engine.dispose()

    if request.param == "sqlite":
        app.dependency_overrides[feedback_session] = database_session
    with TestClient(app) as test_client:
        yield test_client


def payload(**changes):
    return {"name": "독자", "content": "여러 관점을 비교할 수 있어 좋아요.", "submission_key": str(uuid4()), **changes}


def test_public_feedback_persists_across_requests_and_retries(client):
    body = payload(name="  첫 독자  ", content="한" * 200)
    created = client.post("/api/v1/feedback", json=body)
    assert created.status_code == 201
    assert created.json()["name"] == "첫 독자"
    assert "submission_key" not in created.json()
    assert client.post("/api/v1/feedback", json=body).json() == created.json()
    conflict = client.post("/api/v1/feedback", json={**body, "content": "다른 글"})
    assert conflict.status_code == 409
    page = client.get("/api/v1/feedback")
    assert page.headers["cache-control"] == "no-store"
    assert page.json() == {"items": [created.json()], "next_cursor": None}


@pytest.mark.parametrize("changes", [{"name": "   "}, {"content": "\n "}, {"name": "가" * 31}, {"content": "가" * 201}, {"content": "😀" * 201}])
def test_feedback_rejects_empty_or_oversized_values(client, changes):
    assert client.post("/api/v1/feedback", json=payload(**changes)).status_code == 422
    assert client.get("/api/v1/feedback").json()["items"] == []


def test_feedback_counts_unicode_and_rejects_foreign_browser_origins(client):
    body = payload(content="😀" * 200)
    assert client.post("/api/v1/feedback", json=body, headers={"Origin": "https://other.example"}).status_code == 403
    assert client.post("/api/v1/feedback", json=body).status_code == 201


def test_feedback_pagination_has_no_missing_or_repeated_entries(client):
    ids = {client.post("/api/v1/feedback", json=payload()).json()["id"] for _ in range(5)}
    seen = []
    cursor = ""
    while True:
        page = client.get("/api/v1/feedback", params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == sorted(ids, reverse=True)
    assert client.get("/api/v1/feedback?limit=51").status_code == 422
    assert client.get("/api/v1/feedback?cursor=bad").status_code == 422
