-- 시험 지표: 광학밀도 기반 오염도. 판정에는 쓰지 않는다. 표시 전용.
-- uniform/localized/combined 는 그대로 두고 나란히 참고용으로만 낸다.
ALTER TABLE reading ADD COLUMN IF NOT EXISTS od_sum DOUBLE PRECISION;
ALTER TABLE reading ADD COLUMN IF NOT EXISTS od_mean DOUBLE PRECISION;
ALTER TABLE reading ADD COLUMN IF NOT EXISTS od_score DOUBLE PRECISION;
ALTER TABLE reading ADD COLUMN IF NOT EXISTS roi_mean_reading DOUBLE PRECISION;
ALTER TABLE reading ADD COLUMN IF NOT EXISTS roi_mean_baseline DOUBLE PRECISION;
ALTER TABLE reading ADD COLUMN IF NOT EXISTS pad_scale DOUBLE PRECISION;
