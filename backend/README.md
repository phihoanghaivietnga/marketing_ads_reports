# Marketing Analytics Dashboard — Backend

FastAPI backend + Celery ETL pipeline for cross-platform marketing analytics.
Fetches ad data from Facebook Ads (TikTok & Google coming in Phase 2),
normalizes it through a 3-tier ETL pipeline, and serves aggregated reports via REST API.

---

## 1. Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.12+ | Runtime |
| uv (Astral) | latest | Package & environment manager |
| PostgreSQL | 15+ | Primary database |
| Redis | 7+ | Celery broker + API cache |
| Docker (optional) | latest | Run Redis locally without install |

### Facebook API access

To use the Facebook adapter, you need:
- A Facebook App with **Marketing API** enabled
- An access token with `ads_read` permission
- At least one Ad Account with recent campaign data

Set these in `.env` (see section 3).

---

## 2. Quick Start (< 15 minutes)

```bash
# 1. Install dependencies
cd backend
uv sync

# 2. Configure environment
cp .env.example .env
# Edit .env — fill in DATABASE_URL, REDIS_URL, FACEBOOK_ACCESS_TOKEN

# 3. Create database and run migrations
#    (Run from project root, against your Postgres instance)
psql "$DATABASE_URL" -f ../database/001_extensions_and_schema.sql
psql "$DATABASE_URL" -f ../database/002_dim_tables.sql
psql "$DATABASE_URL" -f ../database/003_raw_and_staging_tables.sql
psql "$DATABASE_URL" -f ../database/004_fact_table.sql
psql "$DATABASE_URL" -f ../database/005_indexes_and_constraints.sql
psql "$DATABASE_URL" -f ../database/006_seed_platforms.sql

# 4. Start Redis (Docker or local)
docker run -d --name redis -p 6379:6379 redis:7-alpine

# 5. Start Celery worker (ETL pipeline)
uv run celery -A app.etl.celery_app worker --loglevel=info -Q fetch,normalize,load

# 6. Start API server (in another terminal)
uv run uvicorn app.main:app --reload --port 8000

# 7. Verify
curl http://localhost:8000/health
# → {"status":"ok"}

# Swagger UI at http://localhost:8000/docs
```

---

## 3. Environment Variables

All variables are in `.env` (copy from `.env.example`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_ENV` | No | `development` | `development` / `staging` / `production` |
| `APP_DEBUG` | No | `true` | Enable SQL echo + debug logging |
| `API_V1_PREFIX` | No | `/api/v1` | API URL prefix |
| `API_KEY` | **Yes** | — | X-API-Key header value for auth |
| `DATABASE_URL` | **Yes** | — | `postgresql+asyncpg://user:pass@host:port/db` |
| `DB_POOL_SIZE` | No | `10` | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | No | `20` | Max overflow connections |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis for API cache |
| `CELERY_BROKER_URL` | No | `redis://localhost:6379/1` | Celery message broker |
| `CELERY_RESULT_BACKEND` | No | `redis://localhost:6379/2` | Celery result store |
| `CACHE_TTL_RECENT` | No | `300` | Cache TTL when `date_to` is within 24h |
| `CACHE_TTL_HISTORICAL` | No | `3600` | Cache TTL for frozen historical data |
| `FACEBOOK_APP_ID` | No | — | Facebook App ID |
| `FACEBOOK_APP_SECRET` | No | — | Facebook App Secret |
| `FACEBOOK_ACCESS_TOKEN` | **Yes** | — | Facebook API access token |
| `FACEBOOK_API_VERSION` | No | `v19.0` | Facebook Graph API version |
| `TIKTOK_APP_ID` | No | — | Phase 2 — leave empty |
| `TIKTOK_APP_SECRET` | No | — | Phase 2 — leave empty |
| `TIKTOK_ACCESS_TOKEN` | No | — | Phase 2 — leave empty |
| `GOOGLE_ADS_*` | No | — | Phase 2 — leave empty (5 variables) |
| `RATE_LIMIT_FACEBOOK_PER_MIN` | No | `200` | Facebook API rate limit |
| `RATE_LIMIT_TIKTOK_PER_MIN` | No | `100` | TikTok API rate limit |
| `RATE_LIMIT_GOOGLE_PER_MIN` | No | `150` | Google Ads API rate limit |

---

## 4. Database Setup

Run the 6 SQL scripts **in order** from the `database/` directory:

| Order | File | What it creates |
|---|---|---|
| 1 | `001_extensions_and_schema.sql` | `pgcrypto` + `pg_trgm` extensions |
| 2 | `002_dim_tables.sql` | Star Schema dimensions: platform, account, campaign, ad_set, ad |
| 3 | `003_raw_and_staging_tables.sql` | Landing zone: `raw_events` + `staging_ad_metrics` |
| 4 | `004_fact_table.sql` | `fact_ad_metrics` with `UNIQUE(ad_id, date)` for idempotent UPSERT |
| 5 | `005_indexes_and_constraints.sql` | Query performance indexes |
| 6 | `006_seed_platforms.sql` | Insert FACEBOOK, TIKTOK, GOOGLE into `dim_platform` |

All scripts use `IF NOT EXISTS` / `ON CONFLICT DO NOTHING` — safe to re-run.

### Database Schema (Star Schema)

```
dim_platform (platform_code: FACEBOOK|TIKTOK|GOOGLE)
  └─ dim_account (external_id, UNIQUE per platform)
       └─ dim_campaign (external_id, UNIQUE per account)
            └─ dim_ad_set (external_id, targeting_meta JSONB)
                 └─ dim_ad (external_id, creative_meta JSONB)
                      └─ fact_ad_metrics (1 row per ad per day, UNIQUE)
```

### ETL Data Flow

```
[Facebook API] ──fetch──> raw_events (JSONB, append-only)
                               │
                     normalize_and_stage
                               │
                               ▼
                    staging_ad_metrics (canonical fields, FK unresolved)
                               │
                        load_to_fact
                               │
                               ▼
                    fact_ad_metrics (FK resolved, UPSERT idempotent)
```

---

## 5. Running the ETL Pipeline

### Trigger a single fetch manually

```python
# Start a Python shell in the backend directory
uv run python

>>> from app.etl.tasks import fetch_and_land, normalize_and_stage, load_to_fact

# Step 1: Fetch raw data from Facebook
>>> result = fetch_and_land("FACEBOOK", "act_123456789", "2026-06-01")
>>> raw_id = result["raw_id"]
>>> print(f"Inserted raw_id={raw_id}, records={result['record_count']}")

# Step 2: Normalize and stage
>>> result = normalize_and_stage(raw_id)
>>> print(f"Staging: {result['staging_count']} rows, {result['error_count']} errors")

# Step 3: Load to fact table
>>> result = load_to_fact()
>>> print(f"Loaded: {result['loaded_count']} fact rows")
```

### Using the E2E test script

```bash
cd backend
uv run python ../scripts/test_e2e.py --account-id act_123456789 --date 2026-06-01
```

### Using the idempotency test script

```bash
cd backend
uv run python ../scripts/test_idempotency.py --account-id act_123456789 --date 2026-06-01
```

### Schedule with cron

```bash
# Run fetch for yesterday's data every day at 2 AM
0 2 * * * cd /path/to/backend && uv run python -c "from app.etl.tasks import fetch_and_land; fetch_and_land('FACEBOOK', 'act_123456789', (__import__('datetime').date.today() - __import__('datetime').timedelta(days=1)).isoformat())"
```

### Monitor with Flower

```bash
uv run celery -A app.etl.celery_app flower --port=5555
# Dashboard at http://localhost:5555
```

---

## 6. API Reference

Base URL: `http://localhost:8000`

All `/api/v1/*` endpoints require header: `X-API-Key: <your-api-key>`

### `GET /health`

No auth required.

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### `GET /api/v1/metrics`

Aggregate ad metrics with optional filters and period comparison.

**Query Parameters:**

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `date_from` | date (YYYY-MM-DD) | Yes | — | Start date (inclusive) |
| `date_to` | date (YYYY-MM-DD) | Yes | — | End date (inclusive) |
| `platform_codes` | list[str] | No | `null` | Filter by platform: `FACEBOOK`, `TIKTOK`, `GOOGLE` |
| `campaign_ids` | list[int] | No | `null` | Filter by campaign IDs |
| `granularity` | enum | No | `day` | `day` / `week` / `month` |
| `compare_previous_period` | bool | No | `false` | Include previous period data |
| `compare_mode` | enum | No | `previous_period` | `previous_period` / `previous_year` |

**Example 1 — Basic query:**

```bash
curl -H "X-API-Key: change-me-to-a-random-secret" \
  "http://localhost:8000/api/v1/metrics?date_from=2026-06-01&date_to=2026-06-07"
```

**Response:**

```json
{
  "current": [
    {
      "date": "2026-06-01",
      "spend": "125.50",
      "impressions": 5000,
      "clicks": 120,
      "conversions": 5,
      "conversion_value": "250.00"
    }
  ],
  "previous": null,
  "summary": {
    "spend": {
      "current": "125.50",
      "previous": null,
      "change_pct": null
    },
    "impressions": {
      "current": "5000",
      "previous": null,
      "change_pct": null
    },
    "clicks": {
      "current": "120",
      "previous": null,
      "change_pct": null
    },
    "conversions": {
      "current": "5",
      "previous": null,
      "change_pct": null
    },
    "conversion_value": {
      "current": "250.00",
      "previous": null,
      "change_pct": null
    }
  }
}
```

**Example 2 — With comparison:**

```bash
curl -H "X-API-Key: change-me-to-a-random-secret" \
  "http://localhost:8000/api/v1/metrics?date_from=2026-06-01&date_to=2026-06-07&compare_previous_period=true&compare_mode=previous_period"
```

### `GET /api/v1/campaigns`

List campaigns for filter dropdown.

**Query Parameters:**

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `platform_codes` | list[str] | No | `null` | Filter by platform |

**Example:**

```bash
curl -H "X-API-Key: change-me-to-a-random-secret" \
  "http://localhost:8000/api/v1/campaigns?platform_codes=FACEBOOK&platform_codes=GOOGLE"
```

**Response:**

```json
{
  "campaigns": [
    {"id": 1, "name": "Summer Sale 2026", "platform_code": "FACEBOOK"},
    {"id": 2, "name": "Retargeting Q3", "platform_code": "FACEBOOK"}
  ],
  "total": 2
}
```

### Caching

- `/api/v1/metrics`: cached in Redis with TTL 300s (recent data) or 3600s (historical)
- `/api/v1/campaigns`: cached in Redis with TTL 600s
- Cache key = SHA-256 hash of all query parameters
- Cache failures never block the request

---

## 7. Architecture Overview

### Clean Architecture (Hexagonal)

```
┌─────────────────────────────────────────────────┐
│                   API Layer                      │
│  api/routers/   api/schemas/   api/deps.py      │
│  (FastAPI endpoints, Pydantic validation, auth)  │
├─────────────────────────────────────────────────┤
│                  Domain Layer                    │
│  domain/models.py   domain/normalizer.py         │
│  (Pure business logic, CanonicalAdMetric)        │
├─────────────────────────────────────────────────┤
│                 Adapter Layer                    │
│  adapters/base.py   adapters/facebook_adapter.py │
│  (Platform-specific API integrations)            │
├─────────────────────────────────────────────────┤
│               Repository Layer                   │
│  repository/raw_events_repo.py                   │
│  repository/staging_repo.py                      │
│  repository/fact_repo.py                         │
│  (Database access, raw SQL, idempotent UPSERT)   │
├─────────────────────────────────────────────────┤
│                   ETL Layer                      │
│  etl/celery_app.py   etl/tasks.py                │
│  etl/rate_limiter.py                             │
│  (Celery workers, 3-step pipeline)               │
├─────────────────────────────────────────────────┤
│             Infrastructure Layer                 │
│  infra/settings.py   infra/db.py                 │
│  infra/redis_client.py                           │
│  (Config, DB engine, Redis pool)                 │
└─────────────────────────────────────────────────┘
```

### Adding a New Platform (3 steps)

1. **Insert platform seed:**
   ```sql
   INSERT INTO dim_platform (platform_code, platform_name)
   VALUES ('LINKEDIN', 'LinkedIn Ads')
   ON CONFLICT (platform_code) DO NOTHING;
   ```

2. **Write adapter class:**
   ```python
   # adapters/linkedin_adapter.py
   from app.adapters.base import AdPlatformAdapter
   from app.domain.models import CanonicalAdMetric

   class LinkedInAdapter(AdPlatformAdapter):
       platform_code = "LINKEDIN"
       async def fetch_raw(self, account_external_id, target_date):
           # Call LinkedIn Ads API
           ...
       def normalize(self, raw):
           # Map LinkedIn fields -> CanonicalAdMetric
           ...
   ```

3. **Register in normalizer:**
   ```python
   # domain/normalizer.py — add to _get_registry()
   from app.adapters.linkedin_adapter import LinkedInAdapter
   _adapter_registry["LINKEDIN"] = LinkedInAdapter
   ```

**No schema migration needed.** Platform-specific fields go into `extra_metrics` JSONB.

---

## 8. Testing

### End-to-End Test

Fetches real Facebook data and verifies it flows through all 3 tiers:

```bash
cd backend
uv run python ../scripts/test_e2e.py --account-id act_123456789 --date 2026-06-01
```

Expected output:
- `raw_events` has 1 row with `processed=FALSE`
- `staging_ad_metrics` has normalized rows with `loaded_to_fact=FALSE`
- `fact_ad_metrics` has aggregated metrics
- `GET /api/v1/metrics` returns matching data

### Idempotency Test

Verifies re-running the pipeline creates zero duplicates:

```bash
cd backend
uv run python ../scripts/test_idempotency.py --account-id act_123456789 --date 2026-06-01
```

Expected output:
- `fact_ad_metrics` row count unchanged before/after re-run
- `fetch_and_land` returns `raw_id=None` (ON CONFLICT DO NOTHING)
- `normalize_and_stage` skips already-processed raw rows
- `load_to_fact` returns `loaded_count=0` (idempotent)

### Running with pytest

```bash
cd backend
uv run pytest ../scripts/ -v
```

---

## 9. Troubleshooting

### "password authentication failed for user postgres"

PostgreSQL is not running or credentials are wrong.
- Check `DATABASE_URL` in `.env`
- Verify PostgreSQL is running: `pg_isready`
- Ensure the database exists: `createdb marketing_analytics`

### "ConnectionRefusedError" on Redis

Redis is not running.
```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

### "FACEBOOK_ACCESS_TOKEN is not set"

The Facebook adapter requires a valid access token.
- Get a token from [Facebook Graph API Explorer](https://developers.facebook.com/tools/explorer/)
- Add `ads_read` permission
- Copy the token to `FACEBOOK_ACCESS_TOKEN` in `.env`

### "Error validating access token" from Facebook

The token has expired or lacks permissions.
- Facebook short-lived tokens expire in ~1 hour
- Use a System User token or exchange for a long-lived token
- Verify the token has `ads_read` scope

### HTTP 401 on API calls

The `X-API-Key` header is missing or wrong.
- Check `API_KEY` in `.env`
- Include header: `X-API-Key: <value>`
- Default value from `.env.example`: `change-me-to-a-random-secret`

### Staging rows have `validation_errors`

Some raw records failed normalization.
```sql
SELECT staging_id, validation_errors
FROM staging_ad_metrics
WHERE validation_errors IS NOT NULL;
```
Common causes:
- Missing `date_start` in Facebook response
- Empty `campaign_id` or `ad_id`
- Negative metric values

### Celery worker not processing tasks

Check the worker queue configuration.
```bash
uv run celery -A app.etl.celery_app worker -Q fetch,normalize,load --loglevel=info
```
Verify Redis is accessible at `CELERY_BROKER_URL`.

---

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI entrypoint
│   ├── domain/
│   │   ├── models.py            # CanonicalAdMetric
│   │   └── normalizer.py        # normalize_raw() dispatcher
│   ├── adapters/
│   │   ├── base.py              # AdPlatformAdapter ABC
│   │   ├── facebook_adapter.py  # Facebook Marketing API
│   │   ├── tiktok_adapter.py    # Stub (Phase 2)
│   │   └── google_adapter.py    # Stub (Phase 2)
│   ├── repository/
│   │   ├── raw_events_repo.py   # Raw JSON landing
│   │   ├── staging_repo.py      # Staging insert/query
│   │   └── fact_repo.py         # Dimension resolution + UPSERT + aggregate queries
│   ├── etl/
│   │   ├── celery_app.py        # Celery configuration
│   │   ├── tasks.py             # fetch_and_land, normalize_and_stage, load_to_fact
│   │   └── rate_limiter.py      # TokenBucket per platform
│   ├── api/
│   │   ├── deps.py              # API key auth, DB/Redis dependencies
│   │   ├── routers/
│   │   │   ├── metrics.py       # GET /api/v1/metrics
│   │   │   └── campaigns.py     # GET /api/v1/campaigns
│   │   └── schemas/
│   │       ├── metrics_schema.py
│   │       └── campaign_schema.py
│   └── infra/
│       ├── settings.py          # Pydantic Settings from .env
│       ├── db.py                # Async SQLAlchemy engine + session
│       └── redis_client.py      # Async Redis client
├── pyproject.toml               # uv dependencies
├── .env.example                 # Environment template
└── README.md                    # This file