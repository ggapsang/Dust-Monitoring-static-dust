"""판독 결과 객체.

스코어는 **기준 사진 대비 차이**다. 패드 부착 직후 깨끗할 때 찍은 사진과
이후 순회 때 찍은 사진을 같은 처리로 돌린 뒤, 칸별로 빼서 얻는다. 사진 한
장의 절대값만으로는 깨끗할 때의 값을 알 수 없어 오염 여부를 판단할 수 없다.

시계열 추세와 등급 판정은 여전히 상위 계층 몫이다.

``numpy`` 배열을 밖으로 흘리지 않도록 스칼라는 전부 ``float`` 로 변환해
담는다. ``to_dict()`` 는 그대로 JSON 직렬화 가능한 형태를 돌려준다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class FailureReason(str, Enum):
    """판독 불가 사유. 성공 시에는 ``None`` 이다."""

    PAD_NOT_FOUND = "pad_not_found"
    """이미지에서 패드 테두리를 찾지 못했다."""

    ROTATION_AMBIGUOUS = "rotation_ambiguous"
    """비어 있는 모서리를 확정할 수 없었다."""

    QUALITY_SHARPNESS = "quality_sharpness"
    QUALITY_SATURATION = "quality_saturation"
    QUALITY_ANGLE = "quality_angle"
    QUALITY_PAD_SIZE = "quality_pad_size"
    QUALITY_ANCHOR_CONTRAST = "quality_anchor_contrast"
    """앵커 간 밝기차가 너무 작아 정규화가 성립하지 않는다."""

    NO_VALID_CELLS = "no_valid_cells"
    """비분진 배제 후 남은 구획이 없다."""

    INVALID_IMAGE = "invalid_image"
    """이미지를 읽을 수 없거나 형식이 지원되지 않는다."""

    BASELINE_UNREADABLE = "baseline_unreadable"
    """기준 사진을 판독하지 못했다. 상세 사유는 ``failure_detail`` 에 담긴다."""

    NORMALIZATION_MISMATCH = "normalization_mismatch"
    """두 사진이 서로 다른 방식으로 정규화되어 뺄셈이 성립하지 않는다."""

    GRID_MISMATCH = "grid_mismatch"
    """기준 사진과 판독 사진의 격자가 어긋나 칸을 맞출 수 없다."""


class ExclusionReason(str, Enum):
    """구획이 측정에서 빠진 사유."""

    MASKED = "masked"
    """인쇄물·경계와 겹쳐 유효 픽셀이 부족하다."""

    CHROMA = "chroma"
    """채도가 임계를 넘어 분진이 아닌 변색(녹·유분·결로)으로 본다."""

    SATURATED = "saturated"
    """포화 화소 비율이 임계를 넘었다. 정반사로 본다."""


class TargetIdStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    """판독 실패. 패드 자체는 읽혔으므로 판독 불가 사유로 올리지 않는다."""

    DISABLED = "disabled"


def _f(value: Any) -> float | None:
    """numpy 스칼라를 포함한 값을 순수 float 로. NaN/None 은 None 으로."""
    if value is None:
        return None
    out = float(value)
    return None if np.isnan(out) else out


@dataclass
class QualityMetrics:
    """품질 게이트 산출값. 게이트 통과 여부와 무관하게 항상 채운다."""

    edge_rise_ratio: float | None = None
    """테두리 에지의 10-90% 상승 거리 ÷ 패드 픽셀 크기.

    **원본 이미지**에서 잰다. 정면 보정 후에는 warp 보간이 스케일을 선명도에
    섞어 넣어(확대하면 에지가 완만해지고 축소하면 서는) 측정이 촬영 거리에
    교란된다. 이 지표는 '에지가 패드 폭의 몇 %를 차지하는가' 이므로 정의상
    거리 무관이며, 작을수록 선명하다.
    """

    tenengrad: float | None = None
    """원본 테두리 영역의 Tenengrad. 실증에서 ``edge_rise_ratio`` 와 어느
    쪽이 실제 판독 실패와 더 잘 맞는지 비교하기 위해 함께 반환한다."""

    saturated_bright_ratio: float | None = None
    saturated_dark_ratio: float | None = None
    """원본 패드 ROI 의 포화 화소 비율. 상단/하단 포화를 따로 센다."""

    tilt_deg: float | None = None
    """추정 촬영 각도(도). 카메라 내부 파라미터가 없으므로 검출 사변형의
    왜곡도로부터 얻은 프록시다."""

    pad_size_px: float | None = None
    """검출 사변형 면적의 제곱근."""

    anchor_contrast: float | None = None
    """``I_white - I_black``. 앵커가 없는 규격에서는 테두리와 여백의 대비."""

    def to_dict(self) -> dict[str, float | None]:
        return {
            "edge_rise_ratio": _f(self.edge_rise_ratio),
            "tenengrad": _f(self.tenengrad),
            "saturated_bright_ratio": _f(self.saturated_bright_ratio),
            "saturated_dark_ratio": _f(self.saturated_dark_ratio),
            "tilt_deg": _f(self.tilt_deg),
            "pad_size_px": _f(self.pad_size_px),
            "anchor_contrast": _f(self.anchor_contrast),
        }


@dataclass
class NormalizationInfo:
    """조도 정규화 진단값.

    앵커 값을 그대로 내보내는 이유: 앵커도 분진을 받아 시간에 따라
    드리프트한다. 모듈은 상태가 없으므로 드리프트 추적은 상위 계층이 한다.
    """

    method: str = "two_point"
    """``two_point`` (앵커 2점) 또는 ``border_ratio`` (테두리 나눗셈)."""

    anchor_black: float | None = None
    anchor_white: float | None = None
    anchor_black_mad: float | None = None
    anchor_white_mad: float | None = None
    """앵커 대표값과 그 MAD. 중앙값을 쓰므로 국소 이물에 흔들리지 않는다."""

    plane_residual_rms: float | None = None
    """조명 평면 최소자승 적합의 잔차 RMS. 테두리 링을 조밀 표본(수백 점)해
    적합하므로 잔차가 의미를 갖는다. 4변 대표값 4점만 쓰면 3자유도 평면에
    잔차가 사실상 없어 신뢰도를 판정할 수 없다."""

    plane_condition_number: float | None = None
    """적합 설계행렬의 조건수. 크면 기울기 추정이 불안정하다."""

    plane_gradient: tuple[float, float] | None = None
    """정규화 좌표 한 변당 밝기 변화율 (dx, dy)."""

    def to_dict(self) -> dict[str, Any]:
        grad = self.plane_gradient
        return {
            "method": self.method,
            "anchor_black": _f(self.anchor_black),
            "anchor_white": _f(self.anchor_white),
            "anchor_black_mad": _f(self.anchor_black_mad),
            "anchor_white_mad": _f(self.anchor_white_mad),
            "plane_residual_rms": _f(self.plane_residual_rms),
            "plane_condition_number": _f(self.plane_condition_number),
            "plane_gradient": None if grad is None else [_f(grad[0]), _f(grad[1])],
        }


@dataclass
class Cell:
    """구획 하나."""

    row: int
    col: int
    value: float | None
    """오염량. 판독 사진의 오염도에서 기준 사진의 같은 칸 값을 뺀 것이다.
    0 이면 기준 때와 같고, 클수록 그만큼 더 오염되었다. 어느 한쪽이라도
    배제된 칸은 ``None``."""

    reading: float | None
    """판독 사진의 부호 정렬된 오염도."""

    baseline: float | None
    """기준 사진의 같은 칸 값. 둘의 차가 ``value`` 다."""

    reflectance: float | None
    """판독 사진의 정규화 반사율 추정치 rho-hat. 0 = 인쇄색, 1 = 바탕색 기준."""

    chroma_norm: float | None
    """``(max-min) / B``. 분모가 화소 자신이 아니라 조도 기준값이라
    어두운 화소에서 폭주하지 않으면서 조명 불변성이 유지된다.

    OpenCV 8비트 HSV 의 S 는 ``255*(max-min)/max`` 로 화소 자신을 분모에
    쓰므로 흑색 바탕 패드에서 전 구획이 배제 대상이 된다."""

    chroma_abs: float | None
    """``max - min``. 폭주하지는 않지만 노출에 의존한다. 실증에서 정규화값과
    어느 쪽을 쓸지 정하기 위해 둘 다 반환한다."""

    saturated_ratio: float | None
    valid_pixel_ratio: float
    excluded: ExclusionReason | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "col": self.col,
            "value": _f(self.value),
            "reading": _f(self.reading),
            "baseline": _f(self.baseline),
            "reflectance": _f(self.reflectance),
            "chroma_norm": _f(self.chroma_norm),
            "chroma_abs": _f(self.chroma_abs),
            "saturated_ratio": _f(self.saturated_ratio),
            "valid_pixel_ratio": _f(self.valid_pixel_ratio),
            "excluded": self.excluded.value if self.excluded else None,
        }


@dataclass
class Dispersion:
    """구획 값 산포.

    두 가지를 함께 낸다. 균일 침착은 둘 다 작지만, 국소 뭉침은 ``p90_minus_p50``
    이 뚜렷하게 커진다 — 소수 구획만 값이 튀면 IQR 은 덜 움직이기 때문이다.
    """

    stdev: float | None = None
    iqr: float | None = None
    p90_minus_p50: float | None = None

    def to_dict(self) -> dict[str, float | None]:
        return {
            "stdev": _f(self.stdev),
            "iqr": _f(self.iqr),
            "p90_minus_p50": _f(self.p90_minus_p50),
        }


@dataclass
class LineContrast:
    """선군 한 단계의 대비. 상시 지표가 아니라 실증 비교용이다."""

    index: int
    thickness_px: float
    contrast: float | None
    """남아 있는 대비. 1 이면 선이 또렷하고 0 이면 여백과 구분되지 않는다."""

    line_level: float | None
    gap_level: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "thickness_px": _f(self.thickness_px),
            "contrast": _f(self.contrast),
            "line_level": _f(self.line_level),
            "gap_level": _f(self.gap_level),
        }


@dataclass
class PadReadResult:
    """판독 결과. 이 객체 하나가 모듈의 출력이다."""

    success: bool
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None

    dust_score: float | None = None
    """기준 사진 대비 오염량의 대표값. 평균이 아니라 상위 분위수 또는 최대다."""

    score_statistic: str | None = None
    """대표값 산출 방식. 예: ``p90``, ``max``. 실증에서 바뀌므로 함께 실어
    보낸다."""

    dispersion: Dispersion = field(default_factory=Dispersion)
    cells: list[Cell] = field(default_factory=list)
    grid_shape: tuple[int, int] | None = None

    excluded_count: int = 0
    excluded_by_reason: dict[str, int] = field(default_factory=dict)

    quality: QualityMetrics = field(default_factory=QualityMetrics)
    normalization: NormalizationInfo = field(default_factory=NormalizationInfo)

    line_contrasts: list[LineContrast] = field(default_factory=list)

    target_id: str | None = None
    target_id_status: TargetIdStatus = TargetIdStatus.DISABLED
    target_id_confidence: float | None = None

    pad_tone: str | None = None
    spec_name: str | None = None
    rotation_deg: int | None = None
    rotation_margin: float | None = None
    """회전 판정 시 비어 있는 모서리와 나머지 사이의 최소 대비. 임계 조정에 쓴다."""

    corners: list[list[float]] | None = None
    """원본 이미지에서의 패드 네 꼭짓점 (서브픽셀). 회전 보정 후 순서."""

    elapsed_ms: float | None = None

    rectified: np.ndarray | None = field(default=None, repr=False)
    """정면 보정 이미지. 옵션 요청 시에만 채운다."""

    overlay: np.ndarray | None = field(default=None, repr=False)
    """구획 분할 시각화. 옵션 요청 시에만 채운다."""

    @classmethod
    def failed(
        cls,
        reason: FailureReason,
        detail: str | None = None,
        **kwargs: Any,
    ) -> "PadReadResult":
        return cls(success=False, failure_reason=reason, failure_detail=detail, **kwargs)

    def to_dict(self, include_cells: bool = True) -> dict[str, Any]:
        """JSON 직렬화 가능한 형태로. 이미지는 담지 않는다."""
        out: dict[str, Any] = {
            "success": self.success,
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "failure_detail": self.failure_detail,
            "dust_score": _f(self.dust_score),
            "score_statistic": self.score_statistic,
            "dispersion": self.dispersion.to_dict(),
            "grid_shape": list(self.grid_shape) if self.grid_shape else None,
            "excluded_count": self.excluded_count,
            "excluded_by_reason": dict(self.excluded_by_reason),
            "quality": self.quality.to_dict(),
            "normalization": self.normalization.to_dict(),
            "line_contrasts": [c.to_dict() for c in self.line_contrasts],
            "target_id": self.target_id,
            "target_id_status": self.target_id_status.value,
            "target_id_confidence": _f(self.target_id_confidence),
            "pad_tone": self.pad_tone,
            "spec_name": self.spec_name,
            "rotation_deg": self.rotation_deg,
            "rotation_margin": _f(self.rotation_margin),
            "corners": self.corners,
            "elapsed_ms": _f(self.elapsed_ms),
        }
        if include_cells:
            out["cells"] = [c.to_dict() for c in self.cells]
        return out
