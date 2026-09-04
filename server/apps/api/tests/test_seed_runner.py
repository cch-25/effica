from __future__ import annotations

import hashlib

from apps.api.app.db.ulid import is_valid_ulid
from db.seeds.seed import (
    LEGACY_SEED_ID_PREFIX,
    MINIMUM_ARTICLE_COUNT,
    REAL_SEED_ID_PREFIX,
    _assessment_evidence_payload,
    _load_articles,
    _score_components,
    _stable_ulid,
)
from db.seeds.source_feeds import (
    bootstrap_scheduled_rss_sources,
    scheduled_rss_config,
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


def test_seed_scores_name_the_trusted_openai_assessment_they_use() -> None:
    components = _score_components(
        assessment={
            "actual_model_id": "gpt-5.6-luna",
            "rationale_summary": "공개 가능한 근거",
            "model_alias": "openai-bias-v1",
            "prompt_version": "bias-sensationalism-v1",
        },
        assessment_id="01K00000000000000000000001",
        category="경제",
        bias_label="중립적",
    )

    assert components["analysis_provider"] == "openai"
    assert components["assessment_ids"] == ["01K00000000000000000000001"]
    assert components["actual_model_ids"] == ["gpt-5.6-luna"]


def test_seed_assessment_keeps_summary_with_public_evidence() -> None:
    payload = _assessment_evidence_payload(
        {
            "rationale_summary": "절제된 사실 중심 보도입니다.",
            "evidence": [{"quote": "공개 인용"}],
        }
    )

    assert payload == {
        "rationale_summary": "절제된 사실 중심 보도입니다.",
        "evidence": [{"quote": "공개 인용"}],
    }


def test_scheduled_news_feeds_are_broad_metadata_only_and_source_diverse() -> None:
    newsis = scheduled_rss_config("https://www.newsis.com")
    etoday = scheduled_rss_config("https://www.etoday.co.kr/")

    assert newsis is not None and newsis["feed_url"].endswith("/sokbo.xml")
    assert etoday is not None and etoday["feed_url"].endswith("/etoday_news_all.xml")
    assert newsis["hydrate_article_links"] is False
    assert etoday["metadata_only"] is True
    assert newsis["allow_empty_result"] is False
    assert len(bootstrap_scheduled_rss_sources()) >= 5
