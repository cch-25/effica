"""Explicit fictional member fixture, installed once without replacing real users."""
from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from apps.api.app.db.enums import (
    ArticleStatus,
    CreditStatus,
    ProfileKind,
    QuestionnaireKind,
    ReadSessionStatus,
    UserRole,
    UserStatus,
    VoteQualityStatus,
)
from apps.api.app.db.models import (
    Article,
    ConsentVersion,
    CreditLedger,
    EfficacyResponse,
    Job,
    QuestionnaireResponse,
    QuestionnaireVersion,
    ReadSession,
    User,
    UserConsent,
    UserProfile,
    Vote,
)
from apps.api.app.domains.users import (
    POLITICAL_QUESTIONNAIRE_VERSION,
    political_questionnaire_schema,
    political_questionnaire_scoring,
    score_political_questionnaire,
)
from apps.api.app.jobs.types import resolved_job_priority
from apps.api.app.state import new_id, stable_hash, utcnow

if TYPE_CHECKING:
    from apps.api.app.jobs.types import resolved_job_priority
    from apps.api.app.repositories.platform import MariaDBPlatformRepository
from apps.api.app.state import PlatformState

DEMO_USER_ID = "01K5000000000000000000DE00"
DEMO_NAME = "성실한 독자 (데모)"


def demo_answers() -> dict[str, int]:
    # Economics +65, social -30, international -20. All 30 answers are valid.
    offsets = {"x": [2] * 3 + [1] * 7, "y": [-1] * 6 + [0] * 4,
               "z": [-1] * 4 + [0] * 6}
    indices = {"x": 0, "y": 0, "z": 0}
    answers = {}
    for question in political_questionnaire_schema()["questions"]:
        axis = question["axis"]
        answers[question["id"]] = 3 + offsets[axis][indices[axis]] * question["direction"]
        indices[axis] += 1
    return answers


def demo_profile() -> dict:
    score = score_political_questionnaire(schema_json=political_questionnaire_schema(),
                                         scoring_json=political_questionnaire_scoring(),
                                         answers=demo_answers())
    return {"x": score.x, "y": score.y, "z": score.z, "confidence": score.confidence}


def activity_rows(article_ids: list[str], now):
    """Eight weeks of labeled sample activity; article identities remain real."""
    if not article_ids:
        return
    for index in range(max(48, len(article_ids))):
        yield article_ids[index % len(article_ids)], now - timedelta(
            days=55 - index * 54 / max(47, len(article_ids) - 1)), index


async def ensure_demo_account(repo: MariaDBPlatformRepository) -> str:
    session = repo.session
    now = utcnow()
    # Upsert the fixed member and lock it so concurrent first logins seed once.
    bind = session.get_bind() if hasattr(session, "get_bind") else session._session.bind
    values = dict(id=DEMO_USER_ID, role=UserRole.MEMBER, status=UserStatus.ACTIVE,
                  display_name=DEMO_NAME, created_at=now - timedelta(days=56))
    if bind.dialect.name == "sqlite":
        statement = sqlite_insert(User).values(**values).on_conflict_do_nothing(index_elements=["id"])
    else:
        statement = mysql_insert(User).values(**values).on_duplicate_key_update(id=User.id)
    await session.execute(statement)
    user = await session.scalar(select(User).where(User.id == DEMO_USER_ID).with_for_update())
    if user.status != UserStatus.ACTIVE or user.role != UserRole.MEMBER:
        raise PermissionError("DEMO_ACCOUNT_UNAVAILABLE")
    seeded = await session.scalar(select(QuestionnaireResponse.id).where(
        QuestionnaireResponse.user_id == DEMO_USER_ID).limit(1))
    if seeded:
        return DEMO_USER_ID
    articles = list((await session.scalars(select(Article).where(
        Article.status == ArticleStatus.ACTIVE).order_by(Article.published_at.desc(),
        Article.id.desc()).limit(48).with_for_update())).all())
    article_by_id = {article.id: article for article in articles}
    if not articles:
        raise ValueError("DEMO_CONTENT_UNAVAILABLE")
    versions = list((await session.scalars(select(QuestionnaireVersion))).all())
    political = next(v for v in versions if v.kind == QuestionnaireKind.ONBOARDING
                     and v.version == POLITICAL_QUESTIONNAIRE_VERSION)
    efficacy = max((v for v in versions if v.kind == QuestionnaireKind.EFFICACY),
                   key=lambda v: (v.active_from, v.id))
    consents = list((await session.scalars(select(ConsentVersion).order_by(
        ConsentVersion.active_from.desc(), ConsentVersion.id.desc()))).all())
    purposes = set()
    for consent in consents:
        if consent.purpose in purposes:
            continue
        purposes.add(consent.purpose)
        session.add(UserConsent(id=new_id(), user_id=DEMO_USER_ID,
                               consent_version_id=consent.id, granted_at=now - timedelta(days=56)))
    response_id = new_id()
    session.add(QuestionnaireResponse(id=response_id, user_id=DEMO_USER_ID,
        questionnaire_version_id=political.id, submitted_at=now - timedelta(days=56),
        encrypted_payload=repo._encrypt_answers(demo_answers(), aad=response_id.encode())))
    session.add(UserProfile(id=new_id(), user_id=DEMO_USER_ID, kind=ProfileKind.SELF_REPORTED,
        **demo_profile(), source_version=political.version, active=True,
        created_at=now - timedelta(days=56)))
    for week, value in enumerate([42, 48, 55, 61, 67, 72, 78, 84]):
        session.add(EfficacyResponse(id=new_id(), user_id=DEMO_USER_ID,
            questionnaire_version_id=efficacy.id, normalized_score=value,
            submitted_at=now - timedelta(days=49 - week * 7)))
    voted = set()
    for article_id, at, index in activity_rows([article.id for article in articles], now):
        article = article_by_id[article_id]
        if article.published_at:
            at = max(at, min(article.published_at + timedelta(minutes=5), now))
        read_id = new_id()
        session.add(ReadSession(id=read_id, user_id=DEMO_USER_ID, article_id=article_id,
            article_key=article_id, token_hash=hashlib.sha256(read_id.encode()).digest(),
            expires_at=at + timedelta(hours=1), status=ReadSessionStatus.ELIGIBLE,
            outbound_at=at, returned_at=at + timedelta(minutes=3), client_elapsed_ms=180000,
            policy_version="demo-read-v1"))
        session.add(CreditLedger(id=new_id(), user_id=DEMO_USER_ID,
            event_type="QUALIFIED_READ", event_key=f"read:{read_id}", delta=12,
            policy_version="demo-read-v1", status=CreditStatus.POSTED, created_at=at))
        if article_id not in voted:
            voted.add(article_id)
            article.vote_revision += 1
            revision = article.vote_revision
            session.add(Job(id=new_id(), job_type="aggregate_votes",
                dedupe_key=f"{article_id}:{revision}",
                priority=resolved_job_priority("aggregate_votes"),
                payload_json={"article_id": article_id, "version": revision}))
            session.add(Vote(id=new_id(), user_id=DEMO_USER_ID, article_id=article_id,
                revision=revision, x=25 + index % 7 * 8, y=-20 + index % 5 * 10,
                z=-10 + index % 4 * 10, sensationalism=15 + index % 6 * 5,
                quality_status=VoteQualityStatus.QUALIFIED, active=True,
                created_at=at, updated_at=at))
            session.add(CreditLedger(id=new_id(), user_id=DEMO_USER_ID,
                event_type="QUALIFIED_VOTE", event_key=f"vote:{article_id}", delta=10,
                policy_version="demo-vote-v1", status=CreditStatus.POSTED, created_at=at))
    # Caller rotates the session and commits this fixture atomically.
    await session.flush()
    return DEMO_USER_ID


def ensure_memory_demo_account(state: PlatformState) -> str:
    with state.lock:
        if DEMO_USER_ID in state.users:
            if state.users[DEMO_USER_ID]["status"] != "ACTIVE":
                raise PermissionError("DEMO_ACCOUNT_UNAVAILABLE")
            return DEMO_USER_ID
        now = utcnow()
        state.users[DEMO_USER_ID] = dict(id=DEMO_USER_ID, display_name=DEMO_NAME,
            role="MEMBER", status="ACTIVE", consent_complete=True, onboarding_complete=True,
            behavioral_profile_active=False, created_at=now - timedelta(days=56))
        for consent_id in state.consents:
            state.consent_grants[(DEMO_USER_ID, consent_id)] = True
        profile_id = new_id()
        state.profiles[profile_id] = dict(id=profile_id, profile_id=profile_id,
            user_id=DEMO_USER_ID, kind="SELF_REPORTED", **demo_profile(), sensationalism=None,
            source_version=POLITICAL_QUESTIONNAIRE_VERSION, active=True,
            created_at=now - timedelta(days=56))
        questionnaire_id = next(v["id"] for v in state.questionnaires.values() if v["kind"] == "efficacy")
        state.efficacy[DEMO_USER_ID] = [dict(id=new_id(), questionnaire_version_id=questionnaire_id,
            normalized_score=value, submitted_at=now - timedelta(days=49 - week * 7))
            for week, value in enumerate([42, 48, 55, 61, 67, 72, 78, 84])]
        ledger = state.credits[DEMO_USER_ID] = []
        for article_id, at, index in activity_rows(list(state.articles)[:48], now):
            read_id = new_id()
            state.read_sessions[read_id] = dict(id=read_id, user_id=DEMO_USER_ID,
                article_id=article_id, status="ELIGIBLE", outbound_at=at,
                returned_at=at + timedelta(minutes=3), expires_at=at + timedelta(hours=1),
                policy_version="demo-read-v1", token_hash=stable_hash(read_id))
            ledger.append(dict(id=new_id(), event_type="QUALIFIED_READ", event_key=f"read:{read_id}",
                delta=12, policy_version="demo-read-v1", status="POSTED", created_at=at))
            if (DEMO_USER_ID, article_id) not in state.votes:
                state.votes[(DEMO_USER_ID, article_id)] = [dict(id=new_id(), revision=1,
                    x=25 + index % 7 * 8, y=-20 + index % 5 * 10, z=-10 + index % 4 * 10,
                    sensationalism=15 + index % 6 * 5, quality_status="QUALIFIED", active=True,
                    created_at=at, updated_at=at)]
                ledger.append(dict(id=new_id(), event_type="QUALIFIED_VOTE", event_key=f"vote:{article_id}",
                    delta=10, policy_version="demo-vote-v1", status="POSTED", created_at=at))
        return DEMO_USER_ID
