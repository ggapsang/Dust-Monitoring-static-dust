"""판독 결과 객체.

사진 1장에서 나온 값만 담는다. 시계열 추세, 교체 판정, 알람은 이 모듈을
호출하는 상위 계층 몫이다.

``numpy`` 값을 밖으로 흘리지 않도록 스칼라는 전부 ``float`` 로 바꿔 담는다.
``to_dict()`` 는 그대로 JSON 직렬화 가능한 형태를 돌려준다.
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
    QUALITY_PAD_SIZE = "quality_pad_size"

    BASELINE_UNREADABLE = "baseline_unreadable"
    """기준 이미지를 판독하지 못했다. 상세 사유는 ``failure_detail`` 에 담긴다."""

    PAD_SIZE_MISMATCH = "pad_size_mismatch"
    """기준 이미지와 판독 이미지의 패드 크기가 크게 달라 비교가 성립하지 않는다."""

    NORMALIZATION_FAILED = "normalization_failed"
    """테두리 밝기를 기준으로 삼을 수 없어 조명 정규화가 성립하지 않는다."""

    NO_MEASURABLE_AREA = "no_measurable_area"
    """제외 처리 후 측정할 수 있는 영역이 남지 않았다."""

    INVALID_IMAGE = "invalid_image"
    """이미지를 읽을 수 없거나 형식이 지원되지 않는다."""


class ExclusionReason(str, Enum):
    """분진 판정에서 빠진 사유."""

    PRINT_ELEMENT = "print_element"
    """인쇄물 영역. 테두리, 모서리 블록, TARGET_ID, 선군."""

    SATURATED = "saturated"
    """밝기가 포화되었다. 정반사로 본다."""


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
class Blob:
    """서로 붙어 있는 분진 픽셀 덩어리 하나."""

    area_px: int
    area_ratio: float
    """측정 가능 면적 대비 이 덩어리가 차지하는 비율."""

    mean_depth: float
    """국소 배경 대비 평균 깊이. 클수록 짙다."""

    max_depth: float
    center: tuple[float, float]
    """여백 안에서의 상대 위치 (0-1)."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "area_px": self.area_px,
            "area_ratio": _f(self.area_ratio),
            "mean_depth": _f(self.mean_depth),
            "max_depth": _f(self.max_depth),
            "center": [_f(self.center[0]), _f(self.center[1])],
        }


@dataclass
class DustScores:
    """두 축의 스코어와 종합 지표.

    같은 양이 쌓여도 고르게 깔린 것과 한 군데 몰린 것은 원인도 대응도
    다르다. 하나로 뭉뚱그리면 어느 쪽인지 알 수 없으므로 각각 낸다.
    """

    uniform: float | None = None
    """미세 분진이 넓고 고르게 침착된 정도 (0-1). 패드 전체의 밝기 변화를
    기준으로 산출한다."""

    localized: float | None = None
    """굵은 입자가 한 곳에 뭉쳐 떨어진 정도 (0-1). 가장 크고 짙은 덩어리의
    면적 비율 x 짙기를 정규화한 값이다."""

    combined: float | None = None
    """종합 지표. 확률합 ``u + l - u*l`` 이다. 두 축을 독립 사건으로 보고
    '적어도 하나가 발생할 확률' 에 대응시켰다. 0-1 을 벗어나지 않는다."""

    uniform_raw: float | None = None
    """정규화 전 원값. 정규화 기준을 정하려면 이 분포를 봐야 한다."""

    localized_raw: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "uniform": _f(self.uniform),
            "localized": _f(self.localized),
            "combined": _f(self.combined),
            "uniform_raw": _f(self.uniform_raw),
            "localized_raw": _f(self.localized_raw),
        }


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
    """원본 패드 영역의 포화 화소 비율. 상단/하단 포화를 따로 센다."""

    pad_size_px: float | None = None
    """검출 사변형 면적의 제곱근."""

    def to_dict(self) -> dict[str, float | None]:
        return {
            "edge_rise_ratio": _f(self.edge_rise_ratio),
            "tenengrad": _f(self.tenengrad),
            "saturated_bright_ratio": _f(self.saturated_bright_ratio),
            "saturated_dark_ratio": _f(self.saturated_dark_ratio),
            "pad_size_px": _f(self.pad_size_px),
        }


@dataclass
class NormalizationInfo:
    """조명 정규화 진단값."""

    border_level: float | None = None
    """테두리 밝기. 여백을 이 값으로 나눈다."""

    border_mad: float | None = None
    """테두리 밝기의 MAD. 크면 테두리가 고르지 않다는 뜻이다."""

    plane_residual_rms: float | None = None
    """조명 평면 적합 잔차. 크면 기울기 추정을 믿기 어렵다."""

    plane_gradient: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        grad = self.plane_gradient
        return {
            "border_level": _f(self.border_level),
            "border_mad": _f(self.border_mad),
            "plane_residual_rms": _f(self.plane_residual_rms),
            "plane_gradient": None if grad is None else [_f(grad[0]), _f(grad[1])],
        }


@dataclass
class PadReadResult:
    """판독 결과. 이 객체 하나가 모듈의 출력이다."""

    success: bool
    failure_reason: FailureReason | None = None
    failure_detail: str | None = None

    scores: DustScores = field(default_factory=DustScores)

    blobs: list[Blob] = field(default_factory=list)
    blob_count: int = 0
    measurable_px: int = 0
    excluded_px: dict[str, int] = field(default_factory=dict)

    quality: QualityMetrics = field(default_factory=QualityMetrics)
    normalization: NormalizationInfo = field(default_factory=NormalizationInfo)

    target_id: str | None = None
    target_id_status: TargetIdStatus = TargetIdStatus.DISABLED
    target_id_confidence: float | None = None

    pad_size_diff_ratio: float | None = None
    """기준 이미지와 판독 이미지의 패드 크기 차이 비율."""

    pad_tone: str | None = None
    rotation_deg: int | None = None
    rotation_margin: float | None = None
    elapsed_ms: float | None = None

    baseline_rectified: np.ndarray | None = field(default=None, repr=False)
    """기준 이미지의 정면 보정 결과. 옵션 요청 시에만 채운다."""

    rectified: np.ndarray | None = field(default=None, repr=False)
    """판독 이미지의 정면 보정 결과. 옵션 요청 시에만 채운다."""

    distribution: np.ndarray | None = field(default=None, repr=False)
    """기준 대비 오염도 분포 이미지. 옵션 요청 시에만 채운다."""

    @classmethod
    def failed(
        cls, reason: FailureReason, detail: str | None = None, **kwargs: Any
    ) -> "PadReadResult":
        return cls(success=False, failure_reason=reason, failure_detail=detail, **kwargs)

    def to_dict(self, include_blobs: bool = True) -> dict[str, Any]:
        """JSON 직렬화 가능한 형태로. 이미지는 담지 않는다."""
        out: dict[str, Any] = {
            "success": self.success,
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "failure_detail": self.failure_detail,
            "scores": self.scores.to_dict(),
            "blob_count": self.blob_count,
            "measurable_px": self.measurable_px,
            "pad_size_diff_ratio": _f(self.pad_size_diff_ratio),
            "excluded_px": dict(self.excluded_px),
            "quality": self.quality.to_dict(),
            "normalization": self.normalization.to_dict(),
            "target_id": self.target_id,
            "target_id_status": self.target_id_status.value,
            "target_id_confidence": _f(self.target_id_confidence),
            "pad_tone": self.pad_tone,
            "rotation_deg": self.rotation_deg,
            "rotation_margin": _f(self.rotation_margin),
            "elapsed_ms": _f(self.elapsed_ms),
        }
        if include_blobs:
            out["blobs"] = [b.to_dict() for b in self.blobs]
        return out
