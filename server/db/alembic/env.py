"""Alembic environment for the greenfield MariaDB schema."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import ForeignKeyConstraint, Table, event, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.schema import DropConstraint
from sqlalchemy.sql.compiler import DDLCompiler

ROOT = Path(__file__).resolve().parents[2]
API_PATH = ROOT / "apps" / "api"
if str(API_PATH) not in sys.path:
    sys.path.insert(0, str(API_PATH))

from app.db import models  # noqa: E402,F401  (register every table)
from app.db.base import metadata  # noqa: E402
from app.db.session import database_url_from_env  # noqa: E402

config = context.config

_LONG_EVIDENCE_FK = (
    "fk_weight_recommendations_evidence_snapshot_id_weight_evidence_snapshots"
)
_MARIADB_EVIDENCE_FK = "fk_weight_recommendations_evidence_snapshot"
_TEMP_SCORE_FK_INDEX = "ix_score_versions_article_version_migration"


@compiles(ForeignKeyConstraint, "mysql")
def _compile_mariadb_foreign_key(
    constraint: ForeignKeyConstraint,
    compiler: DDLCompiler,
    **kwargs: object,
) -> str:
    visit = compiler.visit_foreign_key_constraint
    if not compiler.dialect.is_mariadb:
        return visit(constraint, **kwargs)
    if constraint.name != _LONG_EVIDENCE_FK:
        return visit(constraint, **kwargs)
    constraint.name = _MARIADB_EVIDENCE_FK
    try:
        return visit(constraint, **kwargs)
    finally:
        constraint.name = _LONG_EVIDENCE_FK


@compiles(DropConstraint, "mysql")
def _compile_mariadb_drop_constraint(
    drop: DropConstraint,
    compiler: DDLCompiler,
    **kwargs: object,
) -> str:
    visit = compiler.visit_drop_constraint
    constraint = drop.element
    if (
        compiler.dialect.is_mariadb
        and isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == _LONG_EVIDENCE_FK
    ):
        constraint.name = _MARIADB_EVIDENCE_FK
        try:
            return visit(drop, **kwargs)
        finally:
            constraint.name = _LONG_EVIDENCE_FK
    return visit(drop, **kwargs)


@event.listens_for(Table, "before_create", propagate=True)
def _mariadb_credit_reversal_compatibility(
    table: Table,
    connection: Connection,
    **_: object,
) -> None:
    """Render the immutable 0001 self-FK in a form accepted by MariaDB 11.8.

    MariaDB rejects a CHECK that references a column changed by an ``ON DELETE
    SET NULL`` action. Revision 0003 makes RESTRICT the canonical final schema;
    this hook only lets a fresh database reach that corrective revision without
    rewriting the already-shared 0001 migration.
    """

    if table.name != "credit_ledger" or not getattr(connection.dialect, "_is_mariadb", False):
        return
    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        if constraint.name != "fk_credit_ledger_reversed_ledger_id_credit_ledger":
            continue
        constraint.ondelete = "RESTRICT"
        for element in constraint.elements:
            element.ondelete = "RESTRICT"


@event.listens_for(Table, "after_create", propagate=True)
def _mariadb_score_index_compatibility(
    table: Table,
    connection: Connection,
    **_: object,
) -> None:
    """Keep the score FK indexed while immutable revision 0002 replaces a unique key."""

    if table.name != "score_versions" or not connection.dialect.is_mariadb:
        return
    connection.exec_driver_sql(
        f"CREATE INDEX {_TEMP_SCORE_FK_INDEX} ON score_versions (article_version_id)"
    )


def _database_url() -> str:
    # ``-x url=...`` is useful for CI and must win over root configuration.
    cli_url = context.get_x_argument(as_dictionary=True).get("url")
    if cli_url:
        return cli_url
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    return database_url_from_env()


def run_migrations_offline() -> None:
    """Emit SQL without creating a DB connection."""

    context.configure(
        url=_database_url(),
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        compare_type=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
