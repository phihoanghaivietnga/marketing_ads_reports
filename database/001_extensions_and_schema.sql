-- ============================================================
-- 001_extensions_and_schema.sql
-- Mục đích: Bật extension cần thiết trước khi tạo bảng.
-- Chạy với quyền superuser hoặc user có quyền CREATE EXTENSION.
-- ============================================================

-- Dùng cho gen_random_uuid() nếu sau này cần UUID thay vì BIGSERIAL
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Dùng cho các hàm tìm kiếm text nếu cần (không bắt buộc, để sẵn)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Không tạo schema riêng ở đợt 1 để đơn giản hoá — mọi bảng nằm ở schema "public".
-- Nếu về sau cần multi-tenant tách schema, cân nhắc: CREATE SCHEMA marketing_analytics;
