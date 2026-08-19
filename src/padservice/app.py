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
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.openapi.utils import get_openapi

from padreader.config import Config, load_config, resolve_config_path
from padreader.pipeline import read_pads
from padreader.spec import SPECS

from .schemas import ImageLinks, ReadPathRequest, ReadResponse, to_response

app = FastAPI(title="참조 패드 판독 서비스", version="0.2.0")

# 기동 시 한 번만 읽는다. 이후로는 읽기 전용이며, 요청별 오버라이드는
# 원본을 건드리지 않고 새 객체를 만든다.
_CONFIG_PATH = resolve_config_path()
_BASE_CONFIG: Config = load_config()

CONFIG_EXAMPLE = '{"dust": {"depth_threshold": 0.08}}'
"""문서에 보여줄 오버라이드 예시. 폼 필드의 기본값과 함께 쓴다."""


def _mark_binary(node: Any) -> None:
    """파일 필드에 ``format: binary`` 를 같이 달아 준다.

    FastAPI 는 OpenAPI 3.1 로 문서를 내보내고, 거기서 파일은
    ``contentMediaType`` 으로 표시된다. Swagger UI 는 필드 하나짜리 파일은 그걸
    알아보지만 **파일 목록은 못 알아본다.** 그래서 기준 이미지 칸이 파일 선택
    버튼이 아니라 빈 글상자로 뜨고, 그 안에 무작위 바이너리 문자열이 예시로
    찍힌다.

    3.0 시절 표기인 ``format: binary`` 를 함께 달면 Swagger UI 가 파일 여러 개를
    고르는 칸으로 그린다. 3.1 에서도 ``format`` 은 여전히 허용되므로 문서가
    깨지지 않는다.
    """
    if isinstance(node, dict):
        if node.get("contentMediaType") == "application/octet-stream":
            node["format"] = "binary"
        for value in node.values():
            _mark_binary(value)
    elif isinstance(node, list):
        for value in node:
            _mark_binary(value)


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title, version=app.version, routes=app.routes
    )
    _mark_binary(schema.get("components", {}))
    app.openapi_schema = schema
    return schema


# ---------------------------------------------------------------------------
# 판독 결과 이미지 임시 보관
# ---------------------------------------------------------------------------

IMAGE_CACHE_SIZE = 64
"""동시에 들고 있을 판독 건수. 넘으면 오래된 것부터 버린다."""

IMAGE_CACHE_TTL_SEC = 1800
"""보관 시간. 눈으로 확인하는 용도라 30분이면 넉넉하다."""

IMAGE_KINDS = ("baseline_rectified", "rectified", "distribution")

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


def _links(request: Request, pad) -> ImageLinks | None:
    """패드 하나의 결과 이미지를 보관하고 주소를 만든다."""
    frames: dict[str, bytes] = {}
    for kind, frame in (
        ("baseline_rectified", pad.baseline_rectified),
        ("rectified", pad.rectified),
        ("distribution", pad.distribution),
    ):
        if frame is not None:
            encoded = _encode_png(frame)
            if encoded:
                frames[kind] = encoded
    if not frames:
        return None

    token = _store_images(frames)
    base = str(request.base_url).rstrip("/")
    return ImageLinks(
        baseline_rectified=f"{base}/images/{token}/baseline_rectified.png",
        rectified=f"{base}/images/{token}/rectified.png",
        distribution=f"{base}/images/{token}/distribution.png",
    )


def _all_links(request: Request, batch, visualize: bool):
    """패드 순서와 같은 이미지 주소 목록. 패드마다 따로 보관한다."""
    if not visualize:
        return None
    return [_links(request, pad) for pad in batch.pads]


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
    baseline: list[np.ndarray],
    tone: str,
    overrides: dict[str, Any],
    visualize: bool,
):
    try:
        return read_pads(
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
    file: Annotated[UploadFile, File(description="판독 이미지. 순회 때 찍은 사진")],
    baseline: Annotated[
        list[UploadFile],
        File(
            description=(
                "기준 이미지. 부착 직후 깨끗할 때 찍은 사진이다. **여러 장을 "
                "같은 이름으로 올릴 수 있다** — 기준은 사진이 아니라 패드 단위라, "
                "한 화면에 여러 패드가 찍히면 각자의 기준이 필요하다. "
                "그 자리에서 보이는 것보다 넉넉히 보내도 되고, 짝이 없는 기준은 "
                "쓰이지 않는다."
            )
        ),
    ],
    tone: Annotated[str, Form(description="white = 백색 바탕/흑색 인쇄")] = "white",
    visualize: Annotated[
        bool,
        Form(
            description=(
                "응답의 images 에 판독 결과 이미지 주소를 담을지. "
                "끄면 이미지를 만들지 않아 조금 빨라진다."
            )
        ),
    ] = True,
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
    """사진을 올려 판독한다.

    응답 맨 위의 ``summary`` 한 줄만 봐도 결과를 알 수 있다.

    입력은 전부 본문 한 군데로 받는다. 주소 뒤에 붙는 값은 없다 — 어떤 값을
    어디에 넣어야 하는지 갈리면, 잘못 넣어도 오류 없이 기본값으로 도는 일이
    생긴다.
    """
    overrides = _parse_overrides(config)
    reading = _decode_upload(await file.read(), "판독 이미지")
    baselines = [
        _decode_upload(await item.read(), f"기준 이미지 {index + 1}번째")
        for index, item in enumerate(baseline)
    ]
    if not baselines:
        raise HTTPException(400, "기준 이미지가 없다")

    # OpenCV 연산이 GIL 을 오래 잡는 구간이 있어 이벤트 루프에서 직접 돌리지
    # 않는다.
    result = await run_in_threadpool(
        _run, reading, baselines, tone, overrides, visualize
    )
    return to_response(
        result.to_dict(include_blobs=False),
        images=_all_links(request, result, visualize),
    )


@app.post("/read/path", response_model=ReadResponse, summary="판독 (서버 경로)")
async def read_path(request: Request, body: ReadPathRequest) -> ReadResponse:
    """서버에 이미 있는 사진을 경로로 지정해 판독한다.

    같은 사진·같은 설정이면 ``/read`` 와 같은 값이 나온다.
    """
    reading = cv2.imread(body.path, cv2.IMREAD_COLOR)
    if reading is None:
        raise HTTPException(404, f"판독 이미지를 읽을 수 없다: {body.path}")

    paths = body.baseline_path
    paths = [paths] if isinstance(paths, str) else list(paths)
    if not paths:
        raise HTTPException(400, "기준 이미지 경로가 없다")

    baselines = []
    for path in paths:
        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(404, f"기준 이미지를 읽을 수 없다: {path}")
        baselines.append(image)

    result = await run_in_threadpool(
        _run, reading, baselines, body.tone, body.config or {}, body.visualize
    )
    return to_response(
        result.to_dict(include_blobs=False),
        images=_all_links(request, result, body.visualize),
    )


@app.get(
    "/images/{token}/{kind}.png",
    summary="판독 결과 이미지 보기",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}, "description": "PNG 이미지"}},
)
def get_image(token: str, kind: str) -> Response:
    """``/read`` 가 돌려준 이미지 주소. 브라우저에 붙여 넣으면 바로 보인다.

    ``baseline_rectified`` 와 ``rectified`` 는 각각 기준 사진과 판독 사진을
    정면으로 펴기만 한 것이고, ``distribution`` 은 그 둘의 차이를 색으로
    그린 것이다.

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


app.openapi = custom_openapi  # type: ignore[method-assign]
