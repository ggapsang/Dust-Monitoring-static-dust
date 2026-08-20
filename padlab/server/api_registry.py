"""촬영 단위·개소·기준 사진 등록.

판독을 부르려면 먼저 두 식별자의 대응이 있어야 한다. 촬영 단위 하나에 개소가
여럿 속하고(1:N), 사진 한 장에 패드가 여럿 찍히는 경우가 여기에 해당한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import naming, storage
from .deps import get_root, get_session
from .models import Baseline, Point, Target
from .schemas import (
    BaselineOut,
    ParsedUpload,
    PointIn,
    PointOut,
    PointPatch,
    TargetIn,
    TargetOut,
    TargetPatch,
)

router = APIRouter(prefix="/api", tags=["등록"])


# ---------------------------------------------------------------------------
# 촬영 단위
# ---------------------------------------------------------------------------


@router.get("/targets", response_model=list[TargetOut], summary="촬영 단위 목록")
def list_targets(session: Annotated[Session, Depends(get_session)]) -> list[TargetOut]:
    counts = dict(
        session.execute(
            select(Point.target_id, func.count()).group_by(Point.target_id)
        ).all()
    )
    rows = session.execute(select(Target).order_by(Target.target_id)).scalars()
    return [
        TargetOut(
            target_id=row.target_id,
            name=row.name,
            location_desc=row.location_desc,
            note=row.note,
            created_at=row.created_at,
            point_count=counts.get(row.target_id, 0),
        )
        for row in rows
    ]


@router.post("/targets", response_model=TargetOut, summary="촬영 단위 등록")
def create_target(
    body: TargetIn, session: Annotated[Session, Depends(get_session)]
) -> TargetOut:
    if session.get(Target, body.target_id) is not None:
        raise HTTPException(409, f"이미 등록된 촬영 단위다: {body.target_id}")
    row = Target(
        target_id=body.target_id,
        name=body.name,
        location_desc=body.location_desc,
        note=body.note,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    return TargetOut(**body.model_dump(), created_at=row.created_at, point_count=0)


@router.patch("/targets/{target_id}", response_model=TargetOut, summary="촬영 단위 수정")
def patch_target(
    target_id: str,
    body: TargetPatch,
    session: Annotated[Session, Depends(get_session)],
) -> TargetOut:
    row = session.get(Target, target_id)
    if row is None:
        raise HTTPException(404, f"등록되지 않은 촬영 단위다: {target_id}")

    changes = body.model_dump(exclude_unset=True)
    renamed = changes.pop("target_id", None)
    if renamed and renamed != target_id:
        if session.get(Target, renamed) is not None:
            raise HTTPException(409, f"이미 쓰고 있는 촬영 단위 번호다: {renamed}")
        # 자식 행은 외래키의 ON UPDATE CASCADE 가 따라온다. 지웠다 다시
        # 넣으면 그 촬영 단위의 사진과 개소가 통째로 끊긴다.
        session.execute(
            update(Target).where(Target.target_id == target_id).values(target_id=renamed)
        )
        session.commit()
        target_id = renamed
        row = session.get(Target, target_id)

    for field, value in changes.items():
        setattr(row, field, value)
    session.commit()
    count = session.execute(
        select(func.count()).select_from(Point).where(Point.target_id == target_id)
    ).scalar_one()
    return TargetOut(
        target_id=row.target_id,
        name=row.name,
        location_desc=row.location_desc,
        note=row.note,
        created_at=row.created_at,
        point_count=count,
    )


@router.delete("/targets/{target_id}", summary="촬영 단위 삭제")
def delete_target(
    target_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict[str, str]:
    row = session.get(Target, target_id)
    if row is None:
        raise HTTPException(404, f"등록되지 않은 촬영 단위다: {target_id}")
    attached = session.execute(
        select(func.count()).select_from(Point).where(Point.target_id == target_id)
    ).scalar_one()
    if attached:
        raise HTTPException(
            409,
            f"이 촬영 단위에 개소 {attached}개가 속해 있다. 개소를 먼저 옮기거나 지운다.",
        )
    session.delete(row)
    session.commit()
    return {"deleted": target_id}


# ---------------------------------------------------------------------------
# 개소
# ---------------------------------------------------------------------------


@router.get("/points", response_model=list[PointOut], summary="개소 목록")
def list_points(
    session: Annotated[Session, Depends(get_session)],
    target_id: str | None = None,
) -> list[PointOut]:
    stmt = select(Point).order_by(Point.point_id)
    if target_id:
        stmt = stmt.where(Point.target_id == target_id)
    rows = list(session.execute(stmt).scalars())

    with_baseline = set(
        session.execute(
            select(Baseline.point_id).where(Baseline.superseded_at.is_(None)).distinct()
        )
        .scalars()
        .all()
    )
    return [
        PointOut(
            point_id=row.point_id,
            target_id=row.target_id,
            name=row.name,
            location_desc=row.location_desc,
            tone=row.tone,
            note=row.note,
            created_at=row.created_at,
            has_baseline=row.point_id in with_baseline,
        )
        for row in rows
    ]


@router.post("/points", response_model=PointOut, summary="개소 등록")
def create_point(
    body: PointIn, session: Annotated[Session, Depends(get_session)]
) -> PointOut:
    if session.get(Point, body.point_id) is not None:
        raise HTTPException(409, f"이미 등록된 개소다: {body.point_id}")
    if session.get(Target, body.target_id) is None:
        raise HTTPException(400, f"등록되지 않은 촬영 단위다: {body.target_id}")
    row = Point(**body.model_dump(), created_at=datetime.now(timezone.utc))
    session.add(row)
    session.commit()
    return PointOut(**body.model_dump(), created_at=row.created_at, has_baseline=False)


@router.patch("/points/{point_id}", response_model=PointOut, summary="개소 수정")
def patch_point(
    point_id: str,
    body: PointPatch,
    session: Annotated[Session, Depends(get_session)],
) -> PointOut:
    row = session.get(Point, point_id)
    if row is None:
        raise HTTPException(404, f"등록되지 않은 개소다: {point_id}")

    changes = body.model_dump(exclude_unset=True)
    if changes.get("target_id") and session.get(Target, changes["target_id"]) is None:
        raise HTTPException(400, f"등록되지 않은 촬영 단위다: {changes['target_id']}")

    renamed = changes.pop("point_id", None)
    if renamed and renamed != point_id:
        if session.get(Point, renamed) is not None:
            raise HTTPException(409, f"이미 쓰고 있는 개소 번호다: {renamed}")
        # 기준 사진과 판독 이력은 외래키의 ON UPDATE CASCADE 가 따라온다.
        # 지웠다 다시 넣으면 그 개소의 판독 이력이 통째로 끊긴다.
        #
        # 저장된 기준 사진의 폴더 이름은 옛 번호 그대로 남는다. 경로는 DB 에
        # 있는 것을 그대로 쓰므로 파일은 계속 열린다 - 폴더 이름을 맞추자고
        # 파일을 옮기면, 옮기다 실패했을 때 DB 와 디스크가 어긋난다.
        session.execute(
            update(Point).where(Point.point_id == point_id).values(point_id=renamed)
        )
        session.commit()
        point_id = renamed
        row = session.get(Point, point_id)

    for field, value in changes.items():
        setattr(row, field, value)
    session.commit()
    has_base = (
        session.execute(
            select(func.count())
            .select_from(Baseline)
            .where(Baseline.point_id == point_id)
        ).scalar_one()
        > 0
    )
    return PointOut(
        point_id=row.point_id,
        target_id=row.target_id,
        name=row.name,
        location_desc=row.location_desc,
        tone=row.tone,
        note=row.note,
        created_at=row.created_at,
        has_baseline=has_base,
    )


@router.delete("/points/{point_id}", summary="개소 삭제")
def delete_point(
    point_id: str, session: Annotated[Session, Depends(get_session)]
) -> dict[str, str]:
    row = session.get(Point, point_id)
    if row is None:
        raise HTTPException(404, f"등록되지 않은 개소다: {point_id}")
    session.delete(row)
    session.commit()
    return {"deleted": point_id}


# ---------------------------------------------------------------------------
# 기준 사진
# ---------------------------------------------------------------------------


@router.get("/baselines", response_model=list[BaselineOut], summary="기준 사진 목록")
def list_baselines(
    session: Annotated[Session, Depends(get_session)],
    point_id: str | None = None,
) -> list[BaselineOut]:
    stmt = select(Baseline).order_by(Baseline.point_id, Baseline.effective_from.desc())
    if point_id:
        stmt = stmt.where(Baseline.point_id == point_id)
    return [_baseline_out(row) for row in session.execute(stmt).scalars()]


@router.get(
    "/baselines/current", response_model=list[BaselineOut], summary="개소별 현행 기준"
)
def current_baselines(
    session: Annotated[Session, Depends(get_session)],
) -> list[BaselineOut]:
    stmt = (
        select(Baseline)
        .where(Baseline.superseded_at.is_(None))
        .order_by(Baseline.point_id, Baseline.effective_from.desc())
    )
    seen: set[str] = set()
    out: list[BaselineOut] = []
    for row in session.execute(stmt).scalars():
        if row.point_id in seen:
            continue
        seen.add(row.point_id)
        out.append(_baseline_out(row))
    return out


@router.post("/baselines", response_model=BaselineOut, summary="기준 사진 등록")
async def create_baseline(
    session: Annotated[Session, Depends(get_session)],
    root: Annotated[object, Depends(get_root)],
    file: Annotated[UploadFile, File(description="기준 사진. 패드 하나만 담는다")],
    point_id: Annotated[str | None, Form(description="비우면 파일명에서 읽는다")] = None,
    effective_from: Annotated[
        str | None, Form(description="부착 일시(ISO). 비우면 파일명에서 읽는다")
    ] = None,
) -> BaselineOut:
    """기준 사진을 등록하고 이전 현행 기준을 대체 처리한다.

    **기준 사진에는 패드가 하나만 담겨야 한다.** 여러 개가 담기면 그 패드들의
    부착 시점이 한 장에 묶여, 나중에 하나만 갈아 붙였을 때 나머지 기준까지
    새 시점으로 덮어쓰게 된다.
    """
    parsed = naming.parse_baseline(file.filename or "")
    resolved_point = point_id or (parsed.point_id if parsed else None)
    if not resolved_point:
        raise HTTPException(
            400,
            "개소 번호를 알 수 없다. 파일명이 B_<POINT_ID>_<YYMMDD>_<HHMM>_r<n> "
            "형식이 아니면 point_id 를 함께 보낸다.",
        )
    point = session.get(Point, resolved_point)
    if point is None:
        raise HTTPException(400, f"등록되지 않은 개소다: {resolved_point}")

    moment = _parse_stamp(effective_from) or (parsed.effective_from if parsed else None)
    if moment is None:
        raise HTTPException(400, "부착 일시를 알 수 없다. effective_from 을 함께 보낸다.")

    data = await file.read()
    if not data:
        raise HTTPException(400, "빈 파일이다")

    row = Baseline(
        point_id=resolved_point,
        file_path="",
        original_name=file.filename,
        effective_from=moment,
        revision_hint=parsed.revision_hint if parsed else None,
        registered_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()

    path = storage.baseline_path(
        root, resolved_point, row.id, storage.suffix_of(file.filename or "")
    )
    storage.write(path, data)
    row.file_path = storage.relative(root, path)

    # 부착 일시 순서로 대체 관계를 다시 맞춘다. 파일명의 회차 표기는 보지
    # 않는다 - 같은 정보를 두 곳에 두면 어긋났을 때 믿을 근거가 없다.
    _resequence(session, resolved_point)
    session.commit()
    return _baseline_out(row)


def _resequence(session: Session, point_id: str) -> None:
    """한 개소의 기준 이력을 부착 일시 순으로 이어 붙인다.

    나중 것이 앞의 것을 대체하고, 가장 마지막 것만 현행으로 남는다. 늦게
    등록했어도 부착 일시가 이르면 그 자리에 끼워 넣는다.
    """
    rows = list(
        session.execute(
            select(Baseline)
            .where(Baseline.point_id == point_id)
            .order_by(Baseline.effective_from, Baseline.id)
        ).scalars()
    )
    for current, following in zip(rows, rows[1:]):
        current.superseded_at = following.effective_from
    if rows:
        rows[-1].superseded_at = None


def _baseline_out(row: Baseline) -> BaselineOut:
    return BaselineOut(
        id=row.id,
        point_id=row.point_id,
        file_path=row.file_path,
        original_name=row.original_name,
        effective_from=row.effective_from,
        superseded_at=row.superseded_at,
        revision_hint=row.revision_hint,
        registered_at=row.registered_at,
        is_current=row.superseded_at is None,
    )


# ---------------------------------------------------------------------------
# 업로드 미리보기
# ---------------------------------------------------------------------------


@router.post("/uploads/parse", response_model=list[ParsedUpload], summary="파일명 파싱")
def parse_names(
    session: Annotated[Session, Depends(get_session)],
    filenames: list[str],
    kind: str = "capture",
) -> list[ParsedUpload]:
    """올리기 전에 파일명에서 값을 뽑아 화면이 미리 채우게 한다.

    파싱 결과는 정본이 아니다. 화면에서 확정된 값이 정본이고, 파싱은 입력을
    줄이는 수단이다. 그래서 실패해도 거부하지 않는다.
    """
    out: list[ParsedUpload] = []
    for name in filenames:
        if kind == "baseline":
            parsed = naming.parse_baseline(name)
            if parsed is None:
                out.append(
                    ParsedUpload(
                        filename=name,
                        parsed=False,
                        message="B_<POINT_ID>_<날짜>_<HHMM>_r<n> 형식이 아니다",
                    )
                )
                continue
            known = session.get(Point, parsed.point_id) is not None
            out.append(
                ParsedUpload(
                    filename=name,
                    parsed=True,
                    point_id=parsed.point_id,
                    stamp=parsed.effective_from,
                    revision_hint=parsed.revision_hint,
                    known_id=known,
                    message=None if known else "등록되지 않은 개소다",
                )
            )
            continue

        parsed_capture = naming.parse_capture(name)
        if parsed_capture is None:
            out.append(
                ParsedUpload(
                    filename=name,
                    parsed=False,
                    message="C_<TARGET_ID>_<날짜>_<HHMM>_<nn> 형식이 아니다",
                )
            )
            continue
        known = session.get(Target, parsed_capture.target_id) is not None
        out.append(
            ParsedUpload(
                filename=name,
                parsed=True,
                target_id=parsed_capture.target_id,
                stamp=parsed_capture.captured_at,
                known_id=known,
                message=None if known else "등록되지 않은 촬영 단위다",
            )
        )
    return out


def _parse_stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"일시를 읽을 수 없다: {value!r}") from None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=naming.KST)
