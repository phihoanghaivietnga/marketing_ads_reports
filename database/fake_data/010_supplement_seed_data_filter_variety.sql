-- ============================================================
-- 010_supplement_seed_data_filter_variety.sql
-- Muc dich: KHONG doi cau truc, chi bo sung do da dang gia tri
-- cho cac filter hien dang qua it distinct value de test
-- (Team, Sale Team, Month by campaign).
-- An toan chay lai nhieu lan (UPDATE idempotent theo external_id).
-- Chay SAU 09_seed_fake_data.sql.
-- ============================================================

BEGIN;

-- Da dang hoa Team / Sale Team / Month by campaign cho 1 vai ad_set
-- (khong dung lai tat ca campaign, chi can du de test filter co nhieu lua chon)

UPDATE dim_ad_set
SET targeting_meta = targeting_meta || '{"team": 3, "sale_team": "Sale B", "month_by_campaign": "2026-06"}'::jsonb
WHERE external_id = '2300000000005';

UPDATE dim_ad_set
SET targeting_meta = targeting_meta || '{"team": 4, "sale_team": "Sale B", "month_by_campaign": "2026-06"}'::jsonb
WHERE external_id = '2300000000006';

UPDATE dim_ad_set
SET targeting_meta = targeting_meta || '{"team": 0, "sale_team": "Sale B", "month_by_campaign": "2026-05"}'::jsonb
WHERE external_id = '2300000000003';

UPDATE dim_ad_set
SET targeting_meta = targeting_meta || '{"team": 100, "sale_team": "Sale C", "month_by_campaign": "2026-06"}'::jsonb
WHERE external_id = '2300000000004';

COMMIT;

-- Kiem tra nhanh sau khi chay:
-- SELECT ad_set_id, external_id, targeting_meta->>'team' AS team,
--        targeting_meta->>'sale_team' AS sale_team,
--        targeting_meta->>'month_by_campaign' AS month
-- FROM dim_ad_set ORDER BY ad_set_id;
--
-- Ket qua ky vong: co it nhat 6 gia tri team khac nhau (0,1,2,3,4,100),
-- 3 gia tri sale_team (A,B,C), 3 gia tri month (2026-05,06,07)
-- -> du de click thu nhieu nut Team/filter khac nhau va thay du lieu doi that.
--
-- LUU Y: Team Selector Grid o frontend (16 nut 0-14,100) NEN la hang so
-- cau hinh o frontend (TEAM_IDS constant), KHONG query DISTINCT tu DB --
-- vi nhieu team se khong co campaign nao nhung nut van phai hien thi.
