"""시험 지표: 광학밀도 기반 오염도.

``uniform``/``localized``/``combined`` 을 대체하지 않는다. 임계값·가중치·
차수 같은 자유 파라미터 없이, 노출 영역 전체를 하나의 물리량으로 합산해
나란히 참고용으로 낸다. 어떤 판정(경보·등급·임계 비교)에도 쓰지 않는다.

    d(x,y) = log( B(x,y) / R(x,y) )      B=기준, R=판독, 둘 다 reflectance
    od_sum  = Σ d(x,y)                    부호 그대로, 임계값 없이
    od_mean = od_sum / N                  N = 노출 영역 픽셀 수
    od_score = sqrt(od_mean)  (음수면 0)

흡광은 Beer-Lambert 법칙에 따라 물질량에 지수적으로 작용하므로, 광학밀도
(-log 투과율)가 분진 질량에 비례하는 양이다. 밝기 차를 그대로 쓰면 분진이
두 배여도 값이 두 배가 되지 않지만, 로그를 쓰면 된다 - 이 가산성이
``od_sum`` 을 "입자 하나 = 1배, 입자 스무 개 = 20배" 로 만든다.

노이즈 처리는 별도 장치를 두지 않는다. 노이즈는 밝아지는 쪽과 어두워지는
쪽이 섞여 있어 부호 그대로 더하면 상쇄되고, 분진은 늘 어두워지는 방향이라
상쇄되지 않고 쌓인다. 임계값을 두어 양수만 골라 더리면 이 상쇄가 깨진다.

``reflectance`` 는 ``normalize()`` 가 이미 테두리 밝기로 나눠 둔 값이다 -
노출·게인 차이를 여기서 다시 정규화하지 않는다. 남는 잔차(조명 각도 기울기
등)는 이 지표가 원리적으로 해소하지 못하는 축퇴이며, ``roi_mean_*`` 를
함께 반환해 실증에서 그 영향을 가늠하게 한다.
"""

from __future__ import annotations

import numpy as np

from .result import OpticalDensityScores


def compute_optical_density(
    reading_reflectance: np.ndarray,
    baseline_reflectance: np.ndarray,
    reading_scale: float | None,
    baseline_scale: float | None,
    measurable: np.ndarray,
) -> OpticalDensityScores:
    """노출 영역(``measurable``) 전체에 대한 광학밀도 지표.

    ``reading_scale``/``baseline_scale`` 은 그 사진의 테두리 밝기(raw 0-255
    척도) - reflectance 는 이 값으로 나눈 상대 밝기이므로, 8비트 양자화
    하한(원본 1 단계)을 reflectance 척도로 되돌리는 데 쓴다. 로그가 0 또는
    음수에서 발산하지 않도록 두 사진 모두 이 하한 아래로 내려가지 않게 자른다.
    """
    n = int(measurable.sum())
    if n == 0:
        return OpticalDensityScores()

    floor_r = (1.0 / reading_scale) if reading_scale else np.finfo(np.float64).tiny
    floor_b = (1.0 / baseline_scale) if baseline_scale else np.finfo(np.float64).tiny

    r = np.maximum(reading_reflectance[measurable].astype(np.float64), floor_r)
    b = np.maximum(baseline_reflectance[measurable].astype(np.float64), floor_b)

    d = np.log(b / r)
    od_sum = float(d.sum())
    od_mean = od_sum / n
    od_score = float(np.sqrt(od_mean)) if od_mean > 0 else 0.0

    return OpticalDensityScores(
        od_sum=od_sum,
        od_mean=od_mean,
        od_score=od_score,
        roi_mean_reading=float(r.mean()),
        roi_mean_baseline=float(b.mean()),
    )
