"""FastAPI dependency injection — API key auth, DB session, Redis client."""

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from app.infra.db import get_db
from app.infra.redis_client import get_redis
from app.infra.settings import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    """Validate X-API-Key header against the configured API_KEY.

    Simple auth for Phase 1 — will be replaced with proper
    authentication/authorization in a later phase.
    """
    if api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key