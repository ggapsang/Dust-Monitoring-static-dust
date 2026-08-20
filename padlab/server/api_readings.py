"""판독 결과 조회.

진입 화면이 누적 스프레드시트다. 실증 단계에서 가장 자주 보는 것이 쌓인
지표 값이기 때문이다.

**포인트 간 스코어 직접 비교는 하지 않는다.** 촬영 거리·각도·조명이 개소마다
달라 감도가 다르다. 시계열은 개소 하나를 대상으로 하며 여러 개소를 한
좌표축에 겹쳐 그리지 않는다.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .deps import get_root, get_session
from .models import Baseline, Capture, Point, Reading, Run
from .schemas import (
    Bin,
    DistributionOut,
    ReadingDetail,
    ReadingOut,
    SeriesOut,
    SeriesPoint,
)

router = APIRouter(prefix="/api", tags=["결과 조회"])

METRICS: dict[str, Any] = {
    "score_uniform": Reading.score_uniform,
    "score_localized": Reading.score_localized,
    "score_combined": Reading.score_combined,
    "quality_sharpness": Reading.quality_sharpness,
    "quality_saturated_ratio": Reading.quality_saturated_ratio,
    "quality_pad_size_px": Reading.quality_pad_size_px,
    "quality_pad_size_diff_ratio": Reading.quality_pad_size_diff_ratio,
    "elapsed_ms": Reading.elapsed_ms,
}
"""분포·시계열에서 고를 수 있는 지표. 응답에 실제로 실려 오는 것만 둔다."""

CSV_COLUMNS = [
    ("captured_at", "촬영일시"),
    ("target_id", "TARGET_ID"),
    ("point_id", "개소"),
    ("sequence", "회차"),
    ("success", "성공"),
    ("failure_reason", "실패사유"),
    ("score_uniform", "uniform"),
    ("score_localized", "localized"),
    ("score_combined", "total"),
    ("quality_sharpness", "선명도"),
    ("quality_saturated_ratio", "포화비율"),
    ("quality_pad_size_px", "패드크기"),
    ("quality_pad_size_diff_ratio", "크기차이"),
    ("read_point_id", "판독번호"),
    ("elapsed_ms", "처리시간ms"),
    ("run_kind", "실행구분"),
    ("has_override", "오버라이드"),
]


def _filtered(
    session: Session,
    *,
    point_id: str | None,
    target_id: str | None,
    success: bool | None,
    failure_reason: str | None,
    run_kind: str | None,
    run_id: int | None,
    since: datetime | None,
    until: datetime | None,
) -> Select:
    stmt = (
        select(Reading, Capture, Run)
        .join(Capture, Reading.capture_id == Capture.id)
        .join(Run, Reading.run_id == Run.id)
    )
    if point_id:
        stmt = stmt.where(Reading.point_id == point_id)
    if target_id:
        stmt = stmt.where(Capture.target_id == target_id)
    if success is not None:
        stmt = stmt.where(Reading.success.is_(success))
    if failure_reason:
        stmt = stmt.where(Reading.failure_reason == failure_reason)
    if run_kind:
        stmt = stmt.where(Run.kind == run_kind)
    if run_id:
        stmt = stmt.where(Reading.run_id == run_id)
    if since:
        stmt = stmt.where(Capture.captured_at >= since)
    if until:
        stmt = stmt.where(Capture.captured_at <= until)
    return stmt


def _sequences(session: Session) -> dict[int, int]:
    """판독 건마다의 회차. 개소별로 촬영 일시 순서다.

    재판독이 같은 사진을 다시 쌓으므로 사진 단위로 매긴다 - 판독 건마다
    매기면 같은 사진이 회차 둘을 차지한다.
    """
    rows = session.execute(
        select(Reading.id, Reading.point_id, Capture.captured_at, Capture.id)
        .join(Capture, Reading.capture_id == Capture.id)
        .where(Reading.point_id.isnot(None))
        .order_by(Reading.point_id, Capture.captured_at, Capture.id)
    ).all()

    out: dict[int, int] = {}
    counters: dict[str, dict[int, int]] = {}
    for reading_id, pid, _stamp, capture_id in rows:
        seen = counters.setdefault(pid, {})
        if capture_id not in seen:
            seen[capture_id] = len(seen) + 1
        out[reading_id] = seen[capture_id]
    return out


def _to_out(
    reading: Reading, capture: Capture, run: Run, sequence: int | None
) -> ReadingOut:
    images = {
        kind: f"/files/{path}"
        for kind, path in (
            ("baseline_rectified", reading.img_baseline_rectified),
            ("rectified", reading.img_rectified),
            ("distribution", reading.img_distribution),
        )
        if path
    }
    return ReadingOut(
        id=reading.id,
        run_id=reading.run_id,
        capture_id=reading.capture_id,
        baseline_id=reading.baseline_id,
        point_id=reading.point_id,
        target_id=capture.target_id,
        pad_index=reading.pad_index,
        tone=reading.tone,
        captured_at=capture.captured_at,
        sequence=sequence,
        success=reading.success,
        failure_reason=reading.failure_reason,
        failure_detail=reading.failure_detail,
        summary=reading.summary,
        score_uniform=reading.score_uniform,
        score_localized=reading.score_localized,
        score_combined=reading.score_combined,
        quality_sharpness=reading.quality_sharpness,
        quality_saturated_ratio=reading.quality_saturated_ratio,
        quality_pad_size_px=reading.quality_pad_size_px,
        quality_pad_size_diff_ratio=reading.quality_pad_size_diff_ratio,
        read_point_id=reading.read_point_id,
        elapsed_ms=reading.elapsed_ms,
        run_kind=run.kind,
        has_override=bool(run.config_override),
        images=images,
    )


@router.get("/readings", response_model=list[ReadingOut], summary="판독 결과 목록")
def list_readings(
    session: Annotated[Session, Depends(get_session)],
    point_id: str | None = None,
    target_id: str | None = None,
    success: bool | None = None,
    failure_reason: str | None = None,
    run_kind: str | None = None,
    run_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    order: str = Query(default="captured_at", description="정렬 기준 컬럼"),
    desc: bool = True,
    limit: int = Query(default=500, le=5000),
    offset: int = 0,
) -> list[ReadingOut]:
    stmt = _filtered(
        session,
        point_id=point_id,
        target_id=target_id,
        success=success,
        failure_reason=failure_reason,
        run_kind=run_kind,
        run_id=run_id,
        since=since,
        until=until,
    )
    column = METRICS.get(order) or (
        Capture.captured_at if order == "captured_at" else Reading.id
    )
    stmt = stmt.order_by(column.desc() if desc else column.asc()).limit(limit).offset(offset)

    sequences = _sequences(session)
    return [
        _to_out(reading, capture, run, sequences.get(reading.id))
        for reading, capture, run in session.execute(stmt).all()
    ]


@router.get(
    "/readings/export.csv", response_class=Response, summary="현재 조건의 CSV"
)
def export_csv(
    session: Annotated[Session, Depends(get_session)],
    point_id: str | None = None,
    target_id: str | None = None,
    success: bool | None = None,
    failure_reason: str | None = None,
    run_kind: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Response:
    rows = list_readings(
        session,
        point_id=point_id,
        target_id=target_id,
        success=success,
        failure_reason=failure_reason,
        run_kind=run_kind,
        run_id=None,
        since=since,
        until=until,
        order="captured_at",
        desc=False,
        limit=5000,
        offset=0,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in CSV_COLUMNS])
    for row in rows:
        writer.writerow([getattr(row, field, None) for field, _ in CSV_COLUMNS])

    # BOM 을 붙인다. 안 붙이면 Excel 이 한글 머리글을 깨뜨린다.
    body = "﻿" + buffer.getvalue()
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="readings.csv"'},
    )


@router.get("/readings/{reading_id}", response_model=ReadingDetail, summary="판독 결과 단건")
def get_reading(
    reading_id: int, session: Annotated[Session, Depends(get_session)]
) -> ReadingDetail:
    row = session.get(Reading, reading_id)
    if row is None:
        raise HTTPException(404, f"없는 판독 건이다: {reading_id}")
    capture = session.get(Capture, row.capture_id)
    run = session.get(Run, row.run_id)
    baseline = session.get(Baseline, row.baseline_id) if row.baseline_id else None

    base = _to_out(row, capture, run, _sequences(session).get(row.id))
    return ReadingDetail(
        **base.model_dump(),
        capture_image=f"/files/{capture.file_path}" if capture else None,
        baseline_image=f"/files/{baseline.file_path}" if baseline else None,
        config_override=run.config_override or {},
        response=row.response,
    )


@router.get("/series/{point_id}", response_model=SeriesOut, summary="개소별 회차 시계열")
def series(
    point_id: str,
    session: Annotated[Session, Depends(get_session)],
    metric: str = "score_combined",
    mad_n: float | None = Query(
        default=None, description="추세 이상 경계 배수. 비우면 경계를 내지 않는다"
    ),
    slack: float = Query(default=0.0, description="CUSUM 여유값"),
    run_kind: str = "initial",
) -> SeriesOut:
    """절대량·추세·누적 세 축.

    경계는 개소 자기 이력에서 낸다. 개소마다 감도가 달라 공통 임계를 쓸 수
    없기 때문이다. 값이 비어 있는 동안에는 경계를 내지 않고 계열만 준다.
    """
    if metric not in METRICS:
        raise HTTPException(400, f"알 수 없는 지표다: {metric} (가능: {', '.join(METRICS)})")

    stmt = (
        select(Reading, Capture)
        .join(Capture, Reading.capture_id == Capture.id)
        .join(Run, Reading.run_id == Run.id)
        .where(Reading.point_id == point_id)
        .where(Reading.success.is_(True))
        .where(Run.kind == run_kind)
        .order_by(Capture.captured_at, Capture.id)
    )
    rows = session.execute(stmt).all()

    points: list[SeriesPoint] = []
    deltas: list[float] = []
    previous: float | None = None
    cusum = 0.0
    for index, (reading, capture) in enumerate(rows, start=1):
        value = getattr(reading, metric)
        delta = None if value is None or previous is None else value - previous
        if delta is not None:
            deltas.append(delta)
            cusum = max(0.0, cusum + delta - slack)
        points.append(
            SeriesPoint(
                reading_id=reading.id,
                sequence=index,
                captured_at=capture.captured_at,
                absolute=value,
                delta=delta,
                cusum=cusum if delta is not None else None,
            )
        )
        if value is not None:
            previous = value

    median = _median(deltas)
    mad = _median([abs(d - median) for d in deltas]) if median is not None else None
    limit = None
    if mad_n is not None and median is not None and mad is not None:
        limit = median + mad_n * mad
    return SeriesOut(
        point_id=point_id,
        metric=metric,
        points=points,
        delta_median=median,
        delta_mad=mad,
        limit=limit,
    )


@router.get("/distribution", response_model=DistributionOut, summary="지표 분포")
def distribution(
    session: Annotated[Session, Depends(get_session)],
    metric: str = "score_combined",
    bins: int = Query(default=20, ge=4, le=100),
    point_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> DistributionOut:
    """임계값을 정하기 위한 화면.

    산출값은 게이트 통과 여부와 무관하게 항상 나오므로 성공 건과 실패 건을
    같은 축에 겹쳐 센다. 어느 값에서 실패가 갈리는지를 보기 위해서다.
    """
    if metric not in METRICS:
        raise HTTPException(400, f"알 수 없는 지표다: {metric} (가능: {', '.join(METRICS)})")
    column = METRICS[metric]

    stmt = (
        select(column, Reading.success)
        .join(Capture, Reading.capture_id == Capture.id)
        .where(column.isnot(None))
    )
    if point_id:
        stmt = stmt.where(Reading.point_id == point_id)
    if since:
        stmt = stmt.where(Capture.captured_at >= since)
    if until:
        stmt = stmt.where(Capture.captured_at <= until)
    rows = session.execute(stmt).all()

    reasons = dict(
        session.execute(
            select(Reading.failure_reason, func.count())
            .where(Reading.failure_reason.isnot(None))
            .group_by(Reading.failure_reason)
        ).all()
    )

    values = [float(value) for value, _ in rows]
    if not values:
        return DistributionOut(metric=metric, failure_counts=reasons)

    low, high = min(values), max(values)
    width = (high - low) / bins if high > low else 1.0
    buckets = [
        Bin(start=low + index * width, end=low + (index + 1) * width)
        for index in range(bins)
    ]
    for value, ok in rows:
        index = min(bins - 1, int((float(value) - low) / width)) if high > low else 0
        if ok:
            buckets[index].success += 1
        else:
            buckets[index].failure += 1

    return DistributionOut(
        metric=metric,
        count=len(values),
        minimum=low,
        median=_median(values),
        maximum=high,
        bins=buckets,
        failure_counts=reasons,
    )


def _serve(stored: str, root: Path) -> FileResponse:
    path = (root / stored).resolve()
    # 저장 루트 밖으로 나가지 못하게 막는다. 경로가 요청으로 들어오는 곳이다.
    if not str(path).startswith(str(root.resolve())):
        raise HTTPException(400, "저장소 밖 경로다")
    if not path.is_file():
        raise HTTPException(404, f"없는 파일이다: {stored}")
    return FileResponse(path)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0
