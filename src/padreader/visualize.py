"""오염도 분포 시각화.

기준 대비 어디가 얼마나 오염되었는지를 눈으로 확인한다.

    파랑-빨강   기준 대비 밝기가 얼마나 내려갔는지
    초록 사각형 측정 영역

국소 축은 그리지 않는다. 실제 분진은 밀가루처럼 고와서 낱알이 수백~수천
개로 흩어지는데, 덩어리마다 표시를 하면 화면이 통째로 덮여 정작 어디가
심한지가 안 보인다. 뭉친 자리는 히트맵에서 짙은 색으로 이미 드러난다.
"""

from __future__ import annotations

import cv2
import numpy as np

from .result import DustScores
from .spec import PadSpec

MARGIN_COLOR = (0, 220, 0)
EXCLUDED_DIM = 0.45

MIN_HEAT_SPAN = 0.05
"""히트맵 색 범위의 최소 폭. 색 범위를 고정하지 않을 때만 쓴다.

실제 편차가 좁은데 최소-최대로 늘려 칠하면 노이즈가 색상환 전체로 펼쳐져
깨끗한 패드가 심하게 얼룩진 것처럼 보인다.
"""


def _caption(image: np.ndarray, lines: list[str]) -> None:
    """이미지 하단에 읽을 수 있는 줄을 얹는다."""
    scale = max(0.4, image.shape[1] / 1600.0)
    thickness = max(1, int(round(scale * 2)))
    font = cv2.FONT_HERSHEY_SIMPLEX

    sizes = [cv2.getTextSize(text, font, scale, thickness)[0] for text in lines]
    height = max(size[1] for size in sizes) + 8
    width = max(size[0] for size in sizes)

    top = image.shape[0] - height * len(lines) - 8
    cv2.rectangle(
        image, (4, top - 6), (width + 16, image.shape[0] - 4), (0, 0, 0), cv2.FILLED
    )
    for index, text in enumerate(lines):
        cv2.putText(
            image, text, (10, top + height * (index + 1) - 6), font, scale,
            (255, 255, 255), thickness, cv2.LINE_AA,
        )


def draw_distribution(
    rectified_bgr: np.ndarray,
    uniform_diff: np.ndarray,
    measurable: np.ndarray,
    origin: tuple[int, int],
    scores: DustScores,
    spec: PadSpec,
    pad_size_px: int,
    heat_max: float | None,
) -> np.ndarray:
    """기준 대비 오염도 분포 이미지.

    ``heat_max`` 는 빨강이 가리킬 값이다. 고정해 두면 두 장을 색으로 바로
    견줄 수 있다. ``None`` 이면 사진마다 그 안의 최댓값까지 늘려 칠한다.
    """
    canvas = rectified_bgr.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)

    ox, oy = origin
    height, width = uniform_diff.shape
    region = canvas[oy : oy + height, ox : ox + width]

    values = uniform_diff[measurable]
    observed = float(values.max()) if values.size else 0.0

    if heat_max is not None and heat_max > 0:
        high = float(heat_max)
    else:
        # 고정하지 않을 때. 편차가 좁으면 최소 폭까지만 벌린다.
        high = max(observed, MIN_HEAT_SPAN)

    scaled = np.clip(uniform_diff / high, 0.0, 1.0)
    heat = cv2.applyColorMap((scaled * 255).astype(np.uint8), cv2.COLORMAP_JET)
    blended = cv2.addWeighted(heat, 0.55, region, 0.45, 0)
    region[:] = np.where(measurable[..., None], blended, region)

    # 제외된 자리는 눌러서 측정에서 빠졌음을 보인다.
    excluded = ~measurable
    if excluded.any():
        region[excluded] = (region[excluded] * EXCLUDED_DIM).astype(np.uint8)

    mx0, my0, mx1, my1 = spec.margin.to_pixels(pad_size_px)
    cv2.rectangle(canvas, (mx0, my0), (mx1 - 1, my1 - 1), MARGIN_COLOR, 2)

    # 색 범위를 고정했으면 그 사실과 실제 최댓값을 같이 적는다. 잘린 화소가
    # 있는지 눈으로는 알 수 없기 때문이다.
    fixed = heat_max is not None and heat_max > 0
    heat_line = f"heat 0..{high:.2f}"
    heat_line += f" fixed (max {observed:.2f})" if fixed else " auto"

    _caption(
        canvas,
        [
            f"uniform {scores.uniform:.3f}  localized {scores.localized:.3f}"
            f"  combined {scores.combined:.3f}"
            if scores.combined is not None
            else "score n/a",
            heat_line,
        ],
    )
    return canvas
