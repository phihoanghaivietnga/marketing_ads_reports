"""Database engine and session factory (async, PostgreSQL via asyncpg).

Provides:
- async SQLAlchemy engine with connection pooling
- async_sessionmaker for dependency injection
- get_db() async generator for FastAPI Depends()
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infra.settings import settings

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    echo=settings.app_debug,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async DB session, auto-closed after request."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()