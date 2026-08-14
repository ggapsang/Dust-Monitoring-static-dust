"""판독 서비스.

``padreader`` 를 감싸는 얇은 어댑터다. 판독 로직은 여기 없다 — 이미지를
받아 넘기고 결과를 정리해 돌려줄 뿐이다.

설정은 기동 시 한 번 읽어 읽기 전용으로 쓰고, 요청별 오버라이드는 그때마다
새 설정 객체를 만든다. 그래서 어떤 요청도 다른 요청의 판독 결과를 바꾸지
못한다.

판독 결과 이미지만 서버에 잠깐 머문다. 본문에 base64 로 실으면 응답을 눈으로
읽을 수 없게 되므로 주소로 주고, 짧은 시간 동안만 들고 있다가 버린다.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Annotated, Any

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from padreader.config import Config, load_config, resolve_config_path
from padreader.pipeline import read_pad
from padreader.spec import SPECS

from .schemas import ImageLinks, ReadPathRequest, ReadResponse, to_response

app = FastAPI(title="참조 패드 판독 서비스", version="0.2.0")

# 기동 시 한 번만 읽는다. 이후로는 읽기 전용이며, 요청별 오버라이드는
# 원본을 건드리지 않고 새 객체를 만든다.
_CONFIG_PATH = resolve_config_path()
_BASE_CONFIG: Config = load_config()

CONFIG_EXAMPLE = '{"spec": "v2_protected", "grid": {"rows": 4, "cols": 4}}'
"""문서에 보여줄 오버라이드 예시. 폼 필드의 기본값과 함께 쓴다."""

# ---------------------------------------------------------------------------
# 판독 결과 이미지 임시 보관
# ---------------------------------------------------------------------------

IMAGE_CACHE_SIZE = 64
"""동시에 들고 있을 판독 건수. 넘으면 오래된 것부터 버린다."""

IMAGE_CACHE_TTL_SEC = 1800
"""보관 시간. 눈으로 확인하는 용도라 30분이면 넉넉하다."""

IMAGE_KINDS = ("overlay", "rectified")

_images: "OrderedDict[str, tuple[float, dict[str, bytes]]]" = OrderedDict()


def _encode_png(image: np.ndarray) -> bytes | None:
    ok, buffer = cv2.imencode(".png", image)
    return buffer.tobytes() if ok else None


def _store_images(frames: dict[str, bytes]) -> str:
    """이미지를 보관하고 토큰을 돌려준다.

    토큰은 이미지 내용의 해시다. 같은 입력에 같은 주소가 나오므로, 같은
    요청을 두 번 보내도 응답이 완전히 같고 보관본도 늘지 않는다.
    """
    digest = hashlib.sha256()
    for kind in IMAGE_KINDS:
        digest.update(frames.get(kind, b""))
    token = digest.hexdigest()[:16]

    now = time.monotonic()
    for key in [k for k, (expires, _) in _images.items() if expires <= now]:
        _images.pop(key, None)

    _images[token] = (now + IMAGE_CACHE_TTL_SEC, frames)
    _images.move_to_end(token)
    while len(_images) > IMAGE_CACHE_SIZE:
        _images.popitem(last=False)

    return token


def _links(request: Request, result) -> ImageLinks | None:
    """판독 결과의 이미지를 보관하고 주소를 만든다."""
    frames: dict[str, bytes] = {}
    for kind, frame in (("overlay", result.overlay), ("rectified", result.rectified)):
        if frame is not None:
            encoded = _encode_png(frame)
            if encoded:
                frames[kind] = encoded
    if not frames:
        return None

    token = _store_images(frames)
    base = str(request.base_url).rstrip("/")
    return ImageLinks(
        overlay=f"{base}/images/{token}/overlay.png",
        rectified=f"{base}/images/{token}/rectified.png",
    )


# ---------------------------------------------------------------------------
# 요청 처리
# ---------------------------------------------------------------------------


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


def _decode_upload(data: bytes, label: str) -> np.ndarray:
    if not data:
        raise HTTPException(400, f"{label}이 비어 있다")
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(400, f"{label}을 디코드할 수 없다. 지원하는 형식인지 확인한다.")
    return image


def _run(
    image: np.ndarray,
    baseline: np.ndarray,
    tone: str,
    overrides: dict[str, Any],
    visualize: bool,
):
    try:
        return read_pad(
            image,
            baseline,
            pad_tone=tone,
            config=_BASE_CONFIG,
            overrides=overrides,
            visualize=visualize,
        )
    except ValueError as exc:
        # 설정 오타나 잘못된 값은 요청 잘못이다.
        raise HTTPException(400, str(exc)) from None


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


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


@app.post("/read", response_model=ReadResponse, summary="판독 (이미지 업로드)")
async def read(
    request: Request,
    file: Annotated[UploadFile, File(description="판독 사진. 순회 때 찍은 것")],
    baseline: Annotated[
        UploadFile, File(description="기준 사진. 패드 부착 직후 깨끗할 때 찍은 것")
    ],
    tone: Annotated[str, Query(description="white = 백색 바탕/흑색 인쇄")] = "white",
    visualize: Annotated[
        bool, Query(description="켜면 응답의 images 에 판독 결과 이미지 주소가 들어온다")
    ] = False,
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
) -> ReadResponse:
    """기준 사진과 견주어 판독 사진의 오염량을 낸다.

    두 사진은 같은 관측 포인트에서 같은 카메라로 찍은 것이어야 한다.
    응답 맨 위의 ``summary`` 한 줄만 봐도 결과를 알 수 있다.
    """
    overrides = _parse_overrides(config)
    reading = _decode_upload(await file.read(), "판독 사진")
    baseline_image = _decode_upload(await baseline.read(), "기준 사진")

    # OpenCV 연산이 GIL 을 오래 잡는 구간이 있어 이벤트 루프에서 직접 돌리지
    # 않는다. 두 장을 처리하므로 1초 가까이 걸린다.
    result = await run_in_threadpool(
        _run, reading, baseline_image, tone, overrides, visualize
    )
    return to_response(
        result.to_dict(include_cells=include_cells),
        detail=detail,
        include_cells=include_cells,
        images=_links(request, result) if visualize else None,
    )


@app.post("/read/path", response_model=ReadResponse, summary="판독 (서버 경로)")
async def read_path(request: Request, body: ReadPathRequest) -> ReadResponse:
    """서버에 이미 있는 두 사진을 경로로 지정해 판독한다.

    같은 사진·같은 설정이면 ``/read`` 와 같은 값이 나온다.
    """
    reading = cv2.imread(body.path, cv2.IMREAD_COLOR)
    if reading is None:
        raise HTTPException(404, f"판독 사진을 읽을 수 없다: {body.path}")

    baseline = cv2.imread(body.baseline_path, cv2.IMREAD_COLOR)
    if baseline is None:
        raise HTTPException(404, f"기준 사진을 읽을 수 없다: {body.baseline_path}")

    result = await run_in_threadpool(
        _run, reading, baseline, body.tone, body.config or {}, body.visualize
    )
    return to_response(
        result.to_dict(include_cells=body.include_cells),
        detail=body.detail,
        include_cells=body.include_cells,
        images=_links(request, result) if body.visualize else None,
    )


@app.get(
    "/images/{token}/{kind}.png",
    summary="판독 결과 이미지 보기",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "PNG 이미지"}},
)
def get_image(token: str, kind: str) -> Response:
    """``/read`` 가 돌려준 이미지 주소. 브라우저에 붙여 넣으면 바로 보인다.

    ``overlay`` 는 격자와 측정 영역, 구획별 오염도를 겹쳐 그린 것이고,
    ``rectified`` 는 정면으로 펴기만 한 것이다.

    보관 시간이 지나면 사라진다. 판독을 다시 하면 같은 주소가 다시 생긴다 —
    주소가 이미지 내용의 해시이기 때문이다.
    """
    if kind not in IMAGE_KINDS:
        raise HTTPException(404, f"알 수 없는 이미지 종류: {kind} (가능: {', '.join(IMAGE_KINDS)})")

    entry = _images.get(token)
    if entry is None or entry[0] <= time.monotonic():
        _images.pop(token, None)
        raise HTTPException(
            404,
            "이미지가 없거나 보관 시간이 지났다. visualize=true 로 다시 판독하면 "
            "같은 주소가 다시 생긴다.",
        )

    frame = entry[1].get(kind)
    if frame is None:
        raise HTTPException(404, f"이 판독에는 {kind} 이미지가 없다")

    return Response(content=frame, media_type="image/png")
