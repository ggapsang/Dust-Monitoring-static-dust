"""분진 스코어 산출.

구획별 반사율을 오염도로 뒤집고, 패드 전체를 대표하는 값 하나와 산포를 낸다.

**대표값에 평균을 쓰지 않는다.** 국소 뭉침은 소수 구획만 크게 변하는데
평균을 쓰면 나머지 구획에 희석되어 사라진다. 상위 분위수나 최댓값을 쓴다.

**산포를 두 가지 낸다.** 균일 침착과 국소 뭉침을 구분하려면 하나로는
부족하다. 전체가 고르게 어두워지면 IQR 은 거의 안 움직이지만, 몇 구획만
튀면 ``p90 - p50`` 이 뚜렷하게 벌어진다. 반대로 침착량 자체가 늘면 두 값이
같이 움직인다.

기준 이미지를 갖지 않으므로 청정 상태 대비 변화량은 계산하지 않는다.
여기서 나오는 것은 절대 측정값이고, 비교는 상위 계층 몫이다.
"""

from __future__ import annotations

import numpy as np

from .config import ScoreConfig
from .result import Cell, Dispersion


def soiling(reflectance: float, tone: str) -> float:
    """반사율을 오염도로. 클수록 오염이 심하다.

    반사율은 톤과 무관한 절대 척도(0 = 흡수, 1 = 반사)다. 오염 방향은
    톤이 정한다 — 백색 바탕에는 흑색 분진이 앉아 어두워지고, 흑색 바탕에는
    백색 분진이 앉아 밝아진다.
    """
    return 1.0 - reflectance if tone == "white" else reflectance


def apply_soiling(cells: list[Cell], tone: str) -> None:
    """각 구획의 ``reading`` 에 그 사진의 오염도를 채운다."""
    for cell in cells:
        if cell.excluded is None and cell.reflectance is not None:
            cell.reading = soiling(cell.reflectance, tone)


def subtract_baseline(reading: list[Cell], baseline: list[Cell]) -> list[Cell]:
    """판독 사진의 칸값에서 기준 사진의 같은 칸값을 뺀다.

    이 차이가 오염량이다. 사진 한 장의 절대값은 깨끗할 때 얼마였는지를
    모르면 해석할 수 없다 — 인쇄 농도, 패드 재질, 카메라 개체차가 모두
    섞여 있기 때문이다. 같은 패드를 같은 카메라로 찍은 두 장을 빼면 그
    공통분이 사라지고 그 사이에 쌓인 양만 남는다.

    어느 한쪽이라도 배제된 칸은 뺄 수 없으므로 함께 배제한다. 그 칸이
    왜 빠졌는지는 배제된 쪽의 사유를 따른다.
    """
    combined: list[Cell] = []
    for read_cell, base_cell in zip(reading, baseline):
        read_cell.baseline = base_cell.reading
        excluded = read_cell.excluded or base_cell.excluded
        read_cell.excluded = excluded
        if excluded is None and read_cell.reading is not None and base_cell.reading is not None:
            read_cell.value = read_cell.reading - base_cell.reading
        else:
            read_cell.value = None
        combined.append(read_cell)
    return combined


def _statistic(values: np.ndarray, spec: str) -> float:
    """설정 문자열이 가리키는 대표값.

    ``max`` 또는 ``pNN`` (NN = 0-100 분위수). 평균은 의도적으로 받지 않는다.
    """
    if spec == "max":
        return float(values.max())
    if spec.startswith("p"):
        try:
            q = float(spec[1:])
        except ValueError:
            raise ValueError(f"분위수를 읽을 수 없다: {spec!r}") from None
        if not 0.0 <= q <= 100.0:
            raise ValueError(f"분위수는 0-100 이어야 한다: {spec!r}")
        return float(np.percentile(values, q))
    raise ValueError(f"알 수 없는 대표값 방식: {spec!r} ('max' 또는 'pNN')")


def compute_score(cells: list[Cell], cfg: ScoreConfig) -> tuple[float, Dispersion] | None:
    """대표값과 산포. 측정된 구획이 없으면 ``None``."""
    values = np.array(
        [c.value for c in cells if c.excluded is None and c.value is not None],
        dtype=np.float64,
    )
    if values.size == 0:
        return None

    score = _statistic(values, cfg.statistic)
    p50, p90 = np.percentile(values, [50, 90])
    q1, q3 = np.percentile(values, [25, 75])
    dispersion = Dispersion(
        stdev=float(values.std(ddof=1)) if values.size > 1 else 0.0,
        iqr=float(q3 - q1),
        p90_minus_p50=float(p90 - p50),
    )
    return score, dispersion
