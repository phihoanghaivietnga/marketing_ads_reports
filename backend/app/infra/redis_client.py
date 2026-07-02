"""Async Redis client for caching and Celery broker communication.

Provides:
- Singleton Redis connection pool
- get_redis() async generator for FastAPI Depends()
- init_redis() / close_redis() lifecycle hooks
"""

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.infra.settings import settings

_redis: Redis | None = None


async def init_redis() -> None:
    """Initialize the Redis connection pool (call on app startup)."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=10,
        )


async def close_redis() -> None:
    """Close the Redis connection pool (call on app shutdown)."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency — yields the shared Redis client."""
    if _redis is None:
        await init_redis()
    assert _redis is not None
    yield _redis