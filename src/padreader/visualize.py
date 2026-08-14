"""판독 과정 시각화.

무엇을 어디서 쟀는지 눈으로 확인할 수 있어야 임계값을 조정할 수 있다.
구획 색은 오염도를 그대로 표현하고, 배제된 구획은 사유별로 다르게 표시해
'왜 빠졌는지'가 이미지만으로 읽히게 한다.
"""

from __future__ import annotations

import cv2
import numpy as np

from .cells import CellGrid
from .result import ExclusionReason
from .spec import PadSpec

EXCLUSION_COLORS: dict[ExclusionReason, tuple[int, int, int]] = {
    ExclusionReason.MASKED: (128, 128, 128),
    ExclusionReason.CHROMA: (255, 128, 0),
    ExclusionReason.SATURATED: (0, 200, 255),
}

ROI_COLOR = (0, 220, 0)
ANCHOR_WHITE_COLOR = (255, 255, 255)
ANCHOR_BLACK_COLOR = (60, 60, 60)

MIN_HEAT_SPAN = 0.05
"""히트맵 색 범위의 최소 폭.

구획 값을 최소~최대로 늘려 칠하면, 균일하게 침착된 패드에서 편차가 0.001
밖에 안 되는데도 노이즈가 색상환 전체로 펼쳐져 강한 기울기처럼 보인다.
실제로 균일한 것은 균일하게 보여야 한다.
"""


def _heat(value: float, low: float, high: float) -> tuple[int, int, int]:
    """오염도를 파랑(낮음)-빨강(높음) 으로."""
    span = max(high - low, 1e-6)
    t = float(np.clip((value - low) / span, 0.0, 1.0))
    color = cv2.applyColorMap(np.array([[int(t * 255)]], np.uint8), cv2.COLORMAP_JET)
    b, g, r = color[0, 0].tolist()
    return int(b), int(g), int(r)


def _rect(image: np.ndarray, rect, pad_size_px: int, color, thickness: int = 2) -> None:
    x0, y0, x1, y1 = rect.to_pixels(pad_size_px)
    cv2.rectangle(image, (x0, y0), (x1 - 1, y1 - 1), color, thickness)


def draw_overlay(
    rectified_bgr: np.ndarray,
    grid: CellGrid,
    spec: PadSpec,
    pad_size_px: int,
) -> np.ndarray:
    """구획 분할과 측정 결과를 겹쳐 그린 이미지."""
    canvas = rectified_bgr.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)

    measured = [c.value for c in grid.measured if c.value is not None]
    if measured:
        low, high = min(measured), max(measured)
        # 실제 폭이 좁으면 가운데를 기준으로 최소 폭까지 벌린다.
        if high - low < MIN_HEAT_SPAN:
            middle = (low + high) / 2.0
            low, high = middle - MIN_HEAT_SPAN / 2.0, middle + MIN_HEAT_SPAN / 2.0
    else:
        low, high = 0.0, 1.0

    fill = canvas.copy()
    for cell, (x0, y0, x1, y1) in zip(grid.cells, grid.bounds):
        if cell.excluded is not None:
            color = EXCLUSION_COLORS.get(cell.excluded, (0, 0, 255))
        elif cell.value is None:
            color = (0, 0, 0)
        else:
            color = _heat(cell.value, low, high)
        cv2.rectangle(fill, (x0, y0), (x1 - 1, y1 - 1), color, cv2.FILLED)

    cv2.addWeighted(fill, 0.45, canvas, 0.55, 0, canvas)

    for _, (x0, y0, x1, y1) in zip(grid.cells, grid.bounds):
        cv2.rectangle(canvas, (x0, y0), (x1 - 1, y1 - 1), (255, 255, 255), 1)

    # 측정 여백과 조도 기준 영역이 어디인지 표시한다.
    _rect(canvas, spec.margin, pad_size_px, ROI_COLOR, 2)
    for rect in spec.border_ring_rects():
        _rect(canvas, rect, pad_size_px, ROI_COLOR, 1)
    for rect in spec.anchor_white:
        _rect(canvas, rect, pad_size_px, ANCHOR_WHITE_COLOR, 2)
    for rect in spec.anchor_black:
        _rect(canvas, rect, pad_size_px, ANCHOR_BLACK_COLOR, 2)

    # 비어 있어야 할 모서리를 표시해 회전이 맞았는지 한눈에 보이게 한다.
    _rect(canvas, spec.corner_blocks[spec.empty_corner], pad_size_px, (0, 0, 255), 2)

    # 색이 무엇을 뜻하는지 적어 둔다. 이게 없으면 색만 보고 오염 정도를
    # 짐작하게 되는데, 범위가 이미지마다 달라 서로 다른 패드를 비교할 수 없다.
    if measured:
        label = (
            f"cell {min(measured):.4f}..{max(measured):.4f}"
            f"  color {low:.3f}..{high:.3f}"
        )
        _caption(canvas, label)

    return canvas


def _caption(image: np.ndarray, text: str) -> None:
    """이미지 하단에 읽을 수 있는 한 줄을 얹는다."""
    scale = max(0.4, image.shape[1] / 1600.0)
    thickness = max(1, int(round(scale * 2)))
    (width, height), _ = cv2.getTextSize(
        text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness
    )
    x = 8
    y = image.shape[0] - 8
    cv2.rectangle(
        image, (x - 4, y - height - 6), (x + width + 4, y + 6), (0, 0, 0), cv2.FILLED
    )
    cv2.putText(
        image, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale,
        (255, 255, 255), thickness, cv2.LINE_AA,
    )


def draw_detection(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """원본 위에 검출된 꼭짓점과 변을 그린다."""
    canvas = image.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)

    points = corners.astype(np.int32)
    cv2.polylines(canvas, [points], True, ROI_COLOR, 2)
    for index, (x, y) in enumerate(points):
        cv2.circle(canvas, (int(x), int(y)), 6, (0, 0, 255), -1)
        cv2.putText(
            canvas, str(index), (int(x) + 8, int(y) - 8),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA
        )
    return canvas
