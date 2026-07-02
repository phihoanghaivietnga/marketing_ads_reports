-- ============================================================
-- 002_dim_tables.sql
-- Mục đích: Tạo các bảng Dimension (dim_*) — Star Schema.
-- Thứ tự tạo tuân theo quan hệ FK: platform -> account -> campaign -> ad_set -> ad
-- ============================================================

CREATE TABLE IF NOT EXISTS dim_platform (
    platform_id     SMALLSERIAL PRIMARY KEY,
    platform_code   VARCHAR(20) UNIQUE NOT NULL,   -- 'FACEBOOK', 'TIKTOK', 'GOOGLE'
    platform_name   VARCHAR(50) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE dim_platform IS 'Danh mục nền tảng quảng cáo. Thêm platform mới = insert 1 dòng, KHÔNG cần alter bảng khác.';

CREATE TABLE IF NOT EXISTS dim_account (
    account_id      BIGSERIAL PRIMARY KEY,
    platform_id     SMALLINT NOT NULL REFERENCES dim_platform(platform_id),
    external_id     VARCHAR(100) NOT NULL,          -- ID gốc từ API (ad_account_id)
    account_name    VARCHAR(255),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(platform_id, external_id)
);

CREATE TABLE IF NOT EXISTS dim_campaign (
    campaign_id     BIGSERIAL PRIMARY KEY,
    account_id      BIGINT NOT NULL REFERENCES dim_account(account_id),
    external_id     VARCHAR(100) NOT NULL,
    campaign_name   VARCHAR(255),
    objective       VARCHAR(100),
    status          VARCHAR(20),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(account_id, external_id)
);

CREATE TABLE IF NOT EXISTS dim_ad_set (
    ad_set_id       BIGSERIAL PRIMARY KEY,
    campaign_id     BIGINT NOT NULL REFERENCES dim_campaign(campaign_id),
    external_id     VARCHAR(100) NOT NULL,
    ad_set_name     VARCHAR(255),
    targeting_meta  JSONB DEFAULT '{}',              -- targeting spec khác nhau mỗi platform
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(campaign_id, external_id)
);

CREATE TABLE IF NOT EXISTS dim_ad (
    ad_id           BIGSERIAL PRIMARY KEY,
    ad_set_id       BIGINT NOT NULL REFERENCES dim_ad_set(ad_set_id),
    external_id     VARCHAR(100) NOT NULL,
    ad_name         VARCHAR(255),
    creative_meta   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(ad_set_id, external_id)
);
