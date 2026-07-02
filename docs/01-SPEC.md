# SPEC: Marketing Analytics Dashboard
> Trạng thái: READY FOR PLAN (bỏ qua bước Discuss — mọi quyết định kiến trúc đã chốt trong tài liệu này)
> Đối tượng thực thi: Cline + GSD Core framework
> Phiên bản: 1.0

---

## 1. TỔNG QUAN & MỤC TIÊU

### 1.1 Bài toán
Xây dựng hệ thống Marketing Analytics Dashboard thu thập dữ liệu quảng cáo từ nhiều nền tảng (Facebook Ads trước, TikTok Ads / Google Ads sau), chuẩn hoá về một mô hình dữ liệu chung, và hiển thị báo cáo tổng hợp cross-platform cho người dùng nội bộ.

### 1.2 Phạm vi (Scope) của lần triển khai đầu tiên
- **Trong scope:** Database schema đầy đủ (kèm khả năng mở rộng platform), ETL pipeline cho Facebook Ads (kiến trúc adapter để cắm TikTok/Google sau), FastAPI backend phục vụ dashboard, các script SQL khởi tạo DB.
- **Ngoài scope (đợt 1):** Adapter thật cho TikTok/Google (chỉ cần interface sẵn sàng), authentication/authorization đầy đủ (đợt 1 dùng API key đơn giản), frontend Next.js (tài liệu này tập trung backend + DB; frontend sẽ có SPEC riêng).

### 1.3 Nguyên tắc kiến trúc bắt buộc
1. **Clean Architecture**: tách rõ `domain` (business logic thuần) khỏi `infrastructure` (DB, API ngoài, framework).
2. **Adapter Pattern** cho mọi platform quảng cáo — thêm platform mới KHÔNG được sửa code core.
3. **3-tầng ETL**: Raw Landing → Staging → Fact. Không insert thẳng raw API response vào bảng Fact.
4. **Idempotency bắt buộc**: mọi job chạy lại nhiều lần không được tạo dữ liệu trùng (dùng UPSERT + UNIQUE constraint).
5. **Star Schema** cho reporting: `dim_*` (dimension) tách biệt `fact_*` (metrics).

---

## 2. YÊU CẦU CHỨC NĂNG (FUNCTIONAL REQUIREMENTS)

| ID | Yêu cầu | Ưu tiên |
|---|---|---|
| FR-01 | Hệ thống crawl dữ liệu quảng cáo (spend, impressions, clicks, conversions) từ Facebook Marketing API theo tài khoản quảng cáo, theo ngày | Must |
| FR-02 | Dữ liệu raw response từ API phải được lưu nguyên vẹn (Raw Landing) trước khi xử lý | Must |
| FR-03 | Dữ liệu phải được chuẩn hoá qua tầng Staging về format chung (`CanonicalAdMetric`) trước khi ghi vào Fact table | Must |
| FR-04 | Job crawl chạy lại nhiều lần với cùng tham số (platform, account, ngày) không được tạo bản ghi trùng | Must |
| FR-05 | API backend cho phép truy vấn metrics theo khoảng ngày (`date_from`, `date_to`), lọc theo platform, lọc theo campaign | Must |
| FR-06 | API backend hỗ trợ so sánh với kỳ trước (previous period) và trả sẵn % thay đổi | Must |
| FR-07 | API backend có endpoint riêng để lấy danh sách campaign phục vụ filter dropdown | Must |
| FR-08 | Hệ thống cho phép thêm platform mới (VD TikTok) chỉ bằng cách: (a) thêm 1 dòng `dim_platform`, (b) viết 1 class Adapter mới — không migrate schema | Must |
| FR-09 | API hỗ trợ tổng hợp theo granularity: ngày / tuần / tháng | Should |
| FR-10 | Ghi log lỗi validation ở tầng staging (không chặn toàn bộ batch nếu 1 record lỗi) | Should |

## 3. YÊU CẦU PHI CHỨC NĂNG (NON-FUNCTIONAL REQUIREMENTS)

| ID | Yêu cầu |
|---|---|
| NFR-01 | Backend viết bằng Python 3.12+, FastAPI, quản lý môi trường bằng `uv` (Astral) |
| NFR-02 | ETL chạy bằng Celery + Redis (broker + cache layer dùng chung) |
| NFR-03 | Database: PostgreSQL 15+ |
| NFR-04 | Toàn bộ connection string / secrets đọc từ biến môi trường (`.env`), KHÔNG hardcode |
| NFR-05 | Mọi endpoint trả response theo Pydantic schema tường minh, có validation |
| NFR-06 | Query aggregate cho dashboard phải cache được (Redis), TTL ngắn hơn nếu date range chứa "hôm nay" |
| NFR-07 | Code tổ chức theo Clean Architecture: `domain/`, `adapters/`, `infra/`, `api/` tách biệt rõ ràng |

---

## 4. THIẾT KẾ DATABASE (POSTGRESQL)

### 4.1 Nguyên tắc thiết kế
Sử dụng **Star Schema hybrid**: dimension tables mỏng chuẩn 3NF, fact table dùng cột cứng cho metric phổ biến (spend, impressions, clicks, conversions) + cột `JSONB extra_metrics` cho field đặc thù platform. Đây KHÔNG phải EAV thuần — mục tiêu là giữ tốc độ query aggregate trong khi vẫn linh hoạt mở rộng.

### 4.2 Sơ đồ luồng dữ liệu (data flow)

```
[Facebook / TikTok / Google API]
        │  (Adapter.fetch_raw)
        ▼
┌────────────────────┐
│ raw_events          │  Lưu y nguyên JSON, append-only, KHÔNG business logic
└────────────────────┘
        │  (Normalizer job — chạy độc lập, replay được)
        ▼
┌────────────────────┐
│ staging_ad_metrics   │  Field đã map tên chuẩn, external_id dạng string, CHƯA resolve FK
└────────────────────┘
        │  (Load job — resolve dim FK, UPSERT)
        ▼
┌────────────────────┐        ┌──────────────┐
│ fact_ad_metrics      │◄──────│ dim_platform │
│ (grain: 1 ad/1 ngày) │◄──────│ dim_account  │
└────────────────────┘◄──────│ dim_campaign │
                              │ dim_ad_set   │
                              │ dim_ad       │
                              └──────────────┘
```

### 4.3 Danh sách bảng (chi tiết DDL nằm ở thư mục `database/`, xem mục 6)

**Dimension tables:**
- `dim_platform` — danh mục nền tảng (FACEBOOK, TIKTOK, GOOGLE...)
- `dim_account` — tài khoản quảng cáo, thuộc 1 platform
- `dim_campaign` — chiến dịch, thuộc 1 account
- `dim_ad_set` — nhóm quảng cáo, thuộc 1 campaign, có `targeting_meta JSONB`
- `dim_ad` — quảng cáo cụ thể, thuộc 1 ad_set, có `creative_meta JSONB`

**Landing/Staging (tầng trung gian bắt buộc — xem mục 4.4):**
- `raw_events` — raw JSON response, append-only
- `staging_ad_metrics` — đã map field name, chưa resolve FK, có `validation_errors JSONB`

**Fact table:**
- `fact_ad_metrics` — grain = 1 ad × 1 ngày, `UNIQUE(ad_id, date)` phục vụ idempotency (UPSERT)

### 4.4 Vì sao cần tầng Staging (bắt buộc, không phải optional)
1. **Audit trail**: khi số liệu dashboard lệch so với Ads Manager, cần đối chiếu raw response gốc.
2. **Replay an toàn**: nếu logic normalize sai, chỉ cần chạy lại normalize job trên `raw_events` đã lưu — không cần gọi lại API (tiết kiệm quota, tránh mất dữ liệu lịch sử ngoài giới hạn API).
3. **Cô lập lỗi**: 1 record lỗi validation ở staging không làm fail cả batch; lỗi được ghi vào `validation_errors` để xử lý riêng.
4. **Tách decoupling giữa fetch và transform**: fetch API thành công không phụ thuộc vào transform logic có đúng hay không.

### 4.5 Cơ chế mở rộng platform mới
Khi thêm TikTok Ads:
- Insert 1 dòng vào `dim_platform`.
- Viết `TikTokAdapter` implement `AdPlatformAdapter` interface (xem mục 5.2).
- Field đặc thù TikTok không có trong Facebook → map vào `extra_metrics JSONB`, KHÔNG alter schema.
- Nếu về sau 1 metric trở nên phổ biến/dùng chung → promote thành cột thật qua migration có kiểm soát (không phải reactive).

---

## 5. KIẾN TRÚC ETL PIPELINE

### 5.1 Lựa chọn công nghệ: Celery + Redis (không dùng Cron đơn giản)
Lý do: hệ thống xác định trước sẽ multi-platform, multi-account → cần retry có kiểm soát (exponential backoff khi gặp rate limit), cần queue riêng theo platform để không đá lẫn nhau, cần observability (Flower). Redis dùng chung làm broker (Celery) và cache layer (API response) — không cần thêm hạ tầng.

### 5.2 Cấu trúc thư mục bắt buộc (Clean Architecture)

```
backend/
├── app/
│   ├── domain/
│   │   ├── models.py            # CanonicalAdMetric (dataclass/Pydantic model chuẩn hoá)
│   │   └── normalizer.py        # Map raw JSON -> CanonicalAdMetric
│   ├── adapters/
│   │   ├── base.py              # abstract class AdPlatformAdapter
│   │   ├── facebook_adapter.py  # implement cho Meta Marketing API
│   │   ├── tiktok_adapter.py    # stub, để trống method fetch_raw (TODO đợt 2)
│   │   └── google_adapter.py    # stub, để trống method fetch_raw (TODO đợt 2)
│   ├── repository/
│   │   ├── raw_events_repo.py
│   │   ├── staging_repo.py
│   │   └── fact_repo.py         # UPSERT logic, idempotency
│   ├── etl/
│   │   ├── celery_app.py
│   │   ├── tasks.py             # fetch_and_land, normalize_and_stage, load_to_fact
│   │   └── rate_limiter.py      # token bucket per platform
│   ├── api/
│   │   ├── routers/
│   │   │   ├── metrics.py       # GET /api/v1/metrics
│   │   │   └── campaigns.py     # GET /api/v1/campaigns
│   │   ├── schemas/
│   │   │   ├── metrics_schema.py
│   │   │   └── campaign_schema.py
│   │   └── deps.py              # DB session, Redis client dependency injection
│   ├── infra/
│   │   ├── db.py                # SQLAlchemy engine/session (async)
│   │   ├── redis_client.py
│   │   └── settings.py          # Pydantic Settings đọc từ .env
│   └── main.py                  # FastAPI app entrypoint
├── pyproject.toml               # quản lý bằng uv
├── .env.example
└── README.md
```

### 5.3 Interface Adapter (hợp đồng bắt buộc mọi platform phải tuân theo)

```python
# app/adapters/base.py
from abc import ABC, abstractmethod
from datetime import date

class AdPlatformAdapter(ABC):
    platform_code: str  # 'FACEBOOK' | 'TIKTOK' | 'GOOGLE'

    @abstractmethod
    async def fetch_raw(self, account_external_id: str, target_date: date) -> list[dict]:
        """Gọi API platform, trả về list raw JSON record (chưa transform)."""
        ...

    @abstractmethod
    def normalize(self, raw: dict) -> "CanonicalAdMetric":
        """Map raw JSON -> CanonicalAdMetric (domain model chuẩn hoá)."""
        ...
```

`CanonicalAdMetric` domain model:

```python
# app/domain/models.py
from pydantic import BaseModel
from datetime import date
from decimal import Decimal

class CanonicalAdMetric(BaseModel):
    platform_code: str
    account_external_id: str
    campaign_external_id: str
    ad_set_external_id: str
    ad_external_id: str
    date: date
    spend: Decimal
    impressions: int
    clicks: int
    conversions: int
    conversion_value: Decimal
    extra_metrics: dict = {}
```

### 5.4 Celery tasks (3 bước tách rời, mỗi bước idempotent và có thể chạy lại độc lập)

```python
# app/etl/tasks.py

@app.task(bind=True, max_retries=5, rate_limit="200/m")
def fetch_and_land(self, platform_code: str, account_id: str, target_date: str):
    """Bước 1: gọi API, ghi thẳng vào raw_events. Retry với exponential backoff khi 429."""
    ...

@app.task
def normalize_and_stage(raw_id: int):
    """Bước 2: đọc raw_events chưa processed, chạy Normalizer, ghi vào staging_ad_metrics."""
    ...

@app.task
def load_to_fact(staging_batch_date: str):
    """Bước 3: resolve dimension FK (get-or-create dim_* record), UPSERT vào fact_ad_metrics."""
    ...
```

### 5.5 Idempotency
- `raw_events`: `UNIQUE(platform_code, account_external_id, fetch_date)` — tránh lưu trùng response của cùng 1 lần fetch.
- `fact_ad_metrics`: `UNIQUE(ad_id, date)` kết hợp `INSERT ... ON CONFLICT DO UPDATE` — job chạy lại bao nhiêu lần cũng an toàn, không cần logic check-before-insert (tránh race condition).

### 5.6 Rate Limit — 3 lớp
1. Celery task-level: `@app.task(rate_limit='200/m')`.
2. Token bucket riêng theo platform trong `infra/rate_limiter.py` (mỗi platform limit khác nhau).
3. Exponential backoff + jitter khi gặp HTTP 429: `countdown = 2 ** retries + random.uniform(0,1)`.

---

## 6. DANH SÁCH SCRIPT DATABASE (thư mục `database/`)

Chạy tuần tự theo đúng số thứ tự, thủ công qua `psql` hoặc client bất kỳ:

| File | Nội dung |
|---|---|
| `001_extensions_and_schema.sql` | Tạo extension cần thiết (`pgcrypto`), tạo schema riêng nếu cần |
| `002_dim_tables.sql` | Tạo `dim_platform`, `dim_account`, `dim_campaign`, `dim_ad_set`, `dim_ad` |
| `003_raw_and_staging_tables.sql` | Tạo `raw_events`, `staging_ad_metrics` |
| `004_fact_table.sql` | Tạo `fact_ad_metrics` |
| `005_indexes_and_constraints.sql` | Index bổ sung cho query dashboard (date range, platform filter) |
| `006_seed_platforms.sql` | Insert sẵn 3 dòng platform: FACEBOOK, TIKTOK, GOOGLE |

Chi tiết DDL từng file nằm trực tiếp trong file tương ứng — Cline chỉ cần đọc và chạy, không cần generate lại.

---

## 7. API ENDPOINTS (đợt 1)

### 7.1 `GET /api/v1/metrics`
Query params: `date_from`, `date_to`, `platform_codes[]`, `campaign_ids[]`, `granularity` (day/week/month), `compare_previous_period` (bool), `compare_mode` (previous_period/previous_year).

Response: object gồm `current: list[MetricRow]`, `previous: list[MetricRow] | null`, `summary: {metric_name: {current, previous, change_pct}}`.

Logic tính previous period nằm ở backend (không để frontend tự suy ra), dùng hàm `shift_period()`.

### 7.2 `GET /api/v1/campaigns`
Query params: `platform_codes[]` (optional).
Response: `list[{id, name, platform_code}]`. Cache Redis TTL 10-15 phút (danh sách campaign không đổi liên tục trong ngày).

### 7.3 Caching
Redis cache theo key build từ toàn bộ query params. TTL 300s nếu `date_to >= hôm nay - 1 ngày`, TTL 3600s nếu date range đã "đóng băng" (dữ liệu quá khứ ổn định).

---

## 8. ENVIRONMENT VARIABLES

Xem file `backend/.env.example` — chứa sẵn tất cả biến cần thiết, chỉ cần điền giá trị thật:
- `DATABASE_URL` (Postgres connection string)
- `REDIS_URL` (Celery broker + cache)
- `FACEBOOK_APP_ID`, `FACEBOOK_APP_SECRET`, `FACEBOOK_ACCESS_TOKEN`
- `TIKTOK_APP_ID`, `TIKTOK_APP_SECRET` (để trống, dùng cho đợt 2)
- `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`, `GOOGLE_ADS_CLIENT_SECRET` (để trống, đợt 2)
- `API_KEY` (bảo vệ endpoint đợt 1, đơn giản hoá auth)

---

## 9. TASK BREAKDOWN CHO GSD PLAN PHASE

> Cline thực hiện tuần tự theo thứ tự dưới đây. Mỗi task nên là 1 commit/1 checkpoint riêng.

### Phase A — Hạ tầng & Database
- [ ] A1. Khởi tạo `pyproject.toml` với `uv`, cài FastAPI, SQLAlchemy (async), asyncpg, celery, redis, pydantic-settings, httpx.
- [ ] A2. Tạo `.env.example` (đã có sẵn — xem `backend/.env.example`), copy thành `.env` để dev điền giá trị.
- [ ] A3. Xác nhận 6 script SQL trong `database/` chạy được tuần tự trên Postgres instance của dev (không cần Cline generate, chỉ cần verify).
- [ ] A4. Viết `infra/settings.py` (Pydantic Settings đọc `.env`), `infra/db.py` (async engine/session), `infra/redis_client.py`.

### Phase B — Domain & Adapter layer
- [ ] B1. Viết `domain/models.py` (`CanonicalAdMetric`).
- [ ] B2. Viết `adapters/base.py` (interface `AdPlatformAdapter`).
- [ ] B3. Viết `adapters/facebook_adapter.py` — gọi Facebook Marketing API `/insights` endpoint, trả raw JSON.
- [ ] B4. Viết `domain/normalizer.py` — map raw Facebook JSON → `CanonicalAdMetric`.
- [ ] B5. Tạo stub rỗng `adapters/tiktok_adapter.py`, `adapters/google_adapter.py` (raise `NotImplementedError`, chuẩn bị sẵn cho đợt 2).

### Phase C — Repository & ETL tasks
- [ ] C1. Viết `repository/raw_events_repo.py` (insert raw, mark processed).
- [ ] C2. Viết `repository/staging_repo.py` (insert staging, ghi validation_errors nếu có).
- [ ] C3. Viết `repository/fact_repo.py` (get-or-create dimension record, UPSERT vào fact_ad_metrics).
- [ ] C4. Viết `etl/celery_app.py`, `etl/rate_limiter.py`.
- [ ] C5. Viết 3 Celery tasks: `fetch_and_land`, `normalize_and_stage`, `load_to_fact` (theo mục 5.4).
- [ ] C6. Test thủ công: chạy `fetch_and_land` cho 1 account/1 ngày thật, verify data chảy đúng qua 3 tầng.

### Phase D — API layer
- [ ] D1. Viết `api/schemas/metrics_schema.py`, `api/schemas/campaign_schema.py`.
- [ ] D2. Viết SQL aggregate query trong `fact_repo.py` (theo mẫu mục 7.1).
- [ ] D3. Viết `api/routers/metrics.py` — endpoint `GET /api/v1/metrics`, có xử lý `compare_previous_period`.
- [ ] D4. Viết `api/routers/campaigns.py` — endpoint `GET /api/v1/campaigns`.
- [ ] D5. Tích hợp Redis cache vào repository layer (theo mục 7.3).
- [ ] D6. Viết `main.py`, đăng ký router, middleware API key auth đơn giản.

### Phase E — Kiểm thử & bàn giao
- [ ] E1. Test end-to-end: crawl Facebook 1 account → verify qua `/api/v1/metrics`.
- [ ] E2. Test idempotency: chạy lại `fetch_and_land` + `load_to_fact` 2 lần liên tiếp, verify không có row trùng.
- [ ] E3. Viết `README.md` hướng dẫn setup (`uv sync`, chạy SQL script, chạy Celery worker, chạy `uvicorn`).

---

## 10. TIÊU CHÍ NGHIỆM THU (ACCEPTANCE CRITERIA)

1. Chạy 6 script SQL tuần tự không lỗi trên Postgres sạch.
2. Crawl được dữ liệu thật từ 1 Facebook Ad Account, dữ liệu xuất hiện đúng ở cả 3 tầng (raw → staging → fact).
3. Gọi `GET /api/v1/metrics?date_from=...&date_to=...` trả về đúng số liệu aggregate, khớp thủ công với Facebook Ads Manager.
4. Chạy lại toàn bộ pipeline cho cùng ngày/account 2 lần → số dòng trong `fact_ad_metrics` không đổi (idempotent).
5. Thêm 1 platform mới (giả lập) chỉ cần thêm adapter class + 1 dòng insert `dim_platform` — không phải sửa bảng đã có.
