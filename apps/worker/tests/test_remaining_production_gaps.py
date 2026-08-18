from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from apps.worker.worker.queue import Job, MariaDBQueueRepository
from apps.worker.worker.services import MariaDBResultApplier


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _MergeSession:
    def __init__(self) -> None:
        self.issues = {"source": {"id": "source", "title": "Source", "summary": "Summary"}}
        self.memberships = [{"issue_id": "source", "article_id": "article", "confidence": 0.8}]
        self.statements: list[tuple[str, dict]] = []

    async def execute(self, statement, params):
        query = str(statement).lower()
        self.statements.append((query, dict(params)))
        if "select id, title, summary" in query:
            return _Rows([self.issues["source"]])
        if "select id" in query and "from issues" in query:
            return _Rows([{"id": params["target_id"]}]) if params["target_id"] in self.issues else _Rows([])
        if "insert into issues" in query:
            self.issues[params["target_id"]] = {
                "id": params["target_id"],
                "title": params["title"],
                "summary": params["summary"],
            }
            return _Rows([])
        if "insert into issue_memberships" in query:
            self.memberships.append(
                {"issue_id": "target", "article_id": "article", "confidence": 0.8}
            )
            return _Rows([])
        if "delete from issue_memberships" in query:
            self.memberships = [row for row in self.memberships if row["issue_id"] != "source"]
        return _Rows([])


def test_d11_worker_merge_creates_missing_target_before_moving_memberships() -> None:
    async def scenario() -> None:
        session = _MergeSession()
        applier = MariaDBResultApplier(lambda: None)
        await applier._apply_merge_issue(
            session,
            Job(
                id="merge-job",
                job_type="merge_issue",
                payload={"source_issue_id": "source", "target_issue_id": "target"},
            ),
            {"source_issue_id": "source", "target_issue_id": "target"},
            datetime.now(UTC),
        )

        assert session.issues["target"]["title"] == "Source"
        assert session.memberships == [
            {"issue_id": "target", "article_id": "article", "confidence": 0.8}
        ]
        insert_index = next(
            index for index, (query, _) in enumerate(session.statements) if "insert into issues" in query
        )
        membership_index = next(
            index
            for index, (query, _) in enumerate(session.statements)
            if "insert into issue_memberships" in query
        )
        assert insert_index < membership_index

    asyncio.run(scenario())


def test_wq012_reaper_matches_canonical_and_payload_crawl_run_ids() -> None:
    async def scenario() -> None:
        statements = []

        class Session:
            async def execute(self, statement, params):
                statements.append((str(statement), dict(params)))
                return _Rows([])

        repository = MariaDBQueueRepository(lambda: None, table_name="jobs")
        moment = datetime(2026, 1, 1, tzinfo=UTC)
        await repository._mark_exhausted_crawl_runs(
            Session(), moment=moment, last_error_json='{"code":"MAX_ATTEMPTS_EXHAUSTED"}'
        )

        assert len(statements) == 1
        query = statements[0][0]
        assert "id IN" in query
        assert "JSON_EXTRACT(payload_json, '$.crawl_run_id')" in query
        assert "JSON_UNQUOTE" in query
        assert statements[0][1]["now"] == moment

    asyncio.run(scenario())


def test_crawl_fail_updates_only_pending_or_running_runs() -> None:
    statements: list[str] = []

    class Result:
        def __init__(self, rows=None, rowcount=0):
            self._rows = list(rows or [])
            self.rowcount = rowcount

        def mappings(self):
            return self

        def all(self):
            return list(self._rows)

        def first(self):
            return self._rows[0] if self._rows else None

    class Session:
        async def execute(self, statement, params):
            query = str(statement)
            statements.append(query)
            lowered = query.lower()
            if "select" in lowered and "from jobs" in lowered:
                return Result(
                    [
                        {
                            "id": "job-1",
                            "job_type": "crawl",
                            "payload_json": {"crawl_run_id": "run-1"},
                            "status": "LEASED",
                            "dedupe_key": None,
                            "priority": 0,
                            "available_at": moment,
                            "lease_owner": "worker-1",
                            "lease_expires_at": moment,
                            "attempts": 1,
                            "max_attempts": 3,
                            "last_error_json": None,
                            "created_at": moment,
                            "updated_at": moment,
                        }
                    ]
                )
            return Result(rowcount=1)

        async def close(self):
            return None

    moment = datetime(2026, 1, 1, tzinfo=UTC)

    async def scenario() -> None:
        repository = MariaDBQueueRepository(lambda: Session(), table_name="jobs")
        await repository.fail(
            "job-1",
            "worker-1",
            {"code": "SOURCE_FETCH_FAILED", "message": "boom"},
            retryable=False,
            now=moment,
        )

    asyncio.run(scenario())
    crawl_updates = [query for query in statements if "update crawl_runs" in query.lower()]
    assert len(crawl_updates) == 1
    assert "status IN ('PENDING', 'RUNNING')" in crawl_updates[0]


def test_export_records_lookup_covers_oauth_sessions_and_impressions_without_secrets() -> None:
    queries: list[str] = []

    class Result:
        def mappings(self):
            return self

        def all(self):
            return []

        def first(self):
            return None

    class Session:
        async def execute(self, statement, params):
            queries.append(str(statement))
            return Result()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    async def scenario() -> None:
        from apps.worker.worker.lookups import MariaDBWorkerLookups

        lookups = MariaDBWorkerLookups(lambda: Session(), encryption_secret="unit-test-secret")
        records = await lookups.export_records_lookup("user-1")
        assert "oauth_accounts" in records
        assert "sessions" in records
        assert "feed_impressions" in records

    asyncio.run(scenario())
    sql = "\n".join(queries)
    assert "FROM oauth_accounts" in sql
    assert "provider_subject" in sql
    assert "FROM sessions" in sql
    assert "token_hash" in sql
    assert "expires_at" in sql
    assert "revoked_at" in sql
    assert "FROM feed_impressions" in sql
    for secret in ("access_token", "refresh_token", "session_token", "raw_token", "secret"):
        assert secret not in sql.lower().replace("encryption_secret", "")


def test_vote_snapshot_lookup_returns_latest_revision_and_as_service_binding() -> None:
    class Result:
        def mappings(self):
            return self

        def first(self):
            return {
                "article_id": "article-1",
                "version": 7,
                "aggregate_json": '{"x": 1}',
                "segment_json": '{"all": {"count": 7}}',
                "created_at": datetime(2026, 1, 1, tzinfo=UTC),
            }

    queries: list[str] = []

    class Session:
        async def execute(self, statement, params):
            queries.append(str(statement))
            return Result()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    async def scenario() -> None:
        from apps.worker.worker.lookups import MariaDBWorkerLookups

        lookups = MariaDBWorkerLookups(lambda: Session(), encryption_secret="unit-test-secret")
        snapshot = await lookups.vote_snapshot_lookup("article-1")
        assert snapshot is not None
        assert snapshot["version"] == 7
        assert snapshot["vote_revision"] == 7
        assert snapshot["aggregate"] == {"x": 1}
        assert snapshot["segments"] == {"all": {"count": 7}}
        assert lookups.as_services()["vote_snapshot_lookup"] == lookups.vote_snapshot_lookup

    asyncio.run(scenario())
    assert "FROM vote_aggregate_snapshots" in queries[0]
    assert "ORDER BY version DESC" in queries[0]
