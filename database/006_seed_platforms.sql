-- ============================================================
-- 006_seed_platforms.sql
-- Mục đích: Seed sẵn danh mục platform để backend/ETL dùng ngay.
-- An toàn chạy lại nhiều lần (ON CONFLICT DO NOTHING).
-- ============================================================

INSERT INTO dim_platform (platform_code, platform_name) VALUES
    ('FACEBOOK', 'Facebook Ads'),
    ('TIKTOK',   'TikTok Ads'),
    ('GOOGLE',   'Google Ads')
ON CONFLICT (platform_code) DO NOTHING;

-- Kiểm tra nhanh sau khi chạy:
-- SELECT * FROM dim_platform ORDER BY platform_id;
