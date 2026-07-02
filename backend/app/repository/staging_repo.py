"""Repository for staging_ad_metrics table — Normalized but FK-unresolved metrics.

Each row links back to its raw_events.raw_id for audit trail.
Validation errors are stored in validation_errors JSONB (NULL if valid).
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import CanonicalAdMetric

logger = logging.getLogger(__name__)


async def insert_staging_batch(
    session: AsyncSession,
    raw_id: int,
    platform_code: str,
    account_external_id: str,
    metrics: list[CanonicalAdMetric],
    validation_errors_map: dict[int, list[str]] | None = None,
) -> int:
    """Insert a batch of normalized metrics into staging_ad_metrics.

    Args:
        session: Async DB session
        raw_id: FK to raw_events.raw_id
        platform_code: 'FACEBOOK' | 'TIKTOK' | 'GOOGLE'
        account_external_id: External account ID
        metrics: List of valid CanonicalAdMetric records
        validation_errors_map: Optional dict mapping metric index -> list of error strings
                               for records that failed validation

    Returns:
        Number of staging rows inserted
    """
    if validation_errors_map is None:
        validation_errors_map = {}

    inserted = 0
    for idx, metric in enumerate(metrics):
        errors = validation_errors_map.get(idx)
        sql = text("""
            INSERT INTO staging_ad_metrics (
                raw_id,
                platform_code,
                account_external_id,
                campaign_external_id,
                ad_set_external_id,
                ad_external_id,
                date,
                spend,
                impressions,
                clicks,
                conversions,
                conversion_value,
                extra_metrics,
                validation_errors,
                loaded_to_fact
            ) VALUES (
                :raw_id,
                :platform_code,
                :account_external_id,
                :campaign_external_id,
                :ad_set_external_id,
                :ad_external_id,
                :date,
                :spend,
                :impressions,
                :clicks,
                :conversions,
                :conversion_value,
                :extra_metrics,
                :validation_errors,
                FALSE
            )
        """)

        await session.execute(
            sql,
            {
                "raw_id": raw_id,
                "platform_code": metric.platform_code,
                "account_external_id": metric.account_external_id,
                "campaign_external_id": metric.campaign_external_id or None,
                "ad_set_external_id": metric.ad_set_external_id or None,
                "ad_external_id": metric.ad_external_id or None,
                "date": metric.date,
                "spend": str(metric.spend),
                "impressions": metric.impressions,
                "clicks": metric.clicks,
                "conversions": metric.conversions,
                "conversion_value": str(metric.conversion_value),
                "extra_metrics": _serialize_extra(metric.extra_metrics),
                "validation_errors": errors,
            },
        )
        inserted += 1

    await session.commit()
    logger.info(
        "Inserted %d staging rows for raw_id=%d (platform=%s, account=%s)",
        inserted,
        raw_id,
        platform_code,
        account_external_id,
    )
    return inserted


async def get_unloaded(
    session: AsyncSession,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Fetch staging rows that haven't been loaded to fact yet.

    Returns rows with loaded_to_fact = FALSE, ordered by staging_id.
    """
    sql = text("""
        SELECT staging_id, raw_id, platform_code, account_external_id,
               campaign_external_id, ad_set_external_id, ad_external_id,
               date, spend, impressions, clicks, conversions, conversion_value,
               extra_metrics, validation_errors
        FROM staging_ad_metrics
        WHERE loaded_to_fact = FALSE
        ORDER BY staging_id
        LIMIT :limit
    """)
    result = await session.execute(sql, {"limit": limit})
    rows = result.fetchall()
    return [_row_to_dict(row) for row in rows]


async def mark_loaded(session: AsyncSession, staging_ids: list[int]) -> None:
    """Mark staging rows as loaded to fact (set loaded_to_fact = TRUE)."""
    if not staging_ids:
        return
    sql = text("""
        UPDATE staging_ad_metrics
        SET loaded_to_fact = TRUE
        WHERE staging_id = ANY(:ids)
    """)
    await session.execute(sql, {"ids": staging_ids})
    await session.commit()


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy row to a plain dict."""
    return {
        "staging_id": row.staging_id,
        "raw_id": row.raw_id,
        "platform_code": row.platform_code,
        "account_external_id": row.account_external_id,
        "campaign_external_id": row.campaign_external_id,
        "ad_set_external_id": row.ad_set_external_id,
        "ad_external_id": row.ad_external_id,
        "date": row.date,
        "spend": row.spend,
        "impressions": row.impressions,
        "clicks": row.clicks,
        "conversions": row.conversions,
        "conversion_value": row.conversion_value,
        "extra_metrics": row.extra_metrics or {},
        "validation_errors": row.validation_errors,
    }


def _serialize_extra(extra_metrics: dict) -> Any | None:
    """Return None for empty dicts (cleaner JSONB), otherwise the dict."""
    if not extra_metrics:
        return None
    return extra_metrics