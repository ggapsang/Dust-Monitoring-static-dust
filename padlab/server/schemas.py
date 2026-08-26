"""요청·응답 모델.

판독 응답을 그대로 옮기지 않는다. 여기 있는 것은 실증 관리에 필요한 형태이며,
판독 응답 원본은 ``reading.response`` 에 통째로 남아 있다.

실패 사유의 한글 표기를 이쪽에서 만들지 않는다. 판독 응답의 ``summary`` 에
이미 들어 있고, 같은 문구를 두 곳에 두면 조용히 어긋난다. 화면 표시는
``summary``, 필터·집계는 원문 ``failure_reason`` 을 쓴다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""촬영 단위·개소 번호. 비어 있으면 안 된다.

개소와 촬영 단위는 번호가 곧 기본키이고, 낱건 API 는 전부 URL 경로로
가리킨다(``/points/{point_id}``). 번호가 빈 문자열이면 그 경로가
``/points/`` 로 접혀 어느 낱건 라우트에도 걸리지 않아 405 가 난다 - 화면에는
행이 보이는데 수정도 삭제도 되지 않는 상태로 갇힌다. 실제로 그렇게 갇힌 행이
한 건 생겼다. 들어오는 자리에서 막는다.

공백만 있는 번호도 함께 막는다. 경로로는 가리킬 수 있지만 화면에서 빈칸과
구분되지 않아 같은 혼란을 만든다.
"""

Tone = Literal["white", "black", "chroma"]
"""무채색 패드는 분진 색과 반대인 바탕을 고른다(어두운 분진->white, 밝은
분진->black). chroma 는 유채색(마젠타) 패드 - 판독기가 사진에서 자동
판별하므로 이 값은 등록·표시용일 뿐이고, 실제 판독 호출은 white 와 같은
판정 극성으로 나간다(``runs.py`` 의 ``_reader_tone``)."""


class TargetIn(BaseModel):
    target_id: Identifier = Field(description="AMR 촬영 단위. 에코프로비엠 체계의 값")
    name: str | None = None
    location_desc: str | None = Field(default=None, description="촬영 위치 설명")
    note: str | None = None


class TargetPatch(BaseModel):
    target_id: Identifier | None = Field(
        default=None,
        description="촬영 단위 번호 자체를 바꿀 때만 넣는다. 속한 개소와 사진이 따라온다",
    )
    name: str | None = None
    location_desc: str | None = None
    note: str | None = None


class TargetOut(TargetIn):
    target_id: str
    """내보낼 때는 제약을 풀어 둔다. 제약이 걸리기 전에 들어간 행이 DB 에
    남아 있으면, 그 한 건 때문에 목록 전체가 500 이 되어 지울 수단까지
    사라진다. 막는 자리는 들어오는 쪽이다."""

    created_at: datetime
    point_count: int = 0


class PointIn(BaseModel):
    point_id: Identifier = Field(description="패드에 인쇄된 관측 개소 번호")
    target_id: Identifier = Field(description="이 개소가 찍히는 촬영 단위")
    name: str | None = None
    location_desc: str | None = Field(default=None, description="물리적 위치 설명")
    tone: Tone = Field(
        default="white",
        description=(
            "패드 톤. 개소마다 분진 색이 고정이라 등록 정보로 둔다. "
            "어두운 분진이면 white, 밝은 분진이면 black 이다."
        ),
    )
    note: str | None = None


class PointPatch(BaseModel):
    point_id: Identifier | None = Field(
        default=None,
        description=(
            "개소 번호 자체를 바꿀 때만 넣는다. 기준 사진과 판독 이력이 따라온다. "
            "판독기가 읽어 낸 번호(read_point_id)는 그때 값 그대로 남는다."
        ),
    )
    target_id: Identifier | None = None
    name: str | None = None
    location_desc: str | None = None
    tone: Tone | None = None
    note: str | None = None


class PointOut(PointIn):
    point_id: str
    target_id: str
    """``TargetOut`` 과 같은 이유로 내보낼 때는 제약을 풀어 둔다."""

    created_at: datetime
    has_baseline: bool = False


class BaselineOut(BaseModel):
    id: int
    point_id: str
    file_path: str
    original_name: str | None = None
    effective_from: datetime
    superseded_at: datetime | None = None
    revision_hint: int | None = Field(
        default=None,
        description=(
            "파일명이 말하는 회차. 참고값이며 현행 기준 판정에 쓰지 않는다. "
            "순서는 effective_from 이 정한다."
        ),
    )
    registered_at: datetime
    is_current: bool = False


class BaselinePatch(BaseModel):
    effective_from: datetime | None = Field(
        default=None,
        description=(
            "부착 일시. 이력 순서와 어느 촬영분에 적용되는지를 이 값이 정한다. "
            "고치면 그 개소의 대체 관계를 다시 맞춘다."
        ),
    )


class CaptureOut(BaseModel):
    id: int
    target_id: str
    file_path: str
    original_name: str | None = None
    captured_at: datetime
    uploaded_at: datetime
    note: str | None = None


class ParsedUpload(BaseModel):
    """업로드 전 파일명 파싱 결과. 화면이 값을 미리 채우는 데 쓴다."""

    filename: str
    parsed: bool
    target_id: str | None = None
    point_id: str | None = None
    stamp: datetime | None = None
    revision_hint: int | None = None
    known_id: bool = Field(
        default=False, description="파싱된 식별자가 등록 목록에 있는지"
    )
    message: str | None = None


class RunOut(BaseModel):
    id: int
    executed_at: datetime
    finished_at: datetime | None = None
    kind: str
    status: str
    config_override: dict[str, Any] = {}
    source_run_id: int | None = None
    total_captures: int = 0
    done_captures: int = 0
    notes: list[dict[str, Any]] = []
    reading_count: int = 0
    ignore_baseline_window: bool = Field(
        default=False, description="기준 사진의 등록 시점을 대조하지 않고 돌렸는지"
    )


class ReadingOut(BaseModel):
    id: int
    run_id: int
    capture_id: int
    baseline_id: int | None = None
    point_id: str | None = None
    target_id: str | None = None
    pad_index: int = 0
    tone: str = "white"

    captured_at: datetime | None = None
    sequence: int | None = Field(
        default=None, description="그 개소에서 촬영 일시 순으로 매긴 회차"
    )

    success: bool
    failure_reason: str | None = None
    failure_detail: str | None = None
    summary: str | None = None

    score_uniform: float | None = None
    score_localized: float | None = None
    score_combined: float | None = None
    quality_sharpness: float | None = None
    quality_saturated_ratio: float | None = None
    quality_pad_size_px: float | None = None
    quality_pad_size_diff_ratio: float | None = None
    read_point_id: str | None = None
    elapsed_ms: float | None = None

    # 시험 지표. 판정에는 쓰지 않는다 - 표시 전용.
    od_sum: float | None = None
    od_mean: float | None = None
    od_score: float | None = None
    roi_mean_reading: float | None = None
    roi_mean_baseline: float | None = None
    pad_scale: float | None = None

    pad_type: str | None = None
    chroma_score: float | None = None
    luma_dark_score: float | None = None
    luma_light_score: float | None = None

    requested_at: datetime | None = Field(
        default=None, description="판독을 요청한(실행을 시작한) 일시"
    )
    run_kind: str | None = None
    has_override: bool = False

    images: dict[str, str] = Field(
        default={}, description="저장된 결과 이미지 주소. 없으면 비어 있다"
    )
    capture_image: str | None = Field(
        default=None, description="판독 사진 원본 주소"
    )
    baseline_image: str | None = Field(
        default=None, description="짝지어진 기준 사진 원본 주소"
    )


class ReadingDetail(ReadingOut):
    """단건 조회. 판독 응답 원본까지 함께 준다."""

    config_override: dict[str, Any] = {}
    response: dict[str, Any] | None = None


class SeriesPoint(BaseModel):
    reading_id: int
    sequence: int
    captured_at: datetime
    baseline_id: int | None = None
    baseline_changed: bool = Field(
        default=False,
        description=(
            "이 회차에서 기준 사진이 바뀌었는지. 바뀐 회차는 앞 회차와 견줄 수 "
            "없다 - 값이 '그 기준 대비 쌓인 양' 이라 기준이 달라지면 척도가 "
            "달라진다. 패드를 갈아 붙이면 침착도 0 에서 다시 시작한다."
        ),
    )
    absolute: float | None = Field(default=None, description="그 회차의 기준 대비 총량")
    delta: float | None = Field(
        default=None,
        description="직전 회차 대비 증분. 기준이 바뀐 회차는 비운다",
    )
    cusum: float | None = Field(
        default=None,
        description="증분에서 여유를 뺀 값의 합. 기준이 바뀌면 0 에서 다시 센다",
    )


class SeriesOut(BaseModel):
    point_id: str
    metric: str
    points: list[SeriesPoint] = []
    delta_median: float | None = None
    delta_mad: float | None = None
    limit: float | None = Field(
        default=None,
        description=(
            "추세 이상 경계. 개소 자기 이력에서 낸다(증분 중앙값 + n x MAD). "
            "n 이 비어 있으면 경계를 내지 않는다."
        ),
    )


class Bin(BaseModel):
    start: float
    end: float
    success: int = 0
    failure: int = 0


class DistributionOut(BaseModel):
    metric: str
    count: int = 0
    minimum: float | None = None
    median: float | None = None
    maximum: float | None = None
    bins: list[Bin] = []
    failure_counts: dict[str, int] = Field(
        default={}, description="실패 사유별 건수. 원문 사유 그대로다"
    )
