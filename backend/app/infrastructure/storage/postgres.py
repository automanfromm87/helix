"""Async SQLAlchemy engine + session factory.

Lifespan-managed singleton: `initialize` opens the pool, `shutdown` disposes
it. Other modules grab the session factory through `get_postgres()`.
"""

import logging
from functools import lru_cache
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class Postgres:
    def __init__(self) -> None:
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
        self._settings = get_settings()

    async def initialize(self) -> None:
        if self._engine is not None:
            return
        try:
            self._engine = create_async_engine(
                self._settings.postgres_dsn,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                future=True,
            )
            self._session_factory = async_sessionmaker(
                self._engine, expire_on_commit=False, class_=AsyncSession
            )
            # Smoke-test the connection so a misconfigured DSN fails loudly at boot.
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Successfully connected to Postgres")
        except Exception as e:
            logger.error(f"Failed to connect to Postgres: {e}")
            raise

    async def shutdown(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Disconnected from Postgres")
        get_postgres.cache_clear()

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Postgres engine not initialized. Call initialize() first.")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("Postgres session factory not initialized.")
        return self._session_factory

    def session(self) -> AsyncSession:
        """Open a new transactional session. Caller is responsible for commit/rollback."""
        return self.session_factory()


@lru_cache()
def get_postgres() -> Postgres:
    return Postgres()
