-- ============================================================
-- 004_fact_table.sql
-- Mục đích: Bảng Fact chính, phục vụ trực tiếp query dashboard.
-- Grain: 1 dòng = 1 ad x 1 ngày.
-- ============================================================

CREATE TABLE IF NOT EXISTS fact_ad_metrics (
    fact_id             BIGSERIAL PRIMARY KEY,
    ad_id                BIGINT NOT NULL REFERENCES dim_ad(ad_id),
    date                 DATE NOT NULL,

    -- Core metrics: universal, mọi platform đều có -> cột cứng để query nhanh
    spend                NUMERIC(14,4) NOT NULL DEFAULT 0,
    impressions          BIGINT NOT NULL DEFAULT 0,
    clicks               BIGINT NOT NULL DEFAULT 0,
    conversions          BIGINT NOT NULL DEFAULT 0,
    conversion_value     NUMERIC(14,4) NOT NULL DEFAULT 0,

    -- Extra metrics: platform-specific (video_views, engagement, reach...) -> JSONB
    extra_metrics        JSONB NOT NULL DEFAULT '{}',

    currency              CHAR(3) NOT NULL DEFAULT 'USD',
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- UNIQUE constraint này là nền tảng cho idempotency (dùng ON CONFLICT DO UPDATE)
    UNIQUE(ad_id, date)
);
COMMENT ON TABLE fact_ad_metrics IS 'Fact table chính. UPSERT qua UNIQUE(ad_id, date) đảm bảo chạy lại job không tạo dữ liệu trùng.';
