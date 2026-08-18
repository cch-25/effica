from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
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
from apps.worker.worker.queue import JobStatus, MariaDBQueueRepository
from apps.worker.worker.services import MariaDBResultApplier

DATABASE_URL = os.environ.get("CI_MARIADB_URL")
API_BASE_URL = os.environ.get("CI_API_BASE_URL")
pytestmark = pytest.mark.mariadb


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
