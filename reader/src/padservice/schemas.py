"""응답 스키마.

요구사항 정의서에 적힌 것만 담는다. 중간 계산값을 같이 뱉으면 정작 봐야 할
스코어가 묻힌다.

    성공 여부와 실패 사유
    두 축 스코어와 combined 지표 (각각 0-1)
    제외 사유별 픽셀 수
    품질 게이트 산출값 네 가지
    판독된 POINT_ID (패드가 붙어 있는 관측 개소 번호)

코어 모듈이 pydantic 을 알 필요가 없도록 변환은 여기서만 한다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReadPathRequest(BaseModel):
    """서버에 있는 사진을 경로로 지정해 판독하는 요청."""

    path: str = Field(description="판독 이미지 경로. 순회 때 찍은 사진")
    baseline_path: str | list[str] = Field(
        description=(
            "기준 이미지 경로. 한 개 또는 목록. 기준은 사진이 아니라 패드 "
            "단위라, 한 화면에 여러 패드가 찍히면 각자의 기준이 필요하다. "
            "짝이 없는 기준은 쓰이지 않으므로 넉넉히 보내도 된다."
        )
    )
    tone: str = Field(default="white", description="white = 백색 바탕/흑색 인쇄")
    visualize: bool = Field(
        default=True,
        description=(
            "판독 결과 이미지 주소를 함께 받을지. "
            "끄면 이미지를 만들지 않아 조금 빨라진다."
        ),
    )
    expected_point_ids: list[str] | None = Field(
        default=None,
        description=(
            "이 사진에 있을 개소 번호 목록. 주면 **닫힌 판독**을 한다 - 숫자를 "
            "0~9 중에서 자유롭게 읽는 대신 이 후보 안에서 배정한다. 네 자리를 "
            "자유롭게 읽으면 경우의 수가 1만 개라 한 자리만 흔들려도 없는 번호가 "
            "나오는데, 후보를 주면 그런 답이 아예 나올 수 없다. 실촬영 10건에서 "
            "열린 판독 7건, 닫힌 판독 10건이 맞았다."
        ),
    )
    config: dict[str, Any] | None = Field(
        default=None,
        description="설정 일부 덮어쓰기. 비워 두면 서버 설정을 그대로 쓴다.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "path": "/data/patrol.png",
                    "baseline_path": ["/data/clean_1078.png", "/data/clean_1079.png"],
                    "tone": "white",
                    "visualize": True,
                }
            ]
        }
    }


class ImageLinks(BaseModel):
    """결과 이미지 주소. 브라우저에 그대로 붙여 넣으면 보인다."""

    baseline_rectified: str = Field(description="기준 이미지의 정합 사진")
    rectified: str = Field(description="판독 이미지의 정합 사진")
    distribution: str = Field(description="기준 대비 오염도 분포 사진")


class ScoresModel(BaseModel):
    """두 축의 스코어와 combined 지표. 각각 0-1."""

    uniform: float | None = Field(default=None, description="고르게 오염된 정도")
    localized: float | None = Field(default=None, description="한 군데가 심하게 오염된 정도")
    combined: float | None = Field(default=None, description="두 축을 합친 값")


class QualityModel(BaseModel):
    """품질 게이트 산출값."""

    sharpness: float | None = Field(default=None, description="선명도. 작을수록 선명하다")
    saturated_ratio: float | None = Field(default=None, description="포화 픽셀 비율")
    pad_size_px: float | None = Field(default=None, description="패드 영역 픽셀 크기")
    pad_size_diff_ratio: float | None = Field(
        default=None, description="기준 이미지와의 패드 크기 차이 비율"
    )


class OpticalDensityModel(BaseModel):
    """시험 지표. 광학밀도 기반 오염도 - 어떤 판정에도 쓰지 않는다. 표시 전용."""

    od_sum: float | None = Field(default=None, description="노출 영역 전체의 log(기준/판독) 합. 임계값 없음")
    od_mean: float | None = Field(default=None, description="od_sum / 노출 영역 픽셀 수")
    od_score: float | None = Field(default=None, description="sqrt(od_mean), 음수면 0")
    roi_mean_reading: float | None = Field(default=None, description="노출 영역의 판독 사진 평균 밝기(정규화)")
    roi_mean_baseline: float | None = Field(default=None, description="노출 영역의 기준 사진 평균 밝기(정규화)")
    pad_scale: float | None = Field(default=None, description="정합 시 원본 패드 크기 대비 확대 배율")


class PadResult(BaseModel):
    """패드 하나의 판독 결과."""

    success: bool
    summary: str = Field(description="이 패드 한 줄 요약")
    point_id_raw: str | None = Field(
        default=None,
        description=(
            "숫자를 그대로 읽은 값. 후보를 받아 배정했으면 point_id 와 다를 수 "
            "있다. 오독이 몇 건이었는지 나중에 세려면 배정 결과와 실제로 읽은 "
            "값이 따로 있어야 한다."
        ),
    )
    point_id: str | None = Field(
        default=None,
        description=(
            "패드에 인쇄된 관측 개소 번호. 패드가 붙어 있는 물리적 개소를 "
            "가리킨다. AMR 쪽 TARGET_ID(한 웨이포인트에서 PTZ 프리셋을 잡고 "
            "찍은 사진 한 장)와 같은 것이 아니며, 한 장에 패드가 여러 개 "
            "찍히므로 촬영 단위와 개소는 1:N 이다."
        ),
    )

    scores: ScoresModel = ScoresModel()
    quality: QualityModel = QualityModel()
    optical_density: OpticalDensityModel = OpticalDensityModel()
    excluded_px: dict[str, int] = Field(
        default={}, description="분진 판정에서 빠진 픽셀 수. 사유별"
    )

    failure_reason: str | None = None
    failure_detail: str | None = None

    images: ImageLinks | None = Field(
        default=None, description="결과 이미지 주소. visualize 를 끄면 비어 있다"
    )


class ReadResponse(BaseModel):
    """판독 결과. 사진에서 찾은 패드마다 한 건씩 ``pads`` 에 담는다.

    한 화면에 패드가 여러 개 찍히는 일이 현장에서 실제로 일어난다. 가장 크게
    찍힌 하나만 돌려주면 나머지는 조용히 사라지고, 어느 것이 돌아왔는지도 알
    수 없다. 하나만 찍힌 흔한 경우에도 ``pads`` 는 항상 목록이라, 받는 쪽이
    경우를 나눌 필요가 없다.

    ``success`` 는 **하나라도 판독됐는가** 다. 개별 패드의 성패는 각 항목의
    ``success`` 를 본다.

    판독 불가도 HTTP 200 으로 돌아온다. 요청 자체는 정상이었고 사진이 기준에
    못 미친 것이므로, 그 구분을 상태 코드가 아니라 ``success`` 로 표현한다.
    """

    success: bool
    summary: str = Field(description="사람이 읽는 한 줄 요약")
    pads: list[PadResult] = Field(default=[], description="찾은 패드마다 한 건")

    failure_reason: str | None = Field(
        default=None, description="패드를 하나도 못 찾았거나 사진 자체를 못 읽었을 때만"
    )
    failure_detail: str | None = None
    elapsed_ms: float | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "summary": "패드 2개 판독 · 1078 total 0.307 · 1079 total 0.021 · 812ms",
                    "pads": [
                        {
                            "success": True,
                            "summary": "판독 성공 · combined 0.307 (uniform 0.036 · localized 0.305) · point_id 1078",
                            "point_id": "1078",
                            "scores": {"uniform": 0.036, "localized": 0.305, "combined": 0.307},
                            "quality": {
                                "sharpness": 0.0029,
                                "saturated_ratio": 0.0,
                                "pad_size_px": 616.1,
                                "pad_size_diff_ratio": 0.004,
                            },
                            "excluded_px": {"print_element": 0, "saturated": 0},
                        }
                    ],
                    "elapsed_ms": 812.0,
                }
            ]
        }
    }


FAILURE_LABELS: dict[str, str] = {
    "pad_not_found": "패드를 찾지 못함",
    "rotation_ambiguous": "회전 방향을 확정하지 못함",
    "quality_sharpness": "선명도 미달",
    "quality_saturation": "밝기 포화 과다",
    "quality_pad_size": "패드가 너무 작게 찍힘",
    "normalization_failed": "테두리를 조명 기준으로 삼을 수 없음",
    "no_measurable_area": "제외 후 측정할 영역이 남지 않음",
    "invalid_image": "이미지를 읽을 수 없음",
    "baseline_unreadable": "기준 이미지를 판독하지 못함",
    "pad_size_mismatch": "기준 이미지와 패드 크기가 크게 다름",
    "baseline_pad_missing": "기준 이미지에 같은 번호의 패드가 없음",
}


def _r(value: Any, digits: int = 3) -> Any:
    """소수 자리를 잘라 읽을 수 있게 만든다."""
    return None if value is None else round(float(value), digits)


def pad_summary(pad: dict[str, Any]) -> str:
    """패드 하나를 한 줄로. 실패했으면 왜인지가, 성공했으면 스코어가 먼저 보이게 한다."""
    if not pad.get("success"):
        reason = pad.get("failure_reason") or "알 수 없는 사유"
        label = FAILURE_LABELS.get(reason, reason)
        detail = pad.get("failure_detail")
        return f"판독 불가 · {label}{f' ({detail})' if detail else ''}"

    scores = pad.get("scores") or {}
    parts = ["판독 성공"]
    if scores.get("combined") is not None:
        parts.append(
            f"combined {scores['combined']:.3f}"
            f" (uniform {scores.get('uniform') or 0:.3f} · localized {scores.get('localized') or 0:.3f})"
        )
    if pad.get("point_id"):
        parts.append(f"point_id {pad['point_id']}")
    return " · ".join(parts)


def build_summary(payload: dict[str, Any]) -> str:
    """사진 한 쌍 전체를 한 줄로.

    패드가 하나뿐이면 그 패드의 요약을 그대로 쓴다 — 흔한 경우에 줄이 길어지지
    않게 하기 위해서다. 여러 개면 번호와 total 만 늘어놓는다.
    """
    elapsed = payload.get("elapsed_ms")
    tail = f" · {elapsed:.0f}ms" if elapsed is not None else ""
    pads = payload.get("pads") or []

    if not payload.get("success") and not pads:
        reason = payload.get("failure_reason") or "알 수 없는 사유"
        label = FAILURE_LABELS.get(reason, reason)
        detail = payload.get("failure_detail")
        return f"판독 불가 · {label}{f' ({detail})' if detail else ''}{tail}"

    if len(pads) == 1:
        return pad_summary(pads[0]) + tail

    parts = []
    for pad in pads:
        name = pad.get("point_id") or "번호 미상"
        if pad.get("success"):
            parts.append(f"{name} total {(pad.get('scores') or {}).get('combined', 0):.3f}")
        else:
            reason = pad.get("failure_reason") or ""
            parts.append(f"{name} {FAILURE_LABELS.get(reason, reason)}")
    return f"패드 {len(pads)}개 판독 · " + " · ".join(parts) + tail


def to_pad(pad: dict[str, Any], images: ImageLinks | None = None) -> PadResult:
    """패드 하나의 판독 결과를 응답 모델로."""
    scores = pad.get("scores") or {}
    quality = pad.get("quality") or {}
    od = pad.get("optical_density") or {}
    return PadResult(
        success=pad["success"],
        summary=pad_summary(pad),
        point_id=pad.get("point_id"),
        point_id_raw=pad.get("point_id_raw"),
        scores=ScoresModel(
            uniform=_r(scores.get("uniform")),
            localized=_r(scores.get("localized")),
            combined=_r(scores.get("combined")),
        ),
        quality=QualityModel(
            sharpness=_r(quality.get("edge_rise_ratio"), 4),
            saturated_ratio=_r(quality.get("saturated_bright_ratio"), 4),
            pad_size_px=_r(quality.get("pad_size_px"), 1),
            pad_size_diff_ratio=_r(pad.get("pad_size_diff_ratio"), 4),
        ),
        optical_density=OpticalDensityModel(
            od_sum=_r(od.get("od_sum"), 5),
            od_mean=_r(od.get("od_mean"), 6),
            od_score=_r(od.get("od_score"), 5),
            roi_mean_reading=_r(od.get("roi_mean_reading"), 4),
            roi_mean_baseline=_r(od.get("roi_mean_baseline"), 4),
            pad_scale=_r(od.get("pad_scale"), 3),
        ),
        excluded_px=pad.get("excluded_px") or {},
        failure_reason=pad.get("failure_reason"),
        failure_detail=pad.get("failure_detail"),
        images=images,
    )


def to_response(
    payload: dict[str, Any], *, images: list[ImageLinks | None] | None = None
) -> ReadResponse:
    """판독 결과 사전을 응답 모델로. ``images`` 는 패드 순서와 같은 목록이다."""
    pads = payload.get("pads") or []
    links = images or [None] * len(pads)
    return ReadResponse(
        success=payload["success"],
        summary=build_summary(payload),
        pads=[to_pad(pad, link) for pad, link in zip(pads, links)],
        failure_reason=payload.get("failure_reason"),
        failure_detail=payload.get("failure_detail"),
        elapsed_ms=_r(payload.get("elapsed_ms"), 1),
    )
