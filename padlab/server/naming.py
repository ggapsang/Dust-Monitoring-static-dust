"""업로드 파일명 파싱.

파일명이 곧 메타데이터 입력이다. 수십 장을 올리면서 화면에서 사진마다
촬영 단위와 일시를 지정하는 것은 지금 ``/docs`` 를 두드리는 것과 비용이
같으므로, 파일명에서 뽑아 미리 채우고 사람은 틀린 것만 고친다.

**파싱 결과는 정본이 아니다.** 화면에서 확정된 값이 정본이고, 파싱은 입력을
줄이는 수단일 뿐이다. 그래서 실패해도 거부하지 않는다 - 해당 사진만
사람이 지정하도록 표시한다.

    판독 사진   C_<TARGET_ID>_<YYMMDD>_<HHMM>_<nn>.jpg
    기준 사진   B_<POINT_ID>_<YYMMDD>_<HHMM>_r<n>.jpg

구분자는 ``_`` 고정이고 필드 안에 ``_`` 를 쓰지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
"""사람이 파일명에 적는 시각의 시간대."""

CAPTURE_RE = re.compile(
    r"^C_(?P<id>[^_]+)_(?P<date>\d{6})_(?P<time>\d{4})_(?P<seq>\d+)$"
)
BASELINE_RE = re.compile(
    r"^B_(?P<id>[^_]+)_(?P<date>\d{6})_(?P<time>\d{4})_r(?P<rev>\d+)$"
)


@dataclass(frozen=True)
class CaptureName:
    target_id: str
    captured_at: datetime
    sequence: int


@dataclass(frozen=True)
class BaselineName:
    point_id: str
    effective_from: datetime
    revision_hint: int
    """파일명이 말하는 회차. **대체 판정에 쓰지 않는다.**

    순서는 ``effective_from`` 이 이미 갖고 있어서, 이 값과 날짜가 어긋나면
    어느 쪽을 믿을지 정할 근거가 없다. 그래서 참고값으로만 저장하고 현행
    기준 판정은 일시 순서로 한다.
    """


def _stamp(date: str, time: str) -> datetime:
    """``YYMMDD`` 와 ``HHMM`` 을 UTC 시각으로.

    사람이 붙이는 값이라 현지 시각(KST)으로 읽고 UTC 로 바꿔 저장한다. DB 를
    UTC 로 통일해야 나중에 시간대가 섞였을 때 값 자체는 흔들리지 않는다.
    """
    naive = datetime.strptime(date + time, "%y%m%d%H%M")
    return naive.replace(tzinfo=KST).astimezone(timezone.utc)


def parse_capture(filename: str) -> CaptureName | None:
    match = CAPTURE_RE.match(_stem(filename))
    if not match:
        return None
    try:
        stamp = _stamp(match["date"], match["time"])
    except ValueError:
        return None
    return CaptureName(match["id"], stamp, int(match["seq"]))


def parse_baseline(filename: str) -> BaselineName | None:
    match = BASELINE_RE.match(_stem(filename))
    if not match:
        return None
    try:
        stamp = _stamp(match["date"], match["time"])
    except ValueError:
        return None
    return BaselineName(match["id"], stamp, int(match["rev"]))


def _stem(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name
