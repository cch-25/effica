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
from sqlalchemy import MetaData, text
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
            url = f"mariadb+asyncmy://root@localhost/inventory_test?unix_socket={socket}"
            # Start from the previous deployed schema. Full historical rebuilds
            # have unrelated legacy identifier-length incompatibilities.
            async def previous_schema():
                from apps.api.app.db import models  # noqa: F401
                from apps.api.app.db.base import metadata

                previous = MetaData(naming_convention=metadata.naming_convention)
                for table in metadata.sorted_tables:
                    if table.name != "article_inventory_guard":
                        table.to_metadata(previous)
                for name in ("votes", "read_sessions"):
                    column = previous.tables[name].c.article_id
                    column.nullable = False
                    for fk in column.foreign_keys:
                        fk.ondelete = "RESTRICT"
                        fk.constraint.ondelete = "RESTRICT"
                database = create_async_engine(url)
                try:
                    async with database.begin() as connection:
                        await connection.run_sync(previous.create_all)
                finally:
                    await database.dispose()

            asyncio.run(previous_schema())
            env = {**os.environ, "DATABASE_URL": url}
            subprocess.run([sys.executable, "-m", "alembic", "-c", "db/alembic.ini", "stamp", "0020_questionnaire_beta"], env=env, check=True, capture_output=True)
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
