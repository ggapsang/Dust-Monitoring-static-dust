"""패드 검출.

이미지에서 참조 패드의 굵은 외곽 테두리를 찾고 네 꼭짓점을 서브픽셀
정밀도로 구한다.

두 가지가 이 구현의 핵심이다.

1. **링 구조 요구.** 굵은 사각 테두리는 속이 빈 링이므로 컨투어 계층에서
   자식을 갖는다. 이 조건을 걸면 현장 배경의 사각형 물체 대부분이 떨어져
   나간다.

2. **코너를 정제하지 않고 변을 맞춘다.** 두꺼운 인쇄 테두리의 꼭짓점은
   라운딩과 잉크 번짐으로 뭉개져 있어 ``cornerSubPix`` 같은 코너 정제의
   전제가 성립하지 않는다. 대신 네 변마다 수백 개의 에지 교차점을 서브픽셀로
   찾아 직선을 맞추고, 인접 직선의 교점을 꼭짓점으로 삼는다. 표본이 많아
   개별 노이즈가 평균화되고, 꼭짓점이 실제로 뭉개져 있어도 무관하다.

3. **이진화 임계를 한 번만 시도하지 않는다.** 화면에서 패드가 차지하는
   비중이 작으면 오츠 임계는 패드가 아니라 배경과 바탕면 사이에 잡힌다.
   테두리 잉크는 순흑이 아니라 회색이므로 그 임계 바로 아래에 놓이고,
   패드가 조금 밝게 찍히면 테두리 일부가 임계를 넘어 링에 구멍이 뚫린다.
   링이 끊기면 바깥 윤곽이 사각형이 아니라 띠를 훑는 모양이 되어 검출이
   통째로 실패한다. 그래서 후보를 못 찾으면 임계를 인쇄색 쪽으로 넓혀
   다시 시도한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import DetectConfig
from .geometry import intersect_lines, line_from_points, order_corners, quad_area
from .profile import (
    crossing_offsets,
    edge_samples,
    plateau_levels,
    sample_across,
    usable_rows,
)


@dataclass
class Detection:
    """검출 결과."""

    corners: np.ndarray
    """(4, 2) float64. 시계방향 TL, TR, BR, BL. 원본 이미지 좌표."""

    coarse_corners: np.ndarray
    """서브픽셀 정제 전의 컨투어 근사 꼭짓점. 진단용."""

    area: float
    edge_sample_counts: tuple[int, int, int, int]
    """변별로 직선 적합에 실제로 쓰인 표본 수. 적으면 그 변의 신뢰도가 낮다."""

    edge_residuals: tuple[float, float, float, float]
    """변별 직선 적합 잔차 RMS(px). 크면 테두리가 가려졌거나 곡면에 붙어 있다."""


def _prepare(gray: np.ndarray, cfg: DetectConfig) -> np.ndarray:
    """이진화에 쓸 흐린 이미지. 분진 측정은 원본으로 하므로 여기서만 쓴다."""
    if cfg.blur_ksize and cfg.blur_ksize >= 3:
        k = cfg.blur_ksize | 1
        return cv2.GaussianBlur(gray, (k, k), 0)
    return gray


def _otsu_level(work: np.ndarray, tone: str) -> float:
    """오츠 임계값."""
    flag = cv2.THRESH_BINARY_INV if tone == "white" else cv2.THRESH_BINARY
    level, _ = cv2.threshold(work, 0, 255, flag | cv2.THRESH_OTSU)
    return float(level)


def _binarize(
    gray: np.ndarray, tone: str, cfg: DetectConfig, scale: float = 1.0
) -> np.ndarray:
    """인쇄색을 255 로 하는 이진 이미지.

    패드 톤에 따라 극성을 뒤집어 이후 로직을 하나로 통일한다.

    ``scale`` 은 오츠 임계를 인쇄색 쪽으로 얼마나 넓힐지다. 1.0 이 오츠
    그대로이고, 키우면 더 옅은 잉크까지 인쇄색으로 친다. 백색 바탕은 잉크가
    어두우므로 임계를 올리고, 흑색 바탕은 잉크가 밝으므로 같은 비율만큼
    내린다.
    """
    work = _prepare(gray, cfg)
    flag = cv2.THRESH_BINARY_INV if tone == "white" else cv2.THRESH_BINARY

    if scale == 1.0:
        _, binary = cv2.threshold(work, 0, 255, flag | cv2.THRESH_OTSU)
        return binary

    otsu = _otsu_level(work, tone)
    factor = scale if tone == "white" else 2.0 - scale
    level = float(np.clip(otsu * factor, 1.0, 254.0))
    _, binary = cv2.threshold(work, level, 255, flag)
    return binary


def _candidate_quads(
    binary: np.ndarray, cfg: DetectConfig
) -> list[np.ndarray]:
    """링 구조를 갖는 사각형 후보들. 면적 큰 순."""
    contours, hierarchy = cv2.findContours(
        binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    if hierarchy is None:
        return []

    image_area = float(binary.shape[0] * binary.shape[1])
    out: list[tuple[float, np.ndarray]] = []

    for idx, contour in enumerate(contours):
        # RETR_CCOMP 에서 부모가 없는 것이 바깥 윤곽이다.
        if hierarchy[0][idx][3] != -1:
            continue
        if cfg.require_ring and hierarchy[0][idx][2] == -1:
            continue

        area = cv2.contourArea(contour)
        if not (cfg.min_pad_area_ratio * image_area <= area <= cfg.max_pad_area_ratio * image_area):
            continue

        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, cfg.approx_epsilon_ratio * peri, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue

        hull_area = cv2.contourArea(cv2.convexHull(contour))
        if hull_area <= 0 or area / hull_area < cfg.min_solidity:
            continue

        quad = order_corners(approx.reshape(4, 2).astype(np.float64))
        sides = np.linalg.norm(np.roll(quad, -1, axis=0) - quad, axis=1)
        if sides.min() <= 0 or sides.max() / sides.min() > cfg.max_aspect_ratio:
            continue

        out.append((area, quad))

    out.sort(key=lambda pair: pair[0], reverse=True)
    return [quad for _, quad in out]


def _refine_edge(
    gray: np.ndarray,
    p0: np.ndarray,
    p1: np.ndarray,
    outward: np.ndarray,
    cfg: DetectConfig,
) -> tuple[np.ndarray, np.ndarray, int, float] | None:
    """한 변의 바깥 경계를 서브픽셀로 찾아 직선을 맞춘다.

    변을 따라 표본점을 찍고, 각 점에서 변에 수직인 방향으로 밝기 단면을
    떠서 중간 레벨을 지나는 위치를 선형보간으로 찾는다. 그 점들에 총최소자승
    직선을 맞춘다.

    Returns
    -------
    (방향벡터, 통과점, 표본수, 잔차RMS) 또는 실패 시 ``None``.
    """
    length = float(np.linalg.norm(p1 - p0))
    if length < 8:
        return None

    centers = edge_samples(p0, p1, cfg.edge_trim_ratio)

    # 탐색 반경은 패드 크기에 맞춘다. 너무 좁으면 에지를 놓치고, 너무 넓으면
    # 이웃 인쇄물이 단면에 섞인다.
    radius = int(np.clip(round(length * 0.02), 4, 24))
    profiles = sample_across(gray, centers, outward, radius)

    inner_level, outer_level = plateau_levels(profiles, radius)
    keep = usable_rows(inner_level, outer_level)
    if keep.sum() < 8:
        return None

    rows, offsets = crossing_offsets(profiles[keep], radius)
    if rows.size < 8:
        return None

    kept_centers = centers[keep][rows]
    pts = kept_centers + offsets[:, None] * outward[None, :]
    direction, origin = line_from_points(pts)
    normal = np.array([-direction[1], direction[0]])
    residual = float(np.sqrt(np.mean(((pts - origin) @ normal) ** 2)))
    return direction, origin, len(pts), residual


def detect_pad(
    gray: np.ndarray, tone: str, cfg: DetectConfig
) -> Detection | None:
    """패드를 찾아 서브픽셀 꼭짓점을 반환한다. 못 찾으면 ``None``.

    임계를 여러 번 시도한다. 처음 값이 오츠 그대로이고, 후보를 못 찾으면
    인쇄색 쪽으로 넓혀 다시 본다. 꼭짓점은 어느 임계로 찾았든 원본 밝기
    단면에서 다시 맞추므로 정밀도가 임계에 좌우되지 않는다.
    """
    scales = cfg.threshold_scales or [1.0]
    for scale in scales:
        found = _detect_at(gray, tone, cfg, scale)
        if found is not None:
            return found
    return None


def _detect_at(
    gray: np.ndarray, tone: str, cfg: DetectConfig, scale: float
) -> Detection | None:
    """임계 하나로 패드를 찾는다."""
    binary = _binarize(gray, tone, cfg, scale)

    for quad in _candidate_quads(binary, cfg):
        center = quad.mean(axis=0)
        lines = []
        counts = []
        residuals = []

        for i in range(4):
            p0, p1 = quad[i], quad[(i + 1) % 4]
            edge_mid = (p0 + p1) / 2.0
            outward = edge_mid - center
            norm = np.linalg.norm(outward)
            if norm < 1e-9:
                break
            refined = _refine_edge(gray, p0, p1, outward / norm, cfg)
            if refined is None:
                break
            direction, origin, count, residual = refined
            lines.append((direction, origin))
            counts.append(count)
            residuals.append(residual)

        if len(lines) != 4:
            continue

        corners = []
        for i in range(4):
            # 꼭짓점 i 는 변 (i-1)->i 와 변 i->(i+1) 이 만나는 곳이다.
            prev_dir, prev_pt = lines[(i - 1) % 4]
            curr_dir, curr_pt = lines[i]
            point = intersect_lines(prev_dir, prev_pt, curr_dir, curr_pt)
            if point is None:
                break
            corners.append(point)

        if len(corners) != 4:
            continue

        refined_quad = order_corners(np.array(corners))
        # 정제 결과가 근사 사각형에서 크게 벗어나면 잘못 맞춘 것이다.
        drift = np.linalg.norm(refined_quad - quad, axis=1).max()
        if drift > 0.05 * np.sqrt(quad_area(quad)):
            continue

        return Detection(
            corners=refined_quad,
            coarse_corners=quad,
            area=quad_area(refined_quad),
            edge_sample_counts=tuple(counts),  # type: ignore[arg-type]
            edge_residuals=tuple(residuals),  # type: ignore[arg-type]
        )

    return None
