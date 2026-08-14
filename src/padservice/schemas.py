"""응답 스키마.

판독 결과를 그대로 미러하되, **기본 응답은 짧게** 유지한다. 88개 구획과
진단값을 한꺼번에 쏟아내면 정작 봐야 할 분진 스코어가 묻힌다.

    기본            핵심만. 성공 여부, 스코어, 산포, ID
    detail=true     품질 게이트와 정규화 진단값
    include_cells   구획별 값 88개

코어 모듈이 pydantic 을 알 필요가 없도록 변환은 여기서만 한다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 요청
# ---------------------------------------------------------------------------


class ReadPathRequest(BaseModel):
    """서버에 있는 이미지를 경로로 지정해 판독하는 요청.

    설정을 쿼리 문자열이 아니라 본문의 객체로 받는다. 업로드 엔드포인트는
    multipart 라 설정을 폼 필드로 받는데, 여기까지 쿼리로 두면 폼으로 보낸
    설정이 조용히 무시되고 기본값으로 읽히는 사고가 난다. 판독 결과가
    달라지는데 아무 오류도 나지 않는 것이 가장 나쁜 형태다.
    """

    paths: list[str] = Field(
        description="서버에서 접근 가능한 이미지 경로. 여러 개를 한 번에 넣을 수 있다.",
        min_length=1,
    )
    tone: str = Field(default="white", description="white = 백색 바탕/흑색 인쇄")
    detail: bool = Field(default=False, description="품질·정규화 진단값을 포함할지")
    include_cells: bool = Field(default=False, description="구획별 값을 포함할지")
    config: dict[str, Any] | None = Field(
        default=None,
        description="설정 일부 덮어쓰기. 비워 두면 서버 설정을 그대로 쓴다.",
    )

    model_config = {
        # 문서 UI 가 보여줄 기본 예시. 이게 없으면 paths 에 "string" 이 들어간
        # 요청이 만들어져 곧바로 실패한다.
        "json_schema_extra": {
            "examples": [
                {
                    "paths": ["/data/white_cov00.png", "/data/white_cov20.png"],
                    "tone": "white",
                    "detail": False,
                    "include_cells": False,
                    "config": {"spec": "v2_protected"},
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# 응답 조각
# ---------------------------------------------------------------------------


class DispersionModel(BaseModel):
    """구획 값이 얼마나 흩어져 있는지."""

    stdev: float | None = None
    iqr: float | None = None
    p90_minus_p50: float | None = Field(
        default=None,
        description="국소 뭉침 지표. 몇 칸만 튀면 IQR 보다 먼저 벌어진다.",
    )


class QualityModel(BaseModel):
    edge_rise_ratio: float | None = Field(
        default=None, description="흐림 정도. 작을수록 선명하다."
    )
    tenengrad: float | None = None
    saturated_bright_ratio: float | None = None
    saturated_dark_ratio: float | None = None
    tilt_deg: float | None = Field(default=None, description="추정 촬영 각도")
    pad_size_px: float | None = None
    anchor_contrast: float | None = None


class NormalizationModel(BaseModel):
    method: str
    anchor_black: float | None = None
    anchor_white: float | None = None
    anchor_black_mad: float | None = None
    anchor_white_mad: float | None = None
    plane_residual_rms: float | None = Field(
        default=None, description="조명 추정 잔차. 크면 기울기 추정을 믿기 어렵다."
    )
    plane_condition_number: float | None = None
    plane_gradient: list[float] | None = None


class CellModel(BaseModel):
    row: int
    col: int
    value: float | None
    reflectance: float | None
    chroma_norm: float | None
    chroma_abs: float | None
    saturated_ratio: float | None
    valid_pixel_ratio: float
    excluded: str | None


class LineContrastModel(BaseModel):
    index: int
    thickness_px: float | None
    contrast: float | None
    line_level: float | None
    gap_level: float | None


# ---------------------------------------------------------------------------
# 응답
# ---------------------------------------------------------------------------


class ReadResult(BaseModel):
    """이미지 한 장의 판독 결과.

    판독 불가도 오류가 아니다. 요청 자체는 정상이었고 이미지가 기준에 못
    미친 것이므로, 그 구분을 ``success`` 로 표현한다.
    """

    file: str = Field(description="어느 이미지의 결과인지")
    success: bool
    summary: str = Field(description="사람이 읽는 한 줄 요약")

    dust_score: float | None = Field(default=None, description="분진 오염도. 클수록 심하다.")
    score_statistic: str | None = None
    dispersion: DispersionModel = DispersionModel()

    target_id: str | None = None
    target_id_status: str | None = None
    target_id_confidence: float | None = None

    failure_reason: str | None = None
    failure_detail: str | None = None

    pad_tone: str | None = None
    spec_name: str | None = None
    rotation_deg: int | None = None
    grid_shape: list[int] | None = None
    excluded_count: int = 0
    excluded_by_reason: dict[str, int] = {}
    elapsed_ms: float | None = None

    # detail=true 일 때만
    quality: QualityModel | None = None
    normalization: NormalizationModel | None = None
    line_contrasts: list[LineContrastModel] | None = None
    corners: list[list[float]] | None = None
    rotation_margin: float | None = None

    # include_cells=true 일 때만
    cells: list[CellModel] | None = None


class BatchResponse(BaseModel):
    """판독 응답. 한 장을 보내도 여러 장을 보내도 같은 형태다."""

    summary: str = Field(description="전체를 한 줄로. 먼저 이것만 봐도 된다.")
    count: int
    succeeded: int
    results: list[ReadResult]

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "2장 모두 판독 성공 · 분진 0.001 ~ 0.198 · 0.8초",
                    "count": 2,
                    "succeeded": 2,
                    "results": [
                        {
                            "file": "white_cov00.png",
                            "success": True,
                            "summary": "판독 성공 · 분진 0.001 (p90) · 산포 0.000 · 제외 0/88칸 · ID 1078 · 402ms",
                            "dust_score": 0.0006,
                            "score_statistic": "p90",
                            "dispersion": {
                                "stdev": 0.0003,
                                "iqr": 0.0004,
                                "p90_minus_p50": 0.0004,
                            },
                            "target_id": "1078",
                            "target_id_status": "ok",
                            "target_id_confidence": 0.912,
                            "pad_tone": "white",
                            "spec_name": "v2_protected",
                            "rotation_deg": 0,
                            "grid_shape": [8, 11],
                            "excluded_count": 0,
                            "elapsed_ms": 402.1,
                        }
                    ],
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# 변환
# ---------------------------------------------------------------------------

FAILURE_LABELS: dict[str, str] = {
    "pad_not_found": "패드를 찾지 못함",
    "rotation_ambiguous": "회전 방향을 확정하지 못함",
    "quality_sharpness": "선명도 미달",
    "quality_saturation": "밝기 포화 과다",
    "quality_angle": "촬영 각도 초과",
    "quality_pad_size": "패드가 너무 작게 찍힘",
    "quality_anchor_contrast": "조도 기준 대비 부족",
    "no_valid_cells": "측정 가능한 구획 없음",
    "invalid_image": "이미지를 읽을 수 없음",
}


def _r(value: Any, digits: int = 4) -> Any:
    """소수 자리를 잘라 읽을 수 있게 만든다.

    ``0.19801980257034302`` 같은 자리수는 눈으로 읽을 수 없고, 그 끝자리는
    측정 잡음보다 훨씬 작아 아무 의미도 없다. 분진 스코어의 실제 재현
    편차가 0.001 수준이므로 소수 넷째 자리면 충분히 남는다.
    """
    return None if value is None else round(float(value), digits)


def _round_map(values: dict[str, Any] | None, digits: int, **overrides: int) -> dict[str, Any]:
    """사전의 실수 값을 자리수 맞춰 반올림한다. 항목별로 자리수를 달리 줄 수 있다."""
    if not values:
        return {}
    out: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            out[key] = value
        else:
            out[key] = _r(value, overrides.get(key, digits))
    return out


def build_summary(payload: dict[str, Any]) -> str:
    """한 장의 결과를 한 줄로 요약한다.

    실패했으면 왜 실패했는지가, 성공했으면 스코어와 산포가 먼저 보이게 한다.
    """
    elapsed = payload.get("elapsed_ms")
    tail = f" · {elapsed:.0f}ms" if elapsed is not None else ""

    if not payload.get("success"):
        reason = payload.get("failure_reason") or "알 수 없는 사유"
        label = FAILURE_LABELS.get(reason, reason)
        detail = payload.get("failure_detail")
        extra = f" ({detail})" if detail else ""
        return f"판독 불가 · {label}{extra}{tail}"

    parts = ["판독 성공"]

    score = payload.get("dust_score")
    if score is not None:
        parts.append(f"분진 {score:.3f} ({payload.get('score_statistic')})")

    spread = (payload.get("dispersion") or {}).get("p90_minus_p50")
    if spread is not None:
        parts.append(f"산포 {spread:.3f}")

    grid = payload.get("grid_shape")
    total = grid[0] * grid[1] if grid else None
    if total:
        parts.append(f"제외 {payload.get('excluded_count', 0)}/{total}칸")

    status = payload.get("target_id_status")
    if status == "ok":
        parts.append(f"ID {payload.get('target_id')}")
    elif status == "failed":
        parts.append("ID 판독 실패")

    return " · ".join(parts) + tail


def build_batch_summary(results: list[ReadResult], elapsed_sec: float) -> str:
    """여러 장을 한 줄로 요약한다.

    한 장뿐이면 그 한 장의 요약을 그대로 쓴다. 굳이 '1장 중 1장' 이라고
    말할 이유가 없다.
    """
    if len(results) == 1:
        return results[0].summary

    ok = [r for r in results if r.success]
    if len(ok) == len(results):
        head = f"{len(results)}장 모두 판독 성공"
    else:
        failed: dict[str, int] = {}
        for result in results:
            if not result.success:
                label = FAILURE_LABELS.get(
                    result.failure_reason or "", result.failure_reason or "알 수 없음"
                )
                failed[label] = failed.get(label, 0) + 1
        breakdown = ", ".join(f"{label} {count}" for label, count in failed.items())
        head = f"{len(results)}장 중 {len(ok)}장 성공, {len(results) - len(ok)}장 판독 불가 ({breakdown})"

    parts = [head]
    scores = [r.dust_score for r in ok if r.dust_score is not None]
    if scores:
        if len(scores) == 1:
            parts.append(f"분진 {scores[0]:.3f}")
        else:
            parts.append(f"분진 {min(scores):.3f} ~ {max(scores):.3f}")
    parts.append(f"{elapsed_sec:.1f}초")
    return " · ".join(parts)


def to_result(
    name: str, payload: dict[str, Any], *, detail: bool, include_cells: bool
) -> ReadResult:
    """판독 결과 사전을 응답 모델로. 요청한 부분만 채운다."""
    result = ReadResult(
        file=name,
        success=payload["success"],
        summary=build_summary(payload),
        dust_score=_r(payload.get("dust_score")),
        score_statistic=payload.get("score_statistic"),
        dispersion=DispersionModel(**_round_map(payload.get("dispersion"), 4)),
        target_id=payload.get("target_id"),
        target_id_status=payload.get("target_id_status"),
        target_id_confidence=_r(payload.get("target_id_confidence"), 3),
        failure_reason=payload.get("failure_reason"),
        failure_detail=payload.get("failure_detail"),
        pad_tone=payload.get("pad_tone"),
        spec_name=payload.get("spec_name"),
        rotation_deg=payload.get("rotation_deg"),
        grid_shape=payload.get("grid_shape"),
        excluded_count=payload.get("excluded_count", 0),
        excluded_by_reason=payload.get("excluded_by_reason") or {},
        elapsed_ms=_r(payload.get("elapsed_ms"), 1),
    )

    if detail:
        # 밝기 카운트나 픽셀 크기는 소수점이 의미 없으므로 자리수를 줄인다.
        result.quality = QualityModel(
            **_round_map(payload.get("quality"), 4, tenengrad=1, pad_size_px=1, anchor_contrast=1)
        )
        normalization = payload.get("normalization")
        if normalization:
            rounded = _round_map(
                normalization, 4,
                anchor_black=1, anchor_white=1,
                anchor_black_mad=1, anchor_white_mad=1,
                plane_condition_number=2,
            )
            gradient = normalization.get("plane_gradient")
            rounded["plane_gradient"] = (
                None if gradient is None else [_r(v) for v in gradient]
            )
            result.normalization = NormalizationModel(**rounded)
        result.line_contrasts = [
            LineContrastModel(**_round_map(c, 4, thickness_px=1))
            for c in payload.get("line_contrasts") or []
        ]
        corners = payload.get("corners")
        result.corners = (
            None if corners is None else [[_r(v, 1) for v in point] for point in corners]
        )
        result.rotation_margin = _r(payload.get("rotation_margin"), 3)

    if include_cells:
        result.cells = [CellModel(**_round_map(c, 4)) for c in payload.get("cells") or []]

    return result
