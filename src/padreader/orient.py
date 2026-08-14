"""회전 방향 판정.

모서리 블록은 네 모서리 중 세 곳에만 인쇄되어 있다. 비어 있는 한 곳이
어디인지로 패드가 0/90/180/270 중 어느 방향으로 붙어 있는지가 정해진다.

판정 자체는 "네 자리 중 가장 바탕색에 가까운 곳 찾기" 로 간단하지만, 그
결과를 얼마나 믿을 수 있는지가 더 중요하다. 그래서 판정 마진을 함께 낸다.
마진은 '비어 있는 자리와 그 다음으로 빈 자리의 차이'를 '잉크와 바탕의 전체
대비'로 나눈 값이다. 분모를 전체 대비로 잡아야 값이 조명·노출과 무관해지고,
도안 결함으로 빈 자리가 부분적으로 채워진 경우가 낮은 마진으로 드러난다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import CORNER_NAMES
from .rectify import crop
from .spec import PadSpec

CORNER_ROI_INSET = 0.2
"""모서리 블록 ROI 를 안쪽으로 얼마나 좁혀 볼지 (블록 한 변 대비).

경계의 잉크 번짐과 사영변환 잔차를 피한다.
"""


@dataclass
class Orientation:
    rotation_index: int
    """꼭짓점 순서를 몇 칸 돌려야 하는지 (0-3). 90도 단위 회전량과 같다."""

    rotation_deg: int
    margin: float
    """판정 신뢰도. 1 에 가까울수록 확실하고, 0 이면 구분이 안 된다."""

    corner_inkness: dict[str, float]
    """자리별 잉크 정도(0-1). 진단용."""


def _inkness(values: np.ndarray, tone: str) -> np.ndarray:
    """밝기를 '잉크에 가까운 정도' 로 바꾼다.

    백색 바탕 패드는 인쇄가 어둡고 흑색 바탕 패드는 밝다. 여기서 뒤집어
    두면 이후 판정 로직이 톤에 무관해진다.
    """
    return 255.0 - values if tone == "white" else values


def determine_orientation(
    rectified_gray: np.ndarray,
    spec: PadSpec,
    tone: str,
    pad_size_px: int,
) -> Orientation:
    """잠정 순서로 보정한 이미지에서 회전량을 판정한다.

    Parameters
    ----------
    rectified_gray
        꼭짓점을 **아직 회전 보정하지 않은** 순서로 정면 보정한 흑백 이미지.
    """
    inkness: dict[str, float] = {}
    for name, rect in spec.corner_blocks.items():
        inset = rect.width * CORNER_ROI_INSET
        patch = crop(rectified_gray, rect.inset(inset), pad_size_px)
        inkness[name] = float(np.median(_inkness(patch.astype(np.float64), tone)))

    # 전체 대비: 테두리(순수 잉크)와 여백의 가장 깨끗한 쪽(바탕에 가장 가까운
    # 곳) 사이. 여백은 분진이 앉아 잉크 쪽으로 끌려가므로 하위 분위수를 쓴다.
    ring = np.concatenate(
        [
            crop(rectified_gray, rect, pad_size_px).ravel()
            for rect in spec.border_ring_rects()
        ]
    )
    ink_level = float(np.median(_inkness(ring.astype(np.float64), tone)))
    margin_patch = crop(rectified_gray, spec.margin, pad_size_px)
    background_level = float(
        np.percentile(_inkness(margin_patch.astype(np.float64), tone), 10)
    )
    contrast = max(ink_level - background_level, 1e-6)

    ordered = sorted(inkness.items(), key=lambda item: item[1])
    empty_name, empty_value = ordered[0]
    runner_up = ordered[1][1]
    margin = float(np.clip((runner_up - empty_value) / contrast, 0.0, 1.5))

    # 규격상 비어 있어야 할 자리를 실제로 빈 자리에 맞추려면 몇 칸 돌려야 하나.
    found = CORNER_NAMES.index(empty_name)
    expected = CORNER_NAMES.index(spec.empty_corner)
    rotation_index = (found - expected) % 4

    return Orientation(
        rotation_index=rotation_index,
        rotation_deg=rotation_index * 90,
        margin=margin,
        corner_inkness={k: round(v, 2) for k, v in inkness.items()},
    )


def apply_rotation(corners: np.ndarray, rotation_index: int) -> np.ndarray:
    """판정된 회전량만큼 꼭짓점 순서를 돌린다.

    돌린 뒤 다시 정면 보정하면 비어 있는 모서리가 규격 자리로 온다.
    """
    return np.roll(corners, -rotation_index, axis=0)
