-- 유채색(마젠타) 패드 판독. 시험 경로 - 기존 흑백 경로는 그대로 둔다.
ALTER TABLE reading ADD COLUMN IF NOT EXISTS pad_type TEXT;
ALTER TABLE reading ADD COLUMN IF NOT EXISTS chroma_score DOUBLE PRECISION;
ALTER TABLE reading ADD COLUMN IF NOT EXISTS luma_dark_score DOUBLE PRECISION;
ALTER TABLE reading ADD COLUMN IF NOT EXISTS luma_light_score DOUBLE PRECISION;
