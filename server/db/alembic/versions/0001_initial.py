"""Create the complete MAS schema from specification chapter 5.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-16
"""

# ruff: noqa: E501

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _dt() -> sa.types.TypeEngine:
    return mysql.DATETIME(fsp=6)


def _json() -> sa.types.TypeEngine:
    return mysql.JSON()


def _enum(column: str, values: tuple[str, ...], name: str) -> sa.CheckConstraint:
    encoded = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({encoded})", name=name)


def _json_valid(column: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(f"JSON_VALID({column})", name=f"json_valid_{column}")


def _axis_checks() -> tuple[sa.CheckConstraint, ...]:
    return tuple(
        sa.CheckConstraint(f"{column} BETWEEN -100 AND 100", name=f"{column}_range")
        for column in ("x", "y", "z")
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="MEMBER"),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.Column("deleted_at", _dt(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        _enum("role", ("MEMBER", "ANALYST", "REVIEWER", "ADMIN"), "ck_users_role"),
        _enum(
            "status",
            ("ACTIVE", "SUSPENDED", "DELETED", "PENDING_DELETION"),
            "ck_users_status",
        ),
        sa.CheckConstraint(
            "(status = 'DELETED' AND deleted_at IS NOT NULL) OR (status <> 'DELETED')",
            name="ck_users_deleted_status_timestamp",
        ),
    )

    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_subject", sa.String(255), nullable=False),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_oauth_accounts"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_oauth_accounts_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("provider", "provider_subject", name="uq_oauth_provider_subject"),
        sa.Index("ix_oauth_accounts_user_id", "user_id"),
        _enum("provider", ("kakao", "naver", "google", "mock"), "ck_oauth_accounts_provider"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("token_hash", sa.BINARY(32), nullable=False),
        sa.Column("csrf_hash", sa.BINARY(32), nullable=False),
        sa.Column("expires_at", _dt(), nullable=False),
        sa.Column("revoked_at", _dt(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_sessions_user_id_users", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        sa.Index("ix_sessions_user_expires", "user_id", "expires_at"),
    )

    op.create_table(
        "consent_versions",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("body_hash", sa.BINARY(32), nullable=False),
        sa.Column("active_from", _dt(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_consent_versions"),
        sa.UniqueConstraint("purpose", "version", name="uq_consent_versions_purpose_version"),
    )

    op.create_table(
        "user_consents",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("consent_version_id", sa.CHAR(26), nullable=False),
        sa.Column(
            "granted_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.Column("withdrawn_at", _dt(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_consents"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_consents_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["consent_version_id"],
            ["consent_versions.id"],
            name="fk_user_consents_consent_version_id_consent_versions",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("user_id", "consent_version_id", name="uq_user_consents_user_version"),
    )

    op.create_table(
        "questionnaire_versions",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("schema_json", _json(), nullable=False),
        sa.Column("scoring_json", _json(), nullable=False),
        sa.Column("active_from", _dt(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_questionnaire_versions"),
        sa.UniqueConstraint("kind", "version", name="uq_questionnaire_versions_kind_version"),
        _enum("kind", ("onboarding", "efficacy"), "ck_questionnaire_versions_kind"),
        _json_valid("schema_json"),
        _json_valid("scoring_json"),
    )

    op.create_table(
        "questionnaire_responses",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("questionnaire_version_id", sa.CHAR(26), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column(
            "submitted_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_questionnaire_responses"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_questionnaire_responses_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["questionnaire_version_id"],
            ["questionnaire_versions.id"],
            name="fk_qresponses_qversion",
            ondelete="RESTRICT",
        ),
        sa.Index("ix_questionnaire_responses_user_submitted", "user_id", "submitted_at"),
    )

    op.create_table(
        "user_demographics",
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("age_band", sa.String(32), nullable=True),
        sa.Column("gender_response", sa.String(64), nullable=True),
        sa.Column("consent_version_id", sa.CHAR(26), nullable=True),
        sa.Column(
            "updated_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_demographics"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_demographics_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["consent_version_id"],
            ["consent_versions.id"],
            name="fk_user_demographics_consent_version_id_consent_versions",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "user_profiles",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("x", sa.SmallInteger(), nullable=False),
        sa.Column("y", sa.SmallInteger(), nullable=False),
        sa.Column("z", sa.SmallInteger(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("source_version", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_profiles"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_profiles_user_id_users", ondelete="CASCADE"
        ),
        _enum("kind", ("self_reported_profile", "behavioral_profile"), "ck_user_profiles_kind"),
        *_axis_checks(),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        sa.Index("ix_user_profiles_user_kind_active", "user_id", "kind", "active"),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        sa.Column("policy_status", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
        sa.UniqueConstraint("canonical_url", name="uq_sources_canonical_url"),
        _enum("source_type", ("API", "RSS", "CRAWLER"), "ck_sources_source_type"),
        _enum(
            "policy_status",
            ("PENDING", "APPROVED", "REJECTED", "EXPIRED"),
            "ck_sources_policy_status",
        ),
    )

    op.create_table(
        "source_adapters",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("source_id", sa.CHAR(26), nullable=False),
        sa.Column("adapter_type", sa.String(16), nullable=False),
        sa.Column("config_json", _json(), nullable=False),
        sa.Column("rate_limit", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id", name="pk_source_adapters"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_source_adapters_source_id_sources",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("source_id", "adapter_type", name="uq_source_adapters_source_type"),
        _enum(
            "adapter_type",
            ("API", "RSS", "CRAWLER"),
            "ck_source_adapters_adapter_type",
        ),
        sa.CheckConstraint("rate_limit IS NULL OR rate_limit > 0", name="positive_rate_limit"),
        _json_valid("config_json"),
    )

    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("source_id", sa.CHAR(26), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("started_at", _dt(), nullable=True),
        sa.Column("finished_at", _dt(), nullable=True),
        sa.Column("stats_json", _json(), nullable=True),
        sa.Column("error_json", _json(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_crawl_runs"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_crawl_runs_source_id_sources",
            ondelete="RESTRICT",
        ),
        _enum(
            "status",
            ("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"),
            "ck_crawl_runs_status",
        ),
        _json_valid("stats_json"),
        _json_valid("error_json"),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="crawl_finished_after_started",
        ),
    )

    # ``articles.current_version_id`` forms the only intentional cycle in the
    # schema.  Add it after both article tables exist.
    op.create_table(
        "articles",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("source_id", sa.CHAR(26), nullable=False),
        sa.Column("canonical_url", sa.String(2048), nullable=False),
        sa.Column("canonical_url_hash", sa.BINARY(32), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("author", sa.String(255), nullable=True),
        sa.Column("published_at", _dt(), nullable=True),
        sa.Column("current_version_id", sa.CHAR(26), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.Column(
            "updated_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_articles"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_articles_source_id_sources", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("canonical_url_hash", name="uq_articles_canonical_url_hash"),
        _enum("status", ("active", "stale", "removed", "blocked"), "ck_articles_status"),
        sa.Index("ix_articles_source_published", "source_id", "published_at"),
    )

    op.create_table(
        "article_versions",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("article_id", sa.CHAR(26), nullable=False),
        sa.Column("content_hash", sa.BINARY(32), nullable=False),
        sa.Column("normalized_text_ref", sa.String(1024), nullable=True),
        sa.Column(
            "fetched_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.Column("modified_at", _dt(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_article_versions"),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name="fk_article_versions_article_id_articles",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("article_id", "content_hash", name="uq_article_versions_article_hash"),
        sa.Index("ix_article_versions_article_fetched", "article_id", "fetched_at"),
    )
    op.create_foreign_key(
        "fk_articles_current_version_id_article_versions",
        "articles",
        "article_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "issues",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column(
            "opened_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.Column(
            "last_activity_at",
            _dt(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id", name="pk_issues"),
        _enum(
            "status", ("candidate", "active", "merged", "closed", "archived"), "ck_issues_status"
        ),
        sa.CheckConstraint("version > 0", name="positive_version"),
    )

    op.create_table(
        "issue_memberships",
        sa.Column("issue_id", sa.CHAR(26), nullable=False),
        sa.Column("article_id", sa.CHAR(26), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("issue_id", "article_id", name="pk_issue_memberships"),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name="fk_issue_memberships_issue_id_issues",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name="fk_issue_memberships_article_id_articles",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
    )

    op.create_table(
        "fact_check_references",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("article_id", sa.CHAR(26), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("published_at", _dt(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_fact_check_references"),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name="fk_fact_check_references_article_id_articles",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "model_aliases",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("alias", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("actual_model_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("config_json", _json(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_model_aliases"),
        sa.UniqueConstraint("alias", name="uq_model_aliases_alias"),
        _enum("status", ("ACTIVE", "DISABLED", "DEPRECATED"), "ck_model_aliases_status"),
        _json_valid("config_json"),
    )

    op.create_table(
        "model_assessments",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("article_version_id", sa.CHAR(26), nullable=False),
        sa.Column("model_alias_id", sa.CHAR(26), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("x", sa.SmallInteger(), nullable=False),
        sa.Column("y", sa.SmallInteger(), nullable=False),
        sa.Column("z", sa.SmallInteger(), nullable=False),
        sa.Column("sensationalism", mysql.TINYINT(unsigned=True), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("evidence_json", _json(), nullable=False),
        sa.Column("raw_response_ref", sa.String(1024), nullable=True),
        sa.Column("token_usage", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_assessments"),
        sa.ForeignKeyConstraint(
            ["article_version_id"],
            ["article_versions.id"],
            name="fk_model_assessments_article_version_id_article_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_alias_id"],
            ["model_aliases.id"],
            name="fk_model_assessments_model_alias_id_model_aliases",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "article_version_id",
            "model_alias_id",
            "prompt_version",
            name="uq_model_assessments_version_model_prompt",
        ),
        *_axis_checks(),
        sa.CheckConstraint("sensationalism BETWEEN 0 AND 100", name="sensationalism_range"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        sa.CheckConstraint(
            "token_usage IS NULL OR token_usage >= 0", name="nonnegative_token_usage"
        ),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="nonnegative_latency_ms"),
        _enum(
            "status", ("PENDING", "SUCCEEDED", "FAILED", "REJECTED"), "ck_model_assessments_status"
        ),
        _json_valid("evidence_json"),
    )

    op.create_table(
        "weight_profile_revisions",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("weights_json", _json(), nullable=False),
        sa.Column("guardrails_json", _json(), nullable=False),
        sa.Column("based_on_revision_id", sa.CHAR(26), nullable=True),
        sa.Column("created_by", sa.CHAR(26), nullable=True),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.Column("published_at", _dt(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_weight_profile_revisions"),
        sa.ForeignKeyConstraint(
            ["based_on_revision_id"],
            ["weight_profile_revisions.id"],
            name="fk_wprev_based_on",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_weight_profile_revisions_created_by_users",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("revision", name="uq_weight_profile_revisions_revision"),
        sa.CheckConstraint("revision > 0", name="positive_revision"),
        _enum(
            "status",
            ("draft", "simulation", "active", "archived"),
            "ck_weight_profile_revisions_status",
        ),
        _json_valid("weights_json"),
        _json_valid("guardrails_json"),
    )

    op.create_table(
        "score_versions",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("article_version_id", sa.CHAR(26), nullable=False),
        sa.Column("weight_revision_id", sa.CHAR(26), nullable=False),
        sa.Column("x", sa.SmallInteger(), nullable=False),
        sa.Column("y", sa.SmallInteger(), nullable=False),
        sa.Column("z", sa.SmallInteger(), nullable=False),
        sa.Column("sensationalism", mysql.TINYINT(unsigned=True), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("components_json", _json(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_score_versions"),
        sa.ForeignKeyConstraint(
            ["article_version_id"],
            ["article_versions.id"],
            name="fk_score_versions_article_version_id_article_versions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["weight_revision_id"],
            ["weight_profile_revisions.id"],
            name="fk_score_versions_weight_revision_id_weight_profile_revisions",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "article_version_id", "weight_revision_id", name="uq_score_versions_article_weight"
        ),
        *_axis_checks(),
        sa.CheckConstraint("sensationalism BETWEEN 0 AND 100", name="sensationalism_range"),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
        _enum("status", ("draft", "active", "stale", "superseded"), "ck_score_versions_status"),
        _json_valid("components_json"),
    )

    op.create_table(
        "votes",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("article_id", sa.CHAR(26), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("x", sa.SmallInteger(), nullable=False),
        sa.Column("y", sa.SmallInteger(), nullable=False),
        sa.Column("z", sa.SmallInteger(), nullable=False),
        sa.Column("sensationalism", mysql.TINYINT(unsigned=True), nullable=False),
        sa.Column("quality_status", sa.String(16), nullable=False, server_default="VALID"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.Column(
            "updated_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_votes"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_votes_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name="fk_votes_article_id_articles",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "user_id", "article_id", "revision", name="uq_votes_user_article_revision"
        ),
        sa.Index("ix_votes_user_article_active", "user_id", "article_id", "active"),
        sa.CheckConstraint("revision > 0", name="positive_revision"),
        *_axis_checks(),
        sa.CheckConstraint("sensationalism BETWEEN 0 AND 100", name="sensationalism_range"),
        _enum(
            "quality_status",
            ("VALID", "PENDING", "QUALIFIED", "FLAGGED", "REJECTED"),
            "ck_votes_quality_status",
        ),
    )

    op.create_table(
        "vote_aggregate_snapshots",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("article_id", sa.CHAR(26), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("aggregate_json", _json(), nullable=False),
        sa.Column("segment_json", _json(), nullable=False),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vote_aggregate_snapshots"),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name="fk_vote_aggregate_snapshots_article_id_articles",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("article_id", "version", name="uq_vote_aggregate_article_version"),
        sa.CheckConstraint("version > 0", name="positive_version"),
        _json_valid("aggregate_json"),
        _json_valid("segment_json"),
    )

    op.create_table(
        "feed_impressions",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=True),
        sa.Column("article_id", sa.CHAR(26), nullable=False),
        sa.Column("issue_id", sa.CHAR(26), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feed_impressions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_feed_impressions_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name="fk_feed_impressions_article_id_articles",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["issues.id"],
            name="fk_feed_impressions_issue_id_issues",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint("rank > 0", name="positive_rank"),
        sa.Index("ix_feed_impressions_user_created", "user_id", "created_at"),
    )

    op.create_table(
        "read_sessions",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("article_id", sa.CHAR(26), nullable=False),
        sa.Column("token_hash", sa.BINARY(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="CREATED"),
        sa.Column("outbound_at", _dt(), nullable=True),
        sa.Column("returned_at", _dt(), nullable=True),
        sa.Column("client_elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_read_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_read_sessions_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name="fk_read_sessions_article_id_articles",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("token_hash", name="uq_read_sessions_token_hash"),
        _enum(
            "status",
            ("CREATED", "OUTBOUND", "RETURNED", "ELIGIBLE", "REJECTED", "EXPIRED"),
            "ck_read_sessions_status",
        ),
        sa.CheckConstraint(
            "client_elapsed_ms IS NULL OR client_elapsed_ms >= 0", name="nonnegative_client_elapsed"
        ),
        sa.CheckConstraint(
            "returned_at IS NULL OR outbound_at IS NULL OR returned_at >= outbound_at",
            name="read_return_after_outbound",
        ),
    )

    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_key", sa.String(255), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="posted"),
        sa.Column("reversed_ledger_id", sa.CHAR(26), nullable=True),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_credit_ledger"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_credit_ledger_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["reversed_ledger_id"],
            ["credit_ledger.id"],
            name="fk_credit_ledger_reversed_ledger_id_credit_ledger",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "user_id", "event_type", "event_key", name="uq_credit_ledger_user_event"
        ),
        _enum("status", ("posted", "reversed", "voided"), "ck_credit_ledger_status"),
        sa.CheckConstraint(
            "(status = 'reversed' AND reversed_ledger_id IS NOT NULL) OR (status <> 'reversed')",
            name="reversal_reference",
        ),
        sa.Index("ix_credit_ledger_user_created", "user_id", "created_at"),
    )

    op.create_table(
        "tier_snapshots",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("credit_total", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tier_snapshots"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_tier_snapshots_user_id_users", ondelete="CASCADE"
        ),
        sa.CheckConstraint("credit_total >= 0", name="nonnegative_credit_total"),
        sa.CheckConstraint("level >= 0", name="nonnegative_level"),
    )

    op.create_table(
        "efficacy_responses",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("questionnaire_version_id", sa.CHAR(26), nullable=False),
        sa.Column("normalized_score", sa.Numeric(8, 4), nullable=False),
        sa.Column(
            "submitted_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_efficacy_responses"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_efficacy_responses_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["questionnaire_version_id"],
            ["questionnaire_versions.id"],
            name="fk_efficacy_qversion",
            ondelete="RESTRICT",
        ),
    )

    op.create_table(
        "efficacy_aggregate_snapshots",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("cohort_key", sa.String(255), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("aggregate_json", _json(), nullable=False),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_efficacy_aggregate_snapshots"),
        sa.UniqueConstraint("cohort_key", "period", name="uq_efficacy_aggregate_cohort_period"),
        _json_valid("aggregate_json"),
    )

    op.create_table(
        "weight_recommendations",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("base_revision_id", sa.CHAR(26), nullable=False),
        sa.Column("proposed_weights_json", _json(), nullable=False),
        sa.Column("evidence_snapshot_id", sa.CHAR(26), nullable=True),
        sa.Column("provider_assessment_ref", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_weight_recommendations"),
        sa.ForeignKeyConstraint(
            ["base_revision_id"],
            ["weight_profile_revisions.id"],
            name="fk_wrecommend_base",
            ondelete="RESTRICT",
        ),
        _enum(
            "status",
            ("PENDING_REVIEW", "APPROVED", "REJECTED", "PUBLISHED"),
            "ck_weight_recommendations_status",
        ),
        _json_valid("proposed_weights_json"),
    )

    op.create_table(
        "weight_simulations",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("recommendation_id", sa.CHAR(26), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("metrics_json", _json(), nullable=False),
        sa.Column("guardrail_result", _json(), nullable=False),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_weight_simulations"),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["weight_recommendations.id"],
            name="fk_weight_simulations_recommendation_id_weight_recommendations",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("window_days > 0", name="positive_window_days"),
        _json_valid("metrics_json"),
        _json_valid("guardrail_result"),
    )

    op.create_table(
        "autopilot_settings",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="OFF"),
        sa.Column("guardrails_json", _json(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.CHAR(26), nullable=True),
        sa.Column(
            "updated_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_autopilot_settings"),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_autopilot_settings_updated_by_users",
            ondelete="SET NULL",
        ),
        _enum(
            "mode",
            ("OFF", "RECOMMEND", "LIMITED_AUTO"),
            "ck_autopilot_settings_mode",
        ),
        sa.CheckConstraint("version > 0", name="positive_version"),
        _json_valid("guardrails_json"),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.Column("lease_owner", sa.String(255), nullable=True),
        sa.Column("lease_expires_at", _dt(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("payload_json", _json(), nullable=False),
        sa.Column("last_error_json", _json(), nullable=True),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.Column(
            "updated_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.UniqueConstraint("job_type", "dedupe_key", name="uq_jobs_type_dedupe"),
        sa.Index("ix_jobs_status_available_priority", "status", "available_at", "priority"),
        _enum(
            "status",
            ("PENDING", "LEASED", "SUCCEEDED", "FAILED", "DEAD", "CANCELLED"),
            "ck_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="nonnegative_attempts"),
        sa.CheckConstraint("max_attempts > 0", name="positive_max_attempts"),
        _json_valid("payload_json"),
        _json_valid("last_error_json"),
    )

    op.create_table(
        "stored_blobs",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("sha256", sa.BINARY(32), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("payload", mysql.LONGBLOB(), nullable=False),
        sa.Column("expires_at", _dt(), nullable=True),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stored_blobs"),
        sa.UniqueConstraint("sha256", name="uq_stored_blobs_sha256"),
        sa.CheckConstraint("byte_size BETWEEN 0 AND 10485760", name="blob_size_limit"),
    )

    op.create_table(
        "share_cards",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("user_id", sa.CHAR(26), nullable=False),
        sa.Column("public_token_hash", sa.BINARY(32), nullable=False),
        sa.Column("template", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=True),
        sa.Column("snapshot_json", _json(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("blob_id", sa.CHAR(26), nullable=True),
        sa.Column("expires_at", _dt(), nullable=True),
        sa.Column("revoked_at", _dt(), nullable=True),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_share_cards"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_share_cards_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["blob_id"],
            ["stored_blobs.id"],
            name="fk_share_cards_blob_id_stored_blobs",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("public_token_hash", name="uq_share_cards_public_token_hash"),
        _enum(
            "status", ("queued", "rendering", "ready", "failed", "revoked"), "ck_share_cards_status"
        ),
        _json_valid("snapshot_json"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.CHAR(26), nullable=False),
        sa.Column("actor_id", sa.CHAR(26), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_type", sa.String(128), nullable=False),
        sa.Column("target_id", sa.CHAR(26), nullable=True),
        sa.Column("before_json", _json(), nullable=True),
        sa.Column("after_json", _json(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
        sa.Column(
            "created_at", _dt(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name="fk_audit_logs_actor_id_users", ondelete="SET NULL"
        ),
        sa.Index("ix_audit_logs_target_created", "target_type", "target_id", "created_at"),
        _json_valid("before_json"),
        _json_valid("after_json"),
    )


def downgrade() -> None:
    # This is a greenfield migration.  Downgrade is explicit and intentionally
    # destructive; operators should take a database backup before invoking it.
    op.drop_table("audit_logs")
    op.drop_table("share_cards")
    op.drop_table("stored_blobs")
    op.drop_table("jobs")
    op.drop_table("autopilot_settings")
    op.drop_table("weight_simulations")
    op.drop_table("weight_recommendations")
    op.drop_table("efficacy_aggregate_snapshots")
    op.drop_table("efficacy_responses")
    op.drop_table("tier_snapshots")
    op.drop_table("credit_ledger")
    op.drop_table("read_sessions")
    op.drop_table("feed_impressions")
    op.drop_table("vote_aggregate_snapshots")
    op.drop_table("votes")
    op.drop_table("score_versions")
    op.drop_table("weight_profile_revisions")
    op.drop_table("model_assessments")
    op.drop_table("model_aliases")
    op.drop_table("fact_check_references")
    op.drop_table("issue_memberships")
    op.drop_table("issues")
    op.drop_constraint(
        "fk_articles_current_version_id_article_versions", "articles", type_="foreignkey"
    )
    op.drop_table("article_versions")
    op.drop_table("articles")
    op.drop_table("crawl_runs")
    op.drop_table("source_adapters")
    op.drop_table("sources")
    op.drop_table("user_profiles")
    op.drop_table("user_demographics")
    op.drop_table("questionnaire_responses")
    op.drop_table("questionnaire_versions")
    op.drop_table("user_consents")
    op.drop_table("consent_versions")
    op.drop_table("sessions")
    op.drop_table("oauth_accounts")
    op.drop_table("users")
