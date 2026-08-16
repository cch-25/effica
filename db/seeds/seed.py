"""Apply the synthetic MariaDB development seed in one transaction.

The runner intentionally does not manufacture accounts, credentials, tokens,
or questionnaire data.  It reads the root settings only, executes the checked
in SQL fixture, and never prints connection details.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import text

from apps.api.app.core.config import get_settings
from apps.api.app.db.session import create_engine, dispose_engine

SEED_SQL = Path(__file__).with_name("001_fake_data.sql")

EXPECTED_FIXTURE_COUNTS = {
    "sources": ("id", 2),
    "articles": ("id", 2),
    "stored_blobs": ("id", 2),
    "article_versions": ("id", 2),
    "issues": ("id", 2),
    "issue_memberships": ("issue_id", 2),
    "model_aliases": ("id", 1),
}
SEED_ID_PREFIX = "01J00000000000000000000"


def _statements() -> list[str]:
    """Return non-comment SQL statements from the trusted fixture file."""

    source = SEED_SQL.read_text(encoding="utf-8")
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if quote is not None:
            current.append(char)
            if char == "\\" and following:
                current.append(following)
                index += 2
                continue
            if char == quote:
                if following == quote:
                    current.append(following)
                    index += 2
                    continue
                quote = None
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
            index += 1
            continue
        if char == "-" and following == "-":
            index += 2
            while index < len(source) and source[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and following == "*":
            index += 2
            while index + 1 < len(source) and source[index : index + 2] != "*/":
                index += 1
            index += 2
            continue
        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current.clear()
            index += 1
            continue
        current.append(char)
        index += 1
    trailing = "".join(current).strip()
    if quote is not None:
        raise ValueError("seed SQL contains an unterminated quoted value")
    if trailing:
        statements.append(trailing)
    return statements


async def seed(*, dry_run: bool = False) -> int:
    """Apply the fixture and return the number of executed statements."""

    statements = _statements()
    if dry_run:
        return len(statements)

    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
            for table, (column, expected) in EXPECTED_FIXTURE_COUNTS.items():
                # Table and column names are constants above, never runtime
                # input.  Validate the known synthetic identifier namespace so
                # an idempotent no-op cannot hide a constraint-skipped row.
                count = (
                    await connection.execute(
                        text(
                            f"SELECT COUNT(*) FROM {table} "
                            f"WHERE {column} LIKE :seed_prefix"
                        ),
                        {"seed_prefix": f"{SEED_ID_PREFIX}%"},
                    )
                ).scalar_one()
                if int(count) < expected:
                    raise RuntimeError(
                        f"synthetic seed incomplete for {table}: "
                        f"expected at least {expected}, found {count}"
                    )
    finally:
        await dispose_engine()
    return len(statements)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply synthetic development database seeds")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and count fixture statements without opening a database connection",
    )
    args = parser.parse_args()
    count = asyncio.run(seed(dry_run=args.dry_run))
    action = "Validated" if args.dry_run else "Applied"
    print(f"{action} synthetic database seed statements: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
