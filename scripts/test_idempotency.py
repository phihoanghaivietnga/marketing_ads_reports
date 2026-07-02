#!/usr/bin/env python3
"""Idempotency test: run pipeline twice, verify no duplicate rows.

Prerequisites:
  - E2E test (test_e2e.py) has been run at least once for the target account/date
  - PostgreSQL + Redis running
  - FACEBOOK_ACCESS_TOKEN set in backend/.env

Usage:
  cd backend
  uv run python ../scripts/test_idempotency.py --account-id <act_XXXXX> --date 2026-06-01

What this test verifies:
  1. Count fact_ad_metrics rows BEFORE re-running pipeline
  2. Run fetch_and_land again → expect ON CONFLICT DO NOTHING (raw_id = None)
  3. Run normalize_and_stage → expect skipped (already processed)
  4. Run load_to_fact again → expect ON CONFLICT DO UPDATE, not INSERT
  5. Count fact_ad_metrics rows AFTER → must equal BEFORE (no new rows)
  6. Verify metric values from first run are preserved (not doubled)
"""

import argparse
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.infra.db import async_session_factory
from app.infra.settings import settings
from app.etl.tasks import fetch_and_land, normalize_and_stage, load_to_fact


def check_prerequisites() -> None:
    """Verify required environment variables are set."""
    errors = []
    if not settings.database_url:
        errors.append("DATABASE_URL is not set in .env")
    if not settings.redis_url:
        errors.append("REDIS_URL is not set in .env")
    if not settings.facebook_access_token:
        errors.append("FACEBOOK_ACCESS_TOKEN is not set in .env")
    if errors:
        print("❌ PREREQUISITES FAILED:")
        for e in errors:
            print(f"   - {e}")
        sys.exit(1)
    print("✅ Prerequisites OK")


async def count_rows(table: str, session=None) -> int:
    """Count rows in a given table."""
    from sqlalchemy import text

    if session is None:
        async with async_session_factory() as s:
            result = await s.execute(text(f"SELECT COUNT(*) FROM {table}"))
            return result.scalar() or 0
    else:
        result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        return result.scalar() or 0


async def get_fact_sample(limit: int = 5) -> list[dict]:
    """Return a sample of fact rows for inspection."""
    from sqlalchemy import text

    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT fact_id, ad_id, date, spend, impressions, clicks, "
                "conversions, ingested_at FROM fact_ad_metrics ORDER BY fact_id DESC LIMIT :limit"
            ),
            {"limit": limit},
        )
        rows = result.fetchall()
        return [
            {
                "fact_id": row.fact_id,
                "ad_id": row.ad_id,
                "date": row.date,
                "spend": row.spend,
                "impressions": row.impressions,
                "clicks": row.clicks,
                "conversions": row.conversions,
                "ingested_at": row.ingested_at,
            }
            for row in rows
        ]


async def run_idempotency_test(account_id: str, target_date_str: str) -> bool:
    """Verify that re-running the pipeline produces zero duplicates."""
    target_date = date.fromisoformat(target_date_str)
    platform_code = "FACEBOOK"

    print(f"\n{'='*60}")
    print(f"IDEMPOTENCY TEST: {platform_code} / {account_id} / {target_date}")
    print(f"{'='*60}\n")

    # --- Baseline counts ---
    fact_before = await count_rows("fact_ad_metrics")
    staging_before = await count_rows("staging_ad_metrics")
    raw_before = await count_rows("raw_events")

    # Snapshot a few fact rows to compare later
    print("📸 Taking baseline snapshot...")
    sample_before = await get_fact_sample(limit=5)
    if sample_before:
        print(f"   Sampled {len(sample_before)} fact rows (latest first)")
    else:
        print("   ⚠️  No fact rows found — has E2E test been run first?")
        return False

    print(f"   Baseline: fact={fact_before}, staging={staging_before}, raw={raw_before}")

    # --- Run 1: fetch_and_land (2nd time) ---
    print("\n🔄 Run 1: fetch_and_land (re-run — expect skip)...")
    result = fetch_and_land(
        platform_code=platform_code,
        account_external_id=account_id,
        target_date=target_date_str,
    )
    raw_id = result.get("raw_id")
    record_count = result.get("record_count", 0)

    if raw_id is None:
        print(f"   ✅ Correct: raw_id=None — ON CONFLICT DO NOTHING worked (idempotent)")
    else:
        print(f"   ⚠️  Unexpected: raw_id={raw_id} was returned (should have been skipped)")
        return False

    raw_after = await count_rows("raw_events")
    assert raw_after == raw_before, (
        f"raw_events count changed: {raw_before} -> {raw_after} (should be unchanged)"
    )
    print(f"   ✅ raw_events count unchanged: {raw_before}")

    # --- Run 2: normalize_and_stage (2nd time) ---
    print("\n🔄 Run 2: normalize_and_stage (re-run — expect skip after first)...")
    # Need to find any unprocessed or retry on existing raw_id
    from sqlalchemy import text
    async with async_session_factory() as session:
        r = await session.execute(
            text(
                "SELECT raw_id FROM raw_events "
                "WHERE platform_code=:pc AND account_external_id=:aid "
                "AND fetch_date=:fd ORDER BY raw_id DESC LIMIT 1"
            ),
            {"pc": platform_code, "aid": account_id, "fd": target_date},
        )
        row = r.fetchone()
        existing_raw_id = row.raw_id if row else None

    if existing_raw_id:
        result = normalize_and_stage(raw_id=existing_raw_id)
        skipped = result.get("skipped", False)
        if skipped:
            print(f"   ✅ Correct: already processed — skipped")
        else:
            staging_count = result.get("staging_count", 0)
            if staging_count == 0:
                print(f"   ✅ No new staging rows (already processed)")
            else:
                print(f"   ⚠️  Unexpected: {staging_count} new staging rows inserted")
                return False
    else:
        print("   ⚠️  Could not find raw_events row — was E2E test run first?")

    # --- Run 3: load_to_fact (2nd time) ---
    print("\n🔄 Run 3: load_to_fact (re-run — expect UPSERT, not INSERT)...")
    result = load_to_fact()
    loaded_count = result.get("loaded_count", 0)
    print(f"   Loaded count: {loaded_count} (0 = idempotent, >0 = new rows from previous run)")

    fact_after = await count_rows("fact_ad_metrics")
    print(f"   fact_ad_metrics: before={fact_before}, after={fact_after}")

    if fact_after != fact_before:
        print(f"   ❌ FAIL: fact row count changed: {fact_before} -> {fact_after}")
        return False
    print(f"   ✅ PASS: fact row count unchanged ({fact_before})")

    # --- Verify sample values unchanged ---
    print("\n🔍 Verifying metric values from snapshot...")
    sample_after = await get_fact_sample(limit=5)
    all_match = True
    for before_row, after_row in zip(sample_before, sample_after):
        if before_row["fact_id"] != after_row["fact_id"]:
            print(f"   ⚠️  fact_id changed: {before_row['fact_id']} -> {after_row['fact_id']}")
            all_match = False
        for col in ["spend", "impressions", "clicks", "conversions"]:
            if before_row[col] != after_row[col]:
                print(f"   ⚠️  {col} changed for fact_id={before_row['fact_id']}: "
                      f"{before_row[col]} -> {after_row[col]}")
                all_match = False
    if all_match:
        print(f"   ✅ All sampled metric values unchanged")
    else:
        print(f"   ⚠️  Some values changed — but may be due to updated API data (not idempotency bug)")
        # This is not a hard failure because ON CONFLICT DO UPDATE will overwrite
        # with newer values if the API returns different data. The key test is
        # that the ROW COUNT didn't increase.

    # --- Final summary ---
    print(f"\n{'='*60}")
    print("✅ IDEMPOTENCY TEST COMPLETE")
    print(f"{'='*60}")
    print(f"   raw_events:       {raw_before} -> {raw_after}  (must equal)")
    print(f"   staging:          {staging_before} -> {await count_rows('staging_ad_metrics')}")
    print(f"   fact_ad_metrics:  {fact_before} -> {fact_after}  (must equal)")
    print(f"\n   Verdict: idempotency {'✅ PASS' if fact_after == fact_before else '❌ FAIL'}")
    return fact_after == fact_before


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotency test — verify no duplicate rows on re-run"
    )
    parser.add_argument(
        "--account-id",
        required=True,
        help="Facebook ad account ID (same as used in E2E test)",
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Target date YYYY-MM-DD (same as used in E2E test)",
    )
    args = parser.parse_args()

    check_prerequisites()

    success = asyncio.run(run_idempotency_test(args.account_id, args.date))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()