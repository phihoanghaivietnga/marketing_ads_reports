-- ============================================================
-- 005_indexes_and_constraints.sql
-- Mục đích: Index phục vụ các pattern query phổ biến của dashboard
-- (lọc theo date range, filter theo campaign/platform, aggregate).
-- ============================================================

-- Query phổ biến nhất: WHERE date BETWEEN ... GROUP BY date
CREATE INDEX IF NOT EXISTS idx_fact_date
    ON fact_ad_metrics (date);

-- Query theo ad cụ thể trong khoảng ngày (dùng trong UPSERT lookup + drill-down)
CREATE INDEX IF NOT EXISTS idx_fact_ad_date
    ON fact_ad_metrics (ad_id, date);

-- Hỗ trợ join ngược từ fact lên dimension khi filter theo campaign
CREATE INDEX IF NOT EXISTS idx_dim_ad_ad_set
    ON dim_ad (ad_set_id);

CREATE INDEX IF NOT EXISTS idx_dim_ad_set_campaign
    ON dim_ad_set (campaign_id);

CREATE INDEX IF NOT EXISTS idx_dim_campaign_account
    ON dim_campaign (account_id);

CREATE INDEX IF NOT EXISTS idx_dim_account_platform
    ON dim_account (platform_id);

-- Filter theo tên campaign (nếu dashboard có search box)
CREATE INDEX IF NOT EXISTS idx_dim_campaign_name_trgm
    ON dim_campaign USING gin (campaign_name gin_trgm_ops);

-- GIN index cho extra_metrics nếu sau này cần query trực tiếp vào JSONB
CREATE INDEX IF NOT EXISTS idx_fact_extra_metrics
    ON fact_ad_metrics USING gin (extra_metrics);

-- ------------------------------------------------------------
-- GHI CHÚ SCALE: khi fact_ad_metrics vượt vài chục triệu dòng,
-- cân nhắc range partition theo tháng trên cột "date":
--
-- CREATE TABLE fact_ad_metrics (...) PARTITION BY RANGE (date);
-- CREATE TABLE fact_ad_metrics_2026_07 PARTITION OF fact_ad_metrics
--     FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
--
-- Không áp dụng ngay ở đợt 1 để giữ đơn giản, nhưng thiết kế
-- UNIQUE(ad_id, date) hiện tại tương thích với partition sau này.
-- ------------------------------------------------------------
