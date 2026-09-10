from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.worker.worker.daily_scheduler import MariaDBDailyIssueScheduler
from apps.worker.worker.main import WorkerRuntime
from apps.worker.worker.queue import Job
from apps.worker.worker.services import MariaDBResultApplier

NOW = datetime(2026, 9, 10, 7, tzinfo=UTC)


def test_daily_scheduler_runs_through_the_actual_worker_loop():
    async def scenario():
        calls = []

        class Database:
            async def execute(self, statement, params):
                calls.append(params["key"])
                runtime.stop_event.set()
                return SimpleNamespace(rowcount=1)

        scheduler = MariaDBDailyIssueScheduler(lambda: Database(), clock=lambda: NOW)
        runtime = WorkerRuntime(SimpleNamespace(), crawl_scheduler=scheduler)
        await asyncio.wait_for(runtime._crawl_scheduler_loop(), timeout=1)
        assert calls == ["daily-issues:2026-09-10"]
        assert scheduler.interval_seconds == 60
    asyncio.run(scenario())


def test_daily_scheduler_deduplicates_concurrent_workers_and_restarts_at_kst_boundary():
    class Database:
        def __init__(self):
            self.jobs = {}

        async def execute(self, statement, params):
            assert "ON DUPLICATE KEY UPDATE" in str(statement)
            assert "0, 1, :payload" in str(statement)  # No paid automatic retry.
            await asyncio.sleep(0)
            inserted = params["key"] not in self.jobs
            self.jobs.setdefault(params["key"], dict(params))
            return SimpleNamespace(rowcount=int(inserted))

    async def scenario():
        db = Database()
        before = datetime(2026, 9, 9, 14, 59, 59, tzinfo=UTC)
        workers = [MariaDBDailyIssueScheduler(lambda: db, clock=lambda: before)
                   for _ in range(3)]
        assert sum(await asyncio.gather(*(worker.tick(str(i))
                   for i, worker in enumerate(workers)))) == 1
        restarted = MariaDBDailyIssueScheduler(lambda: db, clock=lambda: before)
        assert await restarted.tick("restarted") == 0
        after = MariaDBDailyIssueScheduler(
            lambda: db, clock=lambda: before + timedelta(seconds=1),
        )
        assert await after.tick("next-day") == 1
        assert set(db.jobs) == {"daily-issues:2026-09-09", "daily-issues:2026-09-10"}
        assert len({row["id"] for row in db.jobs.values()}) == 2
        for key, row in db.jobs.items():
            assert json.loads(row["payload"])["run_date"] == key.removeprefix("daily-issues:")

    asyncio.run(scenario())


def article(number: int, *, event: str = "tax"):
    return {
        "article_id": f"{event}-{number}",
        "article_version_id": f"v-{event}-{number}",
        "canonical_url": f"https://publisher-{number}.co.kr/{event}/123456",
        "source_id": f"source-{number}",
        "title": f"국회 세금 정책 개편 여야 논쟁 {number}",
        "content": "새로운 세금 정책에 대해 여당과 야당이 상반된 입장을 제시했다. " * 100,
        "published_at": NOW - timedelta(hours=number),
    }


def issue(count=3, *, event="tax"):
    return {"title": f"세금 정책 {event} 논쟁", "issue_key": event, "topic": "경제",
            "controversy_reason": "세금 부담과 재정 효과에 대한 여야의 견해가 대립한다.",
            "articles": [article(i, event=event) for i in range(count)]}


class EditorialSession:
    def __init__(self, *, reject_persistence=False):
        self.statements = []
        self.articles = {}
        self.memberships = {}
        self.reject_persistence = reject_persistence
        self.prior_rows = []

    async def execute(self, statement, params):
        sql = " ".join(str(statement).split())
        values = dict(params)
        self.statements.append((sql, values))
        if sql.startswith("SELECT i.id AS issue_id"):
            return self.prior_rows
        if sql.startswith("INSERT INTO articles"):
            self.articles[params["url_hash"]] = {
                "id": params["id"], "article_id": params["id"],
                "published_at": params["published_at"],
                "canonical_url": params["url"], "source_url": params["url"],
                "source_id": params["source_id"], "title": params["title"],
                "content": "기사 본문입니다. " * 100,
            }
        if sql.startswith("SELECT id FROM articles"):
            return [self.articles[params["url_hash"]]]
        if sql.startswith("UPDATE articles SET current_version_id"):
            for row in self.articles.values():
                if row["id"] == params["article_id"]:
                    row["article_version_id"] = params["version_id"]
        if sql.startswith("SELECT a.id, a.published_at"):
            return [] if self.reject_persistence else [self.articles[params["hash"]]]
        if sql.startswith("DELETE FROM issue_memberships"):
            self.memberships[params["id"]] = []
        if sql.startswith("INSERT INTO issue_memberships"):
            self.memberships[params["issue_id"]].append(params["article_id"])
        if sql.startswith("SELECT a.id AS article_id"):
            return [row for row in self.articles.values()
                    if row["id"] in self.memberships.get(params["issue_id"], [])]
        return []

    def writes(self, prefix):
        return [params for sql, params in self.statements if sql.startswith(prefix)]


def applier():
    instance = MariaDBResultApplier(lambda: None)

    async def store_blob(_session, payload, **_kwargs):
        return hashlib.sha256(payload).hexdigest()[:26]

    async def no_keyword_cluster(*_args, **_kwargs):
        raise AssertionError("curated events must never use lexical clustering or topic buckets")

    async def comparisons(_session, **_kwargs):
        return None

    instance._store_blob = store_blob
    instance._rolling_cluster_ids = no_keyword_cluster
    instance._upsert_topic_membership = no_keyword_cluster
    instance._enqueue_issue_comparisons_for_article = comparisons
    return instance


@pytest.mark.parametrize("invalid", ["two_sources", "same_publisher", "taxonomy",
                                      "no_controversy", "future", "stale", "unknown_date",
                                      "malformed_date"])
def test_discovery_rejects_ineligible_events_without_retiring_previous_edition(invalid):
    candidate = issue()
    if invalid == "two_sources":
        candidate["articles"] = candidate["articles"][:2]
    elif invalid == "same_publisher":
        for i, row in enumerate(candidate["articles"]):
            row["canonical_url"] = f"https://desk-{i}.same-publisher.co.kr/story/{i}"
    elif invalid == "taxonomy":
        candidate["topic"] = "스포츠"
    elif invalid == "no_controversy":
        candidate.pop("controversy_reason")
    else:
        candidate["articles"][0]["published_at"] = {
            "future": NOW + timedelta(seconds=1),
            "stale": NOW - timedelta(days=7, seconds=1),
            "unknown_date": None,
            "malformed_date": "not-a-date",
        }[invalid]
    session = EditorialSession()
    asyncio.run(applier()._apply_discover_issues(
        session, Job(id="daily", job_type="discover_issues", payload={}),
        {"issues": [candidate]}, NOW,
    ))
    assert session.statements == []


@pytest.mark.parametrize("result", [{"status": "FAILED"}, {"status": "SKIPPED"}, {"issues": []}])
def test_unsuccessful_discovery_keeps_previous_edition(result):
    session = EditorialSession()
    asyncio.run(applier()._apply_discover_issues(
        session, Job(id="daily", job_type="discover_issues", payload={}), result, NOW,
    ))
    assert session.statements == []


def test_discovery_persistence_failure_never_archives_previous_edition():
    session = EditorialSession(reject_persistence=True)
    asyncio.run(applier()._apply_discover_issues(
        session, Job(id="daily", job_type="discover_issues", payload={}),
        {"issues": [issue()]}, NOW,
    ))
    assert session.writes("INSERT INTO articles")
    assert not session.writes("INSERT INTO issues")
    assert not session.writes("UPDATE issues SET status='archived'")


def test_discovery_keeps_exact_event_memberships_and_schedules_every_member_analysis():
    session = EditorialSession()
    first, second = issue(5), issue(3, event="budget")
    # Provider JSON dates must survive the persistence boundary.
    for row in first["articles"] + second["articles"]:
        row["published_at"] = row["published_at"].isoformat()
    asyncio.run(applier()._apply_discover_issues(
        session, Job(id="daily", job_type="discover_issues", payload={}),
        {"issues": [first, second]}, NOW,
    ))
    saved = session.writes("INSERT INTO issues")
    assert [row["priority"] for row in saved] == [1, 2]
    assert session.memberships[saved[0]["id"]] == [f"tax-{i}" for i in range(5)]
    assert session.memberships[saved[1]["id"]] == [f"budget-{i}" for i in range(3)]
    jobs = session.writes("INSERT INTO jobs")
    assert {json.loads(row["payload_json"])["article_version_id"] for row in jobs} == {
        f"v-tax-{i}" for i in range(5)
    } | {f"v-budget-{i}" for i in range(3)}
    assert all(row["job_type"] == "analyze" for row in jobs)
    assert session.writes("UPDATE issues SET status='archived'") == [
        {"id0": saved[0]["id"], "id1": saved[1]["id"]}
    ]


def test_daily_edition_has_at_most_five_distinct_events():
    session = EditorialSession()
    candidates = [issue(event=f"event-{i}") for i in range(6)]
    asyncio.run(applier()._apply_discover_issues(
        session, Job(id="daily", job_type="discover_issues", payload={}),
        {"issues": candidates}, NOW,
    ))
    assert [row["priority"] for row in session.writes("INSERT INTO issues")] == [1, 2, 3, 4, 5]
    assert len(session.articles) == 15
    assert not any(row["article_id"].startswith("event-5-") for row in session.articles.values())


def test_unrelated_sports_article_gets_no_public_topic_bucket():
    session = EditorialSession()
    asyncio.run(MariaDBResultApplier(lambda: None)._upsert_topic_membership(
        session, article_id="sports", title="프로야구 KBO 시즌 개막",
        summary="경기 일정과 점수 안내", now=NOW,
    ))
    assert session.statements == []


def test_new_edition_keeps_valid_previous_events_without_refreshing_dates():
    session = EditorialSession()
    for event in ["expired", "duplicate", "ongoing", "second", "third", "fourth", "overflow"]:
        for i in range(3):
            session.prior_rows.append({
                "issue_id": event, "article_id": f"{event}-{i}",
                "canonical_url": f"https://paper-{0 if event == 'duplicate' else i}.kr/{event}",
                "published_at": NOW - timedelta(days=8 if event == "expired" else 2),
                "created_at": NOW - timedelta(days=2),
            })
    asyncio.run(applier()._apply_discover_issues(
        session, Job(id="daily", job_type="discover_issues", payload={}), {"issues": [issue()]}, NOW,
    ))
    assert session.writes("UPDATE issues SET editorial_priority") == [
        {"id": event, "priority": i + 2} for i, event in enumerate(["ongoing", "second", "third", "fourth"])
    ]
    retained = session.writes("UPDATE issues SET status='archived'")[0]
    assert len(retained) == 5
    assert {retained[f"id{i}"] for i in range(1, 5)} == {"ongoing", "second", "third", "fourth"}
    # No UPDATE of their dates, content, issue version or comparison review.
    assert all("last_activity_at" not in sql and "version=" not in sql for sql, _ in session.statements
               if sql.startswith("UPDATE issues SET editorial_priority"))


def test_persistence_caps_ordinary_articles_at_five_and_extra_context_at_eight():
    for extra_context, expected in [(False, 5), (True, 8)]:
        candidate = issue(10)
        if extra_context:
            for a in candidate["articles"]:
                a["additional_context"] = "앞선 보도에 없는 지방 재정 부담에 관한 본문 근거를 추가한다."
        session = EditorialSession()
        asyncio.run(applier()._apply_discover_issues(
            session, Job(id="daily", job_type="discover_issues", payload={}), {"issues": [candidate]}, NOW,
        ))
        assert len(session.articles) == expected
