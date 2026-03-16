"""Async SQLAlchemy engine and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine = None
_session_factory = None


async def init_db():
    """Create the async engine and session factory.  Called during app lifespan startup."""
    global _engine, _session_factory
    settings = get_settings()
    _engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_size=5,
        max_overflow=10,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def close_db():
    """Dispose the engine.  Called during app lifespan shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


async def get_session() -> AsyncSession:
    """FastAPI dependency that yields an async database session."""
    async with _session_factory() as session:
        yield session
