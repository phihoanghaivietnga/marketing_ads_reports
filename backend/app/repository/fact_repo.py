"""Repository for fact_ad_metrics table — Star Schema Fact with UPSERT idempotency.

Operations:
- get_or_create_dim_account / campaign / ad_set / ad: resolve dimension FK
- upsert_fact_metrics: INSERT ... ON CONFLICT (ad_id, date) DO UPDATE
"""

import logging
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import CanonicalAdMetric

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Dimension resolution — get-or-create pattern
# ------------------------------------------------------------------


async def get_or_create_dim_account(
    session: AsyncSession,
    platform_id: int,
    external_id: str,
    account_name: str = "",
) -> int:
    """Return account_id (lookup or insert) for dim_account.

    Uses INSERT ... ON CONFLICT DO UPDATE to ensure idempotency.
    """
    sql = text("""
        INSERT INTO dim_account (platform_id, external_id, account_name)
        VALUES (:platform_id, :external_id, :account_name)
        ON CONFLICT (platform_id, external_id)
        DO UPDATE SET account_name = EXCLUDED.account_name,
                      updated_at = now()
        RETURNING account_id
    """)
    result = await session.execute(
        sql,
        {
            "platform_id": platform_id,
            "external_id": external_id,
            "account_name": account_name,
        },
    )
    account_id: int = result.fetchone().account_id
    return account_id


async def get_or_create_dim_campaign(
    session: AsyncSession,
    account_id: int,
    external_id: str,
    campaign_name: str = "",
) -> int:
    """Return campaign_id (lookup or insert) for dim_campaign."""
    sql = text("""
        INSERT INTO dim_campaign (account_id, external_id, campaign_name)
        VALUES (:account_id, :external_id, :campaign_name)
        ON CONFLICT (account_id, external_id)
        DO UPDATE SET campaign_name = EXCLUDED.campaign_name,
                      updated_at = now()
        RETURNING campaign_id
    """)
    result = await session.execute(
        sql,
        {
            "account_id": account_id,
            "external_id": external_id,
            "campaign_name": campaign_name,
        },
    )
    campaign_id: int = result.fetchone().campaign_id
    return campaign_id


async def get_or_create_dim_ad_set(
    session: AsyncSession,
    campaign_id: int,
    external_id: str,
    ad_set_name: str = "",
) -> int:
    """Return ad_set_id (lookup or insert) for dim_ad_set."""
    sql = text("""
        INSERT INTO dim_ad_set (campaign_id, external_id, ad_set_name)
        VALUES (:campaign_id, :external_id, :ad_set_name)
        ON CONFLICT (campaign_id, external_id)
        DO UPDATE SET ad_set_name = EXCLUDED.ad_set_name,
                      updated_at = now()
        RETURNING ad_set_id
    """)
    result = await session.execute(
        sql,
        {
            "campaign_id": campaign_id,
            "external_id": external_id,
            "ad_set_name": ad_set_name,
        },
    )
    ad_set_id: int = result.fetchone().ad_set_id
    return ad_set_id


async def get_or_create_dim_ad(
    session: AsyncSession,
    ad_set_id: int,
    external_id: str,
    ad_name: str = "",
) -> int:
    """Return ad_id (lookup or insert) for dim_ad."""
    sql = text("""
        INSERT INTO dim_ad (ad_set_id, external_id, ad_name)
        VALUES (:ad_set_id, :external_id, :ad_name)
        ON CONFLICT (ad_set_id, external_id)
        DO UPDATE SET ad_name = EXCLUDED.ad_name,
                      updated_at = now()
        RETURNING ad_id
    """)
    result = await session.execute(
        sql,
        {
            "ad_set_id": ad_set_id,
            "external_id": external_id,
            "ad_name": ad_name,
        },
    )
    ad_id: int = result.fetchone().ad_id
    return ad_id


async def get_platform_id(session: AsyncSession, platform_code: str) -> int | None:
    """Look up platform_id from dim_platform by platform_code."""
    sql = text("SELECT platform_id FROM dim_platform WHERE platform_code = :code")
    result = await session.execute(sql, {"code": platform_code.upper()})
    row = result.fetchone()
    return row.platform_id if row else None


# ------------------------------------------------------------------
# Fact UPSERT — core idempotency mechanism
# ------------------------------------------------------------------


async def upsert_fact_metrics(
    session: AsyncSession,
    ad_id: int,
    metric: CanonicalAdMetric,
    currency: str = "USD",
) -> None:
    """Upsert a single fact_ad_metrics row.

    Uses INSERT ... ON CONFLICT (ad_id, date) DO UPDATE.
    Running the same job twice produces identical data — no duplicates.

    Args:
        session: Async DB session
        ad_id: FK to dim_ad.ad_id (already resolved)
        metric: CanonicalAdMetric with all metric values
        currency: ISO 4217 currency code (default USD)
    """
    sql = text("""
        INSERT INTO fact_ad_metrics (
            ad_id, date, spend, impressions, clicks, conversions,
            conversion_value, extra_metrics, currency
        ) VALUES (
            :ad_id, :date, :spend, :impressions, :clicks, :conversions,
            :conversion_value, :extra_metrics, :currency
        )
        ON CONFLICT (ad_id, date) DO UPDATE SET
            spend = EXCLUDED.spend,
            impressions = EXCLUDED.impressions,
            clicks = EXCLUDED.clicks,
            conversions = EXCLUDED.conversions,
            conversion_value = EXCLUDED.conversion_value,
            extra_metrics = EXCLUDED.extra_metrics,
            currency = EXCLUDED.currency,
            ingested_at = now()
    """)

    extra = metric.extra_metrics if metric.extra_metrics else None

    await session.execute(
        sql,
        {
            "ad_id": ad_id,
            "date": metric.date,
            "spend": str(metric.spend),
            "impressions": metric.impressions,
            "clicks": metric.clicks,
            "conversions": metric.conversions,
            "conversion_value": str(metric.conversion_value),
            "extra_metrics": extra,
            "currency": currency,
        },
    )


# ------------------------------------------------------------------
# Aggregate queries for API (used in Phase D)
# ------------------------------------------------------------------


async def query_metrics_aggregate(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    platform_codes: list[str] | None = None,
    campaign_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate fact_ad_metrics by date, with optional filters.

    Returns sum of core metrics grouped by date, joined through dim hierarchy.

    Args:
        session: Async DB session
        date_from: Start date (inclusive)
        date_to: End date (inclusive)
        platform_codes: Optional list of platform codes to filter by
        campaign_ids: Optional list of campaign IDs to filter by

    Returns:
        List of dicts with keys: date, spend, impressions, clicks, conversions, conversion_value
    """
    conditions = ["f.date BETWEEN :date_from AND :date_to"]
    params: dict[str, Any] = {
        "date_from": date_from,
        "date_to": date_to,
    }

    if platform_codes:
        conditions.append("dp.platform_code = ANY(:platform_codes)")
        params["platform_codes"] = platform_codes

    if campaign_ids:
        conditions.append("dc.campaign_id = ANY(:campaign_ids)")
        params["campaign_ids"] = campaign_ids

    where_clause = " AND ".join(conditions)

    sql = text(f"""
        SELECT
            f.date,
            SUM(f.spend) AS spend,
            SUM(f.impressions) AS impressions,
            SUM(f.clicks) AS clicks,
            SUM(f.conversions) AS conversions,
            SUM(f.conversion_value) AS conversion_value
        FROM fact_ad_metrics f
        JOIN dim_ad da ON f.ad_id = da.ad_id
        JOIN dim_ad_set das ON da.ad_set_id = das.ad_set_id
        JOIN dim_campaign dc ON das.campaign_id = dc.campaign_id
        JOIN dim_account dacc ON dc.account_id = dacc.account_id
        JOIN dim_platform dp ON dacc.platform_id = dp.platform_id
        WHERE {where_clause}
        GROUP BY f.date
        ORDER BY f.date
    """)

    result = await session.execute(sql, params)
    rows = result.fetchall()
    return [
        {
            "date": row.date,
            "spend": row.spend,
            "impressions": row.impressions,
            "clicks": row.clicks,
            "conversions": row.conversions,
            "conversion_value": row.conversion_value,
        }
        for row in rows
    ]


async def query_campaigns(
    session: AsyncSession,
    platform_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Return distinct campaigns for filter dropdown.

    Args:
        session: Async DB session
        platform_codes: Optional list of platform codes to filter by

    Returns:
        List of dicts with keys: campaign_id, campaign_name, platform_code
    """
    if platform_codes:
        sql = text("""
            SELECT dc.campaign_id, dc.campaign_name, dp.platform_code
            FROM dim_campaign dc
            JOIN dim_account dacc ON dc.account_id = dacc.account_id
            JOIN dim_platform dp ON dacc.platform_id = dp.platform_id
            WHERE dp.platform_code = ANY(:platform_codes)
            ORDER BY dp.platform_code, dc.campaign_name
        """)
        params = {"platform_codes": platform_codes}
    else:
        sql = text("""
            SELECT dc.campaign_id, dc.campaign_name, dp.platform_code
            FROM dim_campaign dc
            JOIN dim_account dacc ON dc.account_id = dacc.account_id
            JOIN dim_platform dp ON dacc.platform_id = dp.platform_id
            ORDER BY dp.platform_code, dc.campaign_name
        """)
        params = {}

    result = await session.execute(sql, params)
    rows = result.fetchall()
    return [
        {
            "campaign_id": row.campaign_id,
            "campaign_name": row.campaign_name,
            "platform_code": row.platform_code,
        }
        for row in rows
    ]