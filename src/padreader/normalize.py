"""조도 정규화.

관측값은 대략 ``I = B0 + g*E*rho`` 다. ``B0`` 는 센서 블랙레벨 오프셋,
``g`` 는 게인, ``E`` 는 조도, ``rho`` 는 반사율이다. 우리가 알고 싶은 것은
``rho`` 뿐이고 나머지는 촬영마다 변한다.

**2점 캘리브레이션** 이 원리적으로는 가장 낫다. 흑·백 앵커가 있으면

    rho_hat = (I - I_black) / (I_white - I_black)

로 ``B0`` 와 ``g*E`` 가 함께 소거된다. 흑색 앵커가 사실상 ``B0`` 를 직접
재 주는 셈이다.

다만 **앵커가 분진으로부터 보호되어 있을 때만** 성립한다. 분진 색은
설계상 잉크 색과 같으므로 바탕톤 앵커는 측정 여백과 완전히 같은 톤이고,
여백이 오염되면 그 앵커도 똑같이 오염된다. 그러면 분자와 분모가 같이
움직여 신호가 상쇄된다 — 백색 패드에서는 비율이 1 로 고정되고, 흑색
패드에서는 분자가 0 으로 죽는다. 그래서 규격이 앵커를 보호된 것으로
선언하지 않는 한 이 경로를 쓰지 않는다.

**테두리 단일 기준**(``border_ratio``)이 실질적인 기본 경로다. 잉크는
반사율이 분진과 같아 오염되어도 값이 거의 변하지 않는, 패드에서 유일하게
안정된 기준면이다. 대신 ``B0`` 를 소거하지 못한다. 백색 패드에서는 기준이
저반사 흑색 잉크라 ``B0`` 의 상대 비중이 가장 크고 분모도 작아 노이즈가
비율에 증폭된다 — 절대 반사율 추정에 큰 편향이 남는다. 단조성은 유지되므로
같은 패드를 같은 카메라로 반복 관측하는 용도에는 쓸 수 있지만, 절대값을
믿으려면 노출·게인 고정과 블랙레벨 보정이 전제되어야 한다.

**기울기 보정** 은 테두리 링에서 한다. 링은 반사율이 일정한 잉크이므로,
정규화 후 링 값이 위치에 따라 변한다면 그게 곧 조도 기울기다. 링을 조밀하게
표본해 평면을 최소자승 적합하고 잔차와 조건수를 함께 낸다 — 변마다 대표값
하나씩 4점만 쓰면 3자유도 평면에 잔차가 남지 않아 신뢰도를 볼 수 없다.

여백 화소로 적합하지 않는 이유: 균일 침착은 여백 전체를 고르게 바꾸는데,
그것까지 조도 기울기로 보고 나눠 버리면 분진 신호가 지워진다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import NormalizeConfig
from .rectify import crop
from .result import NormalizationInfo
from .spec import PadSpec

MIN_ANCHOR_SPAN = 1e-3
"""앵커 대비가 이보다 작으면 나눗셈이 성립하지 않는다."""


@dataclass
class Normalization:
    reflectance: np.ndarray
    """정면 보정 이미지 전체의 반사율 추정. 0 이 완전 흡수, 1 이 완전 반사다.

    패드 톤과 무관한 절대 척도다. 어느 방향이 오염인지는 톤이 정하므로
    스코어 단계에서 뒤집는다.
    """

    scale: float
    """반사율 1 에 해당하는 디지털 카운트. 즉 현재 조명·노출에서의 전체
    다이내믹 레인지다. 채도를 조명 불변으로 만들 때 분모로 쓴다."""

    info: NormalizationInfo
    illumination: np.ndarray | None
    """적합된 조도 상대 필드(평균 1). 기울기 보정을 끄면 ``None``."""


def _median_mad(values: np.ndarray) -> tuple[float, float]:
    """중앙값과 MAD. 국소 이물이 섞여도 흔들리지 않는다."""
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    return median, mad


def _rects_centroid(rects) -> np.ndarray:
    """사각형 무리의 중심. 정규화 좌표."""
    centers = np.array(
        [[(r.x0 + r.x1) / 2.0, (r.y0 + r.y1) / 2.0] for r in rects], dtype=np.float64
    )
    return centers.mean(axis=0)


def _anchor_levels(
    rectified: np.ndarray, rects, pad_size_px: int
) -> tuple[float, float]:
    """앵커 패치들의 대표 밝기와 MAD.

    쌍이 좌우 대칭으로 배치되어 있어, 한꺼번에 중앙값을 잡으면 가로 방향
    조도 기울기가 1차항까지 상쇄된다.
    """
    samples = np.concatenate(
        [crop(rectified, rect.inset(rect.width * 0.2), pad_size_px).ravel() for rect in rects]
    )
    return _median_mad(samples.astype(np.float64))


def _ring_samples(
    rectified: np.ndarray, spec: PadSpec, pad_size_px: int, count: int
) -> tuple[np.ndarray, np.ndarray]:
    """테두리 링에서 (위치, 밝기) 표본을 뽑는다.

    위치는 정규화 좌표라 pad_size_px 가 바뀌어도 적합 계수가 같은 의미를 갖는다.
    """
    positions: list[np.ndarray] = []
    values: list[np.ndarray] = []

    for rect in spec.border_ring_rects():
        x0, y0, x1, y1 = rect.to_pixels(pad_size_px)
        patch = rectified[y0:y1, x0:x1]
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
) -> tuple[np.ndarray, float, float] | None:
    """``c0 + c1*x + c2*y`` 를 최소자승 적합. (계수, 잔차RMS, 조건수)."""
    if positions.shape[0] < 16:
        return None
    design = np.column_stack([np.ones(len(positions)), positions[:, 0], positions[:, 1]])
    coeffs, _, _, _ = np.linalg.lstsq(design, values, rcond=None)
    residual = float(np.sqrt(np.mean((design @ coeffs - values) ** 2)))
    condition = float(np.linalg.cond(design))
    return coeffs, residual, condition


def normalize(
    rectified_gray: np.ndarray,
    spec: PadSpec,
    tone: str,
    cfg: NormalizeConfig,
    pad_size_px: int,
) -> Normalization | None:
    """반사율 추정 맵을 만든다. 정규화가 성립하지 않으면 ``None``.

    반환 맵은 패드 톤과 무관하게 '어두울수록 0, 밝을수록 1' 이다. 오염
    방향을 톤에 맞춰 뒤집는 것은 스코어 단계가 한다.
    """
    image = rectified_gray.astype(np.float64)

    method = cfg.method
    if method == "auto":
        # 보호되지 않은 앵커로 2점을 하면 분진 신호가 상쇄되므로,
        # 규격이 보호를 명시한 경우에만 고른다.
        method = "two_point" if (spec.has_anchors and spec.anchors_protected) else "border_ratio"
    if method == "two_point" and not spec.has_anchors:
        return None

    info = NormalizationInfo(method=method)

    if method == "two_point":
        black, black_mad = _anchor_levels(image, spec.anchor_black, pad_size_px)
        white, white_mad = _anchor_levels(image, spec.anchor_white, pad_size_px)
        info.anchor_black, info.anchor_black_mad = black, black_mad
        info.anchor_white, info.anchor_white_mad = white, white_mad
        span = white - black
        if abs(span) < MIN_ANCHOR_SPAN:
            return None
        offset, scale = black, span
        # 반사율 척도가 앵커가 놓인 자리의 조도에 고정된다. 기울기 보정에서
        # 이 위치의 조도를 1 로 잡아야 척도가 어긋나지 않는다. 앵커는 전부
        # 상단 밴드에 있어서, 패드 평균을 1 로 잡으면 세로 방향 기울기가
        # 그대로 배율 오차로 남는다.
        reference_point = _rects_centroid(spec.anchor_black + spec.anchor_white)
    elif method == "border_ratio":
        positions, values = _ring_samples(image, spec, pad_size_px, cfg.ring_samples)
        if values.size == 0:
            return None
        ink, ink_mad = _median_mad(values)
        info.anchor_black, info.anchor_black_mad = ink, ink_mad
        if abs(ink) < MIN_ANCHOR_SPAN:
            return None
        # 앵커가 없으면 관측을 반사율로 되돌릴 기준이 잉크 하나뿐이다.
        # 잉크 반사율을 가정값으로 놓고 그로부터 게인*조도를 역산한다.
        # 블랙레벨은 여전히 소거되지 않으므로 저반사 잉크(백색 패드)에서
        # 오차가 크다 — 앵커가 있는 도안을 쓰는 편이 낫다.
        assumed = (
            cfg.assumed_ink_reflectance_dark
            if tone == "white"
            else cfg.assumed_ink_reflectance_light
        )
        offset, scale = 0.0, ink / max(assumed, MIN_ANCHOR_SPAN)
        # 기준이 링 전체의 중앙값이므로 척도는 링 무게중심의 조도에 고정된다.
        reference_point = positions.mean(axis=0) if positions.size else np.array([0.5, 0.5])
    else:
        raise ValueError(f"알 수 없는 정규화 방식: {cfg.method!r}")

    reflectance = (image - offset) / scale

    illumination = None
    if cfg.gradient_correction == "border":
        # 조도는 곱해지는 양이므로 보정도 나눗셈이어야 하고, 그러려면 나눌
        # 대상이 0 에서 충분히 떨어져 있어야 한다. 정규화된 반사율은 인쇄
        # 흑색이 0 이라, 기준면이 흑색 잉크인 백색 바탕 패드에서는 링 값이
        # 0 근처에 깔린다. 그대로 나누면 폭주한다.
        #
        # 그래서 실제 반사율에 비례하는 양으로 잠깐 옮겨 놓고 나눈다.
        # rho_abs = dark + rho_hat * (light - dark) 이고 곱셈 보정은 배율에
        # 무관하므로, 상수 offset 만 더한 값으로 계산하면 충분하다.
        offset = cfg.assumed_ink_reflectance_dark / max(
            cfg.assumed_ink_reflectance_light - cfg.assumed_ink_reflectance_dark,
            MIN_ANCHOR_SPAN,
        )
        shifted = reflectance + offset

        positions, values = _ring_samples(shifted, spec, pad_size_px, cfg.ring_samples)
        fit = _fit_plane(positions, values)
        if fit is not None:
            coeffs, residual, condition = fit
            info.plane_residual_rms = residual
            info.plane_condition_number = condition
            info.plane_gradient = (float(coeffs[1]), float(coeffs[2]))

            ys, xs = np.mgrid[0:pad_size_px, 0:pad_size_px]
            plane = coeffs[0] + coeffs[1] * (xs / pad_size_px) + coeffs[2] * (ys / pad_size_px)
            # 척도가 고정된 자리의 조도를 1 로 삼는다. 패드 평균으로 잡으면
            # 그 자리와 평균의 조도 차이가 배율 오차로 남는다.
            reference_level = float(
                coeffs[0] + coeffs[1] * reference_point[0] + coeffs[2] * reference_point[1]
            )
            # 링 자체가 거의 0 이면 조도를 실어 나를 신호가 없다는 뜻이다.
            # 억지로 나누지 말고 보정을 건너뛴다.
            if abs(reference_level) > 10.0 * MIN_ANCHOR_SPAN:
                illumination = (plane / reference_level).astype(np.float64)
                safe = np.clip(illumination, 0.2, 5.0)
                reflectance = shifted / safe - offset
    elif cfg.gradient_correction not in ("none", "margin"):
        raise ValueError(f"알 수 없는 기울기 보정 방식: {cfg.gradient_correction!r}")

    return Normalization(
        reflectance=reflectance.astype(np.float32),
        scale=float(scale),
        info=info,
        illumination=None if illumination is None else illumination.astype(np.float32),
    )
