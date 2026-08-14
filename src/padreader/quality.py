"""품질 게이트.

판독 결과를 믿을 수 있는 이미지인지 먼저 거른다. 산출값은 게이트 통과
여부와 무관하게 항상 계산해 결과에 담는다 — 임계값이 아직 정해지지 않았고,
실증에서 이 값들의 분포를 봐야 정할 수 있기 때문이다.

선명도를 **원본 이미지**에서 재는 것이 중요하다. 정면 보정은 warp 보간을
수반하므로 스케일이 선명도에 직접 개입한다. 작게 찍힌 패드를 키우면 보간으로
에지가 완만해지고, 크게 찍힌 패드를 줄이면 에지가 오히려 선다. 보정 후에
재면 촬영 거리와 무관해지는 게 아니라 패드 픽셀 크기에 교란된다.

원본에서 재도 스케일 문제가 완전히 사라지지는 않는다. 같은 광학 흐림이어도
작게 찍힌 패드는 에지가 적은 화소에 걸쳐 화소당 기울기가 커진다. 그래서
주 지표를 **에지 상승 거리 ÷ 패드 픽셀 크기** 로 잡았다. '에지가 패드 폭의
몇 %를 차지하는가' 라서 정의상 거리 무관이다. Tenengrad 는 실증에서 어느
쪽이 실제 판독 실패와 더 잘 맞는지 비교하려고 함께 낸다.
"""

from __future__ import annotations

import cv2
import numpy as np

from .config import QualityConfig
from .detect import Detection
from .geometry import estimate_tilt_deg
from .profile import edge_samples, rise_distances, sample_across
from .result import FailureReason, QualityMetrics

EDGE_TRIM_RATIO = 0.15
"""선명도 측정에서 변 양 끝을 얼마나 버릴지. 모서리 라운딩을 피한다."""


def _pad_mask(shape: tuple[int, int], corners: np.ndarray) -> np.ndarray:
    mask = np.zeros(shape, np.uint8)
    cv2.fillPoly(mask, [corners.astype(np.int32)], 255)
    return mask


def _border_band_mask(
    shape: tuple[int, int], corners: np.ndarray, thickness_ratio: float
) -> np.ndarray:
    """테두리를 따라가는 띠 마스크.

    선명도는 에지가 있는 곳에서만 의미가 있다. 여백은 원래 평탄해서 거기서
    재면 '깨끗한 패드'가 '흐린 이미지'로 판정된다.
    """
    pad_size = np.sqrt(cv2.contourArea(corners.astype(np.float32)))
    thickness = max(3, int(round(pad_size * thickness_ratio)))
    mask = np.zeros(shape, np.uint8)
    cv2.polylines(mask, [corners.astype(np.int32)], True, 255, thickness)
    return mask


def _edge_rise(gray: np.ndarray, corners: np.ndarray) -> float | None:
    """네 변에서 잰 에지 10-90% 상승 거리의 중앙값(px)."""
    center = corners.mean(axis=0)
    collected: list[np.ndarray] = []

    for i in range(4):
        p0, p1 = corners[i], corners[(i + 1) % 4]
        length = float(np.linalg.norm(p1 - p0))
        if length < 8:
            continue
        edge_mid = (p0 + p1) / 2.0
        outward = edge_mid - center
        norm = float(np.linalg.norm(outward))
        if norm < 1e-9:
            continue

        centers = edge_samples(p0, p1, EDGE_TRIM_RATIO, max_samples=120)
        radius = int(np.clip(round(length * 0.03), 5, 30))
        profiles = sample_across(gray, centers, outward / norm, radius)
        distances = rise_distances(profiles)
        if distances.size:
            collected.append(distances)

    if not collected:
        return None
    return float(np.median(np.concatenate(collected)))


def measure_quality(
    gray: np.ndarray,
    detection: Detection,
    cfg: QualityConfig,
    border_thickness_ratio: float,
) -> QualityMetrics:
    """원본 이미지에서 품질 지표를 산출한다.

    ``anchor_contrast`` 는 정규화 단계에서만 알 수 있으므로 여기서는 비운다.
    """
    corners = detection.corners
    pad_size_px = float(np.sqrt(max(detection.area, 0.0)))

    rise = _edge_rise(gray, corners)
    rise_ratio = None if rise is None or pad_size_px <= 0 else rise / pad_size_px

    band = _border_band_mask(gray.shape[:2], corners, border_thickness_ratio)
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    energy = gx * gx + gy * gy
    tenengrad = float(energy[band > 0].mean()) if np.any(band) else None

    pad = _pad_mask(gray.shape[:2], corners)
    inside = gray[pad > 0]
    if inside.size:
        bright = float((inside >= cfg.saturation_bright_level).mean())
        dark = float((inside <= cfg.saturation_dark_level).mean())
    else:
        bright = dark = None

    return QualityMetrics(
        edge_rise_ratio=rise_ratio,
        tenengrad=tenengrad,
        saturated_bright_ratio=bright,
        saturated_dark_ratio=dark,
        tilt_deg=estimate_tilt_deg(corners),
        pad_size_px=pad_size_px,
    )


def check_gates(metrics: QualityMetrics, cfg: QualityConfig) -> tuple[FailureReason, str] | None:
    """임계를 넘긴 첫 항목을 돌려준다. 전부 통과하면 ``None``.

    임계값이 ``None`` 인 항목은 건너뛴다. 산출값이 ``None`` 인 경우(측정
    실패)도 통과시킨다 — 측정하지 못한 것을 근거로 판독을 막지 않는다.
    """
    checks: list[tuple[float | None, float | None, bool, FailureReason, str]] = [
        (metrics.edge_rise_ratio, cfg.max_edge_rise_ratio, True,
         FailureReason.QUALITY_SHARPNESS, "에지 상승폭"),
        (metrics.tenengrad, cfg.min_tenengrad, False,
         FailureReason.QUALITY_SHARPNESS, "Tenengrad"),
        (metrics.saturated_bright_ratio, cfg.max_saturated_bright_ratio, True,
         FailureReason.QUALITY_SATURATION, "밝은 쪽 포화율"),
        (metrics.saturated_dark_ratio, cfg.max_saturated_dark_ratio, True,
         FailureReason.QUALITY_SATURATION, "어두운 쪽 포화율"),
        (metrics.tilt_deg, cfg.max_tilt_deg, True,
         FailureReason.QUALITY_ANGLE, "추정 촬영 각도"),
        (metrics.pad_size_px, cfg.min_pad_size_px, False,
         FailureReason.QUALITY_PAD_SIZE, "패드 픽셀 크기"),
        (metrics.anchor_contrast, cfg.min_anchor_contrast, False,
         FailureReason.QUALITY_ANCHOR_CONTRAST, "앵커 대비"),
    ]

    for value, limit, is_max, reason, label in checks:
        if value is None or limit is None:
            continue
        if is_max and value > limit:
            return reason, f"{label} {value:.4g} > 임계 {limit:.4g}"
        if not is_max and value < limit:
            return reason, f"{label} {value:.4g} < 임계 {limit:.4g}"
    return None
