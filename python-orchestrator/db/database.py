"""SQLite embedded database setup with async SQLAlchemy."""

import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base

logger = logging.getLogger(__name__)

_engine = None
_session_factory = None


async def init_db(db_path: str) -> None:
    """Initialize the SQLite database, creating tables if needed."""
    global _engine, _session_factory

    # Ensure directory exists
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    url = f"sqlite+aiosqlite:///{db_path}"
    _engine = create_async_engine(url, echo=False)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info(f"Database initialized at {db_path}")


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get the async session factory. Must call init_db first."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _session_factory


async def get_db() -> AsyncSession:
    """Get a database session (for use as FastAPI dependency)."""
    factory = get_session_factory()
    async with factory() as session:
        yield session
