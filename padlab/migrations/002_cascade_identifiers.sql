-- 식별자를 나중에 고칠 수 있게 한다.
--
-- 패드를 갈아 붙여도 POINT_ID 는 그대로 두는 것이 원칙이지만, 번호가 바뀌는
-- 일이 생기면 등록 화면에서 사람이 고친다. 그러려면 자식 행이 따라와야
-- 한다 - 안 그러면 외래키에 걸려 고칠 수가 없고, 지웠다 다시 넣으면 그
-- 개소의 판독 이력이 통째로 끊긴다.
--
-- 이름을 명시해 다시 걸므로 기동할 때마다 다시 흘려도 결과가 같다.

ALTER TABLE point DROP CONSTRAINT IF EXISTS point_target_id_fkey;
ALTER TABLE point ADD CONSTRAINT point_target_id_fkey
    FOREIGN KEY (target_id) REFERENCES target(target_id)
    ON UPDATE CASCADE ON DELETE RESTRICT;

ALTER TABLE capture DROP CONSTRAINT IF EXISTS capture_target_id_fkey;
ALTER TABLE capture ADD CONSTRAINT capture_target_id_fkey
    FOREIGN KEY (target_id) REFERENCES target(target_id)
    ON UPDATE CASCADE ON DELETE RESTRICT;

ALTER TABLE baseline DROP CONSTRAINT IF EXISTS baseline_point_id_fkey;
ALTER TABLE baseline ADD CONSTRAINT baseline_point_id_fkey
    FOREIGN KEY (point_id) REFERENCES point(point_id)
    ON UPDATE CASCADE ON DELETE CASCADE;

ALTER TABLE reading DROP CONSTRAINT IF EXISTS reading_point_id_fkey;
ALTER TABLE reading ADD CONSTRAINT reading_point_id_fkey
    FOREIGN KEY (point_id) REFERENCES point(point_id)
    ON UPDATE CASCADE ON DELETE SET NULL;

-- reading.read_point_id 는 외래키가 아니다. 판독기가 사진에서 읽어 낸 값
-- 그대로이며 등록된 개소를 가리키는 참조가 아니다. 번호를 고쳐도 이 값은
-- 그때 무엇을 읽었는지 남아 있어야 오독을 나중에 셀 수 있다.
