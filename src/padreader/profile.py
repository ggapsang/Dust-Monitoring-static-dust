"""에지 단면 샘플링.

패드 검출의 서브픽셀 정제와 선명도 측정이 같은 것을 본다 — 테두리 경계를
가로지르는 밝기 단면이다. 한쪽은 경계가 **어디인지**를, 다른 쪽은 경계가
**얼마나 완만한지**를 쓴다. 샘플링을 여기 모아 두 곳이 같은 것을 재게 한다.
"""

from __future__ import annotations

import cv2
import numpy as np


def sample_across(
    gray: np.ndarray,
    centers: np.ndarray,
    outward: np.ndarray,
    radius: int,
) -> np.ndarray:
    """각 중심점에서 ``outward`` 방향으로 밝기 단면을 뜬다.

    반환은 ``(N, 2*radius+1)``. 열 0 이 안쪽(잉크), 마지막 열이 바깥이다.
    쌍선형 보간으로 읽으므로 정수 격자에 갇히지 않는다.
    """
    offsets = np.arange(-radius, radius + 1, dtype=np.float32)
    map_x = (centers[:, 0][:, None] + outward[0] * offsets[None, :]).astype(np.float32)
    map_y = (centers[:, 1][:, None] + outward[1] * offsets[None, :]).astype(np.float32)
    sampled = cv2.remap(
        gray, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )
    return sampled.astype(np.float64)


def edge_samples(
    p0: np.ndarray, p1: np.ndarray, trim_ratio: float, max_samples: int = 400
) -> np.ndarray:
    """변 위에 고르게 찍은 표본점. 양 끝의 모서리 라운딩 구간은 뺀다."""
    length = float(np.linalg.norm(p1 - p0))
    count = int(np.clip(length / 2.0, 16, max_samples))
    t = np.linspace(trim_ratio, 1.0 - trim_ratio, count)
    return p0[None, :] + t[:, None] * (p1 - p0)[None, :]


def plateau_levels(profiles: np.ndarray, radius: int) -> tuple[np.ndarray, np.ndarray]:
    """단면 양 끝의 평탄부 레벨 (안쪽, 바깥쪽)."""
    tail = max(2, radius // 3)
    return profiles[:, :tail].mean(axis=1), profiles[:, -tail:].mean(axis=1)


def usable_rows(inner: np.ndarray, outer: np.ndarray, min_contrast: float = 8.0) -> np.ndarray:
    """대비가 살아 있는 표본만 고른다.

    테두리가 가려졌거나 프레임 밖으로 나간 표본은 단면이 평탄해 아무 정보가
    없다. 이런 것을 섞으면 직선 적합과 선명도 측정이 함께 망가진다.
    """
    contrast = np.abs(outer - inner)
    if contrast.size == 0:
        return np.zeros(0, dtype=bool)
    return contrast > max(min_contrast, 0.15 * contrast.max())


def crossing_offsets(profiles: np.ndarray, radius: int) -> tuple[np.ndarray, np.ndarray]:
    """단면이 중간 레벨을 지나는 위치를 서브픽셀로 찾는다.

    Returns
    -------
    (행 인덱스, 중심에서의 오프셋). 교차가 없는 행은 빠진다.
    """
    inner, outer = plateau_levels(profiles, radius)
    mid = (inner + outer) / 2.0
    deviation = profiles - mid[:, None]
    crossings = np.sign(deviation[:, :-1]) * np.sign(deviation[:, 1:]) < 0

    rows: list[int] = []
    offsets: list[float] = []
    for row in range(profiles.shape[0]):
        cols = np.flatnonzero(crossings[row])
        if cols.size == 0:
            continue
        # 여러 번 교차하면 단면 한가운데에 가장 가까운 것을 쓴다.
        j = int(cols[np.argmin(np.abs(cols - radius))])
        d0, d1 = deviation[row, j], deviation[row, j + 1]
        frac = d0 / (d0 - d1) if d0 != d1 else 0.5
        rows.append(row)
        offsets.append((j + frac) - radius)

    return np.array(rows, dtype=int), np.array(offsets, dtype=np.float64)


def rise_distances(
    profiles: np.ndarray, low: float = 0.1, high: float = 0.9
) -> np.ndarray:
    """단면이 10%에서 90%까지 오르는 데 걸리는 거리(px).

    광학 흐림의 직접적인 척도다. 기울기 기반 지표(Tenengrad 등)와 달리
    대비 크기에 비례하지 않아, 잉크 농도나 조명 세기가 달라져도 값이
    흔들리지 않는다.

    반환 배열은 교차를 제대로 찾지 못한 행이 빠져 있어 입력보다 짧을 수 있다.
    """
    radius = (profiles.shape[1] - 1) // 2
    inner, outer = plateau_levels(profiles, radius)
    span = outer - inner

    out: list[float] = []
    for row in range(profiles.shape[0]):
        if abs(span[row]) < 1e-6:
            continue
        # 단면을 0-1 로 정규화하면 부호와 대비 크기가 사라진다.
        unit = (profiles[row] - inner[row]) / span[row]
        positions = []
        for level in (low, high):
            deviation = unit - level
            cols = np.flatnonzero(np.sign(deviation[:-1]) * np.sign(deviation[1:]) < 0)
            if cols.size == 0:
                break
            j = int(cols[np.argmin(np.abs(cols - radius))])
            d0, d1 = deviation[j], deviation[j + 1]
            positions.append(j + (d0 / (d0 - d1) if d0 != d1 else 0.5))
        if len(positions) == 2:
            out.append(abs(positions[1] - positions[0]))

    return np.array(out, dtype=np.float64)
