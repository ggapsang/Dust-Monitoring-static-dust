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

    BASELINE_PAD_MISSING = "baseline_pad_missing"
    """판독 이미지에는 있는 패드가 기준 이미지에는 없다.

    한 화면에 여러 패드가 찍혔을 때, 짝을 찾지 못한 패드에 붙는다. 같은
    번호의 패드가 기준 사진에도 있어야 부착 이후 쌓인 양을 낼 수 있다.
    """

    PAD_SIZE_MISMATCH = "pad_size_mismatch"
    """기준 이미지와 판독 이미지의 패드 크기가 크게 달라 비교가 성립하지 않는다."""

    NORMALIZATION_FAILED = "normalization_failed"
    """테두리 밝기를 기준으로 삼을 수 없어 조명 정규화가 성립하지 않는다."""

    NO_MEASURABLE_AREA = "no_measurable_area"
    """제외 처리 후 측정할 수 있는 영역이 남지 않았다."""

    INVALID_IMAGE = "invalid_image"
    """이미지를 읽을 수 없거나 형식이 지원되지 않는다."""

    ANCHOR_CLIPPED = "anchor_clipped"
    """유채색 패드의 2톤 앵커 패치에서 어느 채널이 포화(255) 또는 바닥(0) 에
    붙었다. 채널별 정규화가 성립하지 않으므로 조용히 잘못된 값을 내지 않고
    판독 전체를 실패로 남긴다."""

    ANCHOR_SPAN_INVALID = "anchor_span_invalid"
    """유채색 앵커의 백색 패치가 흑색 패치보다 밝지 않은 채널이 있다.
    정규화의 분모가 0 이하가 되어 성립하지 않는다."""

    PAD_TYPE_MISMATCH = "pad_type_mismatch"
    """판독 사진과 기준 사진의 패드 종류(무채색/유채색)가 다르게 판별됐다.
    같은 개소인데 패드가 통째로 바뀐 것이 아니라면 판별 자체가 흔들린
    경계 사례이므로, 섞어서 비교하지 않고 실패로 남긴다."""


class ExclusionReason(str, Enum):
    """분진 판정에서 빠진 사유."""

    PRINT_ELEMENT = "print_element"
    """인쇄물 영역. 테두리, 모서리 블록, POINT_ID, 선군."""

    SATURATED = "saturated"
    """밝기가 포화되었다. 정반사로 본다."""


class PointIdStatus(str, Enum):
    """패드에 인쇄된 관측 개소 번호를 읽었는지.

    이 번호는 패드가 붙어 있는 물리적 개소를 가리킨다. AMR 쪽 TARGET_ID(한
    웨이포인트에서 PTZ 프리셋을 잡고 찍은 사진 한 장)와 같은 것이 아니다.
    """

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
    """localized 배경 대비 평균 깊이. 클수록 짙다."""

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
    """두 축의 스코어와 combined 지표.

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
    """combined 지표. 확률합 ``u + l - u*l`` 이다. 두 축을 독립 사건으로 보고
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
class OpticalDensityScores:
    """시험 지표. 광학밀도(−log 투과율) 기반 오염도 - 판정에는 쓰지 않는다.

    임계값도, "가장 큰 덩어리 하나만" 도, 결합식도 없다. 노출 영역 전체 픽셀의
    부호 있는 로그값을 그대로 더한다 - 노이즈는 부호가 섞여 있어 합산 과정에서
    스스로 상쇄되고, 분진은 늘 한 방향(어두워짐)이라 상쇄되지 않고 쌓인다.

    ``uniform``/``localized``/``combined`` 과 나란히 참고용으로만 낸다. 경보·
    등급·임계 비교 어디에도 쓰지 않는다.
    """

    od_sum: float | None = None
    """노출 영역 전체 픽셀의 log(기준/판독) 합. 부호 그대로, 임계값 없이."""

    od_mean: float | None = None
    """``od_sum / 노출 영역 픽셀 수``. 패드 전체가 이만큼 균일하게 어두워진
    것과 같다는 등가 오염 깊이(면적 차원)."""

    od_score: float | None = None
    """``sqrt(od_mean)`` (음수면 0). 선형 차원으로 바꾼 값 - 오염을 한 덩어리로
    모았을 때 그 한 변이 패드 폭의 몇 %인지에 해당한다."""

    roi_mean_reading: float | None = None
    """노출 영역의 판독 사진 평균 밝기(정규화 reflectance). od_score 가 튈 때
    조명 때문인지 가리는 참고값."""

    roi_mean_baseline: float | None = None
    """노출 영역의 기준 사진 평균 밝기(정규화 reflectance)."""

    pad_scale: float | None = None
    """정합 시 원본 패드 크기 대비 확대 배율. 촬영 거리의 대리 지표."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "od_sum": _f(self.od_sum),
            "od_mean": _f(self.od_mean),
            "od_score": _f(self.od_score),
            "roi_mean_reading": _f(self.roi_mean_reading),
            "roi_mean_baseline": _f(self.roi_mean_baseline),
            "pad_scale": _f(self.pad_scale),
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
class ChromaFieldScore:
    """``chroma``/``luma_dark``/``luma_light`` 가 공유하는 형태.

    임계값이 없다. ``sum`` 은 노출 영역 전체 화소의 변화량을 부호 그대로
    더한 것이고, ``mean`` 은 그것을 노출 영역 픽셀 수로 나눈 등가 깊이,
    ``score`` 는 그 제곱근(선형 차원)이다. ``mean`` 이 음수면 ``score`` 는 0 -
    판독이 기준보다 전체적으로 옅어진 경우이며 오염으로 보지 않는다.
    """

    sum: float | None = None
    mean: float | None = None
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"sum": _f(self.sum), "mean": _f(self.mean), "score": _f(self.score)}


@dataclass
class ChromaNormalizationInfo:
    """유채색 패드의 2톤 앵커 채널별 정규화 성립 여부.

    ``uniform``/``localized``/``combined`` 가 쓰는 ``normalization`` 필드와는
    다르다 - 그건 테두리 하나로 미는 조명 평면 진단이고, 이건 흑·백 앵커
    두 점으로 채널마다(R·G·B) 게인·바닥값·화이트밸런스를 지우는 유채색
    전용 보정의 성패다."""

    success: bool = False
    failure_reason: str | None = None
    """실패 이유(``FailureReason`` 값). 성공하면 ``None``."""

    def to_dict(self) -> dict[str, Any]:
        return {"success": self.success, "failure_reason": self.failure_reason}


@dataclass
class ChromaDiagnostics:
    """유채색 지표가 튈 때 원인을 가리는 참고값. 판정에 쓰지 않는다."""

    roi_mean_reading: dict[str, float | None] | None = None
    """노출 영역의 판독 사진 평균(채널별, 앵커로 정규화된 반사율)."""

    roi_mean_baseline: dict[str, float | None] | None = None

    anchor_values: dict[str, Any] | None = None
    """앵커 4개 패치의 원값(raw, 채널별). 판독/기준 각각의 흑·백 앵커 관측값 -
    이 값이 서로 이상하게 가까우면(백-흑 폭이 좁으면) 정규화 자체가 불안정
    하다는 뜻이다."""

    pad_scale: float | None = None
    """정합 시 원본 패드 크기 대비 확대 배율. 촬영 거리의 대리 지표."""

    clipped_ratio: dict[str, float | None] | None = None
    """노출 영역 전체에서 채널별로 포화(255)·바닥(0) 화소가 차지하는 비율.
    앵커 클리핑과 달리 이것만으로는 판독을 실패시키지 않는다 - 노출 영역
    일부의 국소 클리핑은 그 화소만 이상값이 될 뿐 정규화 자체를 깨지 않는다."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "roi_mean_reading": self.roi_mean_reading,
            "roi_mean_baseline": self.roi_mean_baseline,
            "anchor_values": self.anchor_values,
            "pad_scale": _f(self.pad_scale),
            "clipped_ratio": self.clipped_ratio,
        }


@dataclass
class PadReadResult:
    """패드 하나의 판독 결과."""

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
    optical_density: OpticalDensityScores = field(default_factory=OpticalDensityScores)

    pad_type: str | None = None
    """판별된 패드 종류. ``mono`` 또는 ``chroma``. 무채색 경로만 강제했으면
    (``mode="legacy"``) 판별 자체를 하지 않고 항상 ``mono`` 다."""

    chroma_normalization: ChromaNormalizationInfo = field(default_factory=ChromaNormalizationInfo)
    chroma: ChromaFieldScore = field(default_factory=ChromaFieldScore)
    """채도 감소 기반. 무채색 패드거나 정규화에 실패했으면 전부 ``None``."""
    luma_dark: ChromaFieldScore = field(default_factory=ChromaFieldScore)
    """명도 감소(흑색 분진 방향) 기반."""
    luma_light: ChromaFieldScore = field(default_factory=ChromaFieldScore)
    """명도 증가(백색 분진 방향) 기반."""
    chroma_diagnostics: ChromaDiagnostics = field(default_factory=ChromaDiagnostics)

    point_id: str | None = None
    point_id_status: PointIdStatus = PointIdStatus.DISABLED
    point_id_confidence: float | None = None

    point_id_raw: str | None = None
    """열린 판독으로 읽은 번호. 후보에 배정했으면 ``point_id`` 와 다를 수 있다.

    나중에 오독이 몇 건이었는지 세려면 배정 결과와 실제로 읽은 값이 따로
    있어야 한다.
    """

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
            "optical_density": self.optical_density.to_dict(),
            "pad_type": self.pad_type,
            "chroma_normalization": self.chroma_normalization.to_dict(),
            "chroma": self.chroma.to_dict(),
            "luma_dark": self.luma_dark.to_dict(),
            "luma_light": self.luma_light.to_dict(),
            "chroma_diagnostics": self.chroma_diagnostics.to_dict(),
            "point_id": self.point_id,
            "point_id_raw": self.point_id_raw,
            "point_id_status": self.point_id_status.value,
            "point_id_confidence": _f(self.point_id_confidence),
            "pad_tone": self.pad_tone,
            "rotation_deg": self.rotation_deg,
            "rotation_margin": _f(self.rotation_margin),
            "elapsed_ms": _f(self.elapsed_ms),
        }
        if include_blobs:
            out["blobs"] = [b.to_dict() for b in self.blobs]
        return out


@dataclass
class PadReadBatch:
    """사진 한 쌍의 판독 결과. 패드마다 한 건씩 담는다.

    한 화면에 패드가 여러 개 찍히는 일이 현장에서 실제로 일어난다. 그때 가장
    크게 찍힌 하나만 돌려주면 나머지는 조용히 사라지고, 어느 것이 돌아왔는지도
    알 수 없다. 그래서 찾은 패드를 전부 담는다.

    ``success`` 는 **하나라도 판독됐는가** 다. 개별 패드의 성패는 각 항목의
    ``success`` 를 본다.
    """

    success: bool
    pads: list[PadReadResult] = field(default_factory=list)

    failure_reason: FailureReason | None = None
    failure_detail: str | None = None
    """사진 자체를 못 읽었거나 패드를 하나도 못 찾았을 때만 채운다."""

    pad_tone: str | None = None
    elapsed_ms: float | None = None

    @classmethod
    def failed(
        cls, reason: FailureReason, detail: str | None = None
    ) -> "PadReadBatch":
        return cls(success=False, failure_reason=reason, failure_detail=detail)

    @property
    def first(self) -> PadReadResult:
        """가장 크게 찍힌 패드. 한 장에 하나만 찍히는 흔한 경우를 위한 지름길."""
        if self.pads:
            return self.pads[0]
        return PadReadResult.failed(
            self.failure_reason or FailureReason.PAD_NOT_FOUND, self.failure_detail
        )

    def to_dict(self, include_blobs: bool = True) -> dict[str, Any]:
        return {
            "success": self.success,
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "failure_detail": self.failure_detail,
            "pad_tone": self.pad_tone,
            "elapsed_ms": _f(self.elapsed_ms),
            "pads": [p.to_dict(include_blobs) for p in self.pads],
        }
