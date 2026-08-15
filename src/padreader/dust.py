"""분진 픽셀 추출.

여백에서 분진에 해당하는 픽셀을 판정한다. 두 가지 깊이를 함께 낸다.

``uniform_depth``
    패드 전체의 **깨끗한 톤** 대비 얼마나 어두운지. 넓고 고르게 깔린
    분진을 재는 데 쓴다. 국소 배경 대비로 재면 넓게 퍼질수록 주변도 같이
    어두워져 값이 깎이므로 쓰지 않는다.

``local_depth``
    **국소 배경** 대비 얼마나 어두운지. 한 곳에 뭉친 덩어리를 찾는 데 쓴다.
    국소 배경은 형태학적 닫힘으로 추정한다. 창보다 작은 얼룩은 닫힘에서
    지워지므로, 닫힘 결과가 곧 '얼룩이 없었다면 그 자리가 어땠을 밝기'다.

두 깊이 모두 **테두리 잉크를 1 로 놓은 척도**로 정규화한다. 조명 정규화가
이미 여백을 테두리로 나눠 놓았으므로, 배경에서 1 까지가 그 자리에서 가능한
전체 폭이다. 그 폭 대비 얼마나 갔는지를 깊이로 삼으면 0 이 깨끗한 상태,
1 이 잉크만큼 짙은 상태가 되어 톤과 촬영 조건에 무관해진다.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import DustConfig, QualityConfig
from .result import ExclusionReason
from .spec import PadSpec

MIN_TONE_SPAN = 0.05
"""배경과 잉크 사이의 최소 폭. 이보다 좁으면 그 자리에서 분진과 배경을
구분할 대비가 없다는 뜻이다. 나눗셈이 폭주하지 않도록 막는다."""

BACKGROUND_WORK_WINDOW = 21
"""국소 배경을 계산할 때 쓸 실제 커널 크기.

배경은 정의상 완만하므로 원본 해상도에서 큰 커널을 돌릴 이유가 없다.
영상을 줄여 이 크기로 계산한 뒤 다시 키운다.
"""


@dataclass
class DustMap:
    """사진 한 장에서 뽑아낸 분진 정보."""

    uniform_depth: np.ndarray
    """패드 전체의 깨끗한 톤 대비 깊이. 여백 크기의 배열."""

    local_depth: np.ndarray
    """국소 배경 대비 깊이. 여백 크기의 배열."""

    measurable: np.ndarray
    """측정 대상 픽셀. 여백에서 제외 영역을 뺀 것."""

    excluded_pixels: dict[str, int]
    """제외된 픽셀 수. 사유별."""

    origin: tuple[int, int]
    """여백 영역이 정면 보정 이미지에서 시작하는 (x, y)."""


def _odd(value: int) -> int:
    return value if value % 2 else value + 1


def _print_mask(spec: PadSpec, pad_size_px: int, margin_box) -> np.ndarray:
    """여백 안에 걸친 인쇄물 픽셀.

    규격상 여백에는 인쇄물이 없지만, 도안이 바뀌어 들어오면 그 자리가 늘
    어두우므로 분진으로 오인된다. 좌표를 알고 있으니 그냥 뺀다.
    """
    mx0, my0, mx1, my1 = margin_box
    mask = np.zeros((my1 - my0, mx1 - mx0), bool)

    for rect in spec.print_element_rects().values():
        x0, y0, x1, y1 = rect.to_pixels(pad_size_px)
        ix0, iy0 = max(x0, mx0), max(y0, my0)
        ix1, iy1 = min(x1, mx1), min(y1, my1)
        if ix0 < ix1 and iy0 < iy1:
            mask[iy0 - my0 : iy1 - my0, ix0 - mx0 : ix1 - mx0] = True
    return mask


def _local_background(reflectance: np.ndarray, window: int, tone: str) -> np.ndarray:
    """얼룩이 없었다면 그 자리가 어땠을 밝기.

    백색 바탕에서는 분진이 어두우므로 닫힘으로 어두운 얼룩을 메우고,
    흑색 바탕에서는 분진이 밝으므로 열림으로 밝은 얼룩을 깎는다.
    """
    operation = cv2.MORPH_CLOSE if tone == "white" else cv2.MORPH_OPEN
    height, width = reflectance.shape[:2]

    factor = max(1, window // BACKGROUND_WORK_WINDOW)
    if factor > 1:
        small = cv2.resize(
            reflectance,
            (max(1, width // factor), max(1, height // factor)),
            interpolation=cv2.INTER_AREA,
        )
        size = _odd(max(3, window // factor))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        background = cv2.morphologyEx(
            small, operation, kernel, borderType=cv2.BORDER_REPLICATE
        )
        return cv2.resize(background, (width, height), interpolation=cv2.INTER_LINEAR)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (window, window))
    return cv2.morphologyEx(reflectance, operation, kernel, borderType=cv2.BORDER_REPLICATE)


def _depth(region: np.ndarray, background: np.ndarray, tone: str) -> np.ndarray:
    """배경에서 잉크(=1) 까지의 폭 대비 얼마나 갔는지."""
    span = background - 1.0 if tone == "white" else 1.0 - background
    span = np.maximum(span, MIN_TONE_SPAN)
    shift = (background - region) if tone == "white" else (region - background)
    return np.clip(shift / span, 0.0, 1.0).astype(np.float32)


def extract_dust(
    reflectance: np.ndarray,
    rectified_gray: np.ndarray,
    spec: PadSpec,
    tone: str,
    cfg: DustConfig,
    quality_cfg: QualityConfig,
    pad_size_px: int,
) -> DustMap:
    """여백에서 분진 깊이 두 가지를 낸다."""
    margin_box = spec.margin.to_pixels(pad_size_px)
    mx0, my0, mx1, my1 = margin_box

    region = reflectance[my0:my1, mx0:mx1].astype(np.float32)
    region_gray = rectified_gray[my0:my1, mx0:mx1]

    # --- 제외 영역 ---
    printed = _print_mask(spec, pad_size_px, margin_box)

    saturated = np.zeros(region_gray.shape, bool)
    if quality_cfg.saturation_bright_level is not None:
        saturated |= region_gray >= quality_cfg.saturation_bright_level
    if quality_cfg.saturation_dark_level is not None:
        saturated |= region_gray <= quality_cfg.saturation_dark_level

    measurable = ~(printed | saturated)

    # --- 고름: 패드 전체의 깨끗한 톤 대비 ---
    if measurable.any():
        values = region[measurable]
        percentile = float(np.clip(cfg.clean_percentile, 50.0, 100.0))
        clean_level = float(
            np.percentile(values, percentile if tone == "white" else 100.0 - percentile)
        )
    else:
        clean_level = 1.0 + MIN_TONE_SPAN

    clean_plane = np.full(region.shape, clean_level, np.float32)
    uniform_depth = _depth(region, clean_plane, tone)
    uniform_depth = np.where(measurable, uniform_depth, 0.0).astype(np.float32)

    # --- 국소: 국소 배경 대비 ---
    window = _odd(max(3, int(round(cfg.local_window * pad_size_px))))
    background = _local_background(region, window, tone)
    local_depth = _depth(region, background, tone)
    local_depth = np.where(measurable, local_depth, 0.0).astype(np.float32)

    return DustMap(
        uniform_depth=uniform_depth,
        local_depth=local_depth,
        measurable=measurable,
        excluded_pixels={
            ExclusionReason.PRINT_ELEMENT.value: int(printed.sum()),
            ExclusionReason.SATURATED.value: int((saturated & ~printed).sum()),
        },
        origin=(mx0, my0),
    )
