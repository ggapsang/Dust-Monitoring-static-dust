-- 판독 실증 관리 스키마.
--
-- 판독 응답 원본을 jsonb 로 통째로 보관하고, 조회에 쓰는 항목만 컬럼으로
-- 승격한다. 응답 스키마가 바뀌어도 과거 판독 결과를 잃지 않기 위해서다.

CREATE TABLE IF NOT EXISTS target (
    target_id     TEXT PRIMARY KEY,
    name          TEXT,
    location_desc TEXT,
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS point (
    point_id      TEXT PRIMARY KEY,
    target_id     TEXT NOT NULL REFERENCES target(target_id) ON DELETE RESTRICT,
    name          TEXT,
    location_desc TEXT,
    -- 개소마다 분진 색이 고정이라 등록 정보로 둔다. 판독 실행 때 사람이
    -- 매번 지정하지 않는다.
    tone          TEXT NOT NULL DEFAULT 'white' CHECK (tone IN ('white', 'black')),
    note          TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS point_target_idx ON point(target_id);

CREATE TABLE IF NOT EXISTS baseline (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    point_id       TEXT NOT NULL REFERENCES point(point_id) ON DELETE CASCADE,
    file_path      TEXT NOT NULL,
    original_name  TEXT,
    -- 부착 일시. 이 시각 이후 촬영분에 적용된다. 대체 판정도 이 순서를
    -- 따른다 - 파일명의 회차 표기는 참고값일 뿐이다.
    effective_from TIMESTAMPTZ NOT NULL,
    superseded_at  TIMESTAMPTZ,
    revision_hint  INTEGER,
    registered_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS baseline_point_idx ON baseline(point_id, effective_from DESC);

CREATE TABLE IF NOT EXISTS capture (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    target_id     TEXT NOT NULL REFERENCES target(target_id) ON DELETE RESTRICT,
    file_path     TEXT NOT NULL,
    original_name TEXT,
    content_sha256 TEXT,
    captured_at   TIMESTAMPTZ NOT NULL,
    uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    note          TEXT
);
CREATE INDEX IF NOT EXISTS capture_target_idx ON capture(target_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS capture_hash_idx ON capture(content_sha256);

CREATE TABLE IF NOT EXISTS run (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    executed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    config_override JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_run_id   BIGINT REFERENCES run(id),
    kind            TEXT NOT NULL DEFAULT 'initial' CHECK (kind IN ('initial', 'rerun')),
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'done', 'failed')),
    -- 사진 단위 진행 상황. 한 장이 실패해도 나머지를 계속 처리한다.
    total_captures  INTEGER NOT NULL DEFAULT 0,
    done_captures   INTEGER NOT NULL DEFAULT 0,
    -- 판독 요청에서 빠진 개소 등 실행 중 알림. 결과를 못 낸 이유가 남는다.
    notes           JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS reading (
    id                          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                      BIGINT NOT NULL REFERENCES run(id) ON DELETE CASCADE,
    capture_id                  BIGINT NOT NULL REFERENCES capture(id) ON DELETE CASCADE,
    baseline_id                 BIGINT REFERENCES baseline(id),
    point_id                    TEXT REFERENCES point(point_id),
    pad_index                   INTEGER NOT NULL DEFAULT 0,
    tone                        TEXT NOT NULL DEFAULT 'white',

    success                     BOOLEAN NOT NULL,
    failure_reason              TEXT,
    failure_detail              TEXT,
    summary                     TEXT,

    score_uniform               DOUBLE PRECISION,
    score_localized             DOUBLE PRECISION,
    score_combined              DOUBLE PRECISION,
    quality_sharpness           DOUBLE PRECISION,
    quality_saturated_ratio     DOUBLE PRECISION,
    quality_pad_size_px         DOUBLE PRECISION,
    quality_pad_size_diff_ratio DOUBLE PRECISION,
    -- 판독기가 읽어 낸 번호. point_id 와 따로 둔다 - 짝짓기 결과와 판독값을
    -- 분리해야 번호 오독이 있었는지를 나중에 셀 수 있다.
    read_point_id               TEXT,
    elapsed_ms                  DOUBLE PRECISION,

    response                    JSONB,
    img_baseline_rectified      TEXT,
    img_rectified               TEXT,
    img_distribution            TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reading_run_idx ON reading(run_id);
CREATE INDEX IF NOT EXISTS reading_capture_idx ON reading(capture_id);
CREATE INDEX IF NOT EXISTS reading_point_idx ON reading(point_id);
