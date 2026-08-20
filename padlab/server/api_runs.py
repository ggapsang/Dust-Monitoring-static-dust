"""판독 실행과 재판독.

실행은 즉시 반환하고 배경에서 돈다. 판독 한 장이 몇 초라 스무 장이면
1분을 넘기는데, 그동안 요청을 붙들고 있으면 브라우저가 먼저 끊는다.
진행 상황은 ``GET /api/runs/{id}`` 로 본다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import naming, runs, storage
from .deps import (
    get_client,
    get_concurrency,
    get_root,
    get_session,
    get_session_factory,
)
from .models import Capture, Reading, Run, Target
from .reader import ReaderClient
from .schemas import RunOut

router = APIRouter(prefix="/api", tags=["판독 실행"])


@router.post("/runs", response_model=RunOut, summary="판독 실행")
async def create_run(
    background: BackgroundTasks,
    session: Annotated[Session, Depends(get_session)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
    client: Annotated[ReaderClient, Depends(get_client)],
    root: Annotated[Path, Depends(get_root)],
    concurrency: Annotated[int, Depends(get_concurrency)],
    files: Annotated[list[UploadFile], File(description="판독 사진. 여러 장 가능")],
    target_ids: Annotated[
        str,
        Form(
            description=(
                "사진마다의 촬영 단위. JSON 배열이며 files 와 순서가 같다. "
                '예: ["T0042","T0043"]. 비워 두면 파일명이 규칙을 따를 때에 한해 '
                "거기서 읽는다 - 규칙은 손입력을 줄이는 수단일 뿐이라 안 지켜도 된다."
            )
        ),
    ] = "",
    captured_ats: Annotated[
        str,
        Form(description="사진마다의 촬영 일시(ISO). JSON 배열. 비우면 파일명에서 읽는다"),
    ] = "",
    config_override: Annotated[
        str, Form(description="설정 일부 덮어쓰기(JSON 객체). 비우면 서버 설정 그대로")
    ] = "",
    ignore_baseline_window: Annotated[
        bool,
        Form(
            description=(
                "기준 사진의 등록 시점을 대조하지 않는다. 켜면 촬영 일시와 무관하게 "
                "그 개소의 가장 나중 기준을 쓴다. **얻은 값이 부착 이후 쌓인 양이 "
                "아닐 수 있다** - 촬영보다 나중에 붙인 패드를 기준으로 삼으면 그 "
                "사이의 침착이 빠진다."
            )
        ),
    ] = False,
) -> RunOut:
    if not files:
        raise HTTPException(400, "사진이 없다")

    targets = _json_list(target_ids, len(files), "target_ids")
    stamps = _json_list(captured_ats, len(files), "captured_ats")
    overrides = _json_object(config_override)

    capture_ids: list[int] = []
    for index, upload in enumerate(files):
        parsed = naming.parse_capture(upload.filename or "")
        target_id = targets[index] or (parsed.target_id if parsed else None)
        moment = _stamp(stamps[index]) or (parsed.captured_at if parsed else None)

        if not target_id:
            raise HTTPException(
                400,
                f"{upload.filename!r} 의 촬영 단위를 지정하지 않았다. "
                "target_ids 에 값을 넣는다.",
            )
        if moment is None:
            raise HTTPException(400, f"{upload.filename!r} 의 촬영 일시를 알 수 없다")
        if session.get(Target, target_id) is None:
            raise HTTPException(
                400,
                f"등록되지 않은 촬영 단위다: {target_id}. "
                "등록되지 않으면 기준 사진을 모을 수 없어 판독이 성립하지 않는다.",
            )

        data = await upload.read()
        if not data:
            raise HTTPException(400, f"{upload.filename!r} 이 비어 있다")

        capture = Capture(
            target_id=target_id,
            file_path="",
            original_name=upload.filename,
            content_sha256=storage.sha256(data),
            captured_at=moment,
            uploaded_at=datetime.now(timezone.utc),
        )
        session.add(capture)
        session.flush()
        path = storage.capture_path(
            root, moment, capture.id, storage.suffix_of(upload.filename or "")
        )
        storage.write(path, data)
        capture.file_path = storage.relative(root, path)
        capture_ids.append(capture.id)

    run = Run(
        executed_at=datetime.now(timezone.utc),
        config_override=overrides,
        kind="initial",
        status="running",
        total_captures=len(capture_ids),
        done_captures=0,
        notes=[],
        ignore_baseline_window=ignore_baseline_window,
    )
    session.add(run)
    try:
        session.commit()
    except Exception:
        # DB 가 안 받아 준 사진은 남기지 않는다. 주인 없는 파일이 볼륨에
        # 쌓이면 나중에 지워도 되는 것인지 사람이 알 방법이 없다.
        storage.discard(written)
        raise

    background.add_task(
        runs.execute_run,
        run.id,
        capture_ids,
        session_factory,
        client,
        root,
        concurrency,
    )
    return _run_out(session, run)


@router.post("/runs/{run_id}/rerun", response_model=RunOut, summary="실행 단위 재판독")
async def rerun_run(
    run_id: int,
    background: BackgroundTasks,
    session: Annotated[Session, Depends(get_session)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
    client: Annotated[ReaderClient, Depends(get_client)],
    root: Annotated[Path, Depends(get_root)],
    concurrency: Annotated[int, Depends(get_concurrency)],
    body: dict[str, Any] | None = None,
) -> RunOut:
    """같은 사진과 같은 기준으로 설정만 바꿔 다시 판독한다.

    기존 결과를 덮어쓰지 않는다. 새 실행 아래에 쌓아 두 실행을 나란히
    비교한다.
    """
    source = session.get(Run, run_id)
    if source is None:
        raise HTTPException(404, f"없는 실행이다: {run_id}")

    capture_ids = list(
        session.execute(
            select(Reading.capture_id).where(Reading.run_id == run_id).distinct()
        )
        .scalars()
        .all()
    )
    if not capture_ids:
        raise HTTPException(400, "이 실행에는 다시 판독할 사진이 없다")

    return await _spawn_rerun(
        session,
        session_factory,
        client,
        root,
        background,
        concurrency,
        capture_ids,
        run_id,
        body,
    )


@router.post("/readings/rerun", response_model=RunOut, summary="선택 건 재판독")
async def rerun_readings(
    background: BackgroundTasks,
    session: Annotated[Session, Depends(get_session)],
    session_factory: Annotated[Any, Depends(get_session_factory)],
    client: Annotated[ReaderClient, Depends(get_client)],
    root: Annotated[Path, Depends(get_root)],
    concurrency: Annotated[int, Depends(get_concurrency)],
    body: dict[str, Any],
) -> RunOut:
    """판독 건 몇 개를 골라 다시 판독한다. ``reading_ids`` 와 ``config_override``."""
    ids = body.get("reading_ids") or []
    if not ids:
        raise HTTPException(400, "reading_ids 가 비어 있다")

    capture_ids = list(
        session.execute(
            select(Reading.capture_id).where(Reading.id.in_(ids)).distinct()
        )
        .scalars()
        .all()
    )
    if not capture_ids:
        raise HTTPException(404, "해당하는 판독 건이 없다")

    source_run = session.execute(
        select(Reading.run_id).where(Reading.id.in_(ids)).limit(1)
    ).scalar_one_or_none()
    return await _spawn_rerun(
        session,
        session_factory,
        client,
        root,
        background,
        concurrency,
        capture_ids,
        source_run,
        body,
    )


@router.get("/runs", response_model=list[RunOut], summary="실행 목록")
def list_runs(
    session: Annotated[Session, Depends(get_session)], limit: int = 50
) -> list[RunOut]:
    rows = session.execute(
        select(Run).order_by(Run.executed_at.desc()).limit(limit)
    ).scalars()
    return [_run_out(session, row) for row in rows]


@router.get("/runs/{run_id}", response_model=RunOut, summary="실행 상태와 결과 요약")
def get_run(run_id: int, session: Annotated[Session, Depends(get_session)]) -> RunOut:
    row = session.get(Run, run_id)
    if row is None:
        raise HTTPException(404, f"없는 실행이다: {run_id}")
    return _run_out(session, row)


# ---------------------------------------------------------------------------


async def _spawn_rerun(
    session: Session,
    session_factory: Any,
    client: ReaderClient,
    root: Path,
    background: BackgroundTasks,
    concurrency: int,
    capture_ids: list[int],
    source_run_id: int | None,
    body: dict[str, Any] | None,
) -> RunOut:
    overrides = (body or {}).get("config_override") or {}
    if not isinstance(overrides, dict):
        raise HTTPException(400, "config_override 는 JSON 객체여야 한다")

    # 안 주면 원본 실행을 따른다. 재판독은 설정만 바꿔 견주는 것이라 나머지
    # 조건이 말없이 달라지면 두 값을 비교할 수 없다.
    source = session.get(Run, source_run_id) if source_run_id else None
    ignore_window = (body or {}).get("ignore_baseline_window")
    if ignore_window is None:
        ignore_window = bool(source.ignore_baseline_window) if source else False

    run = Run(
        executed_at=datetime.now(timezone.utc),
        config_override=overrides,
        source_run_id=source_run_id,
        kind="rerun",
        status="running",
        total_captures=len(capture_ids),
        done_captures=0,
        notes=[],
        ignore_baseline_window=bool(ignore_window),
    )
    session.add(run)
    session.commit()

    background.add_task(
        runs.execute_run,
        run.id,
        capture_ids,
        session_factory,
        client,
        root,
        concurrency,
    )
    return _run_out(session, run)


def _run_out(session: Session, row: Run) -> RunOut:
    count = session.execute(
        select(func.count()).select_from(Reading).where(Reading.run_id == row.id)
    ).scalar_one()
    return RunOut(
        id=row.id,
        executed_at=row.executed_at,
        finished_at=row.finished_at,
        kind=row.kind,
        status=row.status,
        config_override=row.config_override or {},
        source_run_id=row.source_run_id,
        total_captures=row.total_captures,
        done_captures=row.done_captures,
        notes=row.notes or [],
        reading_count=count,
        ignore_baseline_window=bool(row.ignore_baseline_window),
    )


def _json_list(raw: str, size: int, label: str) -> list[str | None]:
    if not raw.strip():
        return [None] * size
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"{label} 를 JSON 으로 읽을 수 없다: {exc}") from None
    if not isinstance(parsed, list):
        raise HTTPException(400, f"{label} 는 JSON 배열이어야 한다")
    if len(parsed) != size:
        raise HTTPException(
            400, f"{label} 의 개수({len(parsed)})가 사진 수({size})와 다르다"
        )
    return [None if item in (None, "") else str(item) for item in parsed]


def _json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"config_override 를 JSON 으로 읽을 수 없다: {exc}") from None
    if not isinstance(parsed, dict):
        raise HTTPException(400, "config_override 는 JSON 객체여야 한다")
    return parsed


def _stamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"촬영 일시를 읽을 수 없다: {value!r}") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=naming.KST)
