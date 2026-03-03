"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


# Module-level singletons — populated by init_db()
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(url: str, echo: bool = False, pool_size: int = 10) -> AsyncEngine:
    """Create the async engine, session factory, and all tables.

    Parameters
    ----------
    url:
        SQLAlchemy async database URL.
        SQLite example:  ``sqlite+aiosqlite:///sentinel.db``
        Postgres example: ``postgresql+asyncpg://user:pass@host/db``
    echo:
        Log all SQL statements (useful for debugging).
    pool_size:
        Connection pool size (ignored for SQLite).
    """
    global _engine, _session_factory

    connect_args: dict = {}
    engine_kwargs: dict = {"echo": echo}

    if url.startswith("sqlite"):
        # SQLite doesn't support pool_size; use StaticPool for :memory:
        connect_args["check_same_thread"] = False
        if ":memory:" in url:
            from sqlalchemy.pool import StaticPool
            engine_kwargs["poolclass"] = StaticPool
    else:
        engine_kwargs["pool_size"] = pool_size

    _engine = create_async_engine(url, connect_args=connect_args, **engine_kwargs)

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create all tables that are registered with Base
    from .models import _register_models  # noqa: F401 — ensures models are imported
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return _engine


async def close_db() -> None:
    """Dispose of the engine and clean up connection pool."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    return _engine


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that yields a database session with auto rollback on error."""
    if _session_factory is None:
        raise RuntimeError("Database not initialised. Call init_db() first.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
