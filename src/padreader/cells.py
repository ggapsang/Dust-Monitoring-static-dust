"""구획별 측정과 비분진 배제.

측정 여백을 격자로 나눠 구획마다 대표 반사율을 낸다. 여백에는 인쇄물이
전혀 들어가지 않도록 규격이 잡혀 있어 마스킹이 필요 없다. 그래도 마스크를
계산하는 이유는 도안이 바뀌어 인쇄물이 여백으로 들어왔을 때 조용히 오염된
값을 내는 대신 해당 구획을 배제하기 위해서다.

채도로 변색(녹·유분·결로)을 걸러낸다. 지표를 고르는 데 함정이 있다.
OpenCV 8비트 HSV 의 S 는 ``255*(max-min)/max`` 로 **화소 자신**을 분모에
쓴다. 그래서 어두운 화소에서 폭주하고, 측정 영역 전체가 어두운 흑색 바탕
패드에서는 전 구획이 배제 대상이 된다.

여기서는 두 가지를 모두 낸다.

- ``chroma_norm`` = ``(max-min) / scale``. 분모가 화소가 아니라 현재
  조명에서의 전체 다이내믹 레인지라 폭주하지 않으면서 조명 불변이다.
- ``chroma_abs`` = ``max-min``. 폭주하지는 않지만 노출에 의존해서, 조명이
  바뀌면 임계값을 다시 잡아야 한다.

배제 판정에는 설정이 고른 쪽만 쓰고, 어느 쪽이 실제 변색과 잘 맞는지는
실증에서 두 값의 분포를 보고 정한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import ExcludeConfig, GridConfig, QualityConfig
from .result import Cell, ExclusionReason
from .spec import PadSpec, Rect


@dataclass
class CellGrid:
    cells: list[Cell]
    rows: int
    cols: int
    bounds: list[tuple[int, int, int, int]]
    """구획별 픽셀 범위 (x0, y0, x1, y1). 시각화가 쓴다."""

    @property
    def measured(self) -> list[Cell]:
        return [c for c in self.cells if c.excluded is None]


def _print_mask(spec: PadSpec, margin: Rect, pad_size_px: int) -> np.ndarray | None:
    """여백 안에 걸친 인쇄물 마스크. 겹치는 것이 없으면 ``None``."""
    mx0, my0, mx1, my1 = margin.to_pixels(pad_size_px)
    mask = np.zeros((my1 - my0, mx1 - mx0), bool)
    touched = False

    for rect in spec.print_element_rects().values():
        x0, y0, x1, y1 = rect.to_pixels(pad_size_px)
        ix0, iy0 = max(x0, mx0), max(y0, my0)
        ix1, iy1 = min(x1, mx1), min(y1, my1)
        if ix0 < ix1 and iy0 < iy1:
            mask[iy0 - my0 : iy1 - my0, ix0 - mx0 : ix1 - mx0] = True
            touched = True

    return mask if touched else None


def measure_cells(
    reflectance: np.ndarray,
    rectified_bgr: np.ndarray,
    rectified_gray: np.ndarray,
    spec: PadSpec,
    scale: float,
    grid_cfg: GridConfig,
    exclude_cfg: ExcludeConfig,
    quality_cfg: QualityConfig,
    pad_size_px: int,
) -> CellGrid:
    """여백을 격자로 나눠 구획별 값을 산출한다."""
    margin = spec.margin
    mx0, my0, mx1, my1 = margin.to_pixels(pad_size_px)

    region_reflectance = reflectance[my0:my1, mx0:mx1]
    region_gray = rectified_gray[my0:my1, mx0:mx1]
    region_bgr = rectified_bgr[my0:my1, mx0:mx1]

    channel_max = region_bgr.max(axis=2).astype(np.float64)
    channel_min = region_bgr.min(axis=2).astype(np.float64)
    chroma_abs_map = channel_max - channel_min
    chroma_norm_map = chroma_abs_map / max(abs(scale), 1e-6)

    saturated_map = (region_gray >= quality_cfg.saturation_bright_level) | (
        region_gray <= quality_cfg.saturation_dark_level
    )
    invalid_map = _print_mask(spec, margin, pad_size_px)

    height, width = region_reflectance.shape[:2]
    row_edges = np.linspace(0, height, grid_cfg.rows + 1).round().astype(int)
    col_edges = np.linspace(0, width, grid_cfg.cols + 1).round().astype(int)

    cells: list[Cell] = []
    bounds: list[tuple[int, int, int, int]] = []

    for r in range(grid_cfg.rows):
        for c in range(grid_cfg.cols):
            y0, y1 = int(row_edges[r]), int(row_edges[r + 1])
            x0, x1 = int(col_edges[c]), int(col_edges[c + 1])
            bounds.append((mx0 + x0, my0 + y0, mx0 + x1, my0 + y1))

            block_reflectance = region_reflectance[y0:y1, x0:x1]
            total = block_reflectance.size
            if total == 0:
                cells.append(
                    Cell(r, c, None, None, None, None, None, 0.0, ExclusionReason.MASKED)
                )
                continue

            if invalid_map is None:
                valid = np.ones(block_reflectance.shape, bool)
            else:
                valid = ~invalid_map[y0:y1, x0:x1]
            valid_ratio = float(valid.mean())

            block_saturated = saturated_map[y0:y1, x0:x1]
            saturated_ratio = float(block_saturated.mean())
            chroma_norm = float(np.median(chroma_norm_map[y0:y1, x0:x1][valid])) if valid.any() else None
            chroma_abs = float(np.median(chroma_abs_map[y0:y1, x0:x1][valid])) if valid.any() else None

            reason: ExclusionReason | None = None
            if valid_ratio < grid_cfg.min_valid_pixel_ratio:
                reason = ExclusionReason.MASKED
            elif (
                exclude_cfg.max_saturated_ratio is not None
                and saturated_ratio > exclude_cfg.max_saturated_ratio
            ):
                reason = ExclusionReason.SATURATED
            elif exclude_cfg.max_chroma is not None:
                chosen = chroma_norm if exclude_cfg.chroma_metric == "norm" else chroma_abs
                if chosen is not None and chosen > exclude_cfg.max_chroma:
                    reason = ExclusionReason.CHROMA

            if reason is None:
                # 포화 화소는 대표값 계산에서 빼되, 구획 자체는 살린다.
                usable = valid & ~block_saturated
                if not usable.any():
                    usable = valid
                value = float(np.median(block_reflectance[usable]))
            else:
                value = None

            cells.append(
                Cell(
                    row=r,
                    col=c,
                    value=None,
                    reflectance=value,
                    chroma_norm=chroma_norm,
                    chroma_abs=chroma_abs,
                    saturated_ratio=saturated_ratio,
                    valid_pixel_ratio=valid_ratio,
                    excluded=reason,
                )
            )

    return CellGrid(cells=cells, rows=grid_cfg.rows, cols=grid_cfg.cols, bounds=bounds)
