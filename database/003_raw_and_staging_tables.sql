-- ============================================================
-- 003_raw_and_staging_tables.sql
-- Mục đích: Tầng trung gian bắt buộc — Raw Landing + Staging.
-- Không được insert thẳng raw API response vào fact_ad_metrics.
-- ============================================================

-- Tầng 1: Raw Landing — lưu y nguyên JSON response, append-only, KHÔNG business logic
CREATE TABLE IF NOT EXISTS raw_events (
    raw_id                  BIGSERIAL PRIMARY KEY,
    platform_code           VARCHAR(20) NOT NULL,
    account_external_id     VARCHAR(100) NOT NULL,
    fetch_date              DATE NOT NULL,           -- ngày dữ liệu report (không phải ngày chạy job)
    payload                 JSONB NOT NULL,          -- response gốc từ API, không transform
    fetched_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed               BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(platform_code, account_external_id, fetch_date)
);
COMMENT ON TABLE raw_events IS 'Landing zone. Giữ bằng chứng gốc để replay/debug khi cần, không phụ thuộc vào tính đúng của normalize logic.';

CREATE INDEX IF NOT EXISTS idx_raw_events_unprocessed
    ON raw_events (processed)
    WHERE processed = FALSE;

CREATE INDEX IF NOT EXISTS idx_raw_events_platform_date
    ON raw_events (platform_code, fetch_date);


-- Tầng 2: Staging — field đã map tên chuẩn (CanonicalAdMetric), CHƯA resolve dimension FK
CREATE TABLE IF NOT EXISTS staging_ad_metrics (
    staging_id              BIGSERIAL PRIMARY KEY,
    raw_id                  BIGINT REFERENCES raw_events(raw_id),
    platform_code           VARCHAR(20) NOT NULL,
    account_external_id     VARCHAR(100) NOT NULL,
    campaign_external_id    VARCHAR(100),
    ad_set_external_id      VARCHAR(100),
    ad_external_id          VARCHAR(100),
    date                    DATE NOT NULL,
    spend                   NUMERIC(14,4) DEFAULT 0,
    impressions             BIGINT DEFAULT 0,
    clicks                  BIGINT DEFAULT 0,
    conversions             BIGINT DEFAULT 0,
    conversion_value        NUMERIC(14,4) DEFAULT 0,
    extra_metrics           JSONB DEFAULT '{}',
    validation_errors       JSONB,                   -- NULL nếu record hợp lệ
    loaded_to_fact          BOOLEAN NOT NULL DEFAULT FALSE,
    staged_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE staging_ad_metrics IS 'Đã chuẩn hoá field name. 1 record lỗi ghi vào validation_errors, không chặn batch còn lại.';

CREATE INDEX IF NOT EXISTS idx_staging_not_loaded
    ON staging_ad_metrics (loaded_to_fact)
    WHERE loaded_to_fact = FALSE;

CREATE INDEX IF NOT EXISTS idx_staging_ad_date
    ON staging_ad_metrics (platform_code, ad_external_id, date);
