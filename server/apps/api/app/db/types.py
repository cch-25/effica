"""Dialect-portable physical types used by the persistence models."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, LargeBinary
from sqlalchemy.dialects import mysql
from sqlalchemy.types import TypeDecorator


class BlobPayloadType(TypeDecorator[bytes]):
    """Use MariaDB ``LONGBLOB`` while remaining testable on SQLite."""

    impl = LargeBinary
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name in {"mysql", "mariadb"}:
            return dialect.type_descriptor(mysql.LONGBLOB())
        return dialect.type_descriptor(LargeBinary())


class TinyIntType(TypeDecorator[int]):
    """Use MariaDB ``TINYINT UNSIGNED`` while remaining SQLite-compatible."""

    impl = Integer
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name in {"mysql", "mariadb"}:
            return dialect.type_descriptor(mysql.TINYINT(unsigned=True))
        return dialect.type_descriptor(Integer())


__all__ = ["BlobPayloadType", "TinyIntType"]
