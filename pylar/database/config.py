"""Typed configuration for the database layer."""

from __future__ import annotations

from pylar.config.schema import BaseConfig


class DatabaseConfig(BaseConfig):
    """Connection configuration consumed by :class:`ConnectionManager`.

    The ``url`` follows SQLAlchemy's URL syntax and must use an async driver
    (``postgresql+asyncpg``, ``sqlite+aiosqlite``, ``mysql+aiomysql``, ...).
    """

    url: str
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 10
    pool_recycle: int = 3600
    pool_timeout: int = 30
    query_timeout: int = 30
