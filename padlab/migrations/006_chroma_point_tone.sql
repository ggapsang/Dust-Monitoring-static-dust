-- 개소 등록에서 유채색(마젠타) 패드를 고를 수 있게 한다. 판독기가 사진에서
-- 패드 종류를 자동 판별하므로 이 값은 등록/표시용이고, 실제 판독 호출은
-- white 와 같은 판정 극성으로 나간다(runs.py 의 _reader_tone).
ALTER TABLE point DROP CONSTRAINT IF EXISTS point_tone_check;
ALTER TABLE point ADD CONSTRAINT point_tone_check CHECK (tone IN ('white', 'black', 'chroma'));
