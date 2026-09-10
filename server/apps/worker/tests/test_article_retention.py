from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.domains.content.retention import expired, skip_ingestion
from db.article_retention import delete_batch, inventory_plan, plan

NOW = datetime(2026, 9, 5, tzinfo=UTC)


def test_retention_boundary_utc_and_missing_publication_date():
    boundary = NOW - timedelta(days=7)
    assert not expired(boundary, NOW, NOW)
    assert expired(boundary - timedelta(microseconds=1), NOW, NOW)
    assert expired(None, NOW - timedelta(days=8), NOW)
    assert not expired(None, NOW, NOW)
    assert expired("2026-08-28T09:00:00+09:00", NOW, NOW)


# Minimal relational fixture keeps real FK restrictions active, including the
# article/current-version cycle. Tests execute the actual deletion statements.
DDL = [
    "CREATE TABLE articles (id TEXT PRIMARY KEY, canonical_url_hash BLOB UNIQUE, published_at DATETIME, created_at DATETIME, current_version_id TEXT REFERENCES article_versions(id), source_id TEXT DEFAULT 'source', title TEXT DEFAULT '기사')",
    "CREATE TABLE article_retention_tombstones (canonical_url_hash BLOB PRIMARY KEY, retired_at DATETIME)",
    "CREATE TABLE stored_blobs (id TEXT PRIMARY KEY)",
    "CREATE TABLE article_versions (id TEXT PRIMARY KEY, article_id TEXT REFERENCES articles(id) ON DELETE RESTRICT, normalized_text_ref TEXT)",
    "CREATE TABLE model_assessments (id TEXT PRIMARY KEY, article_version_id TEXT REFERENCES article_versions(id) ON DELETE RESTRICT, status TEXT DEFAULT 'SUCCEEDED')",
    "CREATE TABLE score_versions (id TEXT PRIMARY KEY, article_version_id TEXT REFERENCES article_versions(id) ON DELETE RESTRICT)",
    "CREATE TABLE votes (article_id TEXT REFERENCES articles(id) ON DELETE RESTRICT)",
    "CREATE TABLE read_sessions (article_id TEXT REFERENCES articles(id) ON DELETE RESTRICT)",
    "CREATE TABLE feed_impressions (article_id TEXT REFERENCES articles(id) ON DELETE RESTRICT, user_id TEXT)",
    "CREATE TABLE share_cards (snapshot_json TEXT, blob_id TEXT REFERENCES stored_blobs(id))",
    "CREATE TABLE credit_ledger (event_key TEXT)",
    "CREATE TABLE issue_memberships (issue_id TEXT, article_id TEXT REFERENCES articles(id) ON DELETE RESTRICT)",
    "CREATE TABLE issues (id TEXT PRIMARY KEY, version INT DEFAULT 1, status TEXT DEFAULT 'active', editorial_reviewed_at DATETIME, editorial_data_as_of DATETIME)",
    "CREATE TABLE issue_comparison_snapshots (id TEXT, issue_id TEXT, article_frames_json TEXT)",
    "CREATE TABLE vote_aggregate_snapshots (article_id TEXT REFERENCES articles(id) ON DELETE RESTRICT)",
    "CREATE TABLE fact_check_references (article_id TEXT REFERENCES articles(id))",
    "CREATE TABLE jobs (id TEXT PRIMARY KEY, job_type TEXT, status TEXT, payload_json TEXT, lease_expires_at DATETIME)",
]


@pytest.mark.asyncio
async def test_retention_detaches_user_history_and_prevents_reingestion():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        for ddl in DDL:
            await connection.execute(text(ddl))
    factory = async_sessionmaker(engine)
    async with factory() as session:
        for aid in ("old", "undated", "vote", "read", "impression", "card", "credit", "fresh"):
            await session.execute(text("INSERT INTO articles (id,canonical_url_hash,published_at,created_at) VALUES (:id, :hash, :published, :created)"), {
                "id": aid, "hash": hashlib.sha256(aid.encode()).digest(),
                "published": None if aid == "undated" else (NOW if aid == "fresh" else NOW - timedelta(days=8)),
                "created": NOW if aid == "fresh" else NOW - timedelta(days=9),
            })
        for query in (
            "INSERT INTO votes VALUES ('vote')", "INSERT INTO read_sessions VALUES ('read')",
            "INSERT INTO feed_impressions VALUES ('impression','user')",
            "INSERT INTO feed_impressions VALUES ('old',NULL)",
            "INSERT INTO credit_ledger VALUES ('article:credit:vote')",
            "INSERT INTO stored_blobs VALUES ('shared'),('old-body'),('export')",
            "INSERT INTO share_cards VALUES ('{\"article_id\":\"card\"}', 'shared')",
            "INSERT INTO article_versions VALUES ('v-old','old','old-body'),('v-new','fresh','shared')",
            "UPDATE articles SET current_version_id='v-old' WHERE id='old'",
            "INSERT INTO model_assessments (id,article_version_id) VALUES ('a-old','v-old')",
            "INSERT INTO score_versions VALUES ('s-old','v-old')",
            "INSERT INTO issues(id) VALUES ('mixed'),('empty')",
            "INSERT INTO issue_memberships VALUES ('mixed','old'),('mixed','fresh'),('empty','undated')",
            "INSERT INTO issue_comparison_snapshots VALUES ('s1','mixed','{\"article_id\":\"old\"}'),('s2','empty','{}'),('s3','mixed','{\"article_id\":\"fresh\"}')",
            "INSERT INTO jobs VALUES ('j-old','analyze','PENDING','{\"article_version_id\":\"v-old\"}',NULL)",
        ):
            await session.execute(text(query))
        await session.commit()
        preview = await plan(session, NOW)
        expired_ids = {"old", "undated", "vote", "read", "impression", "card", "credit"}
        assert set(preview["article_ids"]) == expired_ids
        assert preview["protected_expired"] == 0
        # A real rollback must restore all rows, including tombstones.
        await delete_batch(session, expired_ids, NOW)
        await session.rollback()
        assert (await plan(session, NOW)) == preview
        result = await delete_batch(session, expired_ids, NOW)
        await session.commit()
        assert result == {"articles": 7, "versions": 1, "blobs": 1, "jobs": 1}
        assert (await session.execute(text("SELECT article_id FROM votes"))).scalar() is None
        assert (await session.execute(text("SELECT COUNT(*) FROM votes"))).scalar() == 1
        assert (await session.execute(text("SELECT COUNT(*) FROM read_sessions"))).scalar() == 1
        assert (await session.execute(text("SELECT COUNT(*) FROM credit_ledger"))).scalar() == 1
        assert (await plan(session, NOW))["delete_count"] == 0
        assert set((await session.execute(text("SELECT id FROM stored_blobs"))).scalars()) == {"shared", "export"}
        assert dict((await session.execute(text("SELECT id,status FROM issues"))).all()) == {"mixed": "active", "empty": "archived"}
        assert list((await session.execute(text("SELECT id FROM issue_comparison_snapshots"))).scalars()) == ["s3"]
        assert await skip_ingestion(session, {}, "old", NOW)
        assert await skip_ingestion(session, {"published_at": NOW - timedelta(days=8)}, "unknown", NOW)
        assert not await skip_ingestion(session, {}, "brand-new", NOW)
    await engine.dispose()


def test_700_articles_keep_300_proportionally_across_all_seven_dates():
    articles = [{"id": f"{day}-{i:03}", "source_id": f"source-{i % 10}",
                 "title": "경제" if i % 2 else "정치", "assessed": i % 3 == 0,
                 "published_at": NOW - timedelta(days=day), "created_at": NOW}
                for day in range(7) for i in range(100)]
    result = inventory_plan(articles, NOW)
    assert result["remaining"] == 300
    assert result["delete_count"] == 400
    assert sorted(row["keep"] for row in result["by_date"].values()) == [42, 43, 43, 43, 43, 43, 43]
    deleted = set(result["article_ids"])
    for day in range(7):
        kept = [a for a in articles if a["id"].startswith(f"{day}-") and a["id"] not in deleted]
        assert len({a["source_id"] for a in kept}) == 10
    survivors = [a for a in articles if a["id"] not in deleted]
    assert inventory_plan(survivors, NOW)["delete_count"] == 0


def test_unequal_dates_use_largest_remainder_and_expiry_has_no_exceptions():
    articles = [{"id": f"{day}-{i:03}", "source_id": "s", "title": "정치",
                 "published_at": NOW - timedelta(days=day), "created_at": NOW}
                for day, count in enumerate([350, 210, 140]) for i in range(count)]
    articles += [{"id": "outdated", "source_id": "s", "title": "정치",
                  "published_at": NOW - timedelta(days=8), "created_at": NOW}]
    result = inventory_plan(articles, NOW)
    assert result["expired"] == 1
    assert "outdated" in result["article_ids"]
    assert sorted(row["keep"] for row in result["by_date"].values()) == [60, 90, 150]
    assert result["remaining"] == 300


def test_future_publication_does_not_defeat_seven_day_storage_expiry():
    assert expired(NOW + timedelta(days=1), NOW - timedelta(days=8), NOW)
