"""Celery ETL tasks — 3 idempotent steps: fetch, normalize, load.

Chain: fetch_and_land -> normalize_and_stage -> load_to_fact

Each step can be run independently (via Celery queue) and is idempotent:
- fetch_and_land: ON CONFLICT DO NOTHING on raw_events UNIQUE constraint
- normalize_and_stage: reads raw_events, upserts staging (idempotent via processed flag)
- load_to_fact: ON CONFLICT DO UPDATE on fact_ad_metrics UNIQUE(ad_id, date)
"""

import logging
from datetime import date, datetime
from typing import Any

from app.etl.celery_app import app
from app.etl.rate_limiter import get_bucket
from app.infra.db import async_session_factory

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Task 1: fetch_and_land
# ------------------------------------------------------------------


@app.task(
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    rate_limit="200/m",
    queue="fetch",
)
def fetch_and_land(
    self: Any,
    platform_code: str,
    account_external_id: str,
    target_date: str,
) -> dict[str, Any]:
    """Step 1: Call platform API, store raw JSON in raw_events.

    Idempotent via UNIQUE(platform_code, account_external_id, fetch_date).
    Retries with exponential backoff + jitter on HTTP 429.

    Args:
        platform_code: 'FACEBOOK' | 'TIKTOK' | 'GOOGLE'
        account_external_id: External account ID
        target_date: ISO date string 'YYYY-MM-DD'

    Returns:
        {"raw_id": int | None, "record_count": int}
    """
    import asyncio

    return asyncio.get_event_loop().run_until_complete(
        _fetch_and_land_async(self, platform_code, account_external_id, target_date)
    )


async def _fetch_and_land_async(
    self: Any,
    platform_code: str,
    account_external_id: str,
    target_date_str: str,
) -> dict[str, Any]:
    """Async implementation of fetch_and_land."""
    from app.adapters.facebook_adapter import FacebookAdapter
    from app.repository.raw_events_repo import insert_raw_event

    target_date = date.fromisoformat(target_date_str)

    # Rate limit — token bucket
    bucket = get_bucket(platform_code)
    wait = await bucket.acquire()
    if wait > 0:
        logger.debug("Rate limit wait: %.2fs for %s", wait, platform_code)

    # Select adapter (hardcoded for now — Phase 2 will add registry)
    if platform_code.upper() == "FACEBOOK":
        adapter = FacebookAdapter()
    else:
        raise NotImplementedError(
            f"Platform '{platform_code}' adapter not implemented yet."
        )

    # Fetch raw data from platform API
    try:
        raw_records = await adapter.fetch_raw(account_external_id, target_date)
    except Exception as exc:
        logger.error(
            "fetch_and_land failed for %s/%s/%s: %s",
            platform_code,
            account_external_id,
            target_date_str,
            exc,
        )
        # Exponential backoff with jitter
        countdown = 2 ** self.request.retries * 1.5
        raise self.retry(exc=exc, countdown=countdown)

    if not raw_records:
        logger.info(
            "No data for %s/%s/%s — nothing to land",
            platform_code,
            account_external_id,
            target_date_str,
        )
        return {"raw_id": None, "record_count": 0}

    # Insert into raw_events (idempotent via ON CONFLICT DO NOTHING)
    async with async_session_factory() as session:
        raw_id = await insert_raw_event(
            session,
            platform_code=platform_code,
            account_external_id=account_external_id,
            fetch_date=target_date,
            payload=raw_records,
        )

    logger.info(
        "fetch_and_land complete: raw_id=%s, platform=%s, account=%s, date=%s, records=%d",
        raw_id,
        platform_code,
        account_external_id,
        target_date_str,
        len(raw_records),
    )
    return {"raw_id": raw_id, "record_count": len(raw_records)}


# ------------------------------------------------------------------
# Task 2: normalize_and_stage
# ------------------------------------------------------------------


@app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="normalize",
)
def normalize_and_stage(
    self: Any,
    raw_id: int,
) -> dict[str, Any]:
    """Step 2: Read raw_events, normalize to CanonicalAdMetric, write to staging.

    Handles invalid records gracefully — writes validation_errors JSONB
    for bad records, does not block the batch.

    Args:
        raw_id: Primary key of the raw_events row to process

    Returns:
        {"staging_count": int, "error_count": int}
    """
    import asyncio

    return asyncio.get_event_loop().run_until_complete(
        _normalize_and_stage_async(self, raw_id)
    )


async def _normalize_and_stage_async(
    self: Any,
    raw_id: int,
) -> dict[str, Any]:
    """Async implementation of normalize_and_stage."""
    from app.domain.normalizer import normalize_raw, validate_canonical
    from app.repository.raw_events_repo import get_by_id, mark_processed
    from app.repository.staging_repo import insert_staging_batch

    async with async_session_factory() as session:
        # 1. Read raw_events row
        raw_row = await get_by_id(session, raw_id)
        if raw_row is None:
            raise ValueError(f"raw_events row {raw_id} not found")

        if raw_row["processed"]:
            logger.info("raw_id=%d already processed — skipped", raw_id)
            return {"staging_count": 0, "error_count": 0, "skipped": True}

        payload = raw_row["payload"]
        platform_code = raw_row["platform_code"]
        account_external_id = raw_row["account_external_id"]

        # payload from JSONB could be a list or a dict with 'data' key
        if isinstance(payload, dict):
            raw_records = payload.get("data", [])
        elif isinstance(payload, list):
            raw_records = payload
        else:
            raw_records = []

        if not raw_records:
            logger.warning("raw_id=%d has empty payload — marking processed", raw_id)
            await mark_processed(session, raw_id)
            return {"staging_count": 0, "error_count": 0}

        # 2. Normalize via domain normalizer
        valid_metrics, errors = normalize_raw(
            platform_code=platform_code,
            account_external_id=account_external_id,
            raw_records=raw_records,
        )

        # 3. Validate each canonical metric
        validation_errors_map: dict[int, list[str]] = {}
        for idx, metric in enumerate(valid_metrics):
            issues = validate_canonical(metric)
            if issues:
                validation_errors_map[idx] = issues

        # 4. Insert into staging
        staging_count = await insert_staging_batch(
            session=session,
            raw_id=raw_id,
            platform_code=platform_code,
            account_external_id=account_external_id,
            metrics=valid_metrics,
            validation_errors_map=validation_errors_map,
        )

        # 5. Mark raw as processed
        await mark_processed(session, raw_id)

    logger.info(
        "normalize_and_stage complete: raw_id=%d, staging=%d, errors=%d",
        raw_id,
        staging_count,
        len(errors),
    )
    return {"staging_count": staging_count, "error_count": len(errors)}


# ------------------------------------------------------------------
# Task 3: load_to_fact
# ------------------------------------------------------------------


@app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    queue="load",
)
def load_to_fact(
    self: Any,
    staging_batch_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Step 3: Resolve dimension FKs, UPSERT into fact_ad_metrics.

    For each staging row with loaded_to_fact=FALSE:
      1. Get-or-create dim_account, dim_campaign, dim_ad_set, dim_ad
      2. UPSERT into fact_ad_metrics (ON CONFLICT DO UPDATE)
      3. Mark staging as loaded

    This is the final step — after this, data appears in the dashboard API.

    Args:
        staging_batch_ids: Optional explicit list of staging IDs to process.
                           If not provided, processes up to 500 unloaded rows.

    Returns:
        {"loaded_count": int}
    """
    import asyncio

    return asyncio.get_event_loop().run_until_complete(
        _load_to_fact_async(staging_batch_ids)
    )


async def _load_to_fact_async(
    staging_batch_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Async implementation of load_to_fact."""
    from app.repository.fact_repo import (
        get_or_create_dim_account,
        get_or_create_dim_ad,
        get_or_create_dim_ad_set,
        get_or_create_dim_campaign,
        get_platform_id,
        upsert_fact_metrics,
    )
    from app.repository.staging_repo import get_unloaded, mark_loaded

    async with async_session_factory() as session:
        # 1. Fetch staging rows
        if staging_batch_ids:
            # TODO: add get_by_ids() to staging_repo for explicit batch
            staging_rows = await get_unloaded(session, limit=500)
            staging_rows = [r for r in staging_rows if r["staging_id"] in staging_batch_ids]
        else:
            staging_rows = await get_unloaded(session, limit=500)

        if not staging_rows:
            logger.info("load_to_fact: no unloaded staging rows")
            return {"loaded_count": 0}

        loaded_ids: list[int] = []
        for row in staging_rows:
            try:
                # Skip rows with validation errors
                if row["validation_errors"]:
                    logger.debug(
                        "Skipping staging_id=%d due to validation_errors", row["staging_id"]
                    )
                    continue

                # 2. Resolve platform_id
                platform_id = await get_platform_id(session, row["platform_code"])
                if platform_id is None:
                    logger.error(
                        "Unknown platform_code '%s' for staging_id=%d — skipping",
                        row["platform_code"],
                        row["staging_id"],
                    )
                    continue

                # 3. Get-or-create dimension hierarchy
                account_id = await get_or_create_dim_account(
                    session,
                    platform_id=platform_id,
                    external_id=row["account_external_id"],
                )

                campaign_id = await get_or_create_dim_campaign(
                    session,
                    account_id=account_id,
                    external_id=row["campaign_external_id"],
                )

                ad_set_id = await get_or_create_dim_ad_set(
                    session,
                    campaign_id=campaign_id,
                    external_id=row["ad_set_external_id"],
                )

                ad_id = await get_or_create_dim_ad(
                    session,
                    ad_set_id=ad_set_id,
                    external_id=row["ad_external_id"],
                )

                # 4. Build CanonicalAdMetric from staging row and UPSERT
                from decimal import Decimal

                from app.domain.models import CanonicalAdMetric

                metric = CanonicalAdMetric(
                    platform_code=row["platform_code"],
                    account_external_id=row["account_external_id"],
                    campaign_external_id=row["campaign_external_id"],
                    ad_set_external_id=row["ad_set_external_id"],
                    ad_external_id=row["ad_external_id"],
                    date=row["date"],
                    spend=Decimal(str(row["spend"] or 0)),
                    impressions=row["impressions"] or 0,
                    clicks=row["clicks"] or 0,
                    conversions=row["conversions"] or 0,
                    conversion_value=Decimal(str(row["conversion_value"] or 0)),
                    extra_metrics=row["extra_metrics"] or {},
                )

                await upsert_fact_metrics(session, ad_id=ad_id, metric=metric)

                loaded_ids.append(row["staging_id"])
            except Exception as exc:
                logger.error(
                    "Failed to load staging_id=%d: %s",
                    row["staging_id"],
                    exc,
                    exc_info=True,
                )
                continue

        # 5. Mark staging rows as loaded
        await mark_loaded(session, loaded_ids)
        await session.commit()

    logger.info("load_to_fact complete: loaded %d rows", len(loaded_ids))
    return {"loaded_count": len(loaded_ids)}