"""GET /api/v1/campaigns endpoint — list campaigns for filter dropdown.

Cached in Redis with TTL 600s (campaign list rarely changes mid-day).
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis, verify_api_key
from app.api.schemas.campaign_schema import CampaignItem, CampaignsResponse
from app.infra.settings import settings
from app.repository.fact_repo import query_campaigns

logger = logging.getLogger(__name__)

router = APIRouter(prefix=settings.api_v1_prefix, tags=["campaigns"])

# Campaign list cache TTL — 10 minutes (data changes slowly)
CAMPAIGN_CACHE_TTL = 600


def _campaign_cache_key(platform_codes: list[str] | None) -> str:
    """Build cache key from platform filter."""
    if platform_codes:
        sorted_codes = ",".join(sorted(platform_codes))
        return f"campaigns:platforms:{sorted_codes}"
    return "campaigns:all"


@router.get("/campaigns", response_model=CampaignsResponse)
async def get_campaigns(
    platform_codes: Optional[list[str]] = Query(
        default=None, description="Optional filter by platform codes"
    ),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _api_key: str = Depends(verify_api_key),
) -> CampaignsResponse:
    """Return list of campaigns for filter dropdown.

    Optional filter by platform (e.g., ?platform_codes=FACEBOOK&platform_codes=GOOGLE).
    Cached in Redis for 10 minutes.
    """
    # Normalize platform codes
    if platform_codes:
        platform_codes = [p.upper() for p in platform_codes]

    # --- Cache check ---
    cache_key = _campaign_cache_key(platform_codes)
    try:
        cached = await redis.get(cache_key)
        if cached:
            logger.debug("Cache HIT for campaigns: %s", cache_key)
            data = json.loads(cached)
            return CampaignsResponse(**data)
    except Exception:
        pass

    # --- Query DB ---
    raw = await query_campaigns(
        session=db,
        platform_codes=platform_codes,
    )

    campaigns = [
        CampaignItem(
            id=row["campaign_id"],
            name=row["campaign_name"],
            platform_code=row["platform_code"],
        )
        for row in raw
    ]

    response = CampaignsResponse(campaigns=campaigns, total=len(campaigns))

    # --- Cache ---
    try:
        await redis.setex(cache_key, CAMPAIGN_CACHE_TTL, response.model_dump_json())
    except Exception:
        pass

    return response