"""Public guestbook with bounded input, cursor pagination and retry-safe writes."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.api.v1.dependencies import get_state
from apps.api.app.core.config import Settings, get_settings
from apps.api.app.core.errors import COMMON_ERROR_RESPONSES, ApiError
from apps.api.app.db.models import FeedbackEntry
from apps.api.app.db.ulid import new_ulid
from apps.api.app.db.utc import utc_now
from apps.api.app.state import PlatformState

router = APIRouter(prefix="/api/v1/feedback", responses=COMMON_ERROR_RESPONSES)


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    submission_key: UUID


class FeedbackView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    content: str
    created_at: datetime


class FeedbackPage(BaseModel):
    items: list[FeedbackView]
    next_cursor: str | None


async def feedback_session(
    settings: Settings = Depends(get_settings),
) -> AsyncIterator[AsyncSession | None]:
    if settings.app_backend == "memory":
        yield None
        return
    from apps.api.app.db.session import get_session

    async for session in get_session():
        yield session


def check_replay(entry: FeedbackView, payload: FeedbackCreate) -> FeedbackView:
    if entry.name != payload.name or entry.content != payload.content:
        raise ApiError(409, "FEEDBACK_CONFLICT", "작성 내용이 변경되었습니다. 다시 등록해 주세요.")
    return entry


@router.get("", response_model=FeedbackPage, operation_id="list_feedback")
async def list_feedback(
    response: Response,
    cursor: str | None = Query(default=None, pattern=r"^[0-9A-HJKMNP-TV-Z]{26}$"),
    limit: int = Query(default=20, ge=1, le=50),
    session: AsyncSession | None = Depends(feedback_session),
    state: PlatformState = Depends(get_state),
) -> FeedbackPage:
    response.headers["Cache-Control"] = "no-store"
    if session is None:
        with state.lock:
            rows = sorted(state.feedback.values(), key=lambda row: row["id"], reverse=True)
            items = [FeedbackView.model_validate(row) for row in rows if not cursor or row["id"] < cursor][:limit + 1]
    else:
        statement = select(FeedbackEntry).order_by(FeedbackEntry.id.desc()).limit(limit + 1)
        if cursor:
            statement = statement.where(FeedbackEntry.id < cursor)
        items = [FeedbackView.model_validate(row) for row in (await session.scalars(statement)).all()]
    return FeedbackPage(items=items[:limit], next_cursor=items[limit - 1].id if len(items) > limit else None)


@router.post("", response_model=FeedbackView, status_code=201, operation_id="create_feedback")
async def create_feedback(
    payload: FeedbackCreate,
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession | None = Depends(feedback_session),
    state: PlatformState = Depends(get_state),
) -> FeedbackView:
    # Anonymous JSON writes carry no account authority. Reject foreign browser
    # origins without requiring a login or a session-bound CSRF token.
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != settings.web_base_url.rstrip("/"):
        raise ApiError(403, "ORIGIN_INVALID", "이 사이트에서 피드백을 작성해 주세요.")
    key = str(payload.submission_key)
    if session is None:
        with state.lock:
            if key in state.feedback:
                return check_replay(FeedbackView.model_validate(state.feedback[key]), payload)
            row = dict(id=new_ulid(), name=payload.name, content=payload.content, created_at=utc_now())
            state.feedback[key] = row
            return FeedbackView.model_validate(row)
    statement = select(FeedbackEntry).where(FeedbackEntry.submission_key == key)
    existing = await session.scalar(statement)
    if existing:
        return check_replay(FeedbackView.model_validate(existing), payload)
    entry = FeedbackEntry(id=new_ulid(), submission_key=key, name=payload.name, content=payload.content, created_at=utc_now())
    session.add(entry)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(statement)
        if existing is None:
            raise
        return check_replay(FeedbackView.model_validate(existing), payload)
    return FeedbackView.model_validate(entry)
