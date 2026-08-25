"""판독 실행.

한 번의 실행에 사진 여러 장을 돌린다. 사진 한 장이 실패해도 나머지를 계속
처리한다 - 스무 장을 올려 놓고 세 번째에서 전체가 멈추면 실증이 진행되지
않는다.

사진 한 장의 처리 순서다.

1. 그 촬영 단위에 속한 개소를 찾는다
2. 개소마다 촬영 일시에 유효한 기준 사진을 고른다
3. 톤이 같은 것끼리 묶어 판독을 부른다
4. 응답의 패드마다 결과를 저장하고 이미지를 곧바로 내려받는다

**기준을 못 찾은 개소는 실행 기록에 남긴다.** 요청에서 빠지면 그 개소는
결과가 없는데, 왜 없는지가 어디에도 없으면 사람이 찾을 방법이 없다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from . import storage
from .models import Baseline, Capture, Point, Reading, Run
from .reader import ReaderClient

IMAGE_COLUMNS = {
    "baseline_rectified": "img_baseline_rectified",
    "rectified": "img_rectified",
    "distribution": "img_distribution",
}


@dataclass
class Job:
    """사진 한 장에 대한 판독 호출 하나. 톤이 다르면 호출이 나뉜다."""

    capture: Capture
    tone: str
    points: list[Point]
    baselines: list[Baseline]


def effective_baseline(
    session: Session, point_id: str, moment: datetime, ignore_window: bool = False
) -> Baseline | None:
    """그 시각에 유효한 기준. 없으면 ``None``.

    부착 일시가 촬영보다 앞서고, 아직 대체되지 않았거나 촬영 이후에 대체된
    것 중 가장 나중 것이다. 패드를 갈아 붙인 뒤에도 그 이전 촬영분은 예전
    기준으로 읽혀야 값이 이어진다.

    순서는 ``effective_from`` 만 본다. 파일명의 회차 표기는 참고값이다 -
    같은 정보를 두 곳에 두면 어긋났을 때 어느 쪽을 믿을 근거가 없다.

    ``ignore_window`` 를 켜면 시점을 보지 않고 그 개소의 가장 나중 기준을
    쓴다. 실증 중에는 기준을 나중에 등록하거나 부착 일시를 대충 넣는 일이
    잦아, 촬영보다 늦은 기준밖에 없어서 판독이 통째로 안 도는 경우가 생긴다.
    켜고 얻은 값은 **부착 이후 쌓인 양이 아닐 수 있다** - 촬영보다 나중에
    붙인 패드를 기준으로 삼으면 그 사이의 침착이 빠진다.
    """
    stmt = select(Baseline).where(Baseline.point_id == point_id)
    if not ignore_window:
        stmt = stmt.where(Baseline.effective_from <= moment).where(
            (Baseline.superseded_at.is_(None)) | (Baseline.superseded_at > moment)
        )
    stmt = stmt.order_by(Baseline.effective_from.desc()).limit(1)
    return session.execute(stmt).scalars().first()


def _reader_tone(point_tone: str) -> str:
    """개소 등록 톤(white/black/chroma) 을 판독기 호출 톤(white/black) 으로.

    판독기의 ``pad_tone`` 은 white/black 두 값만 받는다 - 무채색 패드의
    검출 판정 극성이다. chroma(유채색) 패드는 테두리 잉크·바깥 여백
    배치가 white 톤 무채색 패드와 완전히 같게 도안했으므로(``make_pad_chroma.py``),
    호출 자체는 white 로 나간다. 패드가 실제로 유채색인지는 판독기가
    사진에서 스스로 판별한다(``pad_type`` 필드) - 이 함수는 그 판별과
    무관하게 API 호출값만 맞춰 준다.
    """
    return "white" if point_tone == "chroma" else point_tone


def plan_jobs(
    session: Session, capture: Capture, ignore_window: bool = False
) -> tuple[list[Job], list[dict[str, Any]]]:
    """사진 한 장을 어떻게 부를지 정한다. (호출 목록, 알림 목록)

    톤이 다르면 나눠 부른다. 판독기는 한 번에 한 톤만 찾는다.
    """
    points = list(
        session.execute(
            select(Point)
            .where(Point.target_id == capture.target_id)
            .order_by(Point.point_id)
        ).scalars()
    )
    notes: list[dict[str, Any]] = []
    if not points:
        notes.append(
            {
                "capture_id": capture.id,
                "original_name": capture.original_name,
                "kind": "no_point",
                "message": f"{capture.target_id} 에 등록된 개소가 없다",
            }
        )
        return [], notes

    by_tone: dict[str, tuple[list[Point], list[Baseline]]] = {}
    for point in points:
        base = effective_baseline(
            session, point.point_id, capture.captured_at, ignore_window
        )
        if base is None:
            notes.append(
                {
                    "capture_id": capture.id,
                    "point_id": point.point_id,
                    "kind": "no_baseline",
                    "message": (
                        "등록된 기준 사진이 없어 요청에서 제외했다"
                        if ignore_window
                        else "촬영 일시에 유효한 기준 사진이 없어 요청에서 제외했다. "
                        "등록 시점을 대조하지 않으려면 판독 실행에서 그 항목을 켠다"
                    ),
                    "original_name": capture.original_name,
                }
            )
            continue
        group = by_tone.setdefault(_reader_tone(point.tone), ([], []))
        group[0].append(point)
        group[1].append(base)

    jobs = [
        Job(capture=capture, tone=tone, points=grouped[0], baselines=grouped[1])
        for tone, grouped in sorted(by_tone.items())
    ]
    return jobs, notes


def pair_baseline(baselines: list[Baseline], read_point: str | None) -> Baseline | None:
    """이 패드의 기준을 정한다.

    기준을 하나만 보냈으면 그것으로 확정한다. 판독기가 그 경우 번호를 보지
    않고 짝을 맺기 때문이다 - 후보가 하나뿐이면 그것 말고 짝이 될 것이 없다.
    번호를 잘못 읽어도 짝은 맞으므로, 읽은 번호는 ``read_point_id`` 에 따로
    남겨 오독을 나중에 셀 수 있게 한다.

    여러 개면 번호가 맞는 것만 짝짓는다. 소거법으로 남은 것끼리 맺지
    않는다 - 오검출된 가짜 패드가 멀쩡한 기준을 차지해 조용히 틀린 값을 낸다.
    """
    if len(baselines) == 1:
        return baselines[0]
    if not read_point:
        return None
    return next((b for b in baselines if b.point_id == read_point), None)


def store_reading(
    session: Session,
    root: Path,
    run_id: int,
    job: Job,
    index: int,
    pad: dict[str, Any],
    payload: dict[str, Any],
    frames: dict[str, bytes],
) -> Reading:
    """패드 하나의 결과를 저장한다. 이미지 복사가 실패해도 값은 남긴다.

    ``read_point_id`` 에는 숫자를 그대로 읽은 값을 넣는다. 닫힌 판독에서는
    판독기가 후보에 배정한 값과 다를 수 있고, 오독이 몇 건이었는지 세려면
    배정 결과와 실제로 읽은 값이 따로 있어야 한다.
    """
    read_point = pad.get("point_id")
    baseline = pair_baseline(job.baselines, read_point)
    scores = pad.get("scores") or {}
    quality = pad.get("quality") or {}
    od = pad.get("optical_density") or {}
    chroma = pad.get("chroma") or {}
    luma_dark = pad.get("luma_dark") or {}
    luma_light = pad.get("luma_light") or {}

    reading = Reading(
        run_id=run_id,
        capture_id=job.capture.id,
        baseline_id=baseline.id if baseline else None,
        point_id=baseline.point_id if baseline else None,
        pad_index=index,
        tone=job.tone,
        success=bool(pad.get("success")),
        failure_reason=pad.get("failure_reason"),
        failure_detail=pad.get("failure_detail"),
        summary=pad.get("summary"),
        score_uniform=scores.get("uniform"),
        score_localized=scores.get("localized"),
        score_combined=scores.get("combined"),
        quality_sharpness=quality.get("sharpness"),
        quality_saturated_ratio=quality.get("saturated_ratio"),
        quality_pad_size_px=quality.get("pad_size_px"),
        quality_pad_size_diff_ratio=quality.get("pad_size_diff_ratio"),
        read_point_id=pad.get("point_id_raw") or read_point,
        elapsed_ms=payload.get("elapsed_ms"),
        od_sum=od.get("od_sum"),
        od_mean=od.get("od_mean"),
        od_score=od.get("od_score"),
        roi_mean_reading=od.get("roi_mean_reading"),
        roi_mean_baseline=od.get("roi_mean_baseline"),
        pad_scale=od.get("pad_scale"),
        pad_type=pad.get("pad_type"),
        chroma_score=chroma.get("score"),
        luma_dark_score=luma_dark.get("score"),
        luma_light_score=luma_light.get("score"),
        response=pad,
        created_at=datetime.now(timezone.utc),
    )
    session.add(reading)
    session.flush()

    for kind, data in frames.items():
        column = IMAGE_COLUMNS.get(kind)
        if not column:
            continue
        path = storage.result_dir(root, reading.id) / f"{kind}.png"
        try:
            storage.write(path, data)
        except OSError:
            # 이미지 하나를 못 써도 판독값은 남긴다. 값이 이미지보다 귀하다.
            continue
        setattr(reading, column, storage.relative(root, path))
    return reading


async def execute_run(
    run_id: int,
    capture_ids: list[int],
    session_factory: sessionmaker,
    client: ReaderClient,
    root: Path,
    concurrency: int,
) -> None:
    """실행 하나를 끝까지 돌린다. 배경 작업으로 부른다.

    동시 처리 수를 낮게 잡는다. 판독은 CPU 바운드라 늘려도 선형으로 빨라지지
    않고 서로 느려지기만 한다.
    """
    limit = asyncio.Semaphore(max(1, concurrency))

    async def one(capture_id: int) -> None:
        async with limit:
            await process_capture(capture_id, run_id, session_factory, client, root)

    await asyncio.gather(*(one(cid) for cid in capture_ids), return_exceptions=True)

    with session_factory() as session:
        run = session.get(Run, run_id)
        if run is not None:
            run.status = "done"
            run.finished_at = datetime.now(timezone.utc)
            session.commit()


async def process_capture(
    capture_id: int,
    run_id: int,
    session_factory: sessionmaker,
    client: ReaderClient,
    root: Path,
) -> None:
    with session_factory() as session:
        run = session.get(Run, run_id)
        capture = session.get(Capture, capture_id)
        if run is None or capture is None:
            return
        jobs, notes = plan_jobs(session, capture, bool(run.ignore_baseline_window))
        overrides = dict(run.config_override or {})
        append_notes(run, notes)
        # 판독 호출 동안 세션을 잡고 있지 않는다. 한 장에 몇 초가 걸려서,
        # 커넥션이 그만큼 묶이면 동시 처리 수만큼 풀이 마른다.
        plans = [
            (
                job.tone,
                storage.absolute(root, capture.file_path).as_posix(),
                [storage.absolute(root, b.file_path).as_posix() for b in job.baselines],
                [b.id for b in job.baselines],
                [p.point_id for p in job.points],
            )
            for job in jobs
        ]
        session.commit()

    for tone, image_path, baseline_paths, baseline_ids, point_ids in plans:
        try:
            outcome = await client.read_path(
                image_path, baseline_paths, tone, overrides, point_ids
            )
        except Exception as exc:  # noqa: BLE001 - 사진 한 장의 실패로 다룬다
            _note(session_factory, run_id, capture_id, tone, "read_failed", str(exc)[:400])
            continue

        with session_factory() as session:
            capture = session.get(Capture, capture_id)
            if capture is None:
                return
            job = Job(
                capture=capture,
                tone=tone,
                points=[session.get(Point, pid) for pid in point_ids],
                baselines=[session.get(Baseline, bid) for bid in baseline_ids],
            )
            pads = outcome.payload.get("pads") or []
            saved: list[Reading] = []
            for index, pad in enumerate(pads):
                frames = outcome.images[index] if index < len(outcome.images) else {}
                saved.append(
                    store_reading(
                        session, root, run_id, job, index, pad, outcome.payload, frames
                    )
                )
            if not pads:
                run = session.get(Run, run_id)
                if run is not None:
                    append_notes(
                        run,
                        [
                            {
                                "capture_id": capture_id,
                                "original_name": capture.original_name,
                                "tone": tone,
                                "kind": "no_pad",
                                "message": outcome.payload.get("summary")
                                or "패드를 찾지 못했다",
                            }
                        ],
                    )
            try:
                session.commit()
            except Exception:
                # DB 가 안 받아 준 결과 이미지는 남기지 않는다. 어느 판독의
                # 것인지 가리키는 행이 없으면 지워도 되는지 알 수 없다.
                for row in saved:
                    storage.remove_tree(storage.result_dir(root, row.id))
                raise

    with session_factory() as session:
        run = session.get(Run, run_id)
        if run is not None:
            run.done_captures = run.done_captures + 1
            session.commit()


def _note(
    session_factory: sessionmaker,
    run_id: int,
    capture_id: int,
    tone: str,
    kind: str,
    message: str,
) -> None:
    with session_factory() as session:
        run = session.get(Run, run_id)
        capture = session.get(Capture, capture_id)
        if run is None:
            return
        append_notes(
            run,
            [
                {
                    "capture_id": capture_id,
                    "original_name": capture.original_name if capture else None,
                    "tone": tone,
                    "kind": kind,
                    "message": message,
                }
            ],
        )
        session.commit()


def append_notes(run: Run, notes: list[dict[str, Any]]) -> None:
    """실행 알림을 덧붙인다. 새 리스트로 갈아 끼워야 변경이 감지된다."""
    if not notes:
        return
    run.notes = list(run.notes or []) + notes
