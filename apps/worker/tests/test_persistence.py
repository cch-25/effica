from __future__ import annotations

import asyncio
from typing import Any

from apps.api.app.jobs.payloads import JobPayloadError, validate_job_payload
from apps.worker.worker.handlers import build_default_registry
from apps.worker.worker.main import WorkerConfig, WorkerRuntime
from apps.worker.worker.queue import Job, JobStatus, MemoryQueueRepository
from apps.worker.worker.services import MemoryResultApplier


def test_all_builtin_payload_contracts_accept_identifier_only_producers() -> None:
    values: dict[str, dict[str, Any]] = {
        "crawl": {"source_id": "source-1"},
        "cluster": {"article_ids": ["article-1"]},
        "analyze": {"article_version_id": "version-1"},
        "aggregate_votes": {"article_id": "article-1"},
        "calculate_score": {"article_version_id": "version-1"},
        "recommend_weights": {"recommendation_id": "recommendation-1"},
        "simulate_weights": {"weight_id": "weight-1"},
        "render_share_card": {"share_card_id": "card-1"},
        "export_user": {"user_id": "user-1"},
        "delete_user": {"user_id": "user-1", "confirmed": True},
        "merge_issue": {"source_issue_id": "issue-1", "target_issue_id": "issue-2"},
        "split_issue": {"issue_id": "issue-1", "article_ids": ["article-1"]},
    }
    for job_type, payload in values.items():
        assert validate_job_payload(job_type, payload) == payload


def test_payload_contract_rejects_unsafe_crawler_and_delete_replay() -> None:
    for job_type, payload in (
        ("crawl", {"url": "https://example.test", "source_type": "CRAWLER"}),
        ("delete_user", {"user_id": "user-1"}),
    ):
        try:
            validate_job_payload(job_type, payload)
        except JobPayloadError as exc:
            assert exc.code == "INVALID_JOB_PAYLOAD"
        else:  # pragma: no cover - assertion makes the contract failure clear.
            raise AssertionError(f"{job_type} payload unexpectedly accepted")


def test_runtime_applies_result_before_succeeded_and_keeps_memory_result() -> None:
    async def scenario() -> None:
        repository = MemoryQueueRepository(
            [Job(id="01RESULT", job_type="fixture", payload={"value": 7})]
        )
        applier = MemoryResultApplier()
        registry = build_default_registry()
        registry.register("fixture", lambda payload, context: {"value": payload["value"]})
        runtime = WorkerRuntime(
            repository,
            registry=registry,
            result_applier=applier,
            config=WorkerConfig(worker_id="result-worker"),
        )

        assert await runtime.process_one()
        stored = await repository.get("01RESULT")
        assert stored is not None
        assert stored.status is JobStatus.SUCCEEDED
        assert stored.result == {"value": 7}
        assert applier.results["01RESULT"] == {"value": 7}
        assert applier.contexts["01RESULT"]["job_type"] == "fixture"

    asyncio.run(scenario())


def test_memory_worker_job_chain_has_durable_result_records() -> None:
    async def scenario() -> None:
        jobs = [
            Job("01CHAINCRAWL", "crawl", {"url": "HTTPS://Example.test/a?b=2&a=1"}),
            Job("01CHAINANALYZE", "analyze", {"article_version_id": "version-1", "text": "evidence"}),
            Job(
                "01CHAINVOTES",
                "aggregate_votes",
                {
                    "article_id": "article-1",
                    "votes": [
                        {
                            "vote_id": "vote-1",
                            "user_id": "user-1",
                            "article_id": "article-1",
                            "revision": 1,
                            "x": 1,
                            "y": 2,
                            "z": 3,
                            "sensationalism": 4,
                        }
                    ],
                },
            ),
            Job(
                "01CHAINSCORE",
                "calculate_score",
                {
                    "article_version_id": "version-1",
                    "components": {
                        "model": {"x": 1, "y": 2, "z": 3},
                        "relative": {"x": 0, "y": 0, "z": 0},
                        "crowd": {"x": 0, "y": 0, "z": 0},
                        "source": {"x": 0, "y": 0, "z": 0},
                    },
                    "weights": {"model": 1, "relative": 0, "crowd": 0, "source": 0},
                },
            ),
            Job(
                "01CHAINSPLIT",
                "split_issue",
                {"issue_id": "issue-1", "article_ids": ["article-1"]},
            ),
            Job(
                "01CHAINSHARE",
                "render_share_card",
                {
                    "share_card_id": "card-1",
                    "snapshot": {"coordinate": {"x": 1, "y": 2, "z": 3}, "tier": "Explorer"},
                },
            ),
            Job("01CHAINEXPORT", "export_user", {"user_id": "user-1", "records": {"profile": {}}}),
            Job("01CHAINDELETE", "delete_user", {"user_id": "user-1", "confirmed": True}),
        ]
        repository = MemoryQueueRepository(jobs)
        applier = MemoryResultApplier()
        runtime = WorkerRuntime(
            repository,
            result_applier=applier,
            config=WorkerConfig(worker_id="chain-worker"),
        )
        while await runtime.process_one():
            pass
        rows = await repository.list_jobs()
        assert {row.status for row in rows} == {JobStatus.SUCCEEDED}
        assert set(applier.results) == {row.id for row in jobs}
        assert applier.results["01CHAINANALYZE"]["article_version_id"] == "version-1"
        assert applier.results["01CHAINEXPORT"]["artifact"]["records"] == {"profile": {}}
        assert applier.results["01CHAINDELETE"]["status"] == "scheduled"

    asyncio.run(scenario())
