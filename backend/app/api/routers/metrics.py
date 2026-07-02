"""GET /api/v1/metrics endpoint — aggregate ad metrics with comparison.

Supports:
- Date range filtering (date_from, date_to)
- Platform and campaign filters
- Granularity: day / week / month
- Previous period comparison (previous_period / previous_year)
- Redis caching (TTL varies by date freshness)
"""

import hashlib
import json
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis, verify_api_key
from app.api.schemas.metrics_schema import (
    CompareMode,
    Granularity,
    MetricRow,
    MetricSummary,
    MetricSummaryItem,
    MetricsResponse,
)
from app.infra.settings import settings
from app.repository.fact_repo import query_metrics_aggregate

logger = logging.getLogger(__name__)

router = APIRouter(prefix=settings.api_v1_prefix, tags=["metrics"])


def _shift_period(
    date_from: date, date_to: date, mode: CompareMode
) -> tuple[date, date]:
    """Calculate the previous period date range.

    Args:
        date_from: Current period start
        date_to: Current period end
        mode: PREVIOUS_PERIOD = same length, shifted back
              PREVIOUS_YEAR = same days, 1 year back

    Returns:
        (previous_date_from, previous_date_to)
    """
    delta = (date_to - date_from).days
    if mode == CompareMode.PREVIOUS_YEAR:
        return (
            date_from.replace(year=date_from.year - 1),
            date_to.replace(year=date_to.year - 1),
        )
    # PREVIOUS_PERIOD — shift back by the same duration + 1 day
    return (date_from - timedelta(days=delta + 1), date_from - timedelta(days=1))


def _build_cache_key(query_params: dict) -> str:
    """Build a deterministic cache key from query parameters."""
    raw = json.dumps(query_params, sort_keys=True, default=str)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"metrics:{digest}"


def _compute_change_pct(current: Decimal, previous: Decimal | None) -> float | None:
    """Compute percentage change from current and previous values.

    Returns None if previous is 0 or None.
    """
    if previous is None or previous == 0:
        return None
    return float(((current - previous) / previous) * 100)


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    # --- Query params (validated by FastAPI + Pydantic) ---
    date_from: date = Query(..., description="Start date (inclusive)"),
    date_to: date = Query(..., description="End date (inclusive)"),
    platform_codes: Optional[list[str]] = Query(
        default=None, description="Filter by platform codes"
    ),
    campaign_ids: Optional[list[int]] = Query(
        default=None, description="Filter by campaign IDs"
    ),
    granularity: Granularity = Query(
        default=Granularity.DAY, description="Aggregation granularity"
    ),
    compare_previous_period: bool = Query(
        default=False, description="Include previous period comparison"
    ),
    compare_mode: CompareMode = Query(
        default=CompareMode.PREVIOUS_PERIOD, description="Comparison mode"
    ),
    # --- Dependencies ---
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _api_key: str = Depends(verify_api_key),
) -> MetricsResponse:
    """Aggregate ad metrics with optional filters and comparison.

    Returns current period data, optionally previous period data,
    and a summary with % change for each core metric.

    Cached in Redis:
      - date_to is recent (today/yesterday): TTL 300s
      - date_to is older (frozen data): TTL 3600s
    """
    # Normalize platform codes
    if platform_codes:
        platform_codes = [p.upper() for p in platform_codes]

    # --- Cache check ---
    cache_params = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "platform_codes": platform_codes,
        "campaign_ids": campaign_ids,
        "granularity": granularity.value,
        "compare_previous_period": compare_previous_period,
        "compare_mode": compare_mode.value,
    }
    cache_key = _build_cache_key(cache_params)

    try:
        cached = await redis.get(cache_key)
        if cached:
            logger.debug("Cache HIT for metrics query: %s", cache_key)
            data = json.loads(cached)
            return MetricsResponse(**data)
    except Exception:
        # Cache failure should not block the request
        pass

    # --- Query current period ---
    raw_current = await query_metrics_aggregate(
        session=db,
        date_from=date_from,
        date_to=date_to,
        platform_codes=platform_codes,
        campaign_ids=campaign_ids,
    )

    current_rows = _apply_granularity([MetricRow(**r) for r in raw_current], granularity)

    # --- Query previous period (if requested) ---
    previous_rows: Optional[list[MetricRow]] = None
    if compare_previous_period:
        prev_from, prev_to = _shift_period(date_from, date_to, compare_mode)
        raw_previous = await query_metrics_aggregate(
            session=db,
            date_from=prev_from,
            date_to=prev_to,
            platform_codes=platform_codes,
            campaign_ids=campaign_ids,
        )
        previous_rows = _apply_granularity(
            [MetricRow(**r) for r in raw_previous], granularity
        )

    # --- Build summary ---
    summary = _build_summary(current_rows, previous_rows)

    response = MetricsResponse(
        current=current_rows,
        previous=previous_rows,
        summary=summary,
    )

    # --- Cache the result ---
    try:
        # Short TTL if date_to is recent, long TTL for historical frozen data
        ttl = (
            settings.cache_ttl_recent
            if date_to >= date.today() - timedelta(days=1)
            else settings.cache_ttl_historical
        )
        await redis.setex(
            cache_key,
            ttl,
            response.model_dump_json(),
        )
    except Exception:
        pass

    return response


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _apply_granularity(
    rows: list[MetricRow], granularity: Granularity
) -> list[MetricRow]:
    """Aggregate MetricRows by granularity (day = pass-through, week/month = group)."""
    if granularity == Granularity.DAY or not rows:
        return rows

    grouped: dict[str, MetricRow] = {}
    for row in rows:
        if granularity == Granularity.WEEK:
            # Group by ISO week start (Monday)
            key = (row.date - timedelta(days=row.date.weekday())).isoformat()
        elif granularity == Granularity.MONTH:
            key = row.date.replace(day=1).isoformat()
        else:
            key = row.date.isoformat()

        if key not in grouped:
            grouped[key] = MetricRow(date=row.date, spend=Decimal("0"))
        grouped[key].spend += row.spend
        grouped[key].impressions += row.impressions
        grouped[key].clicks += row.clicks
        grouped[key].conversions += row.conversions
        grouped[key].conversion_value += row.conversion_value

    return sorted(grouped.values(), key=lambda r: r.date)


def _build_summary(
    current: list[MetricRow], previous: list[MetricRow] | None
) -> MetricSummary:
    """Compute total sums and % change for each core metric."""

    def sum_metric(rows: list[MetricRow], attr: str) -> Decimal:
        return sum((getattr(r, attr) for r in rows), Decimal("0"))

    cur_spend = sum_metric(current, "spend")
    cur_impressions = sum_metric(current, "impressions")
    cur_clicks = sum_metric(current, "clicks")
    cur_conversions = sum_metric(current, "conversions")
    cur_conv_value = sum_metric(current, "conversion_value")

    if previous:
        prev_spend = sum_metric(previous, "spend")
        prev_impressions = sum_metric(previous, "impressions")
        prev_clicks = sum_metric(previous, "clicks")
        prev_conversions = sum_metric(previous, "conversions")
        prev_conv_value = sum_metric(previous, "conversion_value")
    else:
        prev_spend = prev_impressions = prev_clicks = prev_conversions = prev_conv_value = None

    return MetricSummary(
        spend=MetricSummaryItem(
            current=cur_spend,
            previous=prev_spend,
            change_pct=_compute_change_pct(cur_spend, prev_spend),
        ),
        impressions=MetricSummaryItem(
            current=Decimal(cur_impressions),
            previous=Decimal(prev_impressions) if prev_impressions is not None else None,
            change_pct=_compute_change_pct(
                Decimal(cur_impressions),
                Decimal(prev_impressions) if prev_impressions is not None else None,
            ),
        ),
        clicks=MetricSummaryItem(
            current=Decimal(cur_clicks),
            previous=Decimal(prev_clicks) if prev_clicks is not None else None,
            change_pct=_compute_change_pct(
                Decimal(cur_clicks),
                Decimal(prev_clicks) if prev_clicks is not None else None,
            ),
        ),
        conversions=MetricSummaryItem(
            current=Decimal(cur_conversions),
            previous=Decimal(prev_conversions) if prev_conversions is not None else None,
            change_pct=_compute_change_pct(
                Decimal(cur_conversions),
                Decimal(prev_conversions) if prev_conversions is not None else None,
            ),
        ),
        conversion_value=MetricSummaryItem(
            current=cur_conv_value,
            previous=prev_conv_value,
            change_pct=_compute_change_pct(cur_conv_value, prev_conv_value),
        ),
    )