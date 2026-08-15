"""조명 정규화.

여백 밝기를 테두리 밝기로 나눈다. 이 처리가 없으면 어두운 곳에서 촬영한
깨끗한 패드가 오염으로 판정된다.

관측값은 대략 ``게인 x 조도 x 반사율`` 이다. 테두리는 반사율이 일정한
인쇄면이므로, 같은 사진 안의 테두리로 나누면 게인과 조도가 함께 사라지고
반사율에 비례하는 값만 남는다.

여기에 더해 조명 기울기를 편다. 옆에서 빛이 들면 깨끗한 패드에서도 한쪽이
어둡게 찍히는데, 그것까지 분진으로 보면 안 된다. 테두리는 어디나 같은
밝기여야 하므로, 테두리를 따라 밝기가 변한다면 그게 곧 조명 기울기다.
테두리 링을 조밀하게 표본해 평면을 맞추고 그만큼 되돌린다.

여백 화소로 기울기를 맞추지 않는다. 고르게 쌓인 분진까지 조명 기울기로 보고
지워 버리기 때문이다.

한계를 적어 둔다. 이 나눗셈은 센서 바닥값을 소거하지 못한다. 관측값이 실제로는
``바닥값 + 게인 x 조도 x 반사율`` 이라서, 분모인 테두리가 저반사면일수록
바닥값이 차지하는 비중이 커진다. 흰 바탕 패드의 검은 테두리가 특히 그렇다.
그래서 분진 판정은 이 값의 절대 크기가 아니라 **국소 배경 대비**로 한다
(``dust.py``). 국소적으로는 바닥값도 상수라 빼는 순간 사라진다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import NormalizeConfig
from .result import NormalizationInfo
from .spec import PadSpec

MIN_BORDER_LEVEL = 1.0
"""테두리 밝기가 이보다 작으면 그것으로 나눌 수 없다.

도안 원본처럼 잉크가 정확히 0 인 이미지가 여기 해당한다. 실제 촬영은 센서
바닥값 때문에 0 이 되지 않는다.
"""


@dataclass
class Normalization:
    reflectance: np.ndarray
    """테두리를 1 로 놓은 상대 밝기. 여백은 이보다 크다(백색 바탕) 또는
    작다(흑색 바탕)."""

    scale: float
    """나눗셈에 쓴 테두리 밝기. 채도를 조명 불변으로 만들 때 분모로 쓴다."""

    info: NormalizationInfo


def _median_mad(values: np.ndarray) -> tuple[float, float]:
    """중앙값과 MAD. 국소 이물이 섞여도 흔들리지 않는다."""
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    return median, mad


def _ring_samples(
    image: np.ndarray, spec: PadSpec, pad_size_px: int, count: int
) -> tuple[np.ndarray, np.ndarray]:
    """테두리 링에서 (위치, 밝기) 표본을 뽑는다.

    위치는 정규화 좌표라 ``pad_size_px`` 가 바뀌어도 적합 계수의 의미가 같다.
    """
    positions: list[np.ndarray] = []
    values: list[np.ndarray] = []

    for rect in spec.border_ring_rects():
        x0, y0, x1, y1 = rect.to_pixels(pad_size_px)
        patch = image[y0:y1, x0:x1]
        if patch.size == 0:
            continue
        ys, xs = np.mgrid[y0:y1, x0:x1]
        positions.append(np.stack([xs.ravel(), ys.ravel()], axis=1) / pad_size_px)
        values.append(patch.ravel())

    if not positions:
        return np.zeros((0, 2)), np.zeros(0)

    all_positions = np.concatenate(positions).astype(np.float64)
    all_values = np.concatenate(values).astype(np.float64)

    if all_values.size > count:
        # 고르게 솎는다. 무작위 추출은 같은 입력에 같은 출력이라는 성질을 깬다.
        step = all_values.size // count
        all_positions = all_positions[::step][:count]
        all_values = all_values[::step][:count]

    return all_positions, all_values


def _fit_plane(
    positions: np.ndarray, values: np.ndarray
) -> tuple[np.ndarray, float] | None:
    """``c0 + c1*x + c2*y`` 를 최소자승 적합. (계수, 잔차 RMS).

    표본이 3점뿐이면 어떤 값이든 완벽히 들어맞아 잔차가 0 이 나온다. 그러면
    추정이 맞는지 틀린지 알 방법이 없으므로 충분한 표본을 요구한다.
    """
    if positions.shape[0] < 16:
        return None
    design = np.column_stack([np.ones(len(positions)), positions[:, 0], positions[:, 1]])
    coeffs, _, _, _ = np.linalg.lstsq(design, values, rcond=None)
    residual = float(np.sqrt(np.mean((design @ coeffs - values) ** 2)))
    return coeffs, residual


def normalize(
    rectified_gray: np.ndarray,
    spec: PadSpec,
    cfg: NormalizeConfig,
    pad_size_px: int,
) -> Normalization | None:
    """여백을 테두리로 나눈 상대 밝기를 만든다. 성립하지 않으면 ``None``."""
    image = rectified_gray.astype(np.float64)

    positions, values = _ring_samples(image, spec, pad_size_px, cfg.ring_samples)
    if values.size == 0:
        return None

    border, border_mad = _median_mad(values)
    info = NormalizationInfo(border_level=border, border_mad=border_mad)

    if abs(border) < MIN_BORDER_LEVEL:
        # 도안 원본처럼 잉크가 0 이면 나눌 수 없다. 애초에 게인이 걸리지
        # 않은 이미지라는 뜻이므로 화소값을 그대로 쓴다.
        scale = 255.0
    else:
        scale = border

    reflectance = image / scale

    if cfg.gradient_correction:
        ring_positions, ring_values = _ring_samples(
            reflectance, spec, pad_size_px, cfg.ring_samples
        )
        fit = _fit_plane(ring_positions, ring_values)
        if fit is not None:
            coeffs, residual = fit
            info.plane_residual_rms = residual
            info.plane_gradient = (float(coeffs[1]), float(coeffs[2]))

            ys, xs = np.mgrid[0:pad_size_px, 0:pad_size_px]
            plane = (
                coeffs[0]
                + coeffs[1] * (xs / pad_size_px)
                + coeffs[2] * (ys / pad_size_px)
            )
            # 링의 평균 조도를 1 로 삼는다. 링이 곧 나눗셈의 기준이므로
            # 그 자리를 1 로 잡아야 척도가 어긋나지 않는다.
            level = float(plane.mean())
            if abs(level) > 1e-6:
                relative = np.clip(plane / level, 0.2, 5.0)
                reflectance = reflectance / relative

    return Normalization(
        reflectance=reflectance.astype(np.float32), scale=float(scale), info=info
    )
