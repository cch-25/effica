from datetime import UTC, datetime, timedelta

import pytest
from app.domains.admin import (
    AutoPilotManager,
    AutoPilotMode,
    SimulationMetrics,
    WeightRevision,
    WeightRevisionStatus,
    evaluate_guardrails,
)
from app.domains.analysis import (
    AssessmentInput,
    DeterministicStubProvider,
    ModelAssessment,
    ensemble_assessments,
    fact_check_does_not_change_axes,
    sanitize_rationale,
)
from app.domains.content import (
    APIAdapter,
    CrawlerAdapter,
    CrawlerPolicyError,
    CrawlerPolicyGuard,
    RSSAdapter,
    canonicalize_url,
    decide_version,
)
from app.domains.efficacy import aggregate_efficacy, efficacy_delta, normalize_efficacy_score
from app.domains.engagement import CreditLedger, evaluate_read_eligibility
from app.domains.feed import FeedCandidate, rank_feed
from app.domains.issues import Issue, IssueClusterStore, cluster_articles
from app.domains.scoring import (
    BehavioralProfile,
    BehaviorEvent,
    ScoreComponents,
    Vote,
    VoteRevisionStore,
    WeightProfile,
    aggregate_votes,
    calculate_article_score,
    canonical_score_json,
    shrink_source_prior,
    update_behavioral_profile,
)
from app.domains.sharing import (
    BlobLimitError,
    BlobStore,
    ShareCard,
    ShareCardStatus,
    ShareCardStore,
    create_public_token,
    hash_public_token,
    make_share_snapshot,
)


def test_url_and_fixture_adapters_are_deterministic():
    assert (
        canonicalize_url("HTTPS://Example.com:443/a/../story/?utm_source=x&b=2&a=1#section")
        == "https://example.com/story?a=1&b=2"
    )
    api = APIAdapter("source")
    article = api.parse(
        {"items": [{"id": "1", "url": "https://example.com/a", "title": "T", "content": "B"}]}
    )[0]
    assert (
        article.canonical_url_hash
        == APIAdapter("source").parse({"url": article.url, "title": "T"})[0].canonical_url_hash
    )
    rss = RSSAdapter("source").parse(
        "<rss><channel><item><title>News</title><link>https://example.com/n</link><description>Body</description></item></channel></rss>"
    )
    assert rss[0].title == "News"


def test_crawler_policy_and_parser():
    with pytest.raises(CrawlerPolicyError):
        CrawlerAdapter("s", CrawlerPolicyGuard("APPROVED", "PENDING")).parse(
            {"url": "https://example.com", "html": "<article>x</article>"}
        )
    result = CrawlerAdapter("s", CrawlerPolicyGuard("APPROVED", "APPROVED")).parse(
        {
            "url": "https://example.com",
            "html": "<html><head><title>Title</title></head><article>Body</article></html>",
        }
    )
    assert result[0].title == "Title" and "Body" in result[0].body


def test_article_version_decision():
    assert decide_version(None, "a").value == "initial"
    assert decide_version("a", "a").value == "unchanged"
    assert decide_version("a", "b").value == "new_version"


def test_issue_clustering_and_idempotent_merge_split():
    groups = cluster_articles(
        [
            {"id": "b", "title": "Budget tax reform"},
            {"id": "a", "title": "Budget tax reform debate"},
            {"id": "c", "title": "Weather forecast"},
        ],
        threshold=0.25,
    )
    assert [item.article_id for item in groups[0]] == ["a", "b"]
    first, second = Issue("i1", "Budget"), Issue("i2", "Other")
    store = IssueClusterStore([first, second])
    store.add_membership("i1", "a", 0.8)
    store.add_membership("i2", "b", 0.7)
    merged = store.merge(["i1", "i2"], target_issue_id="i1", operation_key="merge-1")
    assert store.merge(["i2"], target_issue_id="i1", operation_key="merge-1") is merged
    split = store.split("i1", [["a"], ["b"]], operation_key="split-1", new_issue_ids=["i3", "i4"])
    assert [item.article_ids for item in split] == [("a",), ("b",)]


def test_analysis_schema_masking_ensemble_and_fact_check_independence():
    input_data = AssessmentInput(
        article_version_id="v1",
        title="Source headline",
        content="A useful article",
        source_name="Source",
    )
    providers = [DeterministicStubProvider(model_alias=f"m{i}") for i in range(3)]
    assessments = [provider.analyze_article(input_data, "prompt-1") for provider in providers]
    result = ensemble_assessments(assessments, max_spread=200)
    assert result.eligible and result.successful_model_count == 3
    assert result.y == 0 and result.z == 0
    assert all(item.y == 0 and item.z == 0 for item in assessments)
    assert fact_check_does_not_change_axes(assessments[0], "false").x == assessments[0].x
    assert "[REDACTED_EMAIL]" in sanitize_rationale("mail test@example.com")


def test_ensemble_spread_ignores_legacy_y_z_coordinates():
    common = {
        "article_version_id": "v1",
        "actual_model_id": "model",
        "prompt_version": "two-axis-v1",
        "x": 10,
        "sensationalism": 20,
        "confidence": 0.9,
    }
    assessments = [
        ModelAssessment(model_alias="left-legacy", y=-100, z=100, **common),
        ModelAssessment(model_alias="right-legacy", y=100, z=-100, **common),
    ]

    result = ensemble_assessments(assessments, min_success_models=2, max_spread=0)

    assert result.eligible and result.spread == 0
    assert (result.x, result.y, result.z, result.sensationalism) == (10, 0, 0, 20)


def test_score_is_clamped_and_byte_stable_and_source_prior_shrinks():
    components = ScoreComponents(
        (100, -100, 0),
        (100, -100, 0),
        (100, -100, 0),
        (100, -100, 0),
        model_confidence=0.9,
        vote_count=20,
        source_sample_size=20,
    )
    score = calculate_article_score(components, WeightProfile(version="v1"))
    assert score.x == 100 and score.y == 0 and score.z == 0
    assert score.components["model"] == [100.0, 0.0, 0.0]
    assert canonical_score_json(score) == canonical_score_json(score)
    prior = shrink_source_prior((100, 100, 100, 100), 1, (0, 0, 0, 50))
    assert prior.x < 10 and prior.confidence < 0.1


def test_revisioned_votes_and_segment_suppression():
    store = VoteRevisionStore()
    store.submit(vote_id="v1", user_id="u", article_id="a", x=1, y=2, z=3, sensationalism=4)
    store.revise("v1", x=5)
    assert len(store.history("u", "a")) == 2 and store.active()[0].x == 5
    assert store.active()[0].y == 0 and store.active()[0].z == 0
    result = aggregate_votes(store.active(), segment_by_user={"u": "small"}, min_segment_size=2)
    assert result["segments"] == {}
    assert result["aggregate"]["y"] == 0 and result["aggregate"]["z"] == 0


def test_vote_anomaly_and_behavior_profile_use_only_bias_and_sensationalism():
    profile = update_behavioral_profile(
        BehavioralProfile(y=99, z=-99),
        [
            BehaviorEvent(
                article_x=-40,
                article_y=100,
                article_z=-100,
                article_sensationalism=75,
            )
        ],
    )
    assert (profile.x, profile.sensationalism) == (-40, 75)
    assert profile.y == 0 and profile.z == 0

    # Legacy y/z differences do not make an otherwise repeated two-axis vote
    # distinct after canonicalization.
    first = Vote("a", "u", "one", 1, 10, -100, 100, 30)
    second = Vote("b", "u", "two", 1, 10, 100, -100, 30)
    from app.domains.scoring import detect_vote_anomaly

    assert detect_vote_anomaly(second, prior_votes=[first])


def test_feed_adjacent_and_fallback_reason_codes_and_source_limit():
    candidates = [
        FeedCandidate("1", "i1", "s1", x=30, relevance=0.8),
        FeedCandidate("2", "i2", "s1", x=35, relevance=0.8),
        FeedCandidate("3", "i3", "s2", x=-100, relevance=0.1),
    ]
    ranked = rank_feed(candidates, user_coordinates=(0, 0, 0), limit=3, max_consecutive_source=1)
    assert ranked[0].reason_code == "PERSONALIZED_ADJACENT"
    assert rank_feed(candidates, limit=1)[0].reason_code == "FALLBACK_BALANCED"


def test_feed_distance_uses_bias_and_sensationalism_not_legacy_coordinates():
    common = dict(issue_id="i", source_id="s", x=0, relevance=0.2)
    low = FeedCandidate("low", y=-100, z=100, sensationalism=0, **common)
    high = FeedCandidate("high", y=100, z=-100, sensationalism=100, **common)

    # A two-value profile is the canonical (x, sensationalism) shape. y/z
    # differ maximally but only sensationalism changes proximity.
    ranked = rank_feed([high, low], user_coordinates=(0, 0), limit=2)
    assert ranked[0].article_id == "low"


def test_read_eligibility_and_credit_reversal_are_idempotent():
    now = datetime.now(UTC)
    assert (
        evaluate_read_eligibility(
            outbound_at=now, returned_at=now + timedelta(seconds=1)
        ).reason_code
        == "TOO_FAST"
    )
    assert evaluate_read_eligibility(
        outbound_at=now, returned_at=now + timedelta(seconds=20)
    ).eligible
    ledger = CreditLedger()
    first = ledger.append(
        ledger_id="l1",
        user_id="u",
        event_type="READ_ELIGIBLE",
        event_key="event",
        delta=5,
        policy_version="v1",
    )
    assert (
        ledger.append(
            ledger_id="other",
            user_id="u",
            event_type="READ_ELIGIBLE",
            event_key="event",
            delta=5,
            policy_version="v1",
        )
        is first
    )
    ledger.reverse("l1", ledger_id="l2", event_key="rev", policy_version="v1")
    assert ledger.total("u") == 0


def test_efficacy_normalization_delta_and_small_cohort_hiding():
    assert normalize_efficacy_score([1, 5], reverse_indices=[1]) == 0
    from app.domains.efficacy import EfficacyResponse, calculate_efficacy_score

    baseline = calculate_efficacy_score(
        EfficacyResponse("b", "u", "q", (1, 2), datetime.now(UTC))
    )
    followup = calculate_efficacy_score(
        EfficacyResponse("f", "u", "q", (3, 4), datetime.now(UTC), kind="followup")
    )
    assert efficacy_delta(baseline, followup) > 0
    assert (
        aggregate_efficacy(
            [EfficacyResponse("x", "u", "q", (3,), datetime.now(UTC), cohort_key="tiny")],
            min_cohort_size=2,
        )["cohorts"]
        == {}
    )


def test_autopilot_guardrails_and_immutable_rollback():
    initial = WeightRevision("r0", 0, {"model": 0.5, "source": 0.5}, WeightRevisionStatus.ACTIVE)
    manager = AutoPilotManager(initial, mode=AutoPilotMode.RECOMMEND)
    draft = WeightRevision("r1", 1, {"model": 0.55, "source": 0.45}, WeightRevisionStatus.SIMULATION)
    manager.add_draft(draft)
    metrics = [
        SimulationMetrics(7, 0.1, 0.7, 0.01, 0.99, 1, 10),
        SimulationMetrics(30, 0.1, 0.7, 0.01, 0.99, 1, 10),
    ]
    result = evaluate_guardrails(
        initial.weights, draft.weights, metrics, baseline_metrics=metrics[0], reviewer_approved=True
    )
    manager.publish(
        "r1",
        if_match="r0",
        idempotency_key="publish",
        guardrail_result=result,
        reviewer_approved=True,
    )
    rollback = manager.rollback("r0", if_match="r1", idempotency_key="rollback")
    assert rollback.revision > 1 and manager.revisions["r0"].status == WeightRevisionStatus.ARCHIVED


def test_share_token_blob_limit_dedupe_and_revoke():
    token = create_public_token()
    snapshot = make_share_snapshot(
        coordinates=(1, 2, 3), confidence=0.9, tier="participant", activity=4
    )
    card = ShareCard(
        "c", "u", hash_public_token(token), "default", None, snapshot, ShareCardStatus.READY
    )
    cards = ShareCardStore()
    cards.add(card)
    assert cards.public_get(token)[0] == 200
    cards.revoke("c")
    assert cards.public_get(token)[0] == 404
    blobs = BlobStore(max_bytes=4)
    assert blobs.put(blob_id="b1", payload=b"1234") is blobs.put(blob_id="b2", payload=b"1234")
    with pytest.raises(BlobLimitError):
        blobs.put(blob_id="b3", payload=b"12345")
