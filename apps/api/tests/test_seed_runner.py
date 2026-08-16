from __future__ import annotations

import hashlib

from apps.api.app.db.ulid import is_valid_ulid
from db.seeds.seed import (
    LEGACY_SEED_ID_PREFIX,
    MINIMUM_ARTICLE_COUNT,
    REAL_SEED_ID_PREFIX,
    _load_articles,
    _stable_ulid,
)


def test_real_article_snapshot_contains_at_least_fifty_verified_korean_rows() -> None:
    articles = _load_articles()

    assert len(articles) >= MINIMUM_ARTICLE_COUNT
    assert len({row["canonical_url"] for row in articles}) == len(articles)
    assert len({row["title"] for row in articles}) == len(articles)
    assert all("example.invalid" not in row["canonical_url"] for row in articles)
    assert all(row["canonical_url"].startswith("https://") for row in articles)
    assert all(any("가" <= character <= "힣" for character in row["title"]) for row in articles)
    assert all(any("가" <= character <= "힣" for character in row["category"]) for row in articles)
    assert all(len(row["body_text"]) >= 200 for row in articles)


def test_real_seed_ids_are_stable_valid_ulids_outside_legacy_namespace() -> None:
    first = _stable_ulid("article", "https://example.com/기사")
    second = _stable_ulid("article", "https://example.com/기사")
    different = _stable_ulid("article", "https://example.com/다른-기사")

    assert first == second
    assert first != different
    assert is_valid_ulid(first)
    assert first.startswith(REAL_SEED_ID_PREFIX)
    assert not first.startswith(LEGACY_SEED_ID_PREFIX)


def test_article_body_and_url_hashes_are_not_placeholder_values() -> None:
    articles = _load_articles()
    body_hashes = {hashlib.sha256(row["body_text"].encode()).digest() for row in articles}
    url_hashes = {hashlib.sha256(row["canonical_url"].encode()).digest() for row in articles}

    assert len(body_hashes) == len(articles)
    assert len(url_hashes) == len(articles)
    assert not any("synthetic" in row["body_text"].lower() for row in articles)
    assert not any("mock" in row["title"].lower() for row in articles)
