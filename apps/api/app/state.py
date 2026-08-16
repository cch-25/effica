from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import ulid


def new_id() -> str:
    return str(ulid.new())


def utcnow() -> datetime:
    return datetime.now(UTC)


def stable_hash(value: str | bytes) -> str:
    payload = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def encode_cursor(index: int) -> str:
    return base64.urlsafe_b64encode(f"v1:{index}".encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        version, value = base64.urlsafe_b64decode(padded).decode().split(":", 1)
        if version != "v1" or int(value) < 0:
            raise ValueError
        return int(value)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid cursor") from exc


@dataclass(slots=True)
class PlatformState:
    """Deterministic local backend used when APP_BACKEND=memory.

    The same public services can be backed by SQLAlchemy repositories. Keeping this adapter complete
    makes the full product flow reproducible without external providers or a running database.
    """

    lock: threading.RLock = field(default_factory=threading.RLock)
    default_users: dict[str, str] = field(default_factory=dict)
    users: dict[str, dict[str, Any]] = field(default_factory=dict)
    oauth_accounts: dict[tuple[str, str], str] = field(default_factory=dict)
    oauth_challenges: dict[str, dict[str, Any]] = field(default_factory=dict)
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    consents: dict[str, dict[str, Any]] = field(default_factory=dict)
    consent_grants: dict[tuple[str, str], bool] = field(default_factory=dict)
    questionnaires: dict[str, dict[str, Any]] = field(default_factory=dict)
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    demographics: dict[str, dict[str, Any]] = field(default_factory=dict)
    sources: dict[str, dict[str, Any]] = field(default_factory=dict)
    articles: dict[str, dict[str, Any]] = field(default_factory=dict)
    issues: dict[str, dict[str, Any]] = field(default_factory=dict)
    assessments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    scores: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    votes: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    read_sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    credits: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    efficacy: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    share_cards: dict[str, dict[str, Any]] = field(default_factory=dict)
    public_cards: dict[str, str] = field(default_factory=dict)
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    models: dict[str, dict[str, Any]] = field(default_factory=dict)
    weights: dict[str, dict[str, Any]] = field(default_factory=dict)
    recommendations: dict[str, dict[str, Any]] = field(default_factory=dict)
    simulations: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    autopilot: dict[str, Any] = field(default_factory=dict)
    audit: list[dict[str, Any]] = field(default_factory=list)
    idempotency: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.users:
            self._seed()

    def _seed(self) -> None:
        member_id, analyst_id, reviewer_id, admin_id = (new_id() for _ in range(4))
        for user_id, role, name in [
            (member_id, "MEMBER", "Local Member"),
            (analyst_id, "ANALYST", "Local Analyst"),
            (reviewer_id, "REVIEWER", "Local Reviewer"),
            (admin_id, "ADMIN", "Local Admin"),
        ]:
            self.users[user_id] = {
                "id": user_id,
                "display_name": name,
                "role": role,
                "status": "ACTIVE",
                "consent_complete": False,
                "onboarding_complete": False,
                "behavioral_profile_active": False,
                "created_at": utcnow(),
            }
        self.users[member_id]["consent_complete"] = True
        self.users[member_id]["onboarding_complete"] = True
        self.default_users = {
            "MEMBER": member_id,
            "ANALYST": analyst_id,
            "REVIEWER": reviewer_id,
            "ADMIN": admin_id,
        }
        service_consent, political_consent, questionnaire = new_id(), new_id(), new_id()
        self.consents[service_consent] = {
            "id": service_consent,
            "purpose": "SERVICE",
            "version": "1.0",
            "body_hash": stable_hash("service-consent-v1"),
            "sensitive": False,
        }
        self.consents[political_consent] = {
            "id": political_consent,
            "purpose": "POLITICAL_PROFILE",
            "version": "1.0",
            "body_hash": stable_hash("political-profile-consent-v1"),
            "sensitive": True,
        }
        self.consent_grants[(member_id, service_consent)] = True
        self.consent_grants[(member_id, political_consent)] = True
        self.questionnaires[questionnaire] = {
            "id": questionnaire,
            "kind": "POLITICAL_ONBOARDING",
            "version": "1.0",
            "keys": ["economic", "social", "international"],
        }
        source_ids = [new_id(), new_id(), new_id()]
        for index, (source_id, name, source_type) in enumerate(
            zip(
                source_ids,
                ["Fixture Daily", "Fixture Public", "Fixture World"],
                ["RSS", "API", "CRAWLER"],
                strict=True,
            )
        ):
            self.sources[source_id] = {
                "id": source_id,
                "name": name,
                "source_type": source_type,
                "canonical_url": f"https://fixture{index + 1}.invalid",
                "policy_status": "APPROVED",
                "robots_status": "APPROVED",
                "terms_status": "APPROVED",
                "active": True,
                "version": 1,
            }
        issue_id = new_id()
        article_rows: list[dict[str, Any]] = []
        for index, (source_id, x) in enumerate(
            zip(source_ids, [-35, 5, 42], strict=True), start=1
        ):
            article_id, version_id, score_id = new_id(), new_id(), new_id()
            row = {
                "id": article_id,
                "source_id": source_id,
                "source": self.sources[source_id]["name"],
                "issue_id": issue_id,
                "canonical_url": f"https://fixture{index}.invalid/policy-{index}",
                "title": f"Fixture policy report {index}",
                "author": "Fixture Reporter",
                "summary": "A synthetic report used for deterministic local integration tests.",
                "published_at": utcnow() - timedelta(hours=index),
                "current_version_id": version_id,
                "status": "ACTIVE",
            }
            self.articles[article_id] = row
            article_rows.append(row)
            models = []
            for _model_index, offset in enumerate([0], start=1):
                alias = "openai-default"
                models.append(
                    {
                        "model_alias": alias,
                        "x": x + offset,
                        "y": 15 - index,
                        "z": -10 + index,
                        "sensationalism": 20 + index,
                        "confidence": 0.84,
                        "rationale_summary": "Fixture-only limited evidence summary.",
                        "evidence": [{"article_version_id": version_id, "start": 0, "end": 24}],
                    }
                )
            self.assessments[article_id] = models
            self.scores[article_id] = [
                {
                    "id": score_id,
                    "article_version_id": version_id,
                    "version": 1,
                    "x": x,
                    "y": 15 - index,
                    "z": -10 + index,
                    "sensationalism": 20 + index,
                    "confidence": 0.82,
                    "components": {
                        "llm_ensemble": {"x": x, "weight": 0.65},
                        "relative_framing": {"x": x, "weight": 0.15},
                        "qualified_votes": {"x": 0, "weight": 0.1},
                        "shrunk_source_prior": {"x": x // 2, "weight": 0.1},
                    },
                    "status": "ACTIVE",
                    "created_at": utcnow(),
                }
            ]
        self.issues[issue_id] = {
            "id": issue_id,
            "title": "Fixture policy issue",
            "summary": "Multiple synthetic perspectives on one policy issue.",
            "status": "OPEN",
            "version": 1,
            "article_ids": [row["id"] for row in article_rows],
            "opened_at": utcnow(),
            "last_activity_at": utcnow(),
        }
        model_id = new_id()
        self.models[model_id] = {
            "id": model_id,
            "alias": "openai-default",
            "provider": "openai",
            "actual_model_id": "gpt-5.6-luna",
            "reasoning_effort": "xhigh",
            "secret_env_name": "OPENAI_API_KEY",
            "status": "ACTIVE",
            "version": 1,
        }
        weight_id = new_id()
        self.weights[weight_id] = {
            "id": weight_id,
            "revision": 1,
            "status": "active",
            "weights": {"model": 0.65, "relative": 0.15, "crowd": 0.1, "source": 0.1},
            "guardrails": {"max_revision_delta": 0.1, "minimum_model_success": 0.66},
            "based_on_revision_id": None,
            "created_at": utcnow(),
            "published_at": utcnow(),
        }
        self.autopilot = {
            "mode": "OFF",
            "guardrails": self.weights[weight_id]["guardrails"],
            "manual_locks": [],
            "version": 1,
        }

    def enqueue(self, job_type: str, dedupe_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            for job in self.jobs.values():
                if job["job_type"] == job_type and job["dedupe_key"] == dedupe_key:
                    return job
            job_id = new_id()
            job = {
                "id": job_id,
                "job_type": job_type,
                "dedupe_key": dedupe_key,
                "status": "PENDING",
                "priority": 0,
                "available_at": utcnow(),
                "attempts": 0,
                "max_attempts": 5,
                "payload": payload,
                "last_error": None,
            }
            self.jobs[job_id] = job
            return job

    def audit_action(
        self,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        before: Any,
        after: Any,
        reason: str,
        request_id: str,
    ) -> None:
        self.audit.append(
            {
                "id": new_id(),
                "actor_id": actor_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "before": before,
                "after": after,
                "reason": reason,
                "request_id": request_id,
                "created_at": utcnow(),
            }
        )

    def create_share_card(self, user_id: str, template: str, display_name: str | None) -> dict[str, Any]:
        profile = next(
            (profile for profile in self.profiles.values() if profile["user_id"] == user_id and profile["active"]),
            {"x": 0, "y": 0, "z": 0, "confidence": 0},
        )
        total = sum(entry["delta"] for entry in self.credits.get(user_id, []))
        raw_token = secrets.token_urlsafe(32)
        card_id = new_id()
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        card = {
            "id": card_id,
            "user_id": user_id,
            "status": "ready",
            "public_token": raw_token,
            "public_token_hash": stable_hash(raw_token),
            "template": template,
            "display_name": display_name,
            "snapshot": {
                "coordinate": {key: profile[key] for key in ("x", "y", "z", "confidence")},
                "tier": "Explorer" if total < 100 else "Bridge Builder",
                "credit_total": total,
                "political_data_publication_confirmed": True,
            },
            "png": png,
            "etag": f'"{stable_hash(png)}"',
            "expires_at": utcnow() + timedelta(days=30),
            "revoked_at": None,
        }
        self.share_cards[card_id] = card
        self.public_cards[stable_hash(raw_token)] = card_id
        self.enqueue(
            "render_share_card",
            card_id,
            {
                "share_card_id": card_id,
                "template": template,
                "display_name": display_name,
                "snapshot": card["snapshot"],
                "expires_at": str(card["expires_at"]),
            },
        )
        return card


STATE = PlatformState()
