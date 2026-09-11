"""Real concurrency and migration checks against an isolated local MariaDB.

Never reads DATABASE_URL. The server uses a temporary data directory and Unix
socket with networking disabled, so this test cannot connect to production.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.article_retention import enforce_inventory, ensure_current_inventory, lock_inventory, plan


@pytest.fixture(scope="module")
def isolated_database():
    installer, daemon = shutil.which("mariadb-install-db"), shutil.which("mariadbd")
    if not installer or not daemon:
        pytest.skip("local MariaDB binaries are unavailable")
    with tempfile.TemporaryDirectory(prefix="effica-inventory-", dir="/tmp") as directory:
        root = Path(directory)
        socket = root / "db.sock"
        log = root / "server.log"
        subprocess.run([installer, f"--datadir={root / 'data'}", "--auth-root-authentication-method=normal", "--skip-test-db"], check=True, capture_output=True)
        process = subprocess.Popen([daemon, f"--datadir={root / 'data'}", f"--socket={socket}", f"--pid-file={root / 'db.pid'}", f"--log-error={log}", "--skip-networking"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if socket.exists():
                    break
                if process.poll() is not None:
                    pytest.fail(log.read_text())
                time.sleep(0.1)
            subprocess.run([shutil.which("mariadb"), "--no-defaults", "-uroot", f"--socket={socket}", "-e", "CREATE DATABASE inventory_test"], check=True, capture_output=True)
            url = f"mysql+asyncmy://root@localhost/inventory_test?unix_socket={socket}"
            # Build the actual historical schema, then exercise its upgrade.
            # Cloning current ORM metadata silently imports future columns.
            env = {**os.environ, "DATABASE_URL": url}
            subprocess.run([sys.executable, "-m", "alembic", "-c", "db/alembic.ini", "upgrade", "0020_questionnaire_beta"], env=env, check=True, capture_output=True)
            migration = subprocess.run([sys.executable, "-m", "alembic", "-c", "db/alembic.ini", "upgrade", "head"], env=env, capture_output=True, text=True)
            assert migration.returncode == 0, migration.stderr
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@pytest.mark.asyncio
async def test_real_migrations_atomic_cap_concurrent_writers_and_idle_expiry(isolated_database):
    engine = create_async_engine(isolated_database, isolation_level="READ COMMITTED")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    source = "01K00000000000000000009999"

    async def insert(session, i, published):
        await session.execute(text("""INSERT INTO articles
            (id, source_id, canonical_url, canonical_url_hash, title, published_at, created_at, updated_at, status)
            VALUES (:id,:source,:url,:hash,'경제 기사',:published,:now,:now,'active')"""),
            {"id": f"{i:026}", "source": source, "url": f"https://test.invalid/{i}",
             "hash": hashlib.sha256(str(i).encode()).digest(), "published": published.replace(tzinfo=None), "now": now.replace(tzinfo=None)})

    try:
        async with factory() as session, session.begin():
            await session.execute(text("""INSERT INTO sources
                (id,name,source_type,canonical_url,policy_status,robots_status,terms_status,active)
                VALUES (:id,'Test','RSS','https://test.invalid','APPROVED','APPROVED','APPROVED',1)"""), {"id": source})
            await lock_inventory(session)
            for i in range(700):
                await insert(session, i, now - timedelta(days=i % 7))
            result = await enforce_inventory(session, now, lock=False)
            assert result["articles"] == 400
        async with factory() as session:
            current = await plan(session, now)
            assert current["total"] == 300 and current["delete_count"] == 0

        first_locked = asyncio.Event()
        second_entered = asyncio.Event()

        async def first_writer():
            async with factory() as session, session.begin():
                await lock_inventory(session)
                await insert(session, 900, now)
                first_locked.set()
                await asyncio.sleep(0.15)
                assert not second_entered.is_set()
                await enforce_inventory(session, now, lock=False)

        async def second_writer():
            await first_locked.wait()
            async with factory() as session, session.begin():
                await lock_inventory(session)
                second_entered.set()
                await insert(session, 901, now)
                await enforce_inventory(session, now, lock=False)

        async def observer():
            await first_locked.wait()
            for _ in range(10):
                async with factory() as session:
                    count = (await session.execute(text("SELECT COUNT(*) FROM articles"))).scalar_one()
                    assert count <= 300
                await asyncio.sleep(0.03)

        await asyncio.gather(first_writer(), second_writer(), observer())
        async with factory() as session, session.begin():
            # An idle system still loses expired content via the request/daemon fence.
            await ensure_current_inventory(session, now + timedelta(days=8))
            assert (await session.execute(text("SELECT COUNT(*) FROM articles"))).scalar_one() == 0
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_deletion_keeps_vote_revisions_monotonic(isolated_database):
    from sqlalchemy import select

    from apps.api.app.db.enums import (
        ArticleStatus,
        JobStatus,
        SourcePolicyStatus,
        SourceType,
        UserRole,
        UserStatus,
    )
    from apps.api.app.db.models import Article, Job, Source, User, VoteAggregateSnapshot
    from apps.api.app.db.ulid import new_ulid
    from apps.api.app.db.utc import utc_now
    from apps.api.app.repositories.platform import MariaDBPlatformRepository
    from apps.worker.worker.queue import Job as WorkerJob
    from apps.worker.worker.services import MariaDBResultApplier

    engine = create_async_engine(isolated_database)
    database = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with database() as session:
            first, second, source_id, article_id = [new_ulid() for _ in range(4)]
            session.add_all([User(id=uid, role=UserRole.MEMBER, status=UserStatus.ACTIVE) for uid in (first, second)])
            session.add(Source(id=source_id, name="Review fixture", source_type=SourceType.RSS,
                canonical_url="https://fixture.invalid/feed", policy_status=SourcePolicyStatus.APPROVED,
                active=True))
            await session.flush()
            session.add(Article(id=article_id, source_id=source_id, title="Review fixture",
                canonical_url="https://fixture.invalid/1", canonical_url_hash=hashlib.sha256(b"article").digest(),
                status=ArticleStatus.ACTIVE))
            await session.commit()
            repository = MariaDBPlatformRepository(session, encryption_secret="x" * 40)
            values = dict(x=0, y=0, z=0, sensationalism=0)
            await repository.put_vote_row(user_id=first, article_id=article_id, values=values)
            await repository.put_vote_row(user_id=second, article_id=article_id, values=values)
            jobs = list((await session.scalars(select(Job))).all())
            for job in jobs:
                job.status = JobStatus.SUCCEEDED
            session.add(VoteAggregateSnapshot(id=new_ulid(), article_id=article_id, version=2,
                aggregate_json={"source_revision": 2, "qualified_count": 2, "qualified": values}, segment_json={}))
            await session.commit()
            applier = MariaDBResultApplier(database)
            await applier._apply_delete(session, WorkerJob(id=new_ulid(), job_type="delete_user", payload={"user_id": second}),
                {"user_id": second}, utc_now())
            await session.commit()
            from apps.worker.worker.handlers.aggregate_votes import handle
            from apps.worker.worker.lookups import MariaDBWorkerLookups
            lookups = MariaDBWorkerLookups(database, encryption_secret="x" * 40)
            aggregate = await handle({"article_id": article_id, "version": 3,
                                      "votes": await lookups.votes_lookup(article_id)})
            await applier._apply_aggregate(session, WorkerJob(id=new_ulid(), job_type="aggregate_votes"), aggregate.value, utc_now())
            await session.commit()
            view = await repository.vote_aggregate(article_id)
            assert view["status"] == "ready" and view["qualified_count"] == 1
            result = await repository.put_vote_row(user_id=first, article_id=article_id, values=values)
            queued = list((await session.scalars(select(Job))).all())
            assert result["revision"] == 4
            pending = {j.dedupe_key for j in queued if j.status == JobStatus.PENDING}
            assert {f"{article_id}:3", f"{article_id}:4"} <= pending
            assert (await repository.vote_aggregate(article_id))["status"] == "pending"
            assert await repository.delete_vote_row(user_id=first, article_id=article_id)
            await session.commit()
            assert (await session.get(Article, article_id)).vote_revision == 5
            await applier._apply_delete(session, WorkerJob(id=new_ulid(), job_type="delete_user", payload={"user_id": first}),
                {"user_id": first}, utc_now())
            await session.commit()
            job = await session.scalar(select(Job).where(Job.dedupe_key == f"{article_id}:6"))
            assert job.status == JobStatus.PENDING
            aggregate = await handle({**job.payload_json, "votes": []})
            await applier._apply_aggregate(session, WorkerJob(id=job.id, job_type="aggregate_votes", payload=job.payload_json), aggregate.value, utc_now())
            await session.commit()
            view = await repository.vote_aggregate(article_id)
            assert view["status"] == "ready" and view["qualified_count"] == 0


    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_maintenance_preserves_failed_job_inputs(isolated_database):
    from sqlalchemy import select

    from apps.api.app.db.enums import JobStatus
    from apps.api.app.db.models import Job
    from apps.api.app.db.ulid import new_ulid
    from apps.worker.worker.handlers.delete_user import handle
    from db.storage_maintenance import compact

    engine = create_async_engine(isolated_database)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            payload = {"user_id": new_ulid(), "confirmed": True, "run_date": "2026-09-11"}
            ids = {}
            for status in (JobStatus.FAILED, JobStatus.DEAD, JobStatus.CANCELLED, JobStatus.SUCCEEDED):
                ids[status] = new_ulid()
                session.add(Job(id=ids[status], job_type="delete_user", dedupe_key=ids[status],
                                status=status, payload_json=payload))
            await session.commit()
            await compact(session)
            await session.commit()
            for status, job_id in ids.items():
                stored = await session.scalar(select(Job.payload_json).where(Job.id == job_id))
                if status == JobStatus.SUCCEEDED:
                    assert stored == {"user_id": payload["user_id"]}
                else:
                    assert stored == payload
                    assert (await handle(stored)).value["user_id"] == payload["user_id"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_engagement_migration_backfills_existing_history(isolated_database):
    # Separate database keeps the historical upgrade independent of inventory
    # and concurrency fixtures. Both databases share the isolated Unix socket.
    engine = create_async_engine(isolated_database)
    async with engine.begin() as connection:
        await connection.execute(text("CREATE DATABASE engagement_upgrade"))
    await engine.dispose()
    url = isolated_database.replace("/inventory_test?", "/engagement_upgrade?")
    env = {**os.environ, "DATABASE_URL": url}

    def migrate(revision):
        result = subprocess.run([sys.executable, "-m", "alembic", "-c", "db/alembic.ini", "upgrade", revision],
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    migrate("0023_article_images")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("INSERT INTO users (id) VALUES ('reader')"))
            await connection.execute(text("""INSERT INTO sources
                (id,name,source_type,canonical_url,policy_status,robots_status,terms_status,active)
                VALUES ('source','Test','RSS','https://test.invalid','APPROVED','APPROVED','APPROVED',1)"""))
            await connection.execute(text("""INSERT INTO articles
                (id,source_id,canonical_url,canonical_url_hash,title,status)
                VALUES ('article','source','https://test.invalid/a',UNHEX(SHA2('a',256)),'기사','active')"""))
            await connection.execute(text("""INSERT INTO votes
                (id,user_id,article_id,revision,x,y,z,sensationalism,quality_status)
                VALUES ('vote','reader','article',4,0,0,0,0,'QUALIFIED')"""))
            await connection.execute(text("""INSERT INTO vote_aggregate_snapshots
                (id,article_id,version,aggregate_json,segment_json)
                VALUES ('snapshot','article',9,'{}','{}')"""))
            await connection.execute(text("""INSERT INTO jobs
                (id,job_type,dedupe_key,status,payload_json)
                VALUES ('job','aggregate_votes','article:12','SUCCEEDED','{"article_id":"article"}')"""))
            for identifier, article in (("read1", "article"), ("read2", "article"), ("detached", None)):
                await connection.execute(text("""INSERT INTO read_sessions
                    (id,user_id,article_id,token_hash,expires_at,status,policy_version)
                    VALUES (:id,'reader',:article,:hash,UTC_TIMESTAMP(),'ELIGIBLE','read-v1')"""),
                    {"id": identifier, "article": article, "hash": hashlib.sha256(identifier.encode()).digest()})
        migrate("head")
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT vote_revision FROM articles"))).scalar_one() == 12
            keys = dict((await connection.execute(text("SELECT id, article_key FROM read_sessions"))).all())
            assert keys == {"read1": "article", "read2": "article", "detached": "detached"}
    finally:
        await engine.dispose()
