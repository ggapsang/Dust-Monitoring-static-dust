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


def _binarize_local(
    gray: np.ndarray, tone: str, cfg: DetectConfig, open_px: int = 0
) -> np.ndarray:
    """주변과 견주어 인쇄색을 가른다.

    임계 하나를 사진 전체에 쓰면, 사진에서 어두운 것은 무엇이든 인쇄색이
    된다. 요철 도장면의 그늘, 패널 이음새, 설비 그림자가 전부 잉크로 찍히고
    거기에 닿은 패드 테두리는 그것들과 한 덩어리가 되어 액자 모양을 잃는다.
    그러면 사각형 후보 자체가 만들어지지 않는다.

    화소마다 **자기 주변 평균**과 견주면 그 결합이 끊어진다. 벽 요철의 그늘은
    사진 전체로 보면 어둡지만 주변도 같이 그늘이라 제자리에서는 어둡지 않고,
    테두리 잉크는 바로 옆이 밝은 여백이라 어느 기준으로 보든 어둡다.
    """
    work = _prepare(gray, cfg)
    short = min(gray.shape[:2])
    block = max(3, int(round(cfg.local_block_ratio * short)))
    block |= 1  # 창 크기는 홀수여야 한다

    # adaptiveThreshold 의 임계는 '주변 평균 - C' 다. 백색 바탕은 주변보다
    # 그만큼 어두운 화소를, 흑색 바탕은 그만큼 밝은 화소를 인쇄색으로 친다.
    if tone == "white":
        flag, offset = cv2.THRESH_BINARY_INV, float(cfg.local_offset)
    else:
        flag, offset = cv2.THRESH_BINARY, -float(cfg.local_offset)

    binary = cv2.adaptiveThreshold(
        work, 255, cv2.ADAPTIVE_THRESH_MEAN_C, flag, block, offset
    )

    # 주변과 견줘도 진짜 어두운 선은 남는다. 벽 패널 이음새가 그렇고, 그것이
    # 패드에 닿아 있으면 여전히 한 덩어리다. 다만 이음새는 가늘고 테두리는
    # 굵다. 이 굵기보다 가는 것을 지우면 선만 끊기고 테두리는 남는다.
    if open_px >= 3:
        k = open_px | 1
        binary = cv2.morphologyEx(
            binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        )
    return binary


def _candidate_quads(
    binary: np.ndarray, cfg: DetectConfig
) -> list[tuple[np.ndarray, np.ndarray | None]]:
    """링 구조를 갖는 사각형 후보들. 면적 큰 순.

    (바깥 사각형, 안쪽 사각형) 쌍을 준다. 안쪽은 링의 구멍이며 사각형으로
    근사되지 않으면 ``None`` 이다. 바깥 경계가 그림자나 이음새에 먹혔을 때
    안쪽으로 되짚기 위해 함께 들고 나온다.
    """
    contours, hierarchy = cv2.findContours(
        binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    if hierarchy is None:
        return []

    image_area = float(binary.shape[0] * binary.shape[1])
    out: list[tuple[float, np.ndarray, np.ndarray | None]] = []

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

        out.append((area, quad, _hole_quad(contours, hierarchy, idx, cfg)))

    out.sort(key=lambda item: item[0], reverse=True)
    return [(quad, hole) for _, quad, hole in out]


def _hole_quad(contours, hierarchy, parent: int, cfg: DetectConfig):
    """링의 구멍을 사각형으로 근사한다. 가장 큰 구멍 하나만 본다."""
    best = None
    child = hierarchy[0][parent][2]
    while child != -1:
        area = cv2.contourArea(contours[child])
        if best is None or area > best[0]:
            best = (area, contours[child])
        child = hierarchy[0][child][0]
    if best is None:
        return None

    contour = best[1]
    peri = cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, cfg.approx_epsilon_ratio * peri, True)
    if len(approx) != 4 or not cv2.isContourConvex(approx):
        return None
    return order_corners(approx.reshape(4, 2).astype(np.float64))


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


PROBE_PX = 256
"""테두리 두께를 확인할 때 쓸 정면 보정 크기. 두께만 보므로 작아도 된다."""


def border_matches(
    gray: np.ndarray,
    corners: np.ndarray,
    tone: str,
    border_thickness: float,
    cfg: DetectConfig,
) -> bool:
    """찾은 사각형이 정말 패드 바깥 테두리인지 규격으로 확인한다.

    **검출이 조용히 어긋나는 것을 막는 장치다.** 패드가 벽에서 떨어져 있어
    그림자가 지면, 그림자가 테두리 잉크만큼 어두워 밝기만으로는 패드 끝과
    그림자 시작을 가를 수 없다. 그러면 사각형은 찾아지지만 한쪽 변이 그림자
    속으로 밀려 좌표계 전체가 어긋난다. 검출은 성공으로 보이는데 모서리 블록
    자리가 테두리 위로 올라가 회전 판정이 무너지고, 결국 틀린 값이 조용히
    나온다. 실패로 끊기는 것보다 나쁘다.

    확인은 간단하다. 사각형이 정말 바깥 테두리라면, 정면으로 편 이미지에서
    잉크 띠가 네 변 모두 **0 에서 시작해 규격 두께에서 끝나야** 한다. 한
    변이라도 어긋나면 그 사각형은 테두리가 아니다.
    """
    if cfg.border_tolerance is None:
        return True

    from .rectify import rectify  # 순환 참조를 피해 지역에서 가져온다

    rect, _ = rectify(gray, corners, PROBE_PX)
    if rect.size == 0:
        return False

    # 임계는 잘라낸 패드 안에서 다시 잡는다. 이 시점에는 화면이 아니라 패드가
    # 히스토그램을 채우므로 오츠가 잉크와 여백 사이에 제대로 놓인다.
    level, _ = cv2.threshold(rect, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    ink = rect < level if tone == "white" else rect > level

    expected = float(border_thickness) * PROBE_PX
    tolerance = float(cfg.border_tolerance) * PROBE_PX
    # 네 모서리는 인쇄 번짐으로 뭉개져 있어 그 구간을 뺀다.
    span = slice(int(PROBE_PX * 0.12), int(PROBE_PX * 0.88))
    depth = max(3, int(round(expected * 3)))

    for strip in (
        ink[:depth, span],            # 위에서 아래로
        ink[::-1][:depth, span],      # 아래에서 위로
        ink.T[:depth, span],          # 왼쪽에서 오른쪽으로
        ink.T[::-1][:depth, span],    # 오른쪽에서 왼쪽으로
    ):
        if _band_off(strip, expected, tolerance):
            return False
    return True


def _band_off(strip: np.ndarray, expected: float, tolerance: float) -> bool:
    """잉크 띠 두께가 규격에서 벗어났는지.

    바깥에서 안으로 들어가며 **첫 잉크 자리**를 찾고, 거기서 잉크가 끊길
    때까지의 길이를 잰다. 0 번째 줄부터 세지 않는 이유는, 사각형이 실제
    경계보다 한두 화소 바깥에 놓이면 맨 바깥 줄이 잉크가 아니기 때문이다.
    그 정도는 어긋남이 아니다.

    열마다 따로 재고 중앙값을 쓴다. 여백에 인쇄물이 걸친 열이 섞여도
    중앙값은 흔들리지 않는다.
    """
    padded = np.vstack([strip, np.zeros((1, strip.shape[1]), bool)])
    rows = np.arange(padded.shape[0])[:, None]

    first = np.argmax(padded, axis=0)                 # 첫 잉크 줄
    after = (~padded) & (rows >= first[None, :])
    end = np.argmax(after, axis=0)                    # 잉크가 끊기는 줄

    widths = (end - first).astype(np.float64)
    return abs(float(np.median(widths)) - expected) > tolerance


def detect_pads(
    gray: np.ndarray, tone: str, cfg: DetectConfig, border_thickness: float
) -> list[Detection]:
    """사진에서 패드를 **전부** 찾는다. 면적 큰 순. 없으면 빈 목록.

    이진화를 세 겹으로 시도한다.

    1. 사진 전체에 오츠 임계 하나 (가장 흔한 경우이고 가장 빠르다)
    2. 그 임계를 인쇄색 쪽으로 넓혀 가며 재시도 — 패드가 밝게 찍혀 테두리가
       임계에 걸린 사진을 건진다
    3. 주변 평균과 견주는 국소 이진화 — 요철 도장면이나 이음새처럼 배경이
       어두워 테두리가 배경과 한 덩어리가 되는 사진을 건진다

    **하나를 찾아도 나머지 단계를 마저 본다.** 한 화면의 두 패드가 서로 다른
    임계에서만 보이는 일이 실제로 있다 — 밝은 자리의 패드는 첫 단계에서
    잡히고, 그늘에 있는 패드는 국소 이진화까지 가야 잡힌다. 앞 단계에서
    멈추면 뒤엣것이 조용히 사라진다. 같은 패드가 여러 단계에서 잡히는 것은
    겹침으로 걸러 낸다.

    꼭짓점은 어느 방식으로 찾았든 원본 밝기 단면에서 다시 맞추므로, 정밀도가
    이진화 방식에 좌우되지 않는다.
    """
    found: list[Detection] = []

    def collect(binary: np.ndarray) -> None:
        for det in _detect_in(gray, binary, tone, cfg, border_thickness):
            if not any(_overlaps(det, other) for other in found):
                found.append(det)

    for scale in cfg.threshold_scales or [1.0]:
        collect(_binarize(gray, tone, cfg, scale))

    if cfg.local_fallback:
        for open_px in cfg.local_open_steps or [0]:
            collect(_binarize_local(gray, tone, cfg, open_px))

    found.sort(key=lambda d: d.area, reverse=True)
    return found


def detect_pad(
    gray: np.ndarray, tone: str, cfg: DetectConfig, border_thickness: float
) -> Detection | None:
    """가장 크게 찍힌 패드 하나. 여러 개가 찍혔는지 알 수 없으므로 진단용이다."""
    found = detect_pads(gray, tone, cfg, border_thickness)
    return found[0] if found else None


def _overlaps(a: Detection, b: Detection) -> bool:
    """두 검출이 사실상 같은 패드인지. 중심 거리가 작은 쪽 크기의 절반 안이면 같다.

    바깥 테두리로 맞춘 것과 안쪽에서 되짚은 것이 같은 패드를 두 번 내놓을 수
    있어, 목록에 담기 전에 걸러 낸다.
    """
    ca, cb = a.corners.mean(axis=0), b.corners.mean(axis=0)
    smaller = min(np.sqrt(a.area), np.sqrt(b.area))
    return float(np.linalg.norm(ca - cb)) < smaller * 0.5


def _detect_in(
    gray: np.ndarray,
    binary: np.ndarray,
    tone: str,
    cfg: DetectConfig,
    border_thickness: float,
) -> list[Detection]:
    """이진 이미지 하나에서 패드를 전부 찾는다.

    후보마다 바깥 테두리로 먼저 맞춰 보고, 맞춘 결과가 규격과 어긋나면 안쪽
    테두리로 다시 맞춘다. 둘 다 어긋나면 그 후보를 버린다.
    """
    out: list[Detection] = []

    def keep(det: Detection) -> None:
        if not any(_overlaps(det, other) for other in out):
            out.append(det)

    for quad, hole in _candidate_quads(binary, cfg):
        found = _fit_quad(gray, quad, cfg)
        if found is not None and border_matches(
            gray, found.corners, tone, border_thickness, cfg
        ):
            keep(found)
            continue

        if hole is None:
            continue
        inner = _fit_quad(gray, hole, cfg)
        if inner is None:
            continue
        outer = _outer_from_inner(inner.corners, border_thickness)
        if outer is None:
            continue
        if border_matches(gray, outer, tone, border_thickness, cfg):
            keep(
                Detection(
                    corners=outer,
                    coarse_corners=quad,
                    area=quad_area(outer),
                    edge_sample_counts=inner.edge_sample_counts,
                    edge_residuals=inner.edge_residuals,
                )
            )
    return out


def _outer_from_inner(inner: np.ndarray, border_thickness: float) -> np.ndarray | None:
    """안쪽 테두리 꼭짓점에서 바깥 테두리 꼭짓점을 복원한다.

    테두리 두께는 규격으로 알고 있으므로, 안쪽 사각형이 정규화 좌표에서
    ``[t, 1-t]`` 구간에 놓인다는 사실만으로 바깥이 결정된다. 중심에서 일정
    배율로 늘리지 않고 사영변환으로 되짚는 이유는, 비스듬히 찍힌 사진에서는
    단순 확대가 맞지 않기 때문이다.
    """
    t = float(border_thickness)
    if not (0.0 < t < 0.4):
        return None
    src = np.array(
        [[t, t], [1.0 - t, t], [1.0 - t, 1.0 - t], [t, 1.0 - t]], np.float32
    )
    matrix = cv2.getPerspectiveTransform(src, inner.astype(np.float32))
    unit = np.array([[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]], np.float32)
    return cv2.perspectiveTransform(unit, matrix)[0].astype(np.float64)


def _fit_quad(
    gray: np.ndarray, quad: np.ndarray, cfg: DetectConfig
) -> Detection | None:
    """근사 사각형의 네 변을 서브픽셀로 맞춰 꼭짓점을 낸다."""
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
            return None
        refined = _refine_edge(gray, p0, p1, outward / norm, cfg)
        if refined is None:
            return None
        direction, origin, count, residual = refined
        lines.append((direction, origin))
        counts.append(count)
        residuals.append(residual)

    corners = []
    for i in range(4):
        # 꼭짓점 i 는 변 (i-1)->i 와 변 i->(i+1) 이 만나는 곳이다.
        prev_dir, prev_pt = lines[(i - 1) % 4]
        curr_dir, curr_pt = lines[i]
        point = intersect_lines(prev_dir, prev_pt, curr_dir, curr_pt)
        if point is None:
            return None
        corners.append(point)

    refined_quad = order_corners(np.array(corners))
    # 정제 결과가 근사 사각형에서 크게 벗어나면 잘못 맞춘 것이다.
    drift = np.linalg.norm(refined_quad - quad, axis=1).max()
    if drift > 0.05 * np.sqrt(quad_area(quad)):
        return None

    return Detection(
        corners=refined_quad,
        coarse_corners=quad,
        area=quad_area(refined_quad),
        edge_sample_counts=tuple(counts),  # type: ignore[arg-type]
        edge_residuals=tuple(residuals),  # type: ignore[arg-type]
    )
