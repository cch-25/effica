"""Replace synthetic development content with verified Korean news articles.

This importer is intentionally separate from the worker crawler.  It loads a
checked-in snapshot of manually verified article pages, removes the legacy
synthetic seed namespace, and writes the content graph in one transaction.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

from apps.api.app.core.config import get_settings
from apps.api.app.db.session import create_engine, dispose_engine
from apps.api.app.db.ulid import _encode_ulid
from apps.api.app.domains.issues.topics import infer_issue_topic
from db.seeds.pipeline_recovery import (
    default_recovery_generation,
    run_pipeline_recovery,
)

ARTICLE_DATA = Path(__file__).with_name("articles.json")
MINIMUM_ARTICLE_COUNT = 50
LEGACY_SEED_ID_PREFIX = "01J000000000000000000"
REAL_SEED_ID_PREFIX = "01M03XWF00NEWSSEED"
_KOREAN_RE = re.compile(r"[가-힣]")


def _stable_ulid(kind: str, key: str) -> str:
    """Return a canonical deterministic ULID in the real-article namespace."""

    digest = hashlib.sha256(f"korean-news-seed:{kind}:{key}".encode()).digest()
    suffix = _encode_ulid(int.from_bytes(digest[:5], "big"))[-8:]
    identifier = f"{REAL_SEED_ID_PREFIX}{suffix}"
    if not identifier.startswith(REAL_SEED_ID_PREFIX):
        raise RuntimeError("real article seed ULID namespace changed unexpectedly")
    return identifier


def _parse_published_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"published_at must include a timezone: {value}")
    return parsed.astimezone(UTC).replace(tzinfo=None)


def _score_components(
    *,
    assessment: dict[str, Any],
    assessment_id: str,
    category: str,
    bias_label: str,
) -> dict[str, Any]:
    """Build a public score component payload with durable AI provenance."""

    return {
        "analysis_provider": "openai",
        "assessment_ids": [assessment_id],
        "actual_model_ids": [assessment["actual_model_id"]],
        "분석방식": "LLM",
        "평가기준": ["편향성", "과장성"],
        "편향판정": bias_label,
        "분류": category,
        "근거요약": assessment["rationale_summary"],
        "모델평가ID": assessment_id,
        "모델별칭": assessment["model_alias"],
        "프롬프트버전": assessment["prompt_version"],
        "호환필드": {"y": 0, "z": 0},
    }


def _assessment_evidence_payload(assessment: dict[str, Any]) -> dict[str, Any]:
    """Keep the public model summary beside its structured evidence."""

    return {
        "rationale_summary": assessment["rationale_summary"],
        "evidence": assessment["evidence"],
    }


def _load_articles(*, require_assessments: bool = True) -> list[dict[str, Any]]:
    payload = json.loads(ARTICLE_DATA.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) < MINIMUM_ARTICLE_COUNT:
        raise ValueError(f"articles.json must contain at least {MINIMUM_ARTICLE_COUNT} rows")

    required = {
        "source_name",
        "source_home_url",
        "canonical_url",
        "title",
        "published_at",
        "body_text",
        "category",
    }
    urls: set[str] = set()
    for index, row in enumerate(payload, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"article {index} must be an object")
        missing = sorted(required - row.keys())
        if missing:
            raise ValueError(f"article {index} is missing fields: {', '.join(missing)}")
        for field in required:
            if not isinstance(row[field], str) or not row[field].strip():
                raise ValueError(f"article {index} has an empty {field}")
            row[field] = row[field].strip()
        for field in ("title", "body_text", "category", "source_name"):
            if not _KOREAN_RE.search(row[field]):
                raise ValueError(f"article {index} {field} is not Korean")
        if len(row["body_text"]) < 200:
            raise ValueError(f"article {index} body_text is too short to be an original article")
        for field in ("source_home_url", "canonical_url"):
            parsed = urlparse(row[field])
            if parsed.scheme != "https" or not parsed.netloc:
                raise ValueError(f"article {index} {field} must be a direct HTTPS URL")
        if row["canonical_url"] in urls:
            raise ValueError(f"duplicate canonical_url: {row['canonical_url']}")
        urls.add(row["canonical_url"])
        _parse_published_at(row["published_at"])
        author = row.get("author")
        row["author"] = author.strip() if isinstance(author, str) and author.strip() else None
        if require_assessments:
            assessment = row.get("llm_assessment")
            if not isinstance(assessment, dict):
                raise ValueError(f"article {index} is missing its LLM assessment")
            assessment_required = {
                "model_alias",
                "actual_model_id",
                "prompt_version",
                "bias",
                "sensationalism",
                "confidence",
                "evidence",
                "rationale_summary",
                "token_usage",
                "latency_ms",
                "status",
            }
            assessment_missing = sorted(assessment_required - assessment.keys())
            if assessment_missing:
                raise ValueError(
                    f"article {index} assessment is missing fields: "
                    f"{', '.join(assessment_missing)}"
                )
            bias = assessment["bias"]
            sensationalism = assessment["sensationalism"]
            confidence = assessment["confidence"]
            if not isinstance(bias, int) or not -100 <= bias <= 100:
                raise ValueError(f"article {index} assessment bias is invalid")
            if not isinstance(sensationalism, int) or not 0 <= sensationalism <= 100:
                raise ValueError(f"article {index} assessment sensationalism is invalid")
            if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ValueError(f"article {index} assessment confidence is invalid")
            if assessment["status"] != "SUCCEEDED":
                raise ValueError(f"article {index} assessment did not succeed")
            if assessment["prompt_version"] != "bias-sensationalism-v1":
                raise ValueError(f"article {index} assessment prompt version is invalid")
            if not str(assessment["actual_model_id"]).startswith("gpt-"):
                raise ValueError(f"article {index} assessment model is not OpenAI GPT")
    return payload


async def _delete_seed_content(connection: Any) -> None:
    patterns = {
        "legacy": f"{LEGACY_SEED_ID_PREFIX}%",
        "real": f"{REAL_SEED_ID_PREFIX}%",
    }
    params = {"legacy": patterns["legacy"], "real": patterns["real"]}
    article_match = "id LIKE :legacy OR id LIKE :real"
    version_match = "article_id IN (SELECT id FROM articles WHERE " + article_match + ")"

    await connection.execute(
        text(
            "DELETE FROM feed_impressions WHERE article_id IN "
            f"(SELECT id FROM articles WHERE {article_match})"
        ),
        params,
    )
    for table in ("read_sessions", "vote_aggregate_snapshots", "votes", "fact_check_references"):
        await connection.execute(
            text(
                f"DELETE FROM {table} WHERE article_id IN "
                f"(SELECT id FROM articles WHERE {article_match})"
            ),
            params,
        )
    await connection.execute(
        text(
            "DELETE FROM issue_memberships WHERE article_id IN "
            f"(SELECT id FROM articles WHERE {article_match}) "
            "OR issue_id LIKE :legacy OR issue_id LIKE :real"
        ),
        params,
    )
    for table in ("score_versions", "model_assessments"):
        await connection.execute(
            text(
                f"DELETE FROM {table} WHERE article_version_id IN "
                f"(SELECT id FROM article_versions WHERE {version_match})"
            ),
            params,
        )
    await connection.execute(
        text(
            "DELETE FROM weight_simulations WHERE recommendation_id IN "
            "(SELECT id FROM weight_recommendations WHERE base_revision_id LIKE :legacy)"
        ),
        params,
    )
    await connection.execute(
        text("DELETE FROM weight_recommendations WHERE base_revision_id LIKE :legacy"), params
    )
    await connection.execute(
        text("DELETE FROM weight_profile_revisions WHERE id LIKE :legacy"), params
    )
    await connection.execute(
        text(f"UPDATE articles SET current_version_id = NULL WHERE {article_match}"), params
    )
    await connection.execute(text(f"DELETE FROM article_versions WHERE {version_match}"), params)
    await connection.execute(text(f"DELETE FROM articles WHERE {article_match}"), params)
    await connection.execute(
        text("DELETE FROM crawl_runs WHERE source_id LIKE :legacy OR source_id LIKE :real"), params
    )
    await connection.execute(
        text("DELETE FROM source_adapters WHERE source_id LIKE :legacy OR source_id LIKE :real"),
        params,
    )
    await connection.execute(
        text("DELETE FROM sources WHERE id LIKE :legacy OR id LIKE :real"), params
    )
    await connection.execute(
        text("DELETE FROM issues WHERE id LIKE :legacy OR id LIKE :real"), params
    )
    await connection.execute(
        text(
            "DELETE FROM stored_blobs WHERE (id LIKE :legacy OR id LIKE :real) "
            "AND id NOT IN (SELECT blob_id FROM share_cards WHERE blob_id IS NOT NULL)"
        ),
        params,
    )


async def _insert_articles(connection: Any, articles: list[dict[str, Any]]) -> None:
    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    sources = {
        (row["source_name"], row["source_home_url"])
        for row in articles
    }
    source_ids: dict[str, str] = {}
    for source_name, source_url in sorted(sources):
        existing = await connection.execute(
            text(
                """
                SELECT sources.id
                FROM sources
                WHERE sources.active = 1
                  AND (
                    sources.canonical_url = :url
                    OR LOWER(TRIM(sources.name)) = LOWER(TRIM(:name))
                  )
                ORDER BY
                  CASE WHEN sources.policy_status = 'APPROVED'
                         AND sources.robots_status = 'APPROVED'
                         AND sources.terms_status = 'APPROVED'
                         AND EXISTS (
                           SELECT 1 FROM source_adapters
                           WHERE source_adapters.source_id = sources.id
                             AND source_adapters.active = 1
                         )
                    THEN 0
                    WHEN sources.canonical_url = :url THEN 1
                    ELSE 2
                  END,
                  sources.id
                LIMIT 1
                """
            ),
            {"name": source_name[:255], "url": source_url},
        )
        existing_source_id = existing.scalar_one_or_none()
        if existing_source_id is not None:
            source_ids[source_url] = str(existing_source_id)
            continue
        source_id = _stable_ulid("source", source_url)
        await connection.execute(
            text(
                """
                INSERT INTO sources
                  (id, name, source_type, canonical_url, policy_status,
                   robots_status, terms_status, active)
                VALUES
                  (:id, :name, 'CRAWLER', :url, 'PENDING', 'PENDING', 'PENDING', 1)
                """
            ),
            {
                "id": source_id,
                "name": source_name[:255],
                "url": source_url,
            },
        )
        source_ids[source_url] = source_id

    category_dates: dict[str, list[datetime]] = {}
    for row in articles:
        category_dates.setdefault(row["category"], []).append(
            _parse_published_at(row["published_at"])
        )
    for category, dates in sorted(category_dates.items()):
        await connection.execute(
            text(
                """
                INSERT INTO issues
                  (id, title, summary, topic, status, opened_at, last_activity_at, version)
                VALUES (:id, :title, :summary, :topic, 'active', :opened_at, :last_activity_at, 1)
                """
            ),
            {
                "id": _stable_ulid("issue", category),
                "title": category[:500],
                "summary": f"{category} 분야의 최신 한국어 원문 기사 모음",
                "topic": infer_issue_topic(category, f"{category} 분야의 최신 한국어 원문 기사 모음"),
                "opened_at": min(dates),
                "last_activity_at": max(dates),
            },
        )

    model_alias_id = _stable_ulid("model-alias", "openai-bias-v1")
    assessment_models = {row["llm_assessment"]["actual_model_id"] for row in articles}
    if len(assessment_models) != 1:
        raise ValueError("all article assessments must use the same OpenAI model")
    actual_model_id = next(iter(assessment_models))
    await connection.execute(
        text(
            """
            INSERT INTO model_aliases
              (id, alias, provider, actual_model_id, status, config_json)
            VALUES
              (:id, 'openai-bias-v1', 'openai', :actual_model_id, 'DEPRECATED', :config_json)
            ON DUPLICATE KEY UPDATE actual_model_id = VALUES(actual_model_id),
              provider = VALUES(provider), status = VALUES(status),
              config_json = VALUES(config_json)
            """
        ),
        {
            "id": model_alias_id,
            "actual_model_id": actual_model_id,
            "config_json": json.dumps(
                {
                    "평가기준": ["편향성", "과장성"],
                    "프롬프트버전": "bias-sensationalism-v1",
                },
                ensure_ascii=False,
            ),
        },
    )

    weight_id = _stable_ulid("weight", "llm-only-bias")
    await connection.execute(
        text(
            """
            INSERT INTO weight_profile_revisions
              (id, revision, status, weights_json, guardrails_json,
               based_on_revision_id, created_by, created_at, published_at)
            VALUES
              (:id, 20260816, 'active', :weights, :guardrails,
               NULL, NULL, :created_at, :created_at)
            ON DUPLICATE KEY UPDATE status = VALUES(status),
              weights_json = VALUES(weights_json), guardrails_json = VALUES(guardrails_json),
              published_at = VALUES(published_at)
            """
        ),
        {
            "id": weight_id,
            "weights": json.dumps(
                {"model": 1.0, "relative": 0.0, "crowd": 0.0, "source": 0.0},
                ensure_ascii=False,
            ),
            "guardrails": json.dumps(
                {
                    "평가기준": ["편향성", "과장성"],
                    "호환필드": {"y": 0, "z": 0},
                    "설명": "LLM 평가를 그대로 사용하는 실제 기사 스냅샷",
                },
                ensure_ascii=False,
            ),
            "created_at": fetched_at,
        },
    )

    for row in articles:
        url = row["canonical_url"]
        body = row["body_text"].encode("utf-8")
        article_id = _stable_ulid("article", url)
        blob_id = _stable_ulid("blob", url)
        version_id = _stable_ulid("version", url)
        source_id = source_ids[row["source_home_url"]]
        published_at = _parse_published_at(row["published_at"])
        assessment = row["llm_assessment"]
        bias = int(assessment["bias"])
        sensationalism = int(assessment["sensationalism"])
        confidence = float(assessment["confidence"])
        assessment_id = _stable_ulid("assessment", url)
        await connection.execute(
            text(
                """
                INSERT INTO articles
                  (id, source_id, canonical_url, canonical_url_hash, title, author,
                   published_at, current_version_id, status, created_at, updated_at)
                VALUES
                  (:id, :source_id, :url, :url_hash, :title, :author,
                   :published_at, NULL, 'active', :created_at, :updated_at)
                """
            ),
            {
                "id": article_id,
                "source_id": source_id,
                "url": url,
                "url_hash": hashlib.sha256(url.encode()).digest(),
                "title": row["title"][:500],
                "author": row["author"][:255] if row["author"] else None,
                "published_at": published_at,
                "created_at": fetched_at,
                "updated_at": fetched_at,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO stored_blobs
                  (id, sha256, mime_type, byte_size, payload, expires_at, created_at)
                VALUES
                  (:id, :sha256, 'text/plain; charset=utf-8', :byte_size,
                   :payload, NULL, :created_at)
                """
            ),
            {
                "id": blob_id,
                "sha256": hashlib.sha256(body).digest(),
                "byte_size": len(body),
                "payload": body,
                "created_at": fetched_at,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO article_versions
                  (id, article_id, content_hash, normalized_text_ref, raw_payload_ref,
                   raw_payload_expires_at, fetched_at, modified_at)
                VALUES
                  (:id, :article_id, :content_hash, :blob_id, NULL, NULL, :fetched_at, NULL)
                """
            ),
            {
                "id": version_id,
                "article_id": article_id,
                "content_hash": hashlib.sha256(body).digest(),
                "blob_id": blob_id,
                "fetched_at": fetched_at,
            },
        )
        await connection.execute(
            text("UPDATE articles SET current_version_id = :version_id WHERE id = :article_id"),
            {"version_id": version_id, "article_id": article_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO issue_memberships
                  (issue_id, article_id, confidence, created_at)
                VALUES (:issue_id, :article_id, 1.0000, :created_at)
                """
            ),
            {
                "issue_id": _stable_ulid("issue", row["category"]),
                "article_id": article_id,
                "created_at": fetched_at,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO model_assessments
                  (id, article_version_id, model_alias_id, prompt_version, x, y, z,
                   sensationalism, confidence, evidence_json, raw_response_ref,
                   token_usage, latency_ms, status, created_at)
                VALUES
                  (:id, :version_id, :model_alias_id, :prompt_version, :bias, 0, 0,
                   :sensationalism, :confidence, :evidence, NULL,
                   :token_usage, :latency_ms, 'SUCCEEDED', :created_at)
                """
            ),
            {
                "id": assessment_id,
                "version_id": version_id,
                "model_alias_id": model_alias_id,
                "prompt_version": assessment["prompt_version"],
                "bias": bias,
                "sensationalism": sensationalism,
                "confidence": confidence,
                "evidence": json.dumps(
                    _assessment_evidence_payload(assessment),
                    ensure_ascii=False,
                ),
                "token_usage": int(assessment["token_usage"]),
                "latency_ms": int(assessment["latency_ms"]),
                "created_at": fetched_at,
            },
        )
        bias_label = "좌편향" if bias < -10 else "우편향" if bias > 10 else "중립적"
        await connection.execute(
            text(
                """
                INSERT INTO score_versions
                  (id, article_version_id, weight_revision_id, x, y, z,
                   sensationalism, confidence, components_json, status, created_at)
                VALUES
                  (:id, :version_id, :weight_id, :bias, 0, 0, :sensationalism,
                   :confidence, :components, 'active', :created_at)
                """
            ),
            {
                "id": _stable_ulid("score", url),
                "version_id": version_id,
                "weight_id": weight_id,
                "bias": bias,
                "sensationalism": sensationalism,
                "confidence": confidence,
                "components": json.dumps(
                    _score_components(
                        assessment=assessment,
                        assessment_id=assessment_id,
                        category=row["category"],
                        bias_label=bias_label,
                    ),
                    ensure_ascii=False,
                ),
                "created_at": fetched_at,
            },
        )


async def seed(*, dry_run: bool = False) -> dict[str, int]:
    articles = _load_articles()
    summary = {
        "articles": len(articles),
        "sources": len({row["source_home_url"] for row in articles}),
        "issues": len({row["category"] for row in articles}),
    }
    if dry_run:
        return summary

    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            await _delete_seed_content(connection)
            await _insert_articles(connection, articles)
            actual = (
                await connection.execute(
                    text("SELECT COUNT(*) FROM articles WHERE id LIKE :prefix"),
                    {"prefix": f"{REAL_SEED_ID_PREFIX}%"},
                )
            ).scalar_one()
            legacy = (
                await connection.execute(
                    text("SELECT COUNT(*) FROM articles WHERE id LIKE :prefix"),
                    {"prefix": f"{LEGACY_SEED_ID_PREFIX}%"},
                )
            ).scalar_one()
            graph = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          COUNT(DISTINCT a.current_version_id) AS versions,
                          COUNT(DISTINCT ma.id) AS assessments,
                          COUNT(DISTINCT sv.id) AS scores,
                          SUM(CASE WHEN ma.y <> 0 OR ma.z <> 0 OR sv.y <> 0 OR sv.z <> 0
                              THEN 1 ELSE 0 END) AS nonzero_legacy_axes
                        FROM articles a
                        JOIN article_versions av ON av.id = a.current_version_id
                        JOIN model_assessments ma
                          ON ma.article_version_id = av.id
                         AND ma.prompt_version = 'bias-sensationalism-v1'
                         AND ma.status = 'SUCCEEDED'
                        JOIN score_versions sv ON sv.article_version_id = av.id
                        WHERE a.id LIKE :prefix
                        """
                    ),
                    {"prefix": f"{REAL_SEED_ID_PREFIX}%"},
                )
            ).mappings().one()
            expected = len(articles)
            graph_counts = {
                "versions": int(graph["versions"] or 0),
                "assessments": int(graph["assessments"] or 0),
                "scores": int(graph["scores"] or 0),
            }
            if (
                int(actual) != expected
                or int(legacy) != 0
                or any(count != expected for count in graph_counts.values())
                or int(graph["nonzero_legacy_axes"] or 0) != 0
            ):
                raise RuntimeError(
                    f"article replacement incomplete: expected={expected}, actual={actual}, "
                    f"legacy={legacy}, graph={graph_counts}, "
                    f"nonzero_legacy_axes={graph['nonzero_legacy_axes']}"
                )
    finally:
        await dispose_engine()
    return summary


async def verify_database() -> dict[str, int]:
    articles = _load_articles()
    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            graph = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          COUNT(DISTINCT a.id) AS articles,
                          COUNT(DISTINCT av.id) AS versions,
                          COUNT(DISTINCT b.id) AS blobs,
                          COUNT(DISTINCT ma.id) AS assessments,
                          COUNT(DISTINCT sv.id) AS scores,
                          SUM(CASE WHEN ma.y <> 0 OR ma.z <> 0 OR sv.y <> 0 OR sv.z <> 0
                              THEN 1 ELSE 0 END) AS nonzero_legacy_axes,
                          SUM(CASE WHEN sv.x < -10 THEN 1 ELSE 0 END) AS left_count,
                          SUM(CASE WHEN sv.x BETWEEN -10 AND 10 THEN 1 ELSE 0 END) AS neutral_count,
                          SUM(CASE WHEN sv.x > 10 THEN 1 ELSE 0 END) AS right_count
                        FROM articles a
                        JOIN article_versions av ON av.id = a.current_version_id
                        JOIN stored_blobs b ON b.id = av.normalized_text_ref
                        JOIN model_assessments ma
                          ON ma.article_version_id = av.id
                         AND ma.prompt_version = 'bias-sensationalism-v1'
                         AND ma.status = 'SUCCEEDED'
                        JOIN score_versions sv ON sv.article_version_id = av.id
                        WHERE a.id LIKE :prefix
                        """
                    ),
                    {"prefix": f"{REAL_SEED_ID_PREFIX}%"},
                )
            ).mappings().one()
            legacy = (
                await connection.execute(
                    text(
                        """
                        SELECT
                          (SELECT COUNT(*) FROM articles WHERE id LIKE :legacy) AS articles,
                          (SELECT COUNT(*) FROM sources WHERE id LIKE :legacy) AS sources,
                          (SELECT COUNT(*) FROM issues WHERE id LIKE :legacy) AS issues
                        """
                    ),
                    {"legacy": f"{LEGACY_SEED_ID_PREFIX}%"},
                )
            ).mappings().one()
            titles = list(
                (
                    await connection.execute(
                        text("SELECT title FROM articles WHERE id LIKE :prefix"),
                        {"prefix": f"{REAL_SEED_ID_PREFIX}%"},
                    )
                ).scalars()
            )
            issue_titles = list(
                (
                    await connection.execute(
                        text("SELECT title FROM issues WHERE id LIKE :prefix"),
                        {"prefix": f"{REAL_SEED_ID_PREFIX}%"},
                    )
                ).scalars()
            )
    finally:
        await dispose_engine()

    expected = len(articles)
    counts = {key: int(graph[key] or 0) for key in ("articles", "versions", "blobs", "assessments", "scores")}
    if (
        any(value != expected for value in counts.values())
        or any(int(legacy[key] or 0) != 0 for key in ("articles", "sources", "issues"))
        or int(graph["nonzero_legacy_axes"] or 0) != 0
        or any(not _KOREAN_RE.search(title) for title in [*titles, *issue_titles])
    ):
        raise RuntimeError(
            f"database verification failed: counts={counts}, legacy={dict(legacy)}, "
            f"nonzero_legacy_axes={graph['nonzero_legacy_axes']}"
        )
    return {
        **counts,
        "left": int(graph["left_count"] or 0),
        "neutral": int(graph["neutral_count"] or 0),
        "right": int(graph["right_count"] or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="실제 한국어 기사 스냅샷을 적재합니다")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB에 연결하지 않고 기사 스냅샷을 검증합니다",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="DB를 변경하지 않고 실제 기사 그래프를 검증합니다",
    )
    parser.add_argument(
        "--repair-pipeline",
        action="store_true",
        help="기본 시드 적재 없이 기존 콘텐츠 파이프라인 결함을 진단·복구합니다",
    )
    parser.add_argument(
        "--generation",
        help="복구 큐 dedupe 세대(기본값: 현재 UTC 날짜)",
    )
    parser.add_argument(
        "--bootstrap-news-sources",
        action="store_true",
        help="검수된 공공기관 공식 RSS 출처를 복구 과정에서 함께 등록합니다",
    )
    args = parser.parse_args()
    if args.repair_pipeline and args.verify_only:
        parser.error("--repair-pipeline과 --verify-only는 함께 사용할 수 없습니다")
    if args.generation and not args.repair_pipeline:
        parser.error("--generation은 --repair-pipeline과 함께 사용해야 합니다")
    if args.bootstrap_news_sources and not args.repair_pipeline:
        parser.error("--bootstrap-news-sources는 --repair-pipeline과 함께 사용해야 합니다")
    if args.repair_pipeline:
        report = asyncio.run(
            run_pipeline_recovery(
                generation=args.generation or default_recovery_generation(),
                dry_run=args.dry_run,
                bootstrap_sources=args.bootstrap_news_sources,
            )
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    if args.dry_run and args.verify_only:
        parser.error("--dry-run과 --verify-only는 함께 사용할 수 없습니다")
    if args.verify_only:
        verified = asyncio.run(verify_database())
        print(
            "원격 DB 검증 완료: "
            f"기사/본문/평가/점수 각 {verified['articles']}개, "
            f"좌편향 {verified['left']}개, 중립적 {verified['neutral']}개, "
            f"우편향 {verified['right']}개"
        )
        return 0
    summary = asyncio.run(seed(dry_run=args.dry_run))
    action = "검증" if args.dry_run else "적재"
    print(
        f"실제 한국어 기사 {action} 완료: "
        f"기사 {summary['articles']}개, 출처 {summary['sources']}개, "
        f"카탈로그 {summary['issues']}개"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
