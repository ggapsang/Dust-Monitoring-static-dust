"""선군 대비 산출.

굵기가 다른 네 단계의 선과 바로 인접한 여백 사이의 대비를 잰다. 여백 방식과
선군 방식 중 어느 쪽이 미세 오염에 먼저 반응하는지 같은 이미지 안에서
비교하기 위한 실증용 지표이며, 상시 지표가 아니다.

대비는 두 값의 **차이**로 낸다. 정규화된 반사율이 이미 '인쇄 흑색 0,
인쇄 백색 1' 척도라서, 차이가 곧 '원래 대비의 몇 %가 남았는가' 가 된다.
1 이면 선이 또렷하고 0 이면 여백과 구분되지 않는다.

Michelson 형태(``|a-b| / (|a|+|b|)``)를 쓰지 않는 이유: 이 척도에서 선은
잉크라 값이 0 근처에 깔린다. 그러면 분모가 분자와 같아져 대비가 굵기와
무관하게 항상 1 로 포화되고, 어느 단계가 먼저 반응하는지를 볼 수 없다.
"""

from __future__ import annotations

import numpy as np

from .result import LineContrast
from .spec import PadSpec

HORIZONTAL_INSET = 0.05
"""선 ROI 를 가로로 얼마나 좁힐지. 양 끝의 인쇄 번짐을 피한다."""

VERTICAL_INSET_RATIO = 0.25
"""선 ROI 를 세로로 굵기의 몇 배만큼 좁힐지.

가장 얇은 단계는 몇 픽셀뿐이라 고정 픽셀로 좁히면 아무것도 남지 않는다.
굵기에 비례해 좁혀야 단계마다 같은 비율의 안쪽만 본다.
"""


def _median_of(reflectance: np.ndarray, rect, pad_size_px: int) -> float | None:
    x0, y0, x1, y1 = rect.to_pixels(pad_size_px)
    height, width = reflectance.shape[:2]
    x0, x1 = max(0, x0), min(width, x1)
    y0, y1 = max(0, y0), min(height, y1)
    if x0 >= x1 or y0 >= y1:
        return None
    return float(np.median(reflectance[y0:y1, x0:x1]))


def measure_lines(
    reflectance: np.ndarray, spec: PadSpec, pad_size_px: int
) -> list[LineContrast]:
    """단계별 선-여백 대비."""
    out: list[LineContrast] = []
    gaps = spec.line_gap_rects()

    for index, (bar, gap_rect) in enumerate(zip(spec.line_bars, gaps)):
        line_rect = bar.rect(spec.line_group_x0, spec.line_group_x1)
        horizontal = line_rect.width * HORIZONTAL_INSET
        vertical = bar.thickness * VERTICAL_INSET_RATIO
        shrunk = type(line_rect)(
            line_rect.x0 + horizontal,
            line_rect.y0 + vertical,
            line_rect.x1 - horizontal,
            line_rect.y1 - vertical,
        )

        line_level = _median_of(reflectance, shrunk, pad_size_px)
        gap_level = _median_of(reflectance, gap_rect, pad_size_px)

        contrast: float | None = None
        if line_level is not None and gap_level is not None:
            contrast = float(abs(gap_level - line_level))

        out.append(
            LineContrast(
                index=index,
                thickness_px=float(bar.thickness * pad_size_px),
                contrast=contrast,
                line_level=line_level,
                gap_level=gap_level,
            )
        )

    return out
