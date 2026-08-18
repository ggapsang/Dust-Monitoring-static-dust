"""응답 스키마.

요구사항 정의서에 적힌 것만 담는다. 중간 계산값을 같이 뱉으면 정작 봐야 할
스코어가 묻힌다.

    성공 여부와 실패 사유
    두 축 스코어와 combined 지표 (각각 0-1)
    제외 사유별 픽셀 수
    품질 게이트 산출값 네 가지
    판독된 TARGET_ID

코어 모듈이 pydantic 을 알 필요가 없도록 변환은 여기서만 한다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReadPathRequest(BaseModel):
    """서버에 있는 사진을 경로로 지정해 판독하는 요청."""

    path: str = Field(description="판독 이미지 경로. 순회 때 찍은 사진")
    baseline_path: str = Field(
        description="기준 이미지 경로. 부착 직후 같은 위치·각도로 찍은 사진"
    )
    tone: str = Field(default="white", description="white = 백색 바탕/흑색 인쇄")
    visualize: bool = Field(
        default=True,
        description=(
            "판독 결과 이미지 주소를 함께 받을지. "
            "끄면 이미지를 만들지 않아 조금 빨라진다."
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
                    "baseline_path": "/data/clean.png",
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


class ReadResponse(BaseModel):
    """판독 결과.

    판독 불가도 HTTP 200 으로 돌아온다. 요청 자체는 정상이었고 사진이 기준에
    못 미친 것이므로, 그 구분을 상태 코드가 아니라 ``success`` 로 표현한다.
    """

    success: bool
    summary: str = Field(description="사람이 읽는 한 줄 요약")

    scores: ScoresModel = ScoresModel()
    quality: QualityModel = QualityModel()
    excluded_px: dict[str, int] = Field(
        default={}, description="분진 판정에서 빠진 픽셀 수. 사유별"
    )

    target_id: str | None = None

    failure_reason: str | None = None
    failure_detail: str | None = None

    images: ImageLinks | None = Field(
        default=None, description="결과 이미지 주소. visualize 를 끄면 비어 있다"
    )
    elapsed_ms: float | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "success": True,
                    "summary": "판독 성공 · combined 0.307 (uniform 0.036 · localized 0.305) · target_id 1078 · 386ms",
                    "scores": {"uniform": 0.036, "localized": 0.305, "combined": 0.307},
                    "quality": {
                        "sharpness": 0.0029,
                        "saturated_ratio": 0.0,
                        "pad_size_px": 616.1,
                        "pad_size_diff_ratio": 0.004,
                    },
                    "excluded_px": {"print_element": 0, "saturated": 0},
                    "target_id": "1078",
                    "failure_reason": None,
                    "failure_detail": None,
                    "elapsed_ms": 386.0,
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
}


def _r(value: Any, digits: int = 3) -> Any:
    """소수 자리를 잘라 읽을 수 있게 만든다."""
    return None if value is None else round(float(value), digits)


def build_summary(payload: dict[str, Any]) -> str:
    """결과를 한 줄로. 실패했으면 왜인지가, 성공했으면 스코어가 먼저 보이게 한다."""
    elapsed = payload.get("elapsed_ms")
    tail = f" · {elapsed:.0f}ms" if elapsed is not None else ""

    if not payload.get("success"):
        reason = payload.get("failure_reason") or "알 수 없는 사유"
        label = FAILURE_LABELS.get(reason, reason)
        detail = payload.get("failure_detail")
        return f"판독 불가 · {label}{f' ({detail})' if detail else ''}{tail}"

    scores = payload.get("scores") or {}
    parts = ["판독 성공"]
    if scores.get("combined") is not None:
        parts.append(
            f"combined {scores['combined']:.3f}"
            f" (uniform {scores.get('uniform') or 0:.3f} · localized {scores.get('localized') or 0:.3f})"
        )
    if payload.get("target_id"):
        parts.append(f"target_id {payload['target_id']}")
    return " · ".join(parts) + tail


def to_response(
    payload: dict[str, Any], *, images: ImageLinks | None = None
) -> ReadResponse:
    """판독 결과 사전을 응답 모델로."""
    scores = payload.get("scores") or {}
    quality = payload.get("quality") or {}

    return ReadResponse(
        success=payload["success"],
        summary=build_summary(payload),
        scores=ScoresModel(
            uniform=_r(scores.get("uniform")),
            localized=_r(scores.get("localized")),
            combined=_r(scores.get("combined")),
        ),
        quality=QualityModel(
            sharpness=_r(quality.get("edge_rise_ratio"), 4),
            saturated_ratio=_r(quality.get("saturated_bright_ratio"), 4),
            pad_size_px=_r(quality.get("pad_size_px"), 1),
            pad_size_diff_ratio=_r(payload.get("pad_size_diff_ratio"), 4),
        ),
        excluded_px=payload.get("excluded_px") or {},
        target_id=payload.get("target_id"),
        failure_reason=payload.get("failure_reason"),
        failure_detail=payload.get("failure_detail"),
        images=images,
        elapsed_ms=_r(payload.get("elapsed_ms"), 1),
    )
