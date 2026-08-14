"""판독 서비스.

``padreader`` 를 감싸는 얇은 어댑터다. 판독 로직은 여기 없다 — 이미지를
받아 넘기고 결과를 정리해 돌려줄 뿐이다.

설정은 기동 시 한 번 읽어 읽기 전용으로 쓰고, 요청별 오버라이드는 그때마다
새 설정 객체를 만든다. 그래서 어떤 요청도 다른 요청의 판독 결과를 바꾸지
못한다.
"""

from __future__ import annotations

import json
import time
from typing import Annotated, Any

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from padreader.config import Config, load_config, resolve_config_path
from padreader.pipeline import read_pad
from padreader.spec import SPECS

from .schemas import (
    FAILURE_LABELS,
    BatchResponse,
    ReadPathRequest,
    ReadResult,
    build_batch_summary,
    to_result,
)

app = FastAPI(title="참조 패드 판독 서비스", version="0.3.0")

# 기동 시 한 번만 읽는다. 이후로는 읽기 전용이며, 요청별 오버라이드는
# 원본을 건드리지 않고 새 객체를 만든다.
_CONFIG_PATH = resolve_config_path()
_BASE_CONFIG: Config = load_config()

MAX_BATCH = 50
"""한 요청에 받을 이미지 수 상한.

장당 0.5초 안팎이라 이 정도가 한 번 기다릴 만한 한계다. 더 많으면
``python -m padtools.batch`` 로 돌리는 편이 낫다.
"""

CONFIG_EXAMPLE = '{"spec": "v2_protected", "grid": {"rows": 4, "cols": 4}}'
"""문서에 보여줄 오버라이드 예시. 폼 필드의 기본값과 함께 쓴다."""


def _parse_overrides(raw: str | None) -> dict[str, Any]:
    """설정 오버라이드 문자열을 파싱한다. 비어 있으면 오버라이드 없음.

    빈 값과 공백만 있는 값을 모두 '오버라이드 없음' 으로 본다. 폼으로 오는
    값이라 브라우저나 클라이언트가 빈 칸을 공백으로 채워 보내는 경우가 있다.
    """
    if raw is None or not raw.strip():
        return {}

    text = raw.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            400,
            f"config 를 JSON 으로 읽을 수 없다 ({exc}). "
            f"받은 값: {text[:80]!r}. "
            f"비워 두면 서버 설정을 그대로 쓰고, 바꿀 부분만 객체로 넣는다. "
            f"예: {CONFIG_EXAMPLE}",
        ) from None

    if not isinstance(parsed, dict):
        raise HTTPException(
            400,
            f"config 는 JSON 객체여야 한다. 받은 것: {type(parsed).__name__}. "
            f"예: {CONFIG_EXAMPLE}",
        )
    return parsed


def _decode(data: bytes) -> np.ndarray | None:
    if not data:
        return None
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def _check_batch_size(count: int) -> None:
    if count == 0:
        raise HTTPException(400, "이미지가 없다")
    if count > MAX_BATCH:
        raise HTTPException(
            400,
            f"한 번에 {MAX_BATCH}장까지만 받는다 (요청 {count}장). "
            f"더 많으면 python -m padtools.batch 로 돌린다.",
        )


def _unreadable(name: str, detail: str) -> ReadResult:
    """이미지를 아예 열지 못한 경우도 결과 한 줄로 돌려준다.

    여러 장을 한 번에 보낼 때 한 장이 깨졌다고 요청 전체를 실패시키면
    나머지 결과까지 버리게 된다.
    """
    return to_result(
        name,
        {
            "success": False,
            "failure_reason": "invalid_image",
            "failure_detail": detail,
            "elapsed_ms": 0.0,
        },
        detail=False,
        include_cells=False,
    )


def _read_one_visual(image: np.ndarray, tone: str, overrides: dict[str, Any]):
    """시각화까지 켜서 한 장을 판독한다. 결과 객체를 그대로 돌려준다."""
    try:
        return read_pad(
            image,
            pad_tone=tone,
            config=_BASE_CONFIG,
            overrides=overrides,
            visualize=True,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


def _read_many(
    items: list[tuple[str, np.ndarray | None, str | None]],
    tone: str,
    overrides: dict[str, Any],
    detail: bool,
    include_cells: bool,
) -> list[ReadResult]:
    """이미지 여러 장을 차례로 판독한다.

    스레드풀 슬롯 하나에서 순서대로 돈다. 장마다 슬롯을 잡으면 몇 장만
    올려도 풀이 말라 다른 요청이 밀린다.
    """
    results: list[ReadResult] = []
    for name, image, error in items:
        if image is None:
            results.append(_unreadable(name, error or "이미지를 디코드할 수 없다"))
            continue
        try:
            payload = read_pad(
                image,
                pad_tone=tone,
                config=_BASE_CONFIG,
                overrides=overrides,
                visualize=False,
            ).to_dict(include_cells=include_cells)
        except ValueError as exc:
            # 설정 오타나 잘못된 값은 요청 잘못이라 전체를 세운다.
            raise HTTPException(400, str(exc)) from None
        results.append(to_result(name, payload, detail=detail, include_cells=include_cells))
    return results


async def _respond(
    items: list[tuple[str, np.ndarray | None, str | None]],
    tone: str,
    overrides: dict[str, Any],
    detail: bool,
    include_cells: bool,
) -> BatchResponse:
    started = time.perf_counter()
    # OpenCV 연산이 GIL 을 오래 잡는 구간이 있어 이벤트 루프에서 직접 돌리지
    # 않는다. 한 장이 0.5초라 워커가 막히면 바로 체감된다.
    results = await run_in_threadpool(
        _read_many, items, tone, overrides, detail, include_cells
    )
    elapsed = time.perf_counter() - started
    return BatchResponse(
        summary=build_batch_summary(results, elapsed),
        count=len(results),
        succeeded=sum(1 for r in results if r.success),
        results=results,
    )


@app.get("/healthz", summary="기동 확인")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "specs": sorted(SPECS)}


@app.get("/config", summary="설정 조회")
def get_config() -> dict[str, Any]:
    """지금 판독에 쓰이고 있는 설정값을 그대로 돌려준다.

    임계값이 실증에서 계속 바뀌므로 무슨 값으로 돌고 있는지 언제든 확인할
    수 있어야 한다. ``null`` 인 임계값은 그 검사를 하지 않는다는 뜻이다.

    ``source`` 는 어느 파일에서 읽었는지다. 설정을 마운트해 놓고도 경로가
    어긋나 기본값으로 돌고 있는 상황을 여기서 잡는다.
    """
    return {
        "source": str(_CONFIG_PATH) if _CONFIG_PATH else None,
        "values": _BASE_CONFIG.to_dict(),
    }


@app.post("/read", response_model=BatchResponse, summary="판독 (이미지 업로드)")
async def read(
    files: Annotated[
        list[UploadFile],
        File(description=f"패드가 찍힌 이미지. 여러 장을 한 번에 올릴 수 있다 (최대 {MAX_BATCH}장)."),
    ],
    tone: Annotated[str, Query(description="white = 백색 바탕/흑색 인쇄")] = "white",
    detail: Annotated[
        bool, Query(description="품질 게이트·조도 정규화 진단값을 함께 받는다")
    ] = False,
    include_cells: Annotated[
        bool, Query(description="구획별 값 전부(기본 88개)를 함께 받는다")
    ] = False,
    config: Annotated[
        str,
        Form(
            description=(
                "설정 일부 덮어쓰기(JSON 객체). **비워 두면 서버 설정을 그대로 쓴다.** "
                "서버 설정 자체는 바뀌지 않으며 이 요청에만 적용된다. "
                f"예: {CONFIG_EXAMPLE}"
            ),
            # 기본값을 빈 문자열로 둔다. 기본값이 없으면 문서 UI 가 스키마
            # 예시인 "string" 을 그대로 보내 JSON 파싱에서 튕긴다.
            examples=[""],
        ),
    ] = "",
) -> BatchResponse:
    """올린 이미지를 판독한다. 한 장이든 여러 장이든 같은 형태로 답한다.

    응답 맨 위의 ``summary`` 한 줄만 봐도 결과를 알 수 있다. 한 장이 깨져
    있어도 나머지는 그대로 판독한다.
    """
    _check_batch_size(len(files))
    overrides = _parse_overrides(config)

    items: list[tuple[str, np.ndarray | None, str | None]] = []
    for upload in files:
        name = upload.filename or "(이름 없음)"
        data = await upload.read()
        if not data:
            items.append((name, None, "빈 파일이다"))
            continue
        items.append((name, _decode(data), "이미지를 디코드할 수 없다. 지원하는 형식인지 확인한다."))

    return await _respond(items, tone, overrides, detail, include_cells)


@app.post(
    "/read/image",
    summary="판독 결과 이미지",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "PNG 이미지"}},
)
async def read_image(
    file: Annotated[UploadFile, File(description="패드가 찍힌 이미지 한 장")],
    tone: Annotated[str, Query(description="white = 백색 바탕/흑색 인쇄")] = "white",
    kind: Annotated[
        str,
        Query(description="overlay = 격자·측정 영역·오염도를 겹쳐 그린 것, rectified = 정면으로 펴기만 한 것"),
    ] = "overlay",
    config: Annotated[
        str,
        Form(
            description=(
                "설정 일부 덮어쓰기(JSON 객체). 비워 두면 서버 설정을 그대로 쓴다. "
                f"예: {CONFIG_EXAMPLE}"
            ),
            examples=[""],
        ),
    ] = "",
) -> Response:
    """무엇을 어디서 쟀는지 눈으로 확인하는 용도. PNG 를 그대로 돌려준다.

    스코어가 이상할 때 이 이미지를 보면 원인이 대개 드러난다 — 패드를 제대로
    잡았는지, 회전이 맞는지(빨간 사각형이 비어 있어야 할 모서리), 격자가
    측정 영역에만 놓였는지, 어느 구획이 왜 빠졌는지.
    """
    if kind not in ("overlay", "rectified"):
        raise HTTPException(400, f"kind 는 overlay 또는 rectified 여야 한다: {kind!r}")

    overrides = _parse_overrides(config)
    image = _decode(await file.read())
    if image is None:
        raise HTTPException(400, "이미지를 디코드할 수 없다. 지원하는 형식인지 확인한다.")

    result = await run_in_threadpool(_read_one_visual, image, tone, overrides)
    if not result.success:
        raise HTTPException(
            422,
            f"판독하지 못해 이미지를 만들 수 없다: "
            f"{FAILURE_LABELS.get(result.failure_reason.value if result.failure_reason else '', '알 수 없음')}"
            f" ({result.failure_detail})",
        )

    frame = result.overlay if kind == "overlay" else result.rectified
    if frame is None:
        raise HTTPException(500, f"{kind} 이미지를 만들지 못했다")

    ok, buffer = cv2.imencode(".png", frame)
    if not ok:
        raise HTTPException(500, "PNG 인코딩에 실패했다")

    return Response(content=buffer.tobytes(), media_type="image/png")


@app.post("/read/path", response_model=BatchResponse, summary="판독 (서버 경로)")
async def read_path(body: ReadPathRequest) -> BatchResponse:
    """서버에 이미 있는 이미지를 경로로 지정해 판독한다.

    같은 이미지·같은 설정이면 ``/read`` 와 같은 값이 나온다.
    """
    _check_batch_size(len(body.paths))

    items: list[tuple[str, np.ndarray | None, str | None]] = [
        (path, cv2.imread(path, cv2.IMREAD_COLOR), f"이미지를 읽을 수 없다: {path}")
        for path in body.paths
    ]
    return await _respond(
        items, body.tone, body.config or {}, body.detail, body.include_cells
    )
