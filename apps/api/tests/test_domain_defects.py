from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from app.domains.admin import (
    AutoPilotManager,
    AutoPilotMode,
    GuardrailResult,
    WeightRevision,
    WeightRevisionStatus,
)
from app.domains.analysis import (
    Evidence,
    ProviderSchemaError,
    validate_public_evidence,
)
from app.domains.content import CrawlerAdapter, CrawlerPolicyError, canonicalize_url
from app.domains.efficacy import EfficacyResponse, aggregate_efficacy
from app.domains.engagement import CreditLedger
from app.domains.feed import FeedCandidate, rank_feed
from app.domains.issues import Issue, IssueClusterStore
from app.domains.issues.topics import (
    PUBLIC_ISSUE_TOPICS,
    canonical_topic_issue_id,
    infer_issue_topic,
    normalize_issue_topic,
)
from app.domains.scoring import Vote, aggregate_votes
from app.domains.users import QuestionnaireVersion, QuestionSpec, score_questionnaire
from app.domains.users.service import QuestionnaireValidationError


def test_public_topic_taxonomy_preserves_culture_and_sports_buckets() -> None:
    assert PUBLIC_ISSUE_TOPICS == (
        "정치",
        "사회",
        "경제",
        "국제",
        "산업",
        "문화",
        "스포츠",
        "기타",
    )
    assert infer_issue_topic("프로야구 KBO 시즌 개막") == "스포츠"
    assert infer_issue_topic("배우 신작 영화 공개") == "문화"
    assert normalize_issue_topic("문화", "전시 소식") == "문화"
    assert infer_issue_topic("분류 키워드가 없는 속보") == "기타"
    assert canonical_topic_issue_id("경제") == canonical_topic_issue_id("경제")
    assert len(canonical_topic_issue_id("경제")) == 26


def test_d01_evidence_quote_must_be_the_exact_unicode_source_slice() -> None:
    with pytest.raises(ProviderSchemaError):
        validate_public_evidence(
            [
                Evidence(
                    article_version_id="v1",
                    start=0,
                    end=3,
                    quote="ZZZ",
                )
            ],
            article_version_id="v1",
            source_text="abc",
        )

    exact = validate_public_evidence(
        [Evidence(article_version_id="v1", start=1, end=2, quote="😀")],
        article_version_id="v1",
        source_text="a😀b",
    )
    assert exact[0].quote == "😀"
    with pytest.raises(ProviderSchemaError):
        validate_public_evidence(
            [Evidence(article_version_id="v1", start=0, end=1, quote="e")],
            article_version_id="v1",
            source_text="é",
        )


def test_d01_evidence_repairs_only_a_unique_exact_quote_location() -> None:
    repaired = validate_public_evidence(
        [Evidence(article_version_id="v1", start=0, end=1, quote="고유 인용")],
        article_version_id="v1",
        source_text="앞 문장. 고유 인용 뒤 문장.",
    )
    assert repaired[0].start == 6
    assert repaired[0].end == 11

    with pytest.raises(ProviderSchemaError):
        validate_public_evidence(
            [Evidence(article_version_id="v1", start=0, end=1, quote="반복")],
            article_version_id="v1",
            source_text="반복, 반복",
        )


def test_d02_query_components_are_encoded_once_and_reserved_escapes_stay_stable() -> None:
    assert canonicalize_url("https://example.test/story?q=a%20b") == (
        "https://example.test/story?q=a%20b"
    )
    assert canonicalize_url("https://example.test/story?q=a+b") == (
        "https://example.test/story?q=a%20b"
    )
    assert canonicalize_url("https://example.test/story?q=%2B") == (
        "https://example.test/story?q=%2B"
    )
    assert canonicalize_url("https://example.test/story?q=%C3%A9") == (
        "https://example.test/story?q=%C3%A9"
    )
    assert canonicalize_url("https://example.test/story?q=%2F") == (
        "https://example.test/story?q=%2F"
    )
    assert canonicalize_url("https://example.test/story?q=%2520") == (
        "https://example.test/story?q=%2520"
    )


def test_d03_questionnaire_rejects_nonfinite_bool_and_numeric_string_answers() -> None:
    questionnaire = QuestionnaireVersion(
        id="q1",
        kind="onboarding",
        version="1",
        questions=(QuestionSpec(id="x", axis="x"),),
    )
    for answer in (float("nan"), float("inf"), float("-inf"), "3", True):
        with pytest.raises(QuestionnaireValidationError):
            score_questionnaire(questionnaire, {"x": answer})


def _vote(user_id: str, revision: int, x: int, *, article_id: str = "a") -> Vote:
    return Vote(
        vote_id=f"{user_id}-{revision}-{x}",
        user_id=user_id,
        article_id=article_id,
        revision=revision,
        x=x,
        y=0,
        z=0,
        sensationalism=20,
        quality_status="QUALIFIED",
        created_at=datetime(2026, 1, revision, tzinfo=UTC),
    )


def test_d04_vote_cohorts_count_distinct_users_and_use_latest_representative() -> None:
    repeated = [_vote("u1", index, index) for index in (1, 2, 3)]
    hidden = aggregate_votes(repeated, segment_by_user={"u1": "small"}, min_segment_size=3)
    assert hidden["segments"] == {}
    assert hidden["suppressed_segment_count"] == 1

    visible = aggregate_votes(
        [_vote(f"u{index}", 1, index) for index in (1, 2, 3)],
        segment_by_user={f"u{index}": "large" for index in (1, 2, 3)},
        min_segment_size=3,
    )
    assert visible["segments"]["large"]["count"] == 3
    assert visible["segments"]["large"]["aggregate"]["x"] == 2


def test_d04_efficacy_cohorts_count_distinct_users() -> None:
    now = datetime.now(UTC)
    repeated = [
        EfficacyResponse(f"r{index}", "u1", "q", (index,), now + timedelta(days=index), "small")
        for index in (1, 2, 3)
    ]
    hidden = aggregate_efficacy(repeated, min_cohort_size=3)
    assert hidden["cohorts"] == {}
    assert hidden["suppressed_cohorts"] == 1

    visible = aggregate_efficacy(
        [
            EfficacyResponse(f"r{index}", f"u{index}", "q", (index,), now, "large")
            for index in (1, 2, 3)
        ],
        min_cohort_size=3,
    )
    assert visible["cohorts"]["large"]["count"] == 3


def test_d05_feed_fallback_keeps_issue_hard_cap() -> None:
    ranked = rank_feed(
        [
            FeedCandidate("a1", "issue-a", "source-a", relevance=1),
            FeedCandidate("a2", "issue-a", "source-a", relevance=0.9),
            FeedCandidate("b1", "issue-b", "source-a", relevance=0.1),
        ],
        limit=3,
        max_consecutive_source=1,
        max_per_issue=1,
    )
    assert len(ranked) == 2
    assert sum(item.candidate.issue_id == "issue-a" for item in ranked) == 1


def test_d06_credit_reversal_cannot_chain_or_be_applied_twice() -> None:
    ledger = CreditLedger()
    ledger.append(
        ledger_id="l1",
        user_id="u",
        event_type="READ_ELIGIBLE",
        event_key="read-1",
        delta=5,
        policy_version="v1",
    )
    ledger.reverse("l1", ledger_id="l2", event_key="reverse-1", policy_version="v1")
    with pytest.raises(ValueError):
        ledger.reverse("l2", ledger_id="l3", event_key="reverse-2", policy_version="v1")
    with pytest.raises(ValueError):
        ledger.reverse("l1", ledger_id="l3", event_key="reverse-2", policy_version="v1")

    def reverse(index: int) -> str:
        try:
            return ledger.reverse(
                "l1",
                ledger_id=f"race-{index}",
                event_key=f"race-{index}",
                policy_version="v1",
            ).ledger_id
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(reverse, range(4)))
    assert results == ["rejected"] * 4
    assert ledger.total("u") == 0


def test_d07_weight_lifecycle_requires_simulation_and_archived_rollback_target() -> None:
    initial = WeightRevision("r0", 0, {"model": 0.5, "source": 0.5}, WeightRevisionStatus.ACTIVE)
    manager = AutoPilotManager(initial, mode=AutoPilotMode.RECOMMEND)
    draft = WeightRevision("draft", 1, {"model": 0.6, "source": 0.4}, WeightRevisionStatus.DRAFT)
    manager.add_draft(draft)
    with pytest.raises(ValueError):
        manager.publish(
            "draft",
            if_match="r0",
            idempotency_key="draft-publish",
            guardrail_result=GuardrailResult(True, ()),
            reviewer_approved=True,
        )
    with pytest.raises(ValueError):
        manager.add_draft(
            WeightRevision("bad", 2, {"model": 0.6, "source": 0.6}, WeightRevisionStatus.DRAFT)
        )

    simulation = WeightRevision(
        "r1", 1, {"model": 0.6, "source": 0.4}, WeightRevisionStatus.SIMULATION
    )
    manager.add_draft(simulation)
    manager.publish(
        "r1",
        if_match="r0",
        idempotency_key="publish-1",
        guardrail_result=GuardrailResult(True, ()),
        reviewer_approved=True,
    )
    with pytest.raises(ValueError):
        manager.rollback("draft", if_match="r1", idempotency_key="bad-rollback")
    assert manager.rollback("r0", if_match="r1", idempotency_key="rollback").status is WeightRevisionStatus.ACTIVE


def test_d08_crawler_adapter_requires_explicit_policy_guard() -> None:
    with pytest.raises(CrawlerPolicyError):
        CrawlerAdapter("source")


def test_d09_split_moves_memberships_out_of_source() -> None:
    source = Issue("source", "Issue")
    store = IssueClusterStore([source])
    store.add_membership("source", "a", 0.8)
    store.add_membership("source", "b", 0.7)
    result = store.split("source", [["a"], ["b"]], operation_key="split", new_issue_ids=["i1", "i2"])
    assert source.article_ids == ()
    assert {article for issue in result for article in issue.article_ids} == {"a", "b"}


def test_d10_feed_mapping_parses_serialized_timestamp() -> None:
    ranked = rank_feed(
        [{"id": "a", "issue_id": "i", "source_id": "s", "published_at": "2026-01-01T00:00:00Z"}],
        now=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert ranked[0].article_id == "a"


def test_d11_merge_creates_missing_target_after_validating_sources() -> None:
    source = Issue("source", "Source")
    store = IssueClusterStore([source])
    store.add_membership("source", "article", 0.9)
    target = store.merge(["source"], target_issue_id="new-target", operation_key="merge")
    assert target.issue_id == "new-target"
    assert target.article_ids == ("article",)
    assert source.status == "merged"


def test_wq002_worker_aggregate_accepts_database_qualified_vote() -> None:
    from worker.handlers.aggregate_votes import handle

    result = asyncio.run(
        handle(
            {
                "article_id": "a",
                "votes": [
                    {
                        "vote_id": "v1",
                        "user_id": "u1",
                        "article_id": "a",
                        "revision": 1,
                        "x": 10,
                        "y": 0,
                        "z": 0,
                        "sensationalism": 20,
                        "quality_status": "QUALIFIED",
                        "active": True,
                    }
                ],
            }
        )
    )
    assert result.value["count"] == 1
    assert result.value["aggregate"]["x"] == 10


def test_canonical_ipv6_non_default_port_brackets_hostname_only() -> None:
    url = "https://[2001:db8::1]:8443/x"
    assert canonicalize_url(url) == "https://[2001:db8::1]:8443/x"
    assert canonicalize_url(canonicalize_url(url)) == url


def test_score_partial_weight_mapping_does_not_inject_profile_defaults() -> None:
    from app.domains.scoring import ScoreComponents, calculate_article_score

    components = ScoreComponents((100, 0, 0), (100, 0, 0), (100, 0, 0), (0, 0, 0))
    score = calculate_article_score(components, {"model": 0.5, "source": 0.5})
    # Missing relative/crowd must be 0, so x = (0.5*100 + 0.5*0) / 1.0 = 50.
    # Injected 0.20 defaults would yield ~64 instead.
    assert score.x == 50
    defaulted = calculate_article_score(components, None)
    assert defaulted.x == 90


def test_vote_sensationalism_rejects_bool_like_axes() -> None:
    with pytest.raises(ValueError, match="sensationalism"):
        Vote("v", "u", "a", 1, 0, 0, 0, True)


def test_ensemble_spread_is_finite_without_successful_models() -> None:
    import math

    from app.domains.analysis import AssessmentStatus, ModelAssessment, ensemble_assessments

    failed = ModelAssessment(
        article_version_id="v1",
        model_alias="m1",
        actual_model_id="model",
        prompt_version="v1",
        x=0,
        sensationalism=0,
        confidence=0.1,
        status=AssessmentStatus.FAILED,
    )
    result = ensemble_assessments([failed])
    assert result.reason_code == "NO_SUCCESSFUL_MODELS"
    assert result.successful_model_count == 0
    assert result.spread is not None
    assert math.isfinite(result.spread)


def test_reason_code_for_normalizes_naive_now_like_rank_feed() -> None:
    from app.domains.feed import reason_code_for

    candidate = FeedCandidate(
        "a",
        "i",
        "s",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    reason = reason_code_for(candidate, now=datetime(2026, 1, 2))
    assert reason == rank_feed([candidate], now=datetime(2026, 1, 2, tzinfo=UTC), limit=1)[0].reason_code


def test_weight_revision_weights_are_immutable_copies() -> None:
    payload = {"model": 0.5, "source": 0.5}
    revision = WeightRevision("r0", 0, payload, WeightRevisionStatus.ACTIVE)
    payload["model"] = 0.9
    assert revision.weights["model"] == 0.5
    with pytest.raises(TypeError):
        revision.weights["model"] = 0.1
    manager = AutoPilotManager(revision, mode=AutoPilotMode.RECOMMEND)
    simulation = WeightRevision(
        "r1", 1, {"model": 0.6, "source": 0.4}, WeightRevisionStatus.SIMULATION
    )
    manager.add_draft(simulation)
    published = manager.publish(
        "r1",
        if_match="r0",
        idempotency_key="publish-immutable",
        guardrail_result=GuardrailResult(True, ()),
        reviewer_approved=True,
    )
    with pytest.raises(TypeError):
        published.weights["model"] = 0.0
    rolled = manager.rollback("r0", if_match="r1", idempotency_key="rollback-immutable")
    with pytest.raises(TypeError):
        rolled.weights["source"] = 0.0
    assert rolled.weights["model"] == 0.5


def test_grant_false_empty_then_true_then_false_avoids_naive_datetime_min() -> None:
    from app.domains.users.models import ConsentPurpose
    from app.domains.users.service import ConsentService, InMemoryUserRepository, UserService

    repository = InMemoryUserRepository()
    users = UserService(repository)
    consents = ConsentService(repository, users)
    user = users.create_user()
    version = repository.add_consent_version(
        purpose=ConsentPurpose.SERVICE,
        version="1",
        body_hash="hash",
    )
    empty = consents.grant(user.id, version.id, granted=False)
    assert empty.granted is False
    granted = consents.grant(user.id, version.id, granted=True)
    assert granted.granted is True
    withdrawn = consents.grant(user.id, version.id, granted=False)
    assert withdrawn.granted is False
    assert withdrawn.withdrawn_at is not None
