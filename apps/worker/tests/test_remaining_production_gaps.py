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
