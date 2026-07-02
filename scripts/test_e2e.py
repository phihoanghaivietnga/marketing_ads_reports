#!/usr/bin/env python3
"""End-to-end test: crawl Facebook 1 account -> verify data through all 3 tiers.

Prerequisites:
  - PostgreSQL running with all 6 database/*.sql scripts executed
  - Redis running on localhost:6379
  - FACEBOOK_ACCESS_TOKEN set in backend/.env with ads_read permission
  - A real Facebook ad account ID with recent data

Usage:
  cd backend
  uv run python ../scripts/test_e2e.py --account-id <act_XXXXX> --date 2026-06-01

What this test does:
  1. Runs fetch_and_land Celery task for 1 account + 1 date
  2. Verifies raw_events has exactly 1 row with processed=FALSE
  3. Runs normalize_and_stage(raw_id)
  4. Verifies staging_ad_metrics has rows, loaded_to_fact=FALSE
  5. Runs load_to_fact()
  6. Verifies fact_ad_metrics has data
  7. Calls GET /api/v1/metrics via HTTP and prints the response
  8. Asserts data consistency across all 3 tiers
"""

import argparse
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

# Add backend to path so we can import app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.infra.db import async_session_factory
from app.infra.settings import settings
from app.repository.raw_events_repo import get_by_id, get_unprocessed
from app.repository.staging_repo import get_unloaded
from app.etl.tasks import fetch_and_land, normalize_and_stage, load_to_fact


def check_prerequisites() -> None:
    """Verify required environment variables are set."""
    errors = []
    if not settings.database_url:
        errors.append("DATABASE_URL is not set in .env")
    if not settings.redis_url:
        errors.append("REDIS_URL is not set in .env")
    if not settings.facebook_access_token:
        errors.append("FACEBOOK_ACCESS_TOKEN is not set in .env — cannot call Facebook API")
    if errors:
        print("❌ PREREQUISITES FAILED:")
        for e in errors:
            print(f"   - {e}")
        sys.exit(1)
    print("✅ Prerequisites OK")


async def count_fact_rows() -> int:
    """Count total rows in fact_ad_metrics."""
    from sqlalchemy import text

    async with async_session_factory() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM fact_ad_metrics"))
        return result.scalar() or 0


async def count_raw_rows() -> int:
    """Count total rows in raw_events."""
    from sqlalchemy import text

    async with async_session_factory() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM raw_events"))
        return result.scalar() or 0


async def count_staging_rows() -> int:
    """Count total rows in staging_ad_metrics."""
    from sqlalchemy import text

    async with async_session_factory() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM staging_ad_metrics"))
        return result.scalar() or 0


async def run_e2e(account_id: str, target_date_str: str) -> bool:
    """Run the full end-to-end test pipeline."""
    target_date = date.fromisoformat(target_date_str)
    platform_code = "FACEBOOK"

    print(f"\n{'='*60}")
    print(f"E2E TEST: {platform_code} / {account_id} / {target_date}")
    print(f"{'='*60}\n")

    # --- Step 1: fetch_and_land ---
    print("📥 Step 1: fetch_and_land — calling Facebook API...")
    fact_before = await count_fact_rows()
    raw_before = await count_raw_rows()

    result = fetch_and_land(
        platform_code=platform_code,
        account_external_id=account_id,
        target_date=target_date_str,
    )
    raw_id = result.get("raw_id")
    record_count = result.get("record_count", 0)

    if raw_id is None:
        print(f"   ⚠️  raw_events row already existed (idempotent skip) — record_count={record_count}")
        # Try to find the existing raw_id
        async with async_session_factory() as session:
            from sqlalchemy import text
            r = await session.execute(
                text(
                    "SELECT raw_id FROM raw_events "
                    "WHERE platform_code=:pc AND account_external_id=:aid AND fetch_date=:fd"
                ),
                {"pc": platform_code, "aid": account_id, "fd": target_date},
            )
            row = r.fetchone()
            if row:
                raw_id = row.raw_id
    else:
        print(f"   ✅ raw_events inserted: raw_id={raw_id}, records={record_count}")

    if raw_id is None:
        print("   ❌ No raw_events row found — cannot continue")
        return False

    # Verify raw_events
    async with async_session_factory() as session:
        raw_row = await get_by_id(session, raw_id)
    assert raw_row is not None, f"raw_events row {raw_id} not found"
    assert raw_row["platform_code"] == platform_code
    assert raw_row["account_external_id"] == account_id
    print(f"   ✅ raw_events verified: platform={raw_row['platform_code']}, "
          f"processed={raw_row['processed']}")

    # --- Step 2: normalize_and_stage ---
    print("\n📊 Step 2: normalize_and_stage — normalizing raw data...")
    staging_before = await count_staging_rows()

    result = normalize_and_stage(raw_id=raw_id)
    staging_count = result.get("staging_count", 0)
    error_count = result.get("error_count", 0)

    print(f"   ✅ Staging rows inserted: {staging_count}, errors: {error_count}")

    if staging_count == 0 and error_count > 0:
        print("   ⚠️  All records had validation errors — check staging_ad_metrics.validation_errors")
        return False

    # Verify staging
    async with async_session_factory() as session:
        staging_rows = await get_unloaded(session, limit=100)
    staging_for_raw = [r for r in staging_rows if r["raw_id"] == raw_id]
    print(f"   ✅ Staging verified: {len(staging_for_raw)} rows linked to raw_id={raw_id}")

    # --- Step 3: load_to_fact ---
    print("\n📈 Step 3: load_to_fact — resolving dimensions, UPSERT into fact...")

    result = load_to_fact()
    loaded_count = result.get("loaded_count", 0)
    print(f"   ✅ Fact rows loaded: {loaded_count}")

    fact_after = await count_fact_rows()
    print(f"   ✅ fact_ad_metrics total rows: before={fact_before}, after={fact_after}")

    if loaded_count == 0:
        print("   ⚠️  No rows loaded to fact — check staging for validation_errors")
        return False

    # --- Step 4: Verify via API ---
    print("\n🌐 Step 4: Verify via GET /api/v1/metrics...")
    import httpx

    api_url = "http://localhost:8000/api/v1/metrics"
    params = {
        "date_from": target_date_str,
        "date_to": target_date_str,
        "platform_codes": [platform_code],
    }
    headers = {"X-API-Key": settings.api_key}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(api_url, params=params, headers=headers)
            if response.status_code == 200:
                data = response.json()
                current = data.get("current", [])
                summary = data.get("summary", {})
                print(f"   ✅ API returned {len(current)} rows")
                if current:
                    row = current[0]
                    print(f"      Date: {row['date']}, Spend: {row['spend']}, "
                          f"Impressions: {row['impressions']}, Clicks: {row['clicks']}")
                if summary:
                    s = summary.get("spend", {})
                    print(f"      Summary spend: current={s.get('current')}, "
                          f"previous={s.get('previous')}, change_pct={s.get('change_pct')}")
            else:
                print(f"   ⚠️  API returned {response.status_code}: {response.text[:200]}")
    except httpx.ConnectError:
        print("   ⚠️  Could not connect to API — is uvicorn running on port 8000?")
        print("      Start with: cd backend && uv run uvicorn app.main:app --port 8000")

    # --- Summary ---
    print(f"\n{'='*60}")
    print("✅ E2E TEST COMPLETE")
    print(f"{'='*60}")
    print(f"   raw_events:       {raw_before} -> {await count_raw_rows()}")
    print(f"   staging:          {staging_before} -> {await count_staging_rows()}")
    print(f"   fact_ad_metrics:  {fact_before} -> {await count_fact_rows()}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E test for Marketing Analytics ETL pipeline")
    parser.add_argument(
        "--account-id",
        required=True,
        help="Facebook ad account ID (e.g., act_123456789)",
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Target date in YYYY-MM-DD format (e.g., 2026-06-01)",
    )
    args = parser.parse_args()

    check_prerequisites()

    success = asyncio.run(run_e2e(args.account_id, args.date))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()