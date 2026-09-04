from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.jobs.types import generate_job_id
from apps.worker.worker.handlers.base import HandlerContext, HandlerResult
from apps.worker.worker.handlers.registry import HandlerRegistry, build_default_registry
from apps.worker.worker.main import WorkerConfig, WorkerRuntime
from apps.worker.worker.queue import Job, JobStatus, MariaDBQueueRepository
from apps.worker.worker.services import MariaDBCrawlScheduler, MariaDBResultApplier

DATABASE_URL = os.environ.get("CI_MARIADB_URL")
API_BASE_URL = os.environ.get("CI_API_BASE_URL")
pytestmark = pytest.mark.mariadb


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="CI_MARIADB_URL is not configured")
async def test_mariadb_share_card_blob_accepts_iso_expiry_timestamp() -> None:
    """Exercise the textual asyncmy binding used by share-card rendering."""

    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            factory = async_sessionmaker(bind=connection, expire_on_commit=False)
            try:
                async with factory() as session:
                    applier = MariaDBResultApplier(factory)
                    payload = f"share-card-ci-{uuid4().hex}".encode()
                    blob_id = await applier._store_blob(
                        session,
                        payload,
                        mime_type="image/png",
                        expires_at="2026-08-27T15:30:00+09:00",
                    )
                    expires_at = await session.scalar(
                        text("SELECT expires_at FROM stored_blobs WHERE id = :id"),
                        {"id": blob_id},
                    )
                    assert expires_at == datetime(2026, 8, 27, 6, 30)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


async def _connection_probe(url: str) -> tuple[str, int, str]:
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            identity, version = (
                await connection.execute(
                    text("SELECT CONNECTION_ID(), VERSION()")
                )
            ).one()
            return connection.dialect.name, int(identity), str(version)
    finally:
        await engine.dispose()


def _probe_from_process(url: str) -> tuple[str, int, str]:
    return asyncio.run(_connection_probe(url))


async def _insert_probe(url: str, table: str, worker_id: int) -> int:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(f"INSERT INTO `{table}` (worker_id) VALUES (:worker_id)"),
                {"worker_id": worker_id},
            )
        return worker_id
    finally:
        await engine.dispose()


def _insert_from_process(arguments: tuple[str, str, int]) -> int:
    return asyncio.run(_insert_probe(*arguments))


@pytest.mark.skipif(not DATABASE_URL, reason="CI_MARIADB_URL is not configured")
def test_mariadb_dialect_and_two_process_connections() -> None:
    """Exercise the real dialect and process boundary used by API + workers."""

    assert DATABASE_URL is not None
    expected_processes = int(os.environ.get("CI_WORKER_PROCESSES", "2"))
    assert expected_processes >= 2

    with ProcessPoolExecutor(max_workers=expected_processes) as pool:
        probes = list(pool.map(_probe_from_process, [DATABASE_URL] * expected_processes))

    assert all(dialect == "mysql" for dialect, _identity, _version in probes)
    assert len({identity for _dialect, identity, _version in probes}) == expected_processes
    assert all(version for _dialect, _identity, version in probes)


async def _run_concurrent_inserts(url: str, expected_processes: int) -> None:
    table = f"effica_ci_concurrency_{uuid4().hex}"
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    f"CREATE TABLE `{table}` ("
                    "worker_id INT PRIMARY KEY"
                    ") ENGINE=InnoDB"
                )
            )
        arguments = [(url, table, worker_id) for worker_id in range(expected_processes)]
        with ProcessPoolExecutor(max_workers=expected_processes) as pool:
            inserted = list(pool.map(_insert_from_process, arguments))
        async with engine.connect() as connection:
            count = int(
                (
                    await connection.execute(text(f"SELECT COUNT(*) FROM `{table}`"))
                ).scalar_one()
            )
        assert inserted == list(range(expected_processes))
        assert count == expected_processes
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE IF EXISTS `{table}`"))
        await engine.dispose()


@pytest.mark.skipif(not DATABASE_URL, reason="CI_MARIADB_URL is not configured")
def test_mariadb_concurrent_transactions_commit_once_per_process() -> None:
    """Exercise concurrent committed writes over independent MariaDB processes."""

    assert DATABASE_URL is not None
    expected_processes = int(os.environ.get("CI_WORKER_PROCESSES", "2"))
    assert expected_processes >= 2
    asyncio.run(_run_concurrent_inserts(DATABASE_URL, expected_processes))


async def _probe_handler(
    payload: Mapping[str, Any], context: HandlerContext
) -> HandlerResult:
    return HandlerResult(
        value={
            "probe_id": str(payload["probe_id"]),
            "worker_id": context.worker_id,
        }
    )


async def _enqueue_probe_jobs(url: str, count: int) -> list[str]:
    engine = create_async_engine(url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        from apps.api.app.jobs.producer import MariaDBJobProducer

        producer = MariaDBJobProducer(factory)
        job_ids: list[str] = []
        for index in range(count):
            job_id = generate_job_id()
            submission = await producer.enqueue(
                "ci_probe",
                {"probe_id": f"mariadb-worker-probe-{index}-{uuid4().hex}"},
                dedupe_key=f"ci-probe:{uuid4().hex}",
                priority=100,
                job_id=job_id,
            )
            job_ids.append(submission.job_id)
        return job_ids
    finally:
        await engine.dispose()


def _run_probe_worker(arguments: tuple[str, str]) -> tuple[str, bool]:
    url, worker_id = arguments

    async def run() -> tuple[str, bool]:
        engine = create_async_engine(url, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        repository = MariaDBQueueRepository(factory, supports_skip_locked=True)
        runtime = WorkerRuntime(
            repository,
            registry=HandlerRegistry({"ci_probe": _probe_handler}),
            config=WorkerConfig(
                worker_id=worker_id,
                lease_seconds=30,
                poll_interval_seconds=0,
                shutdown_grace_seconds=5,
            ),
            result_applier=MariaDBResultApplier(factory),
        )
        try:
            return worker_id, await runtime.process_one()
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _run_export_worker(arguments: tuple[str, str, str]) -> bool:
    url, worker_id, target_job_id = arguments

    async def run() -> bool:
        engine = create_async_engine(url, pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        repository = MariaDBQueueRepository(factory, supports_skip_locked=True)
        runtime = WorkerRuntime(
            repository,
            registry=build_default_registry(),
            config=WorkerConfig(worker_id=worker_id, lease_seconds=30, poll_interval_seconds=0),
            result_applier=MariaDBResultApplier(factory),
        )
        try:
            # A production queue may already contain older available work.
            # Keep processing bounded work until the API-created job reaches
            # its terminal state instead of assuming an otherwise empty DB.
            for _ in range(100):
                target = await repository.get(target_job_id)
                if target is not None and target.status is JobStatus.SUCCEEDED:
                    return True
                if not await runtime.process_one():
                    return False
            return False
        finally:
            await engine.dispose()

    return asyncio.run(run())


async def _request_export_job(base_url: str) -> str:
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        response = await client.post(
            "/api/v1/me/export",
            headers={"X-Debug-Role": "MEMBER", "X-CSRF-Token": "local-csrf"},
        )
        response.raise_for_status()
        assert response.status_code == 202
        payload = response.json()
        # Repeated runs exercise the endpoint's idempotent replay contract;
        # the canonical job may already be terminal.
        assert payload["status"] in {
            "PENDING",
            "LEASED",
            "SUCCEEDED",
            "FAILED",
            "DEAD",
            "CANCELLED",
        }
        job_id = payload["job_id"]
        jobs = await client.get(
            "/api/v1/admin/jobs",
            params={"job_type": "export_user"},
            headers={"X-Debug-Role": "ANALYST"},
        )
        jobs.raise_for_status()
        assert any(item["id"] == job_id for item in jobs.json()["items"])
        return str(job_id)


async def _job_rows(url: str, job_ids: list[str]) -> list[dict[str, object]]:
    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        placeholders = ", ".join(f":id{index}" for index in range(len(job_ids)))
        params = {f"id{index}": job_id for index, job_id in enumerate(job_ids)}
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    f"SELECT id, status, attempts FROM jobs "
                    f"WHERE id IN ({placeholders}) ORDER BY id"
                ),
                params,
            )
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


@pytest.mark.skipif(not DATABASE_URL, reason="CI_MARIADB_URL is not configured")
def test_mariadb_queue_processes_observable_jobs_in_two_worker_processes() -> None:
    """Exercise the repository producer and durable result boundary in two processes."""

    assert DATABASE_URL is not None
    expected_processes = int(os.environ.get("CI_WORKER_PROCESSES", "2"))
    assert expected_processes >= 2
    job_ids = asyncio.run(_enqueue_probe_jobs(DATABASE_URL, expected_processes))
    worker_ids = [f"ci-worker-{index}" for index in range(expected_processes)]
    try:
        with ProcessPoolExecutor(max_workers=expected_processes) as pool:
            results = list(pool.map(_run_probe_worker, [(DATABASE_URL, worker_id) for worker_id in worker_ids]))
        assert all(processed for _worker_id, processed in results), results
        rows = asyncio.run(_job_rows(DATABASE_URL, job_ids))
        assert {str(row["status"]) for row in rows} == {"SUCCEEDED"}
        assert {int(str(row["attempts"])) for row in rows} == {1}

        engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
        try:
            placeholders = ", ".join(f":id{index}" for index in range(len(job_ids)))
            params = {f"id{index}": job_id for index, job_id in enumerate(job_ids)}

            async def read_results() -> set[str]:
                async with engine.connect() as connection:
                    result = await connection.execute(
                        text(
                            "SELECT target_id, after_json FROM audit_logs "
                            "WHERE action = 'JOB_RESULT_APPLIED' AND target_type = 'job' "
                            f"AND target_id IN ({placeholders})"
                        ),
                        params,
                    )
                    values: set[str] = set()
                    for row in result.mappings().all():
                        payload = row["after_json"]
                        if isinstance(payload, str):
                            payload = json.loads(payload)
                        values.add(str(payload["result"]["worker_id"]))
                    return values

            observed_workers = asyncio.run(read_results())
        finally:
            asyncio.run(engine.dispose())
        assert observed_workers == set(worker_ids)
    finally:
        async def cleanup() -> None:
            engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
            try:
                placeholders = ", ".join(f":id{index}" for index in range(len(job_ids)))
                params = {f"id{index}": job_id for index, job_id in enumerate(job_ids)}
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            f"DELETE FROM audit_logs WHERE target_type = 'job' "
                            f"AND target_id IN ({placeholders})"
                        ),
                        params,
                    )
                    await connection.execute(text(f"DELETE FROM jobs WHERE id IN ({placeholders})"), params)
            finally:
                await engine.dispose()

        asyncio.run(cleanup())


@pytest.mark.skipif(
    not DATABASE_URL or not API_BASE_URL,
    reason="CI_MARIADB_URL and CI_API_BASE_URL are required for live API coverage",
)
def test_mariadb_api_repository_enqueues_and_completes_a_real_job() -> None:
    """Use the running API repository, then process its durable export job."""

    assert DATABASE_URL is not None and API_BASE_URL is not None
    job_id = asyncio.run(_request_export_job(API_BASE_URL))
    assert _run_export_worker((DATABASE_URL, "ci-api-worker", job_id))
    rows = asyncio.run(_job_rows(DATABASE_URL, [job_id]))
    assert rows == [{"id": job_id, "status": "SUCCEEDED", "attempts": 1}]


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="CI_MARIADB_URL is not configured")
async def test_mariadb_scheduler_query_and_advisory_lock_are_dialect_valid() -> None:
    """Validate the exact scheduler SELECT without enqueueing production work."""

    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    lock_name = f"effica:ci-scheduler:{uuid4().hex}"
    try:
        async with engine.connect() as connection:
            connection_id = int(
                (await connection.execute(text("SELECT CONNECTION_ID()"))).scalar_one()
            )
            acquired = int(
                (
                    await connection.execute(
                        text("SELECT GET_LOCK(:lock_name, 0)"),
                        {"lock_name": lock_name},
                    )
                ).scalar_one()
            )
            assert acquired == 1
            try:
                owner = int(
                    (
                        await connection.execute(
                            text("SELECT IS_USED_LOCK(:lock_name)"),
                            {"lock_name": lock_name},
                        )
                    ).scalar_one()
                )
                assert owner == connection_id

                scheduler = MariaDBCrawlScheduler(lambda: None, batch_size=5)
                explain = await connection.execute(
                    text(f"EXPLAIN {scheduler.candidate_source_statement()}"),
                    {"dedupe_prefix": "scheduled:", "bucket": "0"},
                )
                assert explain.mappings().all()
            finally:
                released = int(
                    (
                        await connection.execute(
                            text("SELECT RELEASE_LOCK(:lock_name)"),
                            {"lock_name": lock_name},
                        )
                    ).scalar_one()
                )
                assert released == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.skipif(not DATABASE_URL, reason="CI_MARIADB_URL is not configured")
async def test_mariadb_score_promotion_is_innodb_atomic_and_rollback_safe() -> None:
    """Exercise the real FOR UPDATE/upsert/promotion SQL, then roll it all back."""

    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    version_id = ""
    before: list[dict[str, object]] = []
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                target = (
                    await connection.execute(
                        text(
                            """
                            SELECT av.id AS version_id, w.id AS weight_id
                            FROM article_versions av
                            JOIN weight_profile_revisions w ON w.status = 'active'
                            ORDER BY av.id, w.revision DESC
                            LIMIT 1
                            """
                        )
                    )
                ).mappings().first()
                assert target is not None
                version_id = str(target["version_id"])
                weight_id = str(target["weight_id"])
                before = [
                    dict(row)
                    for row in (
                        await connection.execute(
                            text(
                                """
                                SELECT id, status, x, y, z, sensationalism, confidence,
                                       components_json, created_at
                                FROM score_versions
                                WHERE article_version_id = :version_id
                                ORDER BY id
                                """
                            ),
                            {"version_id": version_id},
                        )
                    ).mappings().all()
                ]

                applier = MariaDBResultApplier(lambda: None)
                await applier._apply_score(
                    connection,
                    Job(
                        id=f"ci-score-{uuid4().hex}",
                        job_type="calculate_score",
                        payload={
                            "article_version_id": version_id,
                            "weight_revision_id": weight_id,
                        },
                    ),
                    {
                        "article_version_id": version_id,
                        "weight_revision_id": weight_id,
                        "x": 7,
                        "y": 0,
                        "z": 0,
                        "sensationalism": 11,
                        "confidence": 0.75,
                        "components": {"integration_probe": True},
                    },
                    datetime(2026, 8, 27, 12, 0),
                )
                active_count = int(
                    (
                        await connection.execute(
                            text(
                                """
                                SELECT COUNT(*) FROM score_versions
                                WHERE article_version_id = :version_id
                                  AND status = 'active'
                                """
                            ),
                            {"version_id": version_id},
                        )
                    ).scalar_one()
                )
                assert active_count == 1
            finally:
                await transaction.rollback()

        async with engine.connect() as verification:
            after = [
                dict(row)
                for row in (
                    await verification.execute(
                        text(
                            """
                            SELECT id, status, x, y, z, sensationalism, confidence,
                                   components_json, created_at
                            FROM score_versions
                            WHERE article_version_id = :version_id
                            ORDER BY id
                            """
                        ),
                        {"version_id": version_id},
                    )
                ).mappings().all()
            ]
            assert after == before
    finally:
        await engine.dispose()
