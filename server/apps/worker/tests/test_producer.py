from __future__ import annotations

import asyncio

from apps.api.app.jobs.producer import MariaDBJobProducer


class _Result:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _Transaction:
    entered = 0

    async def __aenter__(self):
        type(self).entered += 1
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Session:
    def __init__(self):
        self.calls = []
        self._transaction = _Transaction()

    def begin(self):
        # A real AsyncSession returns an async context manager here.  It must
        # not be awaited and then entered a second time.
        return self._transaction

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        return _Result(None if len(self.calls) == 1 else {"id": params.get("job_type") and "01PRODUCED"})

    async def close(self):
        return None


def test_mariadb_producer_enters_async_transaction_once() -> None:
    async def scenario() -> None:
        _Transaction.entered = 0
        session = _Session()
        producer = MariaDBJobProducer(lambda: session)
        submission = await producer.enqueue(
            "fixture", {"value": 1}, job_id="01PRODUCED", dedupe_key="fixture-1"
        )
        assert submission.job_id == "01PRODUCED"
        assert _Transaction.entered == 1
        assert len(session.calls) == 2

    asyncio.run(scenario())
