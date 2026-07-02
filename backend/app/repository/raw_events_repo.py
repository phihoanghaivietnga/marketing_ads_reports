"""Repository for raw_events table — Raw JSON Landing layer.

All operations are idempotent:
- Insert uses ON CONFLICT DO NOTHING (UNIQUE on platform_code + account_external_id + fetch_date)
- Processed flag allows selective re-processing
"""

import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def insert_raw_event(
    session: AsyncSession,
    platform_code: str,
    account_external_id: str,
    fetch_date: date,
    payload: list[dict],
) -> int | None:
    """Insert raw API response into raw_events.

    Uses ON CONFLICT DO NOTHING to avoid duplicate entries for the same
    (platform_code, account_external_id, fetch_date) combination.

    Args:
        session: Async DB session
        platform_code: 'FACEBOOK' | 'TIKTOK' | 'GOOGLE'
        account_external_id: External account ID from the platform
        fetch_date: The report date (not the job execution date)
        payload: List of raw dict records from the platform API

    Returns:
        raw_id of the inserted row, or None if it already existed (skipped)
    """
    sql = text("""
        INSERT INTO raw_events (platform_code, account_external_id, fetch_date, payload, processed)
        VALUES (:platform_code, :account_external_id, :fetch_date, :payload, FALSE)
        ON CONFLICT (platform_code, account_external_id, fetch_date) DO NOTHING
        RETURNING raw_id
    """)

    result = await session.execute(
        sql,
        {
            "platform_code": platform_code,
            "account_external_id": account_external_id,
            "fetch_date": fetch_date,
            "payload": json.dumps(payload),  # JSONB accepts JSON string
        },
    )
    row = result.fetchone()
    if row is None:
        logger.debug(
            "raw_events row already exists for %s/%s/%s — skipped",
            platform_code,
            account_external_id,
            fetch_date,
        )
        return None

    await session.commit()
    raw_id: int = row.raw_id
    logger.info(
        "Inserted raw_events id=%d for %s/%s/%s (%d records)",
        raw_id,
        platform_code,
        account_external_id,
        fetch_date,
        len(payload),
    )
    return raw_id


async def mark_processed(session: AsyncSession, raw_id: int) -> None:
    """Mark a raw_events row as processed (set processed=TRUE)."""
    sql = text("UPDATE raw_events SET processed = TRUE WHERE raw_id = :raw_id")
    await session.execute(sql, {"raw_id": raw_id})
    await session.commit()


async def get_unprocessed(
    session: AsyncSession,
    platform_code: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Fetch raw_events rows that haven't been processed yet.

    Args:
        session: Async DB session
        platform_code: Optional filter by platform
        limit: Max rows to return (default 100)

    Returns:
        List of dicts with keys: raw_id, platform_code, account_external_id,
        fetch_date, payload, fetched_at
    """
    if platform_code:
        sql = text("""
            SELECT raw_id, platform_code, account_external_id, fetch_date, payload, fetched_at
            FROM raw_events
            WHERE processed = FALSE AND platform_code = :platform_code
            ORDER BY raw_id
            LIMIT :limit
        """)
        params = {"platform_code": platform_code, "limit": limit}
    else:
        sql = text("""
            SELECT raw_id, platform_code, account_external_id, fetch_date, payload, fetched_at
            FROM raw_events
            WHERE processed = FALSE
            ORDER BY raw_id
            LIMIT :limit
        """)
        params = {"limit": limit}

    result = await session.execute(sql, params)
    rows = result.fetchall()
    return [
        {
            "raw_id": row.raw_id,
            "platform_code": row.platform_code,
            "account_external_id": row.account_external_id,
            "fetch_date": row.fetch_date,
            "payload": row.payload,  # Already dict from JSONB
            "fetched_at": row.fetched_at,
        }
        for row in rows
    ]


async def get_by_id(session: AsyncSession, raw_id: int) -> dict[str, Any] | None:
    """Fetch a single raw_events row by its primary key."""
    sql = text("""
        SELECT raw_id, platform_code, account_external_id, fetch_date, payload, fetched_at, processed
        FROM raw_events
        WHERE raw_id = :raw_id
    """)
    result = await session.execute(sql, {"raw_id": raw_id})
    row = result.fetchone()
    if row is None:
        return None
    return {
        "raw_id": row.raw_id,
        "platform_code": row.platform_code,
        "account_external_id": row.account_external_id,
        "fetch_date": row.fetch_date,
        "payload": row.payload,
        "fetched_at": row.fetched_at,
        "processed": row.processed,
    }