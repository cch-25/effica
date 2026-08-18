"""MariaDB-backed lookup services used by identifier-only worker jobs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from statistics import fmean, pstdev
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import bindparam, text


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8")
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _mapping(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row._mapping if hasattr(row, "_mapping") else row)


class MariaDBWorkerLookups:
    """Short-lived SQL lookups shared by all production worker handlers."""

    def __init__(self, session_factory: Callable[[], Any], *, encryption_secret: str) -> None:
        self._session_factory = session_factory
        self._encryption_key = hashlib.sha256(encryption_secret.encode()).digest()

    async def _one(self, statement: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            result = await session.execute(text(statement), dict(params))
            return _mapping(result.mappings().first())

    async def _all(
        self, statement: str, params: Mapping[str, Any], *, expanding: str | None = None
    ) -> list[dict[str, Any]]:
        query = text(statement)
        if expanding:
            query = query.bindparams(bindparam(expanding, expanding=True))
        async with self._session_factory() as session:
            result = await session.execute(query, dict(params))
            return [dict(row) for row in result.mappings().all()]

    async def source_lookup(self, identifier: Any) -> dict[str, Any] | None:
        row = await self._one(
            """
            SELECT s.id AS source_id, s.name, s.source_type, s.canonical_url,
                   s.policy_status, s.robots_status, s.terms_status,
                   a.adapter_type, a.config_json, a.rate_limit,
                   a.raw_payload_retention_days
            FROM sources s
            LEFT JOIN source_adapters a ON a.source_id = s.id AND a.active = 1
            WHERE s.id = :identifier AND s.active = 1
            ORDER BY a.id LIMIT 1
            """,
            {"identifier": str(identifier)},
        )
        if row is None:
            return None
        row["config"] = _json_value(row.pop("config_json", None), {})
        row["url"] = row["canonical_url"]
        return row

    async def article_version_lookup(self, identifier: Any) -> dict[str, Any] | None:
        row = await self._one(
            """
            SELECT av.id AS article_version_id, av.article_id, a.title, a.author,
                   a.canonical_url AS source_url, s.name AS source_name,
                   b.payload AS normalized_payload
            FROM article_versions av
            JOIN articles a ON a.id = av.article_id
            JOIN sources s ON s.id = a.source_id
            LEFT JOIN stored_blobs b ON b.id = av.normalized_text_ref
            WHERE av.id = :identifier OR a.id = :identifier
            ORDER BY (av.id = :identifier) DESC, av.fetched_at DESC LIMIT 1
            """,
            {"identifier": str(identifier)},
        )
        if row is None:
            return None
        payload = row.pop("normalized_payload", None)
        if isinstance(payload, (bytes, bytearray)):
            row["text"] = bytes(payload).decode("utf-8", errors="replace")
        elif payload is not None:
            row["text"] = str(payload)
        return row

    async def articles_lookup(self, identifier: Any) -> list[dict[str, Any]]:
        ids = [str(value) for value in identifier] if isinstance(identifier, Sequence) and not isinstance(identifier, (str, bytes)) else [str(identifier)]
        if not ids:
            return []
        rows = await self._all(
            """
            SELECT a.id AS article_id, a.title, a.source_id, a.published_at,
                   b.payload AS body
            FROM articles a
            LEFT JOIN article_versions av ON av.id = a.current_version_id
            LEFT JOIN stored_blobs b ON b.id = av.normalized_text_ref
            WHERE a.id IN :identifiers
            """,
            {"identifiers": ids},
            expanding="identifiers",
        )
        for row in rows:
            body = row.get("body")
            row["body"] = bytes(body).decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
        return rows

    async def votes_lookup(self, identifier: Any) -> list[dict[str, Any]]:
        rows = await self._all(
            """
            SELECT id AS vote_id, user_id, article_id, revision, x, y, z,
                   sensationalism, quality_status, active, created_at, updated_at
            FROM votes WHERE article_id = :article_id AND active = 1
            ORDER BY user_id, revision
            """,
            {"article_id": str(identifier)},
        )
        return rows

    async def vote_snapshot_lookup(self, identifier: Any) -> dict[str, Any] | None:
        """Return the latest durable vote aggregate for one article.

        ``aggregate_votes`` uses this lookup when an incoming vote payload
        does not carry a revision.  Returning the aggregate and segment
        projections as well as both revision spellings keeps the production
        service aligned with the handler's fixture and in-memory contracts.
        """

        row = await self._one(
            """
            SELECT article_id, version, aggregate_json, segment_json, created_at
            FROM vote_aggregate_snapshots
            WHERE article_id = :article_id
            ORDER BY version DESC
            LIMIT 1
            """,
            {"article_id": str(identifier)},
        )
        if row is None:
            return None
        row["aggregate"] = _json_value(row.pop("aggregate_json", None), {})
        row["segments"] = _json_value(row.pop("segment_json", None), {})
        row["vote_revision"] = row.get("version")
        return row

    async def weights_lookup(self, identifier: Any) -> dict[str, Any] | None:
        identifier = str(identifier)
        where = "status = 'active'" if identifier == "active" else "id = :identifier"
        row = await self._one(
            f"""
            SELECT id, revision, status, weights_json, guardrails_json,
                   based_on_revision_id
            FROM weight_profile_revisions WHERE {where}
            ORDER BY revision DESC LIMIT 1
            """,
            {"identifier": identifier},
        )
        if row is None:
            return None
        row["weight_revision_id"] = row["id"]
        row["weights"] = _json_value(row.pop("weights_json", None), {})
        row["guardrails"] = _json_value(row.pop("guardrails_json", None), {})
        row["weights"].setdefault("version", str(row["revision"]))
        return row

    async def recommendation_lookup(self, identifier: Any) -> dict[str, Any] | None:
        row = await self._one(
            """
            SELECT r.id AS recommendation_id, r.base_revision_id,
                   r.proposed_weights_json, r.evidence_snapshot_id, r.status,
                   e.evidence_json
            FROM weight_recommendations r
            LEFT JOIN weight_evidence_snapshots e ON e.id = r.evidence_snapshot_id
            WHERE r.id = :identifier LIMIT 1
            """,
            {"identifier": str(identifier)},
        )
        if row is None:
            return None
        row["proposed_weights"] = _json_value(row.pop("proposed_weights_json", None), {})
        row["evidence_snapshot"] = _json_value(row.pop("evidence_json", None), {})
        return row

    async def share_card_lookup(self, identifier: Any) -> dict[str, Any] | None:
        row = await self._one(
            """
            SELECT id AS share_card_id, template, display_name, snapshot_json,
                   expires_at, status
            FROM share_cards
            WHERE id = :identifier AND revoked_at IS NULL AND status <> 'revoked'
            LIMIT 1
            """,
            {"identifier": str(identifier)},
        )
        if row is None:
            return None
        row["snapshot"] = _json_value(row.pop("snapshot_json", None), {})
        return row

    async def score_components_lookup(self, identifier: Any) -> dict[str, Any] | None:
        version = await self._one(
            """
            SELECT av.id AS article_version_id, av.article_id, a.source_id
            FROM article_versions av JOIN articles a ON a.id = av.article_id
            WHERE av.id = :identifier OR a.id = :identifier
            ORDER BY (av.id = :identifier) DESC, av.fetched_at DESC LIMIT 1
            """,
            {"identifier": str(identifier)},
        )
        if version is None:
            return None
        assessments = await self._all(
            """
            SELECT x, y, z, sensationalism, confidence
            FROM model_assessments
            WHERE article_version_id = :version_id AND status = 'SUCCEEDED'
            ORDER BY id
            """,
            {"version_id": version["article_version_id"]},
        )
        votes = await self.votes_lookup(version["article_id"])

        def axes(rows: list[dict[str, Any]]) -> tuple[float, float, float]:
            if not rows:
                return (0.0, 0.0, 0.0)
            return tuple(fmean(float(row[name]) for row in rows) for name in ("x", "y", "z"))  # type: ignore[return-value]

        model = axes(assessments)
        crowd_rows = [row for row in votes if row.get("quality_status") in {"VALID", "QUALIFIED"}]
        crowd = axes(crowd_rows)
        confidence = fmean(float(row["confidence"]) for row in assessments) if assessments else 0.0
        spread_values = [float(row[name]) for row in assessments for name in ("x", "y", "z")]
        spread = pstdev(spread_values) if len(spread_values) > 1 else 0.0
        sensationalism_rows = assessments or crowd_rows
        sensationalism = fmean(float(row["sensationalism"]) for row in sensationalism_rows) if sensationalism_rows else 0.0
        return {
            "components": {
                "model": model,
                "relative": model,
                "crowd": crowd,
                "source": (0.0, 0.0, 0.0),
                "model_confidence": confidence,
                "vote_count": len(crowd_rows),
                "source_sample_size": 0,
                "model_spread": spread,
                "sensationalism": sensationalism,
                "evidence_quality": min(1.0, len(assessments) / 3.0),
            }
        }

    async def analysis_model_lookup(self, identifier: Any = "active") -> dict[str, Any] | None:
        """Return the single active OpenAI GPT configuration for analysis.

        The lookup runs for every analysis job so administrator changes take
        effect without recycling worker processes. Legacy provider rows remain
        available as history but can never be selected for outbound calls.
        """

        del identifier
        row = await self._one(
            """
            SELECT id AS model_alias_id, alias, provider, actual_model_id, config_json
            FROM model_aliases
            WHERE status = 'ACTIVE' AND provider = 'openai'
              AND actual_model_id LIKE 'gpt-%'
            ORDER BY id DESC LIMIT 1
            """,
            {},
        )
        if row is None:
            return None
        config = _json_value(row.pop("config_json", None), {})
        row["reasoning_effort"] = str(config.get("reasoning_effort", "xhigh"))
        return row

    async def export_records_lookup(self, identifier: Any) -> dict[str, Any]:
        user_id = str(identifier)
        records: dict[str, Any] = {}
        queries = {
            "user": "SELECT id, display_name, role, status, created_at, updated_at, deleted_at FROM users WHERE id = :user_id",
            "consents": "SELECT consent_version_id, granted, granted_at, withdrawn_at FROM user_consents WHERE user_id = :user_id ORDER BY granted_at",
            "profiles": "SELECT kind, x, y, z, confidence, source_version, active, created_at FROM user_profiles WHERE user_id = :user_id ORDER BY created_at",
            "demographics": "SELECT age_band, gender_response, updated_at FROM user_demographics WHERE user_id = :user_id",
            "votes": "SELECT article_id, revision, x, y, z, sensationalism, quality_status, active, created_at FROM votes WHERE user_id = :user_id ORDER BY created_at",
            "reads": "SELECT article_id, status, outbound_at, returned_at, client_elapsed_ms, policy_version FROM read_sessions WHERE user_id = :user_id ORDER BY outbound_at",
            "credits": "SELECT event_type, event_key, delta, status, policy_version, created_at FROM credit_ledger WHERE user_id = :user_id ORDER BY created_at",
            "efficacy": "SELECT questionnaire_version_id, normalized_score, submitted_at FROM efficacy_responses WHERE user_id = :user_id ORDER BY submitted_at",
            "share_cards": "SELECT id, template, display_name, snapshot_json, status, expires_at, revoked_at, created_at FROM share_cards WHERE user_id = :user_id ORDER BY created_at",
            "oauth_accounts": "SELECT provider, provider_subject FROM oauth_accounts WHERE user_id = :user_id ORDER BY provider, provider_subject",
            "sessions": "SELECT token_hash, csrf_hash, expires_at, revoked_at FROM sessions WHERE user_id = :user_id ORDER BY expires_at",
            "feed_impressions": "SELECT article_id, issue_id, reason_code, rank, created_at FROM feed_impressions WHERE user_id = :user_id ORDER BY created_at",
        }
        for name, query in queries.items():
            rows = await self._all(query, {"user_id": user_id})
            for row in rows:
                if "snapshot_json" in row:
                    row["snapshot"] = _json_value(row.pop("snapshot_json"), {})
            records[name] = rows[0] if name in {"user", "demographics"} and rows else (None if name in {"user", "demographics"} else rows)
        responses = await self._all(
            "SELECT id, questionnaire_version_id, encrypted_payload, submitted_at FROM questionnaire_responses WHERE user_id = :user_id ORDER BY submitted_at",
            {"user_id": user_id},
        )
        for row in responses:
            encrypted = bytes(row.pop("encrypted_payload"))
            try:
                plain = AESGCM(self._encryption_key).decrypt(encrypted[:12], encrypted[12:], str(row["id"]).encode())
                row["answers"] = json.loads(plain)
            except Exception:
                row["answers_unavailable"] = True
        records["questionnaire_responses"] = responses
        return records

    async def deletion_policy_lookup(self, identifier: Any) -> None:
        del identifier
        return None

    def as_services(self) -> dict[str, Any]:
        return {
            "source_lookup": self.source_lookup,
            "article_version_lookup": self.article_version_lookup,
            "articles_lookup": self.articles_lookup,
            "votes_lookup": self.votes_lookup,
            "vote_snapshot_lookup": self.vote_snapshot_lookup,
            "weights_lookup": self.weights_lookup,
            "recommendation_lookup": self.recommendation_lookup,
            "share_card_lookup": self.share_card_lookup,
            "score_components_lookup": self.score_components_lookup,
            "analysis_model_lookup": self.analysis_model_lookup,
            "export_records_lookup": self.export_records_lookup,
            "deletion_policy_lookup": self.deletion_policy_lookup,
        }
